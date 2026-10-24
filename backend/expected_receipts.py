"""The receipt ledger: an accepted order as stock that is on the way (migration 0069, docs/ROLLOVER_DESIGN.md).

Written in the decision's OWN transaction, by the one place that decides (recommendations.decide_row) and the one
place that undoes a decision (reorder_approval.reverse_decision). The caller commits. Nothing here commits.

    accepted              one live receipt: pieces = plan_q_i (the accepted quantity, else q_i),
                          expected_on = decision date + the product's lead time (days).
                          NONE when that quantity is 0: nothing is on its way, and a 0-piece "expected" receipt
                          counted as open and was flagged not_visible_in_count once a count settled it (QA
                          2026-10-24 finding 3). 36 of the 109 rows of lp_run 6 plan 0. A decided row cannot be
                          re-decided without a reversal, which cancels its receipt, so no live receipt is ever left
                          at a quantity that has since become 0.
    accepted, again       the live receipt is UPDATED to the decided quantity (revision_count, revised_at); a receipt a
                          stock count has already settled is never changed
    dismissed / reversed  the live receipt is cancelled (state cancelled, voided_by_decision), never deleted

Every way a quantity gets decided goes through decide_row: a plain accept, a direct apply (POST quantity-change by a
user with a grant or an admin) and an approved change (POST changes/{k}/approve). So the receipt follows the decided
quantity on all three paths, and tests/backend/test_expected_receipts.py fails if a new writer of the decision appears
that does not call this module.

Lead time: Product_Dimension.lead_time_days, else the plan's own placeholder (analytics.params.PLACEHOLDERS
["lead_days"], the number the LP already plans with). lead_time_source says which, so a placeholder is never mistaken for
a measured lead time.

A receipt is settled ONLY by a stock count (scripts/settle_receipts.py), never by the lead time passing.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from analytics.params import PLACEHOLDERS

# One live receipt per recommendation (ux_expected_receipt_one_live). A settled receipt is left as it is.
UPSERT_SQL = """
    INSERT INTO expected_receipt (recommendation_key, product_key, sku_code, pieces, ordered_at, lead_days_used,
                                  lead_time_source, expected_on)
    SELECT lr.recommendation_key, lr.product_key, pd.sku_code, COALESCE(lr.decided_q_i, lr.q_i),
           COALESCE(lr.decided_at, now()), lead.days, lead.source,
           (COALESCE(lr.decided_at, now())::date + CEIL(lead.days)::int)
    FROM lp_recommendation lr
    JOIN product_dimension pd ON pd.product_key = lr.product_key
    CROSS JOIN LATERAL (SELECT COALESCE(pd.lead_time_days, CAST(:placeholder_lead_days AS numeric)) AS days,
                               CASE WHEN pd.lead_time_days IS NULL THEN 'placeholder' ELSE 'product' END AS source) lead
    WHERE lr.recommendation_key = :key AND lr.status = 'accepted'
      AND COALESCE(lr.decided_q_i, lr.q_i) > 0
    ON CONFLICT (recommendation_key) WHERE state <> 'cancelled' DO UPDATE
    SET pieces = EXCLUDED.pieces,
        revision_count = expected_receipt.revision_count
                         + CASE WHEN expected_receipt.pieces IS DISTINCT FROM EXCLUDED.pieces THEN 1 ELSE 0 END,
        revised_at = CASE WHEN expected_receipt.pieces IS DISTINCT FROM EXCLUDED.pieces THEN now()
                          ELSE expected_receipt.revised_at END
    WHERE expected_receipt.state = 'expected'
    RETURNING receipt_id, pieces, expected_on, revision_count
"""

VOID_SQL = """
    UPDATE expected_receipt
    SET state = 'cancelled', voided_by_decision = :why, voided_at = now()
    WHERE recommendation_key = :key AND state = 'expected'
    RETURNING receipt_id
"""

SETTLED_SQL = """
    SELECT receipt_id, state, settled_by_period FROM expected_receipt
    WHERE recommendation_key = :key AND state IN ('arrived_in_count', 'confirmed')
"""


def record(db: Session, key: int) -> dict | None:
    """Create or update the live receipt of the ACCEPTED recommendation `key` (inside the caller's transaction).
    None when it has no quantity to receive (an order of 0 pieces)."""
    row = db.execute(text(UPSERT_SQL), {"key": key, "placeholder_lead_days": PLACEHOLDERS["lead_days"]}).mappings().first()
    return dict(row) if row else None


def void(db: Session, key: int, why: str) -> int:
    """Cancel the live, unsettled receipt of `key` (why: 'dismissed' or 'reversed'). Returns how many were cancelled."""
    if why not in ("dismissed", "reversed"):
        raise ValueError(f"why must be 'dismissed' or 'reversed', not {why!r}")
    return len(db.execute(text(VOID_SQL), {"key": key, "why": why}).all())


def settled_note(db: Session, key: int) -> str | None:
    """Words for the audit log when a reversal finds the receipt already settled by a count (it is kept)."""
    row = db.execute(text(SETTLED_SQL), {"key": key}).mappings().first()
    if row is None:
        return None
    return f"receipt {row['receipt_id']} already {row['state']} by the {row['settled_by_period']} count; kept"
