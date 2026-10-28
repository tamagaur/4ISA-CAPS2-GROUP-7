"""
tests/test_planning_mart.py — the planning mart (migration 0046, backend/planning_mart.py).

Static checks (no database): the migration writes only inside the `mart` schema, and
mart.refresh_planning()'s defaults are the values the code passes. Helper checks: the planning
refresh rides on every full refresh, is skipped for a scratch target, and a mart that is
missing or out of step is never served. Endpoint check: rows read from the mart are turned
into the response by the same code as the joined rows.

That the mart reproduces the joins for every live row is scripts/rehearse_planning_mart.py's
job (it calls the endpoint both ways); the live test here reruns its cheap cases when the mart
is applied.
"""
from __future__ import annotations

import datetime
import os
import re
from pathlib import Path

import pytest

from analytics import marts
from analytics.params import SKU_COVER_HISTORY_MONTHS, TIER_A_BASIS
from backend import planning_mart
from backend.routers import recommendations as rec
from backend.stock_status import COUNT_OMITS_ZERO_STOCK, STATUSES, URGENCY

REPO = Path(__file__).resolve().parents[1]
MIGRATION = REPO / "analytics" / "db" / "migrations" / "0046_planning_mart.sql"


def _sql() -> str:
    from scripts.run_canonical_load import _strip_sql_file
    return _strip_sql_file(MIGRATION.read_text(encoding="utf-8"))


# ---- static ------------------------------------------------------------------

def test_migration_creates_and_writes_only_inside_the_mart_schema():
    sql = _sql()
    created = re.findall(r"CREATE (?:OR REPLACE )?(?:UNIQUE )?(?:TABLE|VIEW|FUNCTION|INDEX)\s+(?:\w+\s+ON\s+)?([\w.]+)", sql)
    assert created and all(name.startswith("mart.") for name in created if "." in name), created
    for name in created:
        if "." not in name:
            assert re.search(rf"INDEX {name} ON mart\.", sql), name
    written = re.findall(r"(?:INSERT INTO|DELETE FROM|UPDATE|TRUNCATE|ALTER TABLE|DROP \w+)\s+([\w.]+)", sql)
    assert written and all(t.startswith("mart.") for t in written), written


def test_refresh_planning_defaults_are_the_values_the_code_passes():
    sql = _sql()
    assert re.search(r"p_cover_months integer DEFAULT (\d+)", sql).group(1) == str(SKU_COVER_HISTORY_MONTHS)
    default = re.search(r"p_zero_omitting text\[\] DEFAULT ARRAY\[(.*?)\]", sql).group(1)
    assert {v.strip().strip("'") for v in default.split(",")} == set(COUNT_OMITS_ZERO_STOCK)
    assert set(marts.PLANNING_ZERO_OMITTING) == set(COUNT_OMITS_ZERO_STOCK)
    assert re.search(r"p_tier_a_basis text DEFAULT '(\w+)'", sql).group(1) == TIER_A_BASIS
    assert marts.planning_params("x") == {"trigger": "x", "cover_months": SKU_COVER_HISTORY_MONTHS,
                                          "zero_omitting": list(marts.PLANNING_ZERO_OMITTING),
                                          "tier_a_basis": TIER_A_BASIS}
    assert marts.PLANNING_SIGNATURE.count(",") == sql.split("FUNCTION mart.refresh_planning(")[1].split(") RETURNS")[0].count("DEFAULT") - 1


def test_the_mart_allows_exactly_the_status_names_the_app_uses():
    sql = _sql()
    stock = re.search(r"CHECK \(stock_status IN \((.*?)\)\)", sql).group(1)
    assert {v.strip().strip("'") for v in stock.split(",")} == set(STATUSES)
    urgency = re.search(r"CHECK \(urgency IN \((.*?)\)\)", sql).group(1)
    assert {v.strip().strip("'") for v in urgency.split(",")} == set(URGENCY.values())


def test_on_order_is_never_subtracted_from_the_order():
    """DEC-34: the order columns are q_i and q_i x price; on_order appears in no arithmetic."""
    sql = _sql()
    assert "lr.q_i AS order_pieces" in sql
    assert not re.search(r"on_order\w*\s*[-+*/]|[-+*/]\s*\w*\.?on_order", sql)


# ---- the refresh helpers -------------------------------------------------------

