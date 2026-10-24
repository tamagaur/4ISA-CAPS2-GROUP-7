"""
tests/backend/test_recommendation_decisions.py — decided rows stay the plan, a decision is made once on a
current row, and the planner's quantity and reason are captured without touching a recommended value.

The fake sessions answer by SQL text, so these tests check what the code asks and how it answers; the same
statements were also run against the live database inside a rolled-back transaction (reports in
local/limitations_2026-10-20.md and the session report).
"""
from __future__ import annotations

import datetime
import pathlib

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend import auth_utils, lp_cycle
from backend.routers import abc as abc_router
from backend.routers import inventory as inventory_router
from backend.routers import policy_comparison, recommendations as rec, sku as sku_router
from backend.schemas.recommendations import RecommendationDecision
from tests.backend.test_recommendations import FakeResult, _item_row, user_token

REPO = pathlib.Path(__file__).resolve().parents[2]


# ---- 1. decided rows still count as the plan ------------------------------------------------------------

def test_the_cycle_anchor_counts_decided_rows():
    sql, _ = lp_cycle.current_cycle_query("unilever")
    assert "'accepted'" in sql and "'dismissed'" in sql and "'pending'" in sql
    # Not pending-only: pending is one arm of the plan predicate, decided rows are the other.
    assert lp_cycle.PLAN_STATUS_SQL in sql


def test_a_decided_row_with_no_lp_run_is_not_the_plan():
    """2026-10-22: recommendation 4 (Tier C, accepted 2026-08-24, lp_run_key NULL) was counted in the 2026-03
    plan. A decided row is plan only when an LP run produced it; a pending row always is."""
    for sql in (lp_cycle.PLAN_STATUS_SQL, lp_cycle.PLAN_STATUS_SQL_BARE, lp_cycle.CURRENT_CYCLE_CLAUSE):
        assert "lp_run_key IS NOT NULL" in sql and "= 'pending' OR" in sql


def test_freshness_and_the_stored_run_read_the_whole_cycle_not_only_pending():
    fresh, _ = lp_cycle.freshness_query(datetime.date(2026, 3, 1), None, "unilever")
    run, _ = lp_cycle.stored_run_query(datetime.date(2026, 3, 1), "unilever")
    for sql in (fresh, run):
        assert "'accepted'" in sql and "'dismissed'" in sql
        assert lp_cycle.PLAN_STATUS_SQL in sql


def test_open_action_counts_stay_pending_only():
    """superseded_count is "pending rows being withheld": decided rows are done, not withheld."""
    sql, _ = lp_cycle.superseded_count_query(datetime.date(2026, 3, 1), "unilever")
    assert "lr.status = 'pending'" in sql


def test_every_plan_read_uses_the_plan_statuses():
    """The target-stock reads (inventory, policy comparison, ABC, SKU detail, dashboard tier cards) share
    one definition; none still says status = 'pending'."""
    import inspect
    from backend.routers import dashboard

    assert "{PLAN_STATUS_SQL_BARE} AND planning_cycle_date" in inspect.getsource(inventory_router)
    assert "PLAN_STATUS_SQL" in inspect.getsource(policy_comparison.get_policy_comparison)
    assert "PLAN_STATUS_SQL_BARE" in sku_router._SELECT_ONE or "IN ('pending', 'accepted', 'dismissed')" in sku_router._SELECT_ONE
    src = inspect.getsource(abc_router)
    assert src.count("PLAN_STATUS_SQL_BARE} AND planning_cycle_date = :current_cycle") == 2
    q, _ = dashboard._policy_rows_query("unilever", "real", datetime.date(2026, 3, 1))
    assert "'accepted'" in q and lp_cycle.PLAN_STATUS_SQL in q
    # The dashboard's product count is the plan too (2026-10-23); the still-pending subset is a separate column.
    q, _ = dashboard._product_count_query("unilever", "real", datetime.date(2026, 3, 1))
    assert lp_cycle.PLAN_STATUS_SQL in q and "FILTER (WHERE lr.status = 'pending') AS pending_count" in q
    q, _ = dashboard._reorder_preview_query("unilever", "real", datetime.date(2026, 3, 1), "2026-02", {})
    assert lp_cycle.PLAN_STATUS_SQL in q


def test_the_planning_mart_anchors_on_the_same_statuses():
    from backend import planning_mart

    head, _ = planning_mart.head_query("unilever")
    assert "decision_status IN ('pending', 'accepted', 'dismissed')" in head
    assert "decision_status = 'pending')" in head  # only the superseded count is pending-only


# ---- 2. the state machine --------------------------------------------------------------------------------

