"""Settling expected receipts against a stock count (migration 0069, docs/ROLLOVER_DESIGN.md, section b).

A real count dated D for period P settles the receipts it can be evidence for. Nothing is corrected.

    receipt                         what a count does to it
    expected_on <= D                inside the count by assumption: state arrived_in_count, settled_by_period = P,
                                    settled_by_count_date = D. Never added to stock again (stock_opening_v adds only
                                    state = expected).
    expected_on > D                 untouched: the count was taken before it arrived, so it is still on its way and
                                    stock_opening_v adds it on top of the count.
    ordered after D                 untouched (expected_on is never before the order).

not_visible_in_count. The count is evidence that a receipt arrived only if the product's stock plus what it sold rose.
For each settled receipt the month's implied receipts of its product are measured the way derived_receipt_fact measures
them: closing count - opening count + sold. A product missing from a count that WAS taken has 0 on hand (Unilever
files omit zero rows, backend/stock_status.py). When that is <= 0, no receipt of any size is visible in the count:
the receipt is settled all the same and marked not_visible_in_count = true (stock_change_pieces holds the implied
receipts). That is the same impossible-receipt signal the derived-receipts check computes, kept on the receipt so it
accumulates and is visible (GET /inventory/receipt-signals). It is a flag, never a correction: no count, sale, or
receipt is changed.

The test needs the month's sales and the previous count. Where either is missing the receipt is settled, left
untested (stock_change_pieces NULL, not_visible_in_count false) and tested later by retest() once sales load.

The count's PO Qty (inventory_fact.po_qty_*), where SSM ever fills it, is reported next to the open ledger pieces
and is never added (DEC-34, DEC-37).
"""
from __future__ import annotations

_STOCK = """
    SELECT inv.product_key, true AS in_file,
           CASE WHEN pd.pack_size ~ '^[0-9]+(\\.[0-9]+)?$' AND pd.pack_size::numeric > 0
                THEN SUM(inv.quantity_on_hand) * pd.pack_size::numeric + COALESCE(SUM(inv.quantity_pieces), 0)
           END AS pieces
    FROM inventory_fact_real inv JOIN product_dimension pd ON pd.product_key = inv.product_key
    WHERE inv.principal = 'unilever' AND inv._period = {period}
    GROUP BY inv.product_key, pd.pack_size
"""

EVIDENCE_CTE = f"""
WITH cnt AS (
    SELECT MAX(snapshot_date) AS d FROM inventory_fact_real WHERE principal = 'unilever' AND _period = %(p)s
), prev AS (
    SELECT to_char(to_date(%(p)s || '-01', 'YYYY-MM-DD') - interval '1 month', 'YYYY-MM') AS p
), prev_taken AS (
    SELECT EXISTS (SELECT 1 FROM inventory_fact_real i, prev WHERE i.principal = 'unilever' AND i._period = prev.p) AS taken
), cur AS ({_STOCK.format(period="%(p)s")}),
old AS ({_STOCK.format(period="(SELECT p FROM prev)")}),
sales AS (
    SELECT product_key, SUM(quantity_sold) AS q FROM Unilever_SKU_Demand_Fact_Real WHERE calendar_month = %(p)s GROUP BY product_key
), sales_loaded AS (
    SELECT EXISTS (SELECT 1 FROM Unilever_SKU_Demand_Fact_Real WHERE calendar_month = %(p)s) AS loaded
), cand AS (
    {{candidates}}
), ev AS (
    SELECT c.receipt_id, c.product_key, c.pieces, c.expected_on,
           COALESCE(cur.pieces, 0) AS closing, COALESCE(old.pieces, 0) AS opening, COALESCE(s.q, 0) AS sold,
           (sl.loaded AND pt.taken AND (cur.product_key IS NULL OR cur.pieces IS NOT NULL)
                                   AND (old.product_key IS NULL OR old.pieces IS NOT NULL)) AS tested,
           COALESCE(cur.pieces, 0) - COALESCE(old.pieces, 0) + COALESCE(s.q, 0) AS implied_receipts
    FROM cand c
    LEFT JOIN cur ON cur.product_key = c.product_key
    LEFT JOIN old ON old.product_key = c.product_key
    LEFT JOIN sales s ON s.product_key = c.product_key
    CROSS JOIN sales_loaded sl CROSS JOIN prev_taken pt
)
"""