class _Cursor:
    """Answers the to_regprocedure checks with `present` and each refresh with its counts."""

    def __init__(self, present=True):
        self.present, self.calls, self._last = present, [], None

    def execute(self, sql, params=None):
        self.calls.append(sql)
        if "to_regprocedure" in sql:
            self._last = (self.present,)
        elif "refresh_planning(" in sql:
            self._last = ({"planning_mart": 3},)
        else:
            self._last = ({"sales_mart": 1},)

    def fetchone(self):
        return self._last


class _NoQueries:
    def execute(self, *a, **k):
        raise AssertionError("a skipped refresh must not touch the database")


def test_every_full_refresh_also_refreshes_the_planning_mart():
    cur = _Cursor()
    assert marts.refresh_marts_cursor(cur, "run_lp") == {"sales_mart": 1, "planning_mart": 3}
    refreshes = [c for c in cur.calls if "to_regprocedure" not in c]
    assert "mart.refresh(" in refreshes[0] and "mart.refresh_planning(" in refreshes[1]


def test_planning_refresh_is_skipped_for_a_scratch_target_or_without_0046(capsys):
    assert marts.refresh_planning_cursor(_NoQueries(), "load", schema="ssm_scratch") is None
    assert marts.refresh_planning_cursor(_Cursor(present=False), "x") is None
    assert "migration 0046" in capsys.readouterr().out


def test_a_failed_planning_refresh_after_a_committed_write_is_reported_not_raised(capsys):
    class _Conn:
        rolled_back = False

        def cursor(self):
            raise RuntimeError("connection lost")

        def rollback(self):
            self.rolled_back = True

    conn = _Conn()
    assert marts.refresh_planning_conn(conn, "compute_review_flags --write") is None
    assert conn.rolled_back and "REFRESH FAILED" in capsys.readouterr().out


# ---- never served out of step --------------------------------------------------

def test_a_fake_session_or_preview_mode_never_reads_the_mart():
    assert planning_mart.usable(object()) is False
    assert planning_mart.usable(object(), "preview") is False
    assert planning_mart.decide(object(), {}) is False
    assert planning_mart.refresh(object(), "Edit SKU") is False


@pytest.mark.parametrize("head", [
    None,
    {"planning_stale": True, "in_step": True, "basis_current": True},
    {"planning_stale": None, "in_step": True, "basis_current": True},
    {"planning_stale": False, "in_step": False, "basis_current": True},
    {"planning_stale": False, "in_step": True, "basis_current": False},  # built on another Tier A basis
])
def test_a_missing_or_out_of_step_mart_is_not_served(monkeypatch, head):
    monkeypatch.setattr(planning_mart.batch, "prefetch", lambda db, queries: 0)
    monkeypatch.setattr(planning_mart.batch, "first", lambda db, sql, params=None: head)
    assert planning_mart.read(object(), "unilever", "pending", "current", None, None) is None


def test_queries_bind_the_scope_and_filters_and_never_interpolate_them():
    sql, params = planning_mart.rows_query("Unilever", "pending", "current", "2026-01-01", "2026-03-31")
    assert params == {"principal": "unilever", "status": "pending", "from_date": "2026-01-01", "to_date": "2026-03-31"}
    assert "unilever" not in sql and "2026-01-01" not in sql
    assert sql.count("pm.principal = :principal") == 2  # the rows and the current-cycle subquery
    all_sql, all_params = planning_mart.rows_query(None, None, "all", None, None)
    assert all_params == {} and ":principal" not in all_sql and "MAX(pm.planning_cycle_date)" not in all_sql
    for query in (planning_mart.run_query("delmonte"),
                  planning_mart.counts_query("delmonte", None, "current", None, None)):
        assert query[1] == {"principal": "delmonte"} and "delmonte" not in query[0]
    head_sql, head_params = planning_mart.head_query("delmonte")
    assert head_params == {"principal": "delmonte", "tier_a_basis": TIER_A_BASIS} and "delmonte" not in head_sql
    assert TIER_A_BASIS not in head_sql and ":tier_a_basis" in head_sql


def test_packed_rows_unpack_under_the_names_the_endpoint_reads():
    sql, _ = planning_mart.rows_query(None, None, "all", None, None)
    assert "json_build_array(" in sql and " AS r" in sql
    values = [1, "S1", "Product 1", "unilever", 12, "2026-03-01", 100, 300, 120, "pending", 240, 20, 2400, True,
              0.02, "A", "2026-02", 3000, 40, None, None, 1, True, ["collapse"], 0, 0.4]
    (row,) = planning_mart.unpack([{"r": values}])
    assert list(row) == [name for name, _ in planning_mart.ROW_COLUMNS] and len(values) == len(row)
    assert row["planning_cycle_date"] == datetime.date(2026, 3, 1) and row["q_i"] == 100
    assert rec._to_item(row, rec._MART_PRESENT).urgency == "URGENT"


