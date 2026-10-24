"""tests/backend/test_expected_receipts.py - the receipt ledger written inside a decision's transaction (0069).

The fake session of test_reorder_approval answers by SQL text, so these check what the code asks the database and in
what order. A small ledger is simulated from the statements it receives, to show the receipt follows the decided
quantity on every path that decides one. The SQL itself runs against Postgres in tests/etl/test_rollover_scratch.py
(scratch schema).
"""
from __future__ import annotations

import pathlib

from backend import expected_receipts
from backend.routers import reorder_approval as ra
from backend.routers import recommendations as rec
from backend.schemas.recommendations import RecommendationDecision, ReverseRequest
from tests.backend.test_recommendations import FakeResult
from tests.backend.test_reorder_approval import ADMIN, BYPASS, PLANNER, _DB, _change_row, _prior, _propose

REPO = pathlib.Path(__file__).resolve().parents[2]


class _LedgerDB(_DB):
    """_DB plus migration 0069: reports the ledger as present and simulates it from the statements."""

    def __init__(self, receipts=True, settled=None, **kw):
        super().__init__(**kw)
        self.receipts, self.settled = receipts, settled
        self.sim_status, self.sim_decided = self.row["status"], None
        self.ledger: dict[int, dict] = {}

    def execute(self, stmt, params=None):
        sql, p = " ".join(str(stmt).split()), dict(params or {})
        if "to_regclass('review_flag')" in sql:
            self.sql.append((str(stmt), p))
            return FakeResult([{"review_flag": False, "on_order": True, "decision_cols": True, "approval": self.approval,
                                "reversal": self.reversal, "receipts": self.receipts}])
        if "INSERT INTO expected_receipt" in sql:
            self.sql.append((str(stmt), p))
            assert self.sim_status == "accepted", "a receipt is written only for an accepted row, after the decision"
            pieces = self.sim_decided if self.sim_decided is not None else self.row["q_i"]
            if not pieces > 0:                      # the statement's own `> 0` guard
                return FakeResult([])
            live = self.ledger.get(p["key"])
            if live is None:
                self.ledger[p["key"]] = {"pieces": pieces, "state": "expected", "revisions": 0}
            elif live["state"] == "expected" and live["pieces"] != pieces:
                live.update(pieces=pieces, revisions=live["revisions"] + 1)
            return FakeResult([{"receipt_id": 1, "pieces": pieces, "expected_on": None, "revision_count": 0}])
        if sql.startswith("UPDATE expected_receipt"):
            self.sql.append((str(stmt), p))
            live = self.ledger.get(p["key"])
            if live and live["state"] == "expected":
                live["state"] = f"cancelled:{p['why']}"
                return FakeResult([{"receipt_id": 1}])
            return FakeResult([])
        if "FROM expected_receipt" in sql and "state IN ('arrived_in_count'" in sql:
            self.sql.append((str(stmt), p))
            return FakeResult([self.settled] if self.settled else [])
        if "UPDATE lp_recommendation lr" in sql and self.decide_matches:
            self.sim_status = p["status"]
            q = p.get("decided_q")
            self.sim_decided = None if q is None or round(float(q), 2) == self.row["q_i"] else round(float(q), 2)
        if "SET status = 'pending'" in sql:
            self.sim_status, self.sim_decided = "pending", None
        return super().execute(stmt, params)


def _ledger_statements(db):
    return [s for s, _ in db.sql if " ".join(s.split()).startswith(("INSERT INTO expected_receipt", "UPDATE expected_receipt"))]


def _patch(db, user, **body):
    return rec.update_recommendation(1, RecommendationDecision(**body), db=db, current_user=user)


def _in_transaction(db):
    """The ledger write comes after the decision UPDATE and before the commit."""
    order = db.statements()
    first_update = next(i for i, s in enumerate(order) if s.startswith("UPDATE lp_recommendation lr"))
    ledger = next(i for i, s in enumerate(order) if "INSERT INTO expected_receipt" in s or s.startswith("UPDATE expected_receipt"))
    assert first_update < ledger
    assert db.commits == 1


def test_a_plain_accept_records_a_receipt_of_the_recommended_quantity():
    db = _LedgerDB(q_i=384.80)
    _patch(db, ADMIN, status="accepted")
    assert db.ledger[1] == {"pieces": 384.80, "state": "expected", "revisions": 0}
    _in_transaction(db)


def test_a_direct_apply_by_patch_records_the_decided_quantity():
    db = _LedgerDB(q_i=384.80)
    _patch(db, ADMIN, status="accepted", decided_quantity=390.0)
    assert db.ledger[1]["pieces"] == 390.0
    _in_transaction(db)


def test_a_direct_apply_by_a_granted_user_records_the_decided_quantity():
    db = _LedgerDB(q_i=384.80, grants={BYPASS.user_id})
    out, status = _propose(db, user=BYPASS, quantity=390.0)
    assert out.outcome == "applied"
    assert db.ledger[1]["pieces"] == 390.0
    _in_transaction(db)


def test_an_approved_change_records_the_proposed_quantity():
    db = _LedgerDB(q_i=384.80, change=_change_row(proposed_q_i=402.0))
    ra.approve_change(7, None, db=db, admin=ADMIN)
    assert db.ledger[1]["pieces"] == 402.0
    _in_transaction(db)


def test_accepting_a_row_that_plans_zero_pieces_records_no_receipt():
    """36 of 109 rows in lp_run 6 plan 0: a 0-piece 'expected' receipt would count as open (QA 2026-10-24, finding 3)."""
    db = _LedgerDB(q_i=0.0)
    _patch(db, ADMIN, status="accepted")
    assert db.sim_status == "accepted" and db.ledger == {}
    assert db.commits == 1                    # the decision itself is still recorded