class _PatchDB:
    """PATCH against a row in a given state. `updated` = whether the guarded UPDATE matches a row;
    `why` = the row the refusal query reads."""

    def __init__(self, updated: bool, why=None, decision_cols=True):
        self.updated, self.why, self.decision_cols = updated, why, decision_cols
        self.sql: list[tuple[str, dict]] = []
        self.rolled_back = False

    def execute(self, stmt, params=None):
        sql = str(stmt)
        self.sql.append((sql, dict(params or {})))
        if "to_regclass('review_flag')" in sql:
            return FakeResult([{"review_flag": False, "on_order": True, "decision_cols": self.decision_cols}])
        if "AS pack FROM lp_recommendation lr" in sql:
            return FakeResult([{"q_i": 50.0, "pack": None}])
        if "UPDATE lp_recommendation" in sql:
            return FakeResult([{"sku": "U-1", "planning_cycle_date": datetime.date(2026, 3, 1)}] if self.updated else [])
        if "AS current_cycle" in sql:
            return FakeResult([self.why] if self.why else [])
        if "MAX(classification_period) AS p FROM ABC_Classification" in sql:
            return FakeResult([{"principal": "unilever", "p": "2026-02"}])
        if "FROM lp_recommendation lr" in sql:
            return FakeResult([_item_row(current_stock=100.0, rop_i=30.0, q_i=50.0)])
        return FakeResult([])

    def commit(self):
        pass

    def rollback(self):
        self.rolled_back = True

    def updates(self):
        return [(s, p) for s, p in self.sql if "UPDATE lp_recommendation" in s]


def _patch(db, **body):
    return rec.update_recommendation(1, RecommendationDecision(**body), db=db,
                                     current_user=auth_utils.decode_access_token(user_token()))


def test_the_update_itself_refuses_a_decided_or_superseded_row():
    sql = rec._UPDATE_DECISION_SQL
    assert "lr.status = 'pending'" in sql
    assert "MAX(l2.planning_cycle_date)" in sql and "p2.principal = pd.principal" in sql


@pytest.mark.parametrize("current", ["accepted", "dismissed"])
def test_a_decided_row_cannot_be_decided_again(current):
    db = _PatchDB(False, why={"status": current, "planning_cycle_date": datetime.date(2026, 3, 1),
                              "current_cycle": datetime.date(2026, 3, 1)})
    for status, extra in (("accepted", {}), ("dismissed", {"reason": "changed my mind"})):
        with pytest.raises(HTTPException) as err:
            _patch(db, status=status, **extra)
        assert err.value.status_code == 409 and f"already {current}" in err.value.detail
    assert db.rolled_back


def test_a_row_in_a_superseded_cycle_is_refused_with_both_cycles_named():
    db = _PatchDB(False, why={"status": "pending", "planning_cycle_date": datetime.date(2025, 11, 1),
                              "current_cycle": datetime.date(2026, 3, 1)})
    with pytest.raises(HTTPException) as err:
        _patch(db, status="accepted")
    assert err.value.status_code == 409
    assert "2025-11-01" in err.value.detail and "2026-03-01" in err.value.detail and "superseded" in err.value.detail


def test_a_missing_row_is_a_404():
    with pytest.raises(HTTPException) as err:
        _patch(_PatchDB(False, why=None), status="accepted")
    assert err.value.status_code == 404


def test_a_pending_current_row_accepts_and_dismisses():
    assert _patch(_PatchDB(True), status="accepted").status in ("pending", "accepted", "dismissed")
    _patch(_PatchDB(True), status="dismissed", reason="Overstocked")


# ---- 5. capture: validation, storage, response ------------------------------------------------------------

@pytest.mark.parametrize("reason", [None, "", "   "])
def test_a_dismissal_without_a_reason_is_rejected(reason):
    with pytest.raises(ValidationError):
        RecommendationDecision(status="dismissed", reason=reason)


@pytest.mark.parametrize("bad", [-1, -0.01, float("nan"), float("inf"), 1e13])
def test_a_decided_quantity_must_be_a_finite_non_negative_number(bad):
    with pytest.raises(ValidationError):
        RecommendationDecision(status="accepted", decided_quantity=bad)


def test_a_quantity_on_a_dismissal_is_rejected():
    with pytest.raises(ValidationError):
        RecommendationDecision(status="dismissed", reason="no", decided_quantity=10)


def test_zero_is_a_legal_decided_quantity_and_the_reason_is_optional_for_an_override():
    d = RecommendationDecision(status="accepted", decided_quantity=0)
    assert d.decided_quantity == 0 and d.reason is None


def test_the_override_and_reason_are_written_and_the_recommended_columns_are_not():
    db = _PatchDB(True)
    _patch(db, status="accepted", decided_quantity=40, reason="  Truck is half full  ")
    sql, params = db.updates()[0]
    assert params["decided_q"] == 40 and params["reason"] == "Truck is half full"
    set_clause = sql.split("SET", 1)[1].split("FROM product_dimension", 1)[0]
    assert "decided_q_i" in set_clause and "decision_reason" in set_clause
    for column in ("q_i =", "rop_i", "ss_i", "forecast"):
        assert column not in set_clause.replace("decided_q_i", "")
    assert "= lr.q_i THEN NULL" in sql  # an "override" equal to the recommendation is no override


def test_the_override_is_refused_where_migration_0062_is_not_applied():
    with pytest.raises(HTTPException) as err:
        _patch(_PatchDB(True, decision_cols=False), status="accepted", decided_quantity=5)
    assert err.value.status_code == 409 and "0062" in err.value.detail