# ---- the endpoint's answer from mart rows --------------------------------------

CYCLE = datetime.date(2026, 3, 1)
COUNTED = datetime.date(2026, 3, 2)
GENERATED = datetime.datetime(2026, 10, 3, 8, 8, tzinfo=datetime.timezone.utc)


def _mart_row(**overrides) -> dict:
    row = {
        "recommendation_key": 1, "sku_id": "S1", "product_name": "Product 1", "principal": "unilever",
        "pack_size": 12, "planning_cycle_date": CYCLE, "q_i": 100.0, "rop_i": 300.0, "ss_i": 120.0,
        "status": "pending", "current_stock": 240.0, "current_stock_cases": 20.0, "stock_value_pesos": 2400.0,
        "in_stock_count": True, "revenue_share": 0.02, "tier": "A", "tier_period": "2026-02",
        "avg_monthly_sales_pesos": 3000.0,
        "forecast_units": 40.0, "on_order_pieces": None, "on_order_cases": None, "on_order_unparsed": 1,
        "needs_review": True, "review_reasons": ["collapse"], "review_over_run_months": 0,
        "review_collapse_ratio": 0.4,
    }
    return {**row, **overrides}


def _count(**overrides) -> dict:
    return {"planning_cycle_date": CYCLE, "principal": "unilever", "opening_period": "2026-02",
            "first_date": COUNTED, "last_date": COUNTED, "row_count": 785, **overrides}


def _head(**overrides) -> dict:
    return {"cycle": CYCLE, "fc_at": GENERATED, "lp_at": GENERATED, "row_count": 2, "stale_count": 0,
            "superseded": 5, "planning_stale": False, "in_step": True, "basis_current": True, **overrides}


class _StubDb:
    """A session that answers every statement with no rows and counts them. The mart path now runs one extra statement
    per cycle (rec._attach_avg_pieces: the mart stores sales in pesos only, so cover's pieces side is read live)."""

    def __init__(self):
        self.statements = []

    def execute(self, statement, params=None):
        self.statements.append(str(statement))
        return self

    def mappings(self):
        return self

    def __iter__(self):
        return iter(())

    def all(self):
        return []


def test_mart_rows_become_the_same_items_the_joined_rows_do(monkeypatch):
    rows = [_mart_row(), _mart_row(recommendation_key=2, sku_id="S2", in_stock_count=False, current_stock=None,
                                   current_stock_cases=None, stock_value_pesos=None, needs_review=None,
                                   review_reasons=None)]
    monkeypatch.setattr(planning_mart, "read",
                        lambda *a: {"head": _head(), "rows": rows, "counts": [_count()], "run": None})
    db = _StubDb()
    out = rec._from_mart(db, "pending", "current", None, None, "unilever")
    assert sum("avg_monthly_pieces" in q for q in db.statements) == 1, "one pieces statement per cycle, not removed"
    assert [i.model_dump() for i in out.items] == [rec._to_item(r, rec._MART_PRESENT).model_dump() for r in rows]
    first, second = out.items
    assert (first.urgency, first.current_stock, first.needs_review) == ("URGENT", 240.0, True)
    # Missing from Unilever's count = 0 on hand, as the LP reads it.
    assert (second.urgency, second.current_stock, second.stock_not_in_count) == ("CRITICAL", 0.0, True)
    assert out.count == 2 and out.planning_cycle_date == "2026-03-01" and out.superseded_count == 5
    assert out.freshness["is_stale"] is False and out.freshness["row_count"] == 2
    assert out.lp_model["inputs_source"] == "defaults"
    (count,) = out.stock_counts
    assert (count["principal"], count["period"], count["role"], count["available"], count["row_count"],
            count["counted_on"], count["cycle"]) == ("unilever", "2026-02", "opening", True, 785, "2026-03-02", "2026-03-01")


def test_a_principal_with_no_opening_count_says_so(monkeypatch):
    row = _mart_row(in_stock_count=None, current_stock=None, current_stock_cases=None, stock_value_pesos=None)
    no_count = _count(first_date=None, last_date=None, row_count=None)
    monkeypatch.setattr(planning_mart, "read",
                        lambda *a: {"head": _head(), "rows": [row], "counts": [no_count], "run": None})
    out = rec._from_mart(_StubDb(), None, "current", None, None, None)
    assert out.items[0].urgency == "NO DATA" and "no opening stock count" in out.items[0].stock_blocked_reason
    assert out.stock_counts[0]["available"] is False and "no opening stock count" in out.stock_counts[0]["reason"]