def test_a_quantity_change_to_zero_that_is_approved_records_no_receipt():
    db = _LedgerDB(q_i=384.80, change=_change_row(proposed_q_i=0.0))
    ra.approve_change(7, None, db=db, admin=ADMIN)
    assert db.sim_status == "accepted" and db.ledger == {}


def test_a_held_change_writes_no_receipt_until_it_is_approved():
    db = _LedgerDB(q_i=384.80, change=_change_row())
    _propose(db, user=PLANNER, quantity=390.0)
    assert db.ledger == {} and not _ledger_statements(db)


def test_accepting_again_after_a_reversal_gives_a_new_live_receipt_at_the_new_quantity():
    db = _LedgerDB(q_i=384.80, prior=_prior())
    _patch(db, ADMIN, status="accepted", decided_quantity=390.0)
    db.row["status"] = "accepted"
    ra.reverse_decision(1, ReverseRequest(reason="Wrong product"), db=db, admin=ADMIN)
    assert db.ledger[1]["state"] == "cancelled:reversed"
    db.row["status"] = "pending"
    del db.ledger[1]                          # the unique index covers live rows only: the cancelled one no longer blocks
    _patch(db, ADMIN, status="accepted", decided_quantity=402.0)
    assert db.ledger[1]["pieces"] == 402.0 and db.ledger[1]["state"] == "expected"


def test_an_unsettled_receipt_follows_a_changed_quantity_and_counts_the_revision():
    db = _LedgerDB(q_i=384.80)
    _patch(db, ADMIN, status="accepted", decided_quantity=390.0)
    db.sim_decided = 402.0                    # the row is re-decided with another quantity (through decide_row)
    expected_receipts.record(db, 1)
    assert db.ledger[1] == {"pieces": 402.0, "state": "expected", "revisions": 1}


def test_a_dismissal_cancels_any_live_receipt_and_never_writes_one():
    db = _LedgerDB()
    _patch(db, ADMIN, status="dismissed", reason="Not needed")
    assert not db.run("INSERT INTO expected_receipt")
    assert db.run("UPDATE expected_receipt")[0][1]["why"] == "dismissed"


def test_a_reversal_cancels_the_receipt_before_it_commits():
    db = _LedgerDB(prior=_prior())
    db.ledger[1] = {"pieces": 390.0, "state": "expected", "revisions": 0}
    ra.reverse_decision(1, ReverseRequest(reason="Wrong product"), db=db, admin=ADMIN)
    assert db.ledger[1]["state"] == "cancelled:reversed" and db.commits == 1
    assert db.run("DELETE") == []


def test_a_reversal_keeps_a_receipt_a_count_has_settled_and_says_so_in_the_audit():
    settled = {"receipt_id": 9, "state": "arrived_in_count", "settled_by_period": "2026-03"}
    db = _LedgerDB(prior=_prior(), settled=settled)
    db.ledger[1] = {"pieces": 390.0, "state": "arrived_in_count", "revisions": 0}
    ra.reverse_decision(1, ReverseRequest(reason="Wrong product"), db=db, admin=ADMIN)
    assert db.ledger[1]["state"] == "arrived_in_count"
    assert "already arrived_in_count by the 2026-03 count; kept" in db.audit[0]["details"]


def test_nothing_touches_the_ledger_where_migration_0069_is_not_applied():
    db = _LedgerDB(receipts=False, prior=_prior())
    _patch(db, ADMIN, status="accepted", decided_quantity=390.0)
    ra.reverse_decision(1, ReverseRequest(reason="x"), db=db, admin=ADMIN)
    assert not _ledger_statements(db) and db.ledger == {}


# ---- the SQL's shape -----------------------------------------------------------------------------------------

def test_the_receipt_is_the_accepted_quantity_with_the_plans_own_lead_time():
    sql = " ".join(expected_receipts.UPSERT_SQL.split())
    assert "COALESCE(lr.decided_q_i, lr.q_i)" in sql                    # plan_q_i
    assert "lr.status = 'accepted'" in sql
    assert "COALESCE(lr.decided_q_i, lr.q_i) > 0" in sql                # an order of 0 pieces has nothing to arrive
    assert "COALESCE(pd.lead_time_days, CAST(:placeholder_lead_days AS numeric))" in sql
    assert "CASE WHEN pd.lead_time_days IS NULL THEN 'placeholder' ELSE 'product' END" in sql
    assert "ON CONFLICT (recommendation_key) WHERE state <> 'cancelled' DO UPDATE" in sql
    assert "WHERE expected_receipt.state = 'expected'" in sql           # a settled receipt is never changed
    assert "DELETE" not in expected_receipts.UPSERT_SQL + expected_receipts.VOID_SQL


def test_every_writer_of_a_decision_keeps_the_ledger_in_step():
    """A new place that sets lp_recommendation.status / decided_q_i must call backend/expected_receipts."""
    writers = []
    for path in (REPO / "backend").rglob("*.py"):
        text_ = path.read_text(encoding="utf-8")
        if "UPDATE lp_recommendation" in text_ and ("decided_q_i" in text_ or "SET status" in text_):
            writers.append(path.relative_to(REPO).as_posix())
    assert sorted(writers) == ["backend/routers/recommendations.py", "backend/routers/reorder_approval.py"]
    for rel in writers:
        assert "expected_receipts" in (REPO / rel).read_text(encoding="utf-8"), rel