def test_without_migration_0062_a_plain_decision_still_works():
    db = _PatchDB(True, decision_cols=False)
    _patch(db, status="accepted")
    assert "decision_reason" not in db.updates()[0][0]


def test_the_response_returns_recommended_decided_and_reason_side_by_side():
    row = _item_row(current_stock=100.0, rop_i=30.0, q_i=50.0)
    row.update(status="accepted", decided_q_i=40.0, decision_reason="Truck is half full",
               decided_at=datetime.datetime(2026, 10, 21, 3, 0), decided_by="planner@example.com")
    item = rec._to_item(row, None)
    assert (item.q_i, item.recommended_q_i, item.decided_q_i) == (50.0, 50.0, 40.0)
    assert item.decision_reason == "Truck is half full" and item.decided_by == "planner@example.com"


def test_an_undecided_row_has_no_decision_fields():
    item = rec._to_item(_item_row(current_stock=100.0, rop_i=30.0, q_i=50.0), None)
    assert item.recommended_q_i == 50.0 and item.decided_q_i is None and item.decision_reason is None


def test_the_row_query_reads_the_capture_columns_only_where_they_exist():
    assert "lr.decided_q_i" in rec._with_present(rec._SELECT_ONE, {"review_flag": True, "on_order": True, "decision_cols": True})
    absent = rec._with_present(rec._SELECT_ONE, {"review_flag": True, "on_order": True, "decision_cols": False})
    assert "lr.decided_q_i" not in absent and "NULL::numeric AS decided_q_i" in absent


# ---- the decided quantity feeds the displayed plan total, and nothing else -------------------------------
# 2026-10-24: the capture-only rule is lifted narrowly. decided_q_i may feed the plan total and count
# (plan_q_i); it must not reach the forecast, the safety stock or the LP.

def test_plan_quantity_is_the_accepted_quantity_else_q_i():
    assert rec.plan_quantity(50.0, "accepted", 40.0) == 40.0
    assert rec.plan_quantity(50.0, "accepted", 0.0) == 0.0  # zero is a legal decision, not "no override"
    assert rec.plan_quantity(50.0, "accepted", None) == 50.0
    assert rec.plan_quantity(50.0, "pending", None) == 50.0
    assert rec.plan_quantity(50.0, "dismissed", None) == 50.0  # a dismissed row stays in the plan at q_i


def test_the_item_carries_plan_q_i_and_still_the_lp_q_i():
    row = _item_row(current_stock=100.0, rop_i=30.0, q_i=50.0)
    assert rec._to_item(row, None).plan_q_i == 50.0  # nothing decided: the plan reads exactly q_i
    row.update(status="accepted", decided_q_i=40.0)
    item = rec._to_item(row, None)
    assert (item.q_i, item.recommended_q_i, item.plan_q_i) == (50.0, 50.0, 40.0)


def test_only_the_displayed_plan_total_reads_the_decided_quantity():
    dashboard = (REPO / "backend/routers/dashboard.py").read_text(encoding="utf-8")
    assert "decided_q_i" not in dashboard and "plan_q_i" in dashboard  # it reads the derived field only
    for root in ("analytics", "scripts", "transform", "tools"):
        for path in (REPO / root).rglob("*.py"):
            if any(p in path.parts for p in (".venv", "__pycache__")):
                continue
            assert "plan_q_i" not in path.read_text(encoding="utf-8", errors="ignore"), path


# ---- nothing upstream reads the capture ------------------------------------------------------------------

CAPTURE_NAMES = ("decided_q_i", "decision_reason", "decided_quantity")
# The only files allowed to mention the capture columns: the endpoint, its schema, the migration, these tests.
ALLOWED = {
    "backend/routers/recommendations.py", "backend/schemas/recommendations.py",
    "analytics/db/migrations/0062_lp_recommendation_decision_capture.sql",
    "tests/backend/test_recommendation_decisions.py",
    # 2026-10-23: the reversal and approval flow is part of the decision endpoint (it writes, copies and reads the
    # same columns to keep or restore a decision). Still nothing in forecasting, safety stock or the LP.
    "backend/routers/reorder_approval.py", "tests/backend/test_reorder_approval.py",
    "analytics/db/migrations/0067_lp_decision_reversal.sql",
    "analytics/db/migrations/0068_lp_quantity_change_approval.sql",
    # 2026-10-24: the plan-total test feeds a decided quantity through both screens. Test code only.
    "tests/backend/test_dashboard.py",
}


def test_no_forecasting_safety_stock_or_lp_code_reads_the_capture_columns():
    offenders = []
    for root in ("analytics", "backend", "scripts", "transform", "tools", "tests"):
        for path in (REPO / root).rglob("*"):
            if path.suffix not in (".py", ".sql") or any(p in path.parts for p in (".venv", "__pycache__")):
                continue
            rel = path.relative_to(REPO).as_posix()
            if rel in ALLOWED:
                continue
            if any(name in path.read_text(encoding="utf-8", errors="ignore") for name in CAPTURE_NAMES):
                offenders.append(rel)
    assert offenders == []