def test_no_pending_cycle_is_an_empty_list_with_the_reason(monkeypatch):
    head = _head(cycle=None, lp_at=None, row_count=0, superseded=0)
    monkeypatch.setattr(planning_mart, "read", lambda *a: {"head": head, "rows": [], "counts": [], "run": None})
    out = rec._from_mart(object(), None, "current", None, None, "delmonte")
    assert out.items == [] and out.count == 0 and out.planning_cycle_date is None and out.stock_counts == []
    assert out.freshness["reason"] == "No pending LP recommendations, so there is nothing to date."


def test_all_cycles_list_each_cycles_own_count_newest_first_and_withhold_nothing(monkeypatch):
    older = _mart_row(recommendation_key=3, planning_cycle_date=datetime.date(2026, 2, 1))
    counts = [_count(), _count(planning_cycle_date=datetime.date(2026, 2, 1), opening_period="2026-01")]
    monkeypatch.setattr(planning_mart, "read",
                        lambda *a: {"head": _head(), "rows": [_mart_row(), older], "counts": counts, "run": None})
    db = _StubDb()
    out = rec._from_mart(db, None, "all", None, None, None)
    assert sum("avg_monthly_pieces" in q for q in db.statements) == 2, "one pieces statement per cycle listed"
    assert [c["period"] for c in out.stock_counts] == ["2026-02", "2026-01"]
    assert out.superseded_count == 0 and out.count == 2


def test_a_served_mart_response_names_the_abc_run_its_tiers_are_from(monkeypatch):
    """The mart has no tier_a_periods; _from_mart reads it, anchored on the newest
    listed cycle's month as the join path is, and the endpoint's period labels are
    added beside it without replacing it."""
    from backend.data_mode import REAL

    monkeypatch.setattr(planning_mart, "read",
                        lambda *a: {"head": _head(), "rows": [_mart_row()], "counts": [_count()], "run": None})
    monkeypatch.setattr(planning_mart, "usable", lambda db, mode: True)
    monkeypatch.setattr(rec, "label_context", lambda db, inv_period, abc_period, principal: {"stock_period": inv_period})
    monkeypatch.setattr(rec, "latest_abc_period", lambda db, principal, at=None: "2026-02")
    anchors = []
    monkeypatch.setattr(rec, "latest_abc_periods",
                        lambda db, principal, at=None: anchors.append(at) or {"unilever": "2026-02"})
    out = rec.get_recommendations(status="pending", cycle="current", from_date=None, to_date=None,
                                  principal="unilever", mode=REAL, db=_StubDb(), current_user=None)
    assert out.tier_a_periods == {"Unilever": "2026-02"} and anchors == ["2026-03"]
    assert out.stock_period == "2026-02" and out.count == 1


def test_a_refused_mart_falls_back_to_the_joins(monkeypatch):
    monkeypatch.setattr(planning_mart, "read", lambda *a: None)
    assert rec._from_mart(object(), None, "current", None, None, None) is None


# ---- live, read only -----------------------------------------------------------

live = pytest.mark.skipif(not os.environ.get("SUPABASE_DB_URL"), reason="live DB not configured (SUPABASE_DB_URL unset)")


@live
def test_the_live_mart_answers_the_current_cycle_as_the_joins_do():
    psycopg2 = pytest.importorskip("psycopg2")
    from scripts import rehearse_planning_mart as rehearsal

    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
    try:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION READ ONLY")  # transaction-scoped, never session-level (pooler leak)
        cur.execute("SELECT to_regclass('mart.planning_mart') IS NOT NULL")
        applied = cur.fetchone()[0]
    finally:
        conn.rollback()
        conn.close()
    if not applied:
        pytest.skip("mart.planning_mart not present (migration 0046 not applied)")
    try:
        for case in [c for c in rehearsal.CASES if c[1] == "current" and c[2] in (None, "pending")]:
            mart, joins = rehearsal._call("mart", case), rehearsal._call(None, case)
            assert mart is not None, f"{case}: the mart was not served"
            assert rehearsal._diff(joins, mart) == [], case
    finally:
        planning_mart.use_schema("mart")