_NEW = "SELECT er.* FROM expected_receipt er, cnt WHERE er.state = 'expected' AND er.expected_on <= cnt.d"
_RETEST = ("SELECT er.* FROM expected_receipt er WHERE er.state = 'arrived_in_count' "
           "AND er.stock_change_pieces IS NULL AND er.settled_by_period = %(p)s")

SELECT_SQL = EVIDENCE_CTE.format(candidates=_NEW) + """
SELECT ev.*, (cnt.d) AS count_date,
       CASE WHEN ev.tested THEN ev.implied_receipts <= 0 ELSE false END AS not_visible
FROM ev CROSS JOIN cnt ORDER BY ev.receipt_id
"""

SETTLE_SQL = EVIDENCE_CTE.format(candidates=_NEW) + """
UPDATE expected_receipt er
SET state = 'arrived_in_count', settled_by_period = %(p)s, settled_by_count_date = (SELECT d FROM cnt), settled_at = now(),
    stock_change_pieces = CASE WHEN ev.tested THEN ev.implied_receipts END,
    not_visible_in_count = CASE WHEN ev.tested THEN ev.implied_receipts <= 0 ELSE false END
FROM ev WHERE ev.receipt_id = er.receipt_id AND er.state = 'expected'
RETURNING er.receipt_id, er.not_visible_in_count, ev.tested
"""

RETEST_SQL = EVIDENCE_CTE.format(candidates=_RETEST) + """
UPDATE expected_receipt er
SET stock_change_pieces = ev.implied_receipts, not_visible_in_count = (ev.implied_receipts <= 0)
FROM ev WHERE ev.receipt_id = er.receipt_id AND ev.tested AND er.state = 'arrived_in_count'
  AND er.stock_change_pieces IS NULL
RETURNING er.receipt_id, er.not_visible_in_count
"""

def count_date(cur, period: str):
    cur.execute("SELECT MAX(snapshot_date) FROM inventory_fact_real WHERE principal = 'unilever' AND _period = %s", (period,))
    return cur.fetchone()[0]


def latest_count_period(cur) -> str | None:
    cur.execute("SELECT MAX(_period) FROM inventory_fact_real WHERE principal = 'unilever'")
    return cur.fetchone()[0]


def settle(cur, period: str, write: bool = False) -> dict:
    """Settle the receipts the count of `period` can settle, then retest earlier settled-but-untested ones.
    Dry run (write=False) changes nothing and reports what a write would do. Inside the caller's transaction."""
    d = count_date(cur, period)
    if d is None:
        raise ValueError(f"no Unilever stock count for {period}: nothing to settle against")
    cur.execute(SELECT_SQL, {"p": period})
    cols = [c[0] for c in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    out = {"period": period, "count_date": d, "settles": len(rows),
           "tested": sum(1 for r in rows if r["tested"]), "untested": sum(1 for r in rows if not r["tested"]),
           "not_visible": sum(1 for r in rows if r["tested"] and r["implied_receipts"] <= 0),
           "pieces_settled": float(sum(r["pieces"] for r in rows)), "written": False, "retested": 0,
           "retested_not_visible": 0}
    cur.execute("SELECT COUNT(*) FROM expected_receipt WHERE state = 'expected' AND expected_on > %s", (d,))
    out["still_on_the_way"] = cur.fetchone()[0]
    cur.execute("""SELECT COUNT(*), COALESCE(SUM(COALESCE(po_qty_cases, 0)), 0) FROM inventory_fact_real
                   WHERE principal = 'unilever' AND _period = %s AND (po_qty_cases IS NOT NULL OR po_qty_pieces IS NOT NULL)""",
                (period,))
    po_rows, po_cases = cur.fetchone()
    out["po_qty_rows_in_count"] = po_rows       # reported next to the ledger, never added
    if write:
        cur.execute(SETTLE_SQL, {"p": period})
        out["written"] = True
        got = cur.fetchall()
        assert len(got) == out["settles"], (len(got), out["settles"])
        cur.execute("SELECT DISTINCT settled_by_period FROM expected_receipt WHERE state = 'arrived_in_count' "
                    "AND stock_change_pieces IS NULL")
        for (p,) in cur.fetchall():
            cur.execute(RETEST_SQL, {"p": p})
            tested = cur.fetchall()
            out["retested"] += len(tested)
            out["retested_not_visible"] += sum(1 for _, nv in tested if nv)
    return out
