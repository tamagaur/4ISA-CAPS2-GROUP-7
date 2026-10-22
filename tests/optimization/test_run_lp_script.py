"""
tests/optimization/test_run_lp_script.py — the DB-free parts of scripts/run_lp.py.

Covers the 2026-09-29 rework (reports/LP_CLIENT_ALIGNMENT_PLAN_2026-09-29.md,
Step B): the order must move with --allocation-pct (Yuan's ask: the original
bug was output that didn't move with any parameter), the flags default to the
one set of placeholders, the cover rule, and how stock, cost and last year's
sales reach the plan. Also the 2026-09-21 guarantees that still hold: a rerun
never overwrites a decided row, and the dry run stays transaction-scoped.
"""
from __future__ import annotations

from pathlib import Path

import argparse
import datetime
import math

import pandas as pd
import pytest

from analytics.optimization.lp import Z_SCORE, weekly_demand
from analytics.params import PLACEHOLDERS
from scripts.run_lp import (
    RETIRE_QUERY,
    UPSERT_QUERY,
    ProductInput,
    _non_negative_float,
    _positive_float,
    allocation_ceilings,
    build_parser,
    cycle_transaction,
    plan_cycle,
    product_input,
    retire_stale_pending,
    rows_to_retire,
    safety_stock_for,
)


def _product(key, forecast=1200.0, prior_year_pieces=12_000.0, revenue=100_000.0, stock=0.0, cost=None,
             sigma_d=50.0, principal="unilever", stock_period=None):
    return ProductInput(product_key=key, sku_id=f"SKU{key}", principal=principal, forecast=forecast,
                        sigma_d=sigma_d, stock_on_hand=stock, in_stock_file=True, cost_per_piece=cost,
                        prior_year_pieces=prior_year_pieces, prior_year_revenue=revenue,
                        stock_period=stock_period)


def _args(*flags):
    return build_parser().parse_args(list(flags))


def test_the_order_moves_with_allocation_pct():
    """Yuan, 2026-09-29: Q must change when --allocation-pct changes."""
    products = [_product(1, revenue=500_000), _product(2, revenue=300_000), _product(3, revenue=200_000)]
    low = plan_cycle(products, _args("--allocation-pct", "103"))
    high = plan_cycle(products, _args("--allocation-pct", "108"))

    # 36,000 pieces last year x 103% / 12 = 3,090 a month; x 108% = 3,240.
    assert low.allocation == {"unilever": pytest.approx(3090)}
    assert high.allocation == {"unilever": pytest.approx(3240)}
    # Both short of the ~5,470 needed, so each uses its whole allocation.
    assert sum(low.orders.values()) == pytest.approx(3090)
    assert sum(high.orders.values()) == pytest.approx(3240)
    assert low.orders != high.orders
    # The extra 150 pieces go to someone; nobody gets less.
    assert all(high.orders[k] >= low.orders[k] - 1e-6 for k in low.orders)


def test_flags_default_to_the_placeholders():
    """One place (analytics/params.PLACEHOLDERS) feeds both
    the CLI defaults and backend/lp_cycle.lp_model_info()."""
    args = _args()
    for key, value in PLACEHOLDERS.items():
        assert getattr(args, key) == value, key


def test_safety_stock_and_target_cover_review_plus_lead_days():
    plan = plan_cycle([_product(1)], _args("--review-days", "5", "--lead-days", "3"))
    ss = plan.skus[0].safety_stock
    assert ss == pytest.approx(Z_SCORE * 50.0 * math.sqrt(8))
    assert plan.skus[0].target_stock == pytest.approx(weekly_demand(1200.0) * 8 / 5 + ss)


def test_safety_stock_scales_with_sqrt_of_protection_days():
    # A weekly review (5 business days) covers sqrt(5) times one day's sigma.
    assert safety_stock_for(10.0, 5) == pytest.approx(Z_SCORE * 10.0 * math.sqrt(5))


def test_per_sku_cover_rule_floors_every_target_and_aggregate_does_not():
    products = [_product(1, sigma_d=1.0), _product(2, sigma_d=400.0)]
    per_sku = plan_cycle(products, _args("--cover-rule", "per-sku"))
    aggregate = plan_cycle(products, _args("--cover-rule", "aggregate"))
    for s in per_sku.skus:
        assert s.target_stock >= 3 * weekly_demand(s.demand) - 1e-9
    # The low-variability SKU's statistical target is under 3 weeks.
    assert aggregate.skus[0].target_stock < 3 * weekly_demand(aggregate.skus[0].demand)
    assert per_sku.skus[1].target_stock == pytest.approx(aggregate.skus[1].target_stock)  # already above


def test_revenue_share_is_the_priority_and_the_cost_falls_back_to_the_placeholder():
    plan = plan_cycle([_product(1, revenue=300.0, cost=12.5), _product(2, revenue=100.0)], _args())
    assert [s.revenue_weight for s in plan.skus] == pytest.approx([0.75, 0.25])
    assert plan.skus[0].procurement_cost_per_unit == 12.5
    assert plan.skus[1].procurement_cost_per_unit == PLACEHOLDERS["default_procurement_cost_per_unit"]


def test_allocation_is_last_years_pieces_times_pct_over_twelve_per_principal():
    products = [_product(1, prior_year_pieces=12_000), _product(2, prior_year_pieces=-60),  # net returns
                _product(3, prior_year_pieces=24_000, principal="delmonte")]
    assert allocation_ceilings(products, 105) == {"unilever": pytest.approx(1050), "delmonte": pytest.approx(2100)}


def test_product_input_reads_the_stock_file_and_last_calendar_year():
    history = pd.DataFrame({
        "product_key": [7, 7, 7, 8],
        "period": ["2024-12", "2025-01", "2025-12", "2025-06"],
        "total_quantity": [999.0, 100.0, 200.0, 5.0],
        "total_amount": [9_999.0, 1_000.0, 2_000.0, 50.0],
    })
    product, reason = product_input(7, "SKU7", "unilever", 300.0, 1.0, {7: (True, 450.0, 20.0)}, history, 2025)
    assert reason is None
    assert (product.stock_on_hand, product.in_stock_file, product.cost_per_piece) == (450.0, True, 20.0)
    assert (product.prior_year_pieces, product.prior_year_revenue) == (300.0, 3_000.0)


def test_product_missing_from_the_stock_file_counts_as_zero_stock():
    """The stock file lists no zero-stock rows, so no row means none on hand."""
    empty = pd.DataFrame(columns=["product_key", "period", "total_quantity", "total_amount"])
    product, reason = product_input(7, "SKU7", "unilever", 300.0, 1.0, {}, empty, 2025)
    assert reason is None
    assert (product.stock_on_hand, product.in_stock_file, product.cost_per_piece) == (0.0, False, None)


def test_stock_in_cases_without_a_pack_size_is_gated_out():
    empty = pd.DataFrame(columns=["product_key", "period", "total_quantity", "total_amount"])
    product, reason = product_input(7, "SKU7", "delmonte", 300.0, 1.0, {7: (True, None, None)}, empty, 2025)
    assert product is None and "pack size" in reason


def test_rerun_only_updates_rows_still_pending():
    normalized = " ".join(UPSERT_QUERY.split())
    assert "ON CONFLICT (product_key, planning_cycle_date) DO UPDATE SET" in normalized
    assert normalized.endswith("WHERE LP_Recommendation.status = 'pending'")


def test_rerun_restamps_the_rows_it_refreshes():
    # generated_at's DEFAULT now() fires only on INSERT. Live on 2026-09-23
    # every product in the pool already had a row in its cycle, so a rerun
    # was all UPDATEs and backend/lp_cycle.py still dated the LP to the old run.
    normalized = " ".join(UPSERT_QUERY.split())
    assert "generated_at = now()" in normalized


@pytest.mark.parametrize("raw", ["0", "-1", "-0.5"])
def test_positive_flags_reject_zero_and_negatives(raw):
    with pytest.raises(argparse.ArgumentTypeError):
        _positive_float(raw)


def test_positive_flags_accept_fractions():
    assert _positive_float("7.5") == 7.5


def test_lead_days_and_storage_cost_may_be_zero_but_not_negative():
    assert _non_negative_float("0") == 0.0
    with pytest.raises(argparse.ArgumentTypeError):
        _non_negative_float("-1")


def test_dry_run_is_transaction_scoped_never_session_scoped():
    """set_session(readonly=True) is session-scoped: through the :6543
    transaction pooler it leaves default_transaction_read_only on the shared
    server connection, and the next client handed it can't write — it broke
    the app's sign-ins on 2026-09-28. The dry run must stay one READ ONLY
    transaction that nothing commits: with autocommit off, psycopg2 discards
    it on conn.close() and on any error exit, so no path can leave it open.

    Scoped to main() (the real path, --source real): _run_demo_lp (--source demo) is a separate function, its own
    short-lived connections to schema demo only via the direct URL, never the :6543 pooler — a real commit there
    (--write) is unrelated to this pooler-session concern."""
    full_source = (Path(__file__).resolve().parents[2] / "scripts/run_lp.py").read_text(encoding="utf-8")
    source = full_source[full_source.index("\ndef main():"):]
    assert "conn.set_session(readonly" not in source  # the comment may name it; the call must not
    assert "conn.set_session(autocommit=not args.dry_run)" in source
    assert source.count('cur.execute("SET TRANSACTION READ ONLY")') == 1
    assert "conn.commit()" not in source


# ---- --retire-stale-pending ------------------------------------------------
# A rerun refreshes only the products in its pool, so the cycle's other
# pending rows kept q_i/rop_i from the old forecasts and stayed on screen
# (live 2026-09-30: 73 refreshed, 177 left stale). The flag removes those,
# in the cycle's own transaction, after saving them to a CSV.

CYCLE = datetime.date(2026, 3, 1)
_LP_COLUMNS = ["recommendation_key", "product_key", "planning_cycle_date", "q_i", "rop_i", "ss_i",
               "status", "decided_at", "decided_by", "generated_at"]


def _lp_row(key, product_key, status="pending", cycle=CYCLE):
    return {"recommendation_key": key, "product_key": product_key, "planning_cycle_date": cycle,
            "q_i": 10.0, "rop_i": 20.0, "ss_i": 5.0, "status": status,
            "decided_at": None, "decided_by": None, "generated_at": "2026-08-24 07:12:56+00"}


class _RecordingCursor:
    """Stands in for the psycopg2 cursor: answers the read with `rows` and
    records every statement, so a test sees exactly what reached the
    database. With watch_dir, it also notes which files existed when the
    DELETE arrived."""

    def __init__(self, rows=(), delete_rowcount=None, watch_dir=None):
        self._rows = [tuple(r.values()) for r in rows]
        self._delete_rowcount = delete_rowcount
        self._watch_dir = watch_dir
        self.statements: list[tuple[str, object]] = []
        self.files_at_delete: list[list[Path]] = []
        self.description = None
        self.rowcount = -1

    def execute(self, sql, params=None):
        sql = " ".join(sql.split())
        self.statements.append((sql, params))
        if sql.startswith("SELECT"):
            self.description = [(c,) for c in _LP_COLUMNS]
        elif sql.startswith("DELETE"):
            if self._watch_dir is not None:
                self.files_at_delete.append(sorted(self._watch_dir.iterdir()))
            self.rowcount = len(params[0]) if self._delete_rowcount is None else self._delete_rowcount

    def fetchall(self):
        return list(self._rows)


def test_retire_takes_only_pending_rows_outside_the_pool():
    rows = [_lp_row(1, 101), _lp_row(2, 102), _lp_row(3, 103)]
    assert [r["product_key"] for r in rows_to_retire(rows, CYCLE, solved_keys={101})] == [102, 103]


def test_retire_keeps_accepted_and_dismissed_rows():
    rows = [_lp_row(1, 101, "accepted"), _lp_row(2, 102, "dismissed"), _lp_row(3, 103)]
    assert [r["product_key"] for r in rows_to_retire(rows, CYCLE, solved_keys=set())] == [103]


def test_retire_keeps_other_cycles():
    rows = [_lp_row(1, 101, cycle=datetime.date(2026, 2, 1)), _lp_row(2, 102)]
    assert [r["product_key"] for r in rows_to_retire(rows, CYCLE, solved_keys=set())] == [102]


def test_retire_delete_is_still_guarded_on_cycle_and_status():
    normalized = " ".join(RETIRE_QUERY.split())
    assert normalized.startswith("DELETE FROM LP_Recommendation WHERE recommendation_key = ANY(%s)")
    assert "planning_cycle_date = %s" in normalized
    assert "status = 'pending'" in normalized


def test_dry_run_retire_reports_and_writes_nothing(tmp_path):
    cur = _RecordingCursor([_lp_row(1, 101), _lp_row(2, 102)])
    retired, path = retire_stale_pending(cur, CYCLE, {101}, dry_run=True, out_dir=tmp_path)
    assert [r["product_key"] for r in retired] == [102]
    assert path is None
    assert [s for s, _ in cur.statements if not s.startswith("SELECT")] == []
    # A READ ONLY transaction refuses row locks, so the dry run's read takes none.
    assert not any("FOR UPDATE" in s for s, _ in cur.statements)
    assert list(tmp_path.iterdir()) == []


def test_real_retire_saves_every_column_before_deleting(tmp_path):
    rows = [_lp_row(1, 101), _lp_row(2, 102), _lp_row(3, 103, "accepted")]
    cur = _RecordingCursor(rows, watch_dir=tmp_path)
    retired, path = retire_stale_pending(cur, CYCLE, {101}, dry_run=False, out_dir=tmp_path)

    assert [r["product_key"] for r in retired] == [102]
    assert path.name.startswith("retired_2026-03-01_") and path.suffix == ".csv"
    assert cur.files_at_delete == [[path]]  # the CSV was on disk before the DELETE ran
    saved = pd.read_csv(path)
    assert list(saved.columns) == _LP_COLUMNS
    assert saved["recommendation_key"].tolist() == [2]
    assert "FOR UPDATE" in cur.statements[0][0]  # nobody can decide a row between the read and the delete
    delete_sql, delete_params = cur.statements[-1]
    assert delete_sql.startswith("DELETE") and delete_params == ([2], CYCLE)


def test_nothing_stale_writes_no_csv_and_deletes_nothing(tmp_path):
    cur = _RecordingCursor([_lp_row(1, 101), _lp_row(3, 103, "accepted")])
    retired, path = retire_stale_pending(cur, CYCLE, {101}, dry_run=False, out_dir=tmp_path)
    assert (retired, path) == ([], None)
    assert [s for s, _ in cur.statements if s.startswith("DELETE")] == []
    assert list(tmp_path.iterdir()) == []


def test_retire_raises_when_the_delete_removes_a_different_count(tmp_path):
    cur = _RecordingCursor([_lp_row(2, 102)], delete_rowcount=0)
    with pytest.raises(RuntimeError, match="expected 1"):
        retire_stale_pending(cur, CYCLE, set(), dry_run=False, out_dir=tmp_path)


def test_cycle_transaction_commits_a_real_runs_writes_together():
    cur = _RecordingCursor()
    with cycle_transaction(cur, dry_run=False):
        cur.execute("INSERT INTO LP_Recommendation VALUES (1)")
    assert [s for s, _ in cur.statements] == ["BEGIN", "INSERT INTO LP_Recommendation VALUES (1)", "COMMIT"]


def test_cycle_transaction_rolls_back_on_error():
    cur = _RecordingCursor()
    with pytest.raises(RuntimeError):
        with cycle_transaction(cur, dry_run=False):
            raise RuntimeError("retire count mismatch")
    assert [s for s, _ in cur.statements] == ["BEGIN", "ROLLBACK"]


def test_cycle_transaction_sends_nothing_in_a_dry_run():
    """The dry run is already one READ ONLY transaction that nothing commits."""
    cur = _RecordingCursor()
    with cycle_transaction(cur, dry_run=True):
        pass
    assert cur.statements == []


def test_retire_stale_pending_is_opt_in():
    assert _args().retire_stale_pending is False
    assert _args("--retire-stale-pending").retire_stale_pending is True


# ---- item 8: every real run records what it used (lp_run, migration 0037) ----


def test_run_record_holds_every_flag_and_the_fixed_model():
    import datetime
    import json

    from analytics.params import LP_WEIGHTS, MASE_GATE
    from scripts.run_lp import run_record

    args = _args("--allocation-pct", "108")
    plan = plan_cycle([_product(1)], args)
    record = run_record(args, plan, datetime.date(2026, 3, 1), {"unilever": _OPENING_COUNT})
    flags = {k: v for k, v in record["inputs"].items() if k not in ("stock_counts", "notes")}
    assert flags == {key: getattr(args, key) for key in PLACEHOLDERS}
    assert record["inputs"]["allocation_pct"] == 108.0
    assert record["principal_scope"] == "both"
    model = record["model"]
    assert model["weights"] == LP_WEIGHTS and model["mase_gate"] == MASE_GATE
    assert model["allocation"]["basis_year"] == 2025 and model["allocation"]["unit"] == "pieces"
    assert model["allocation"]["monthly_ceiling"] == {k: round(v, 2) for k, v in plan.allocation.items()}
    json.dumps(record["inputs"])
    json.dumps(model)  # both go to JSONB columns


def test_each_refreshed_row_points_at_its_run():
    normalized = " ".join(UPSERT_QUERY.split())
    assert "(product_key, planning_cycle_date, q_i, rop_i, ss_i, status, lp_run_key)" in normalized
    assert "lp_run_key = EXCLUDED.lp_run_key" in normalized


# ---- stock timing (2026-10-03, reports/diagnostics/lp_logic_check_2026-10-03) ----
# Cycle M plans from the stock count of M - 1, the one that opens the month,
# or not at all. Cycle 2026-03 used the count of 2026-04-06 (after March's
# sales), so need = forecast + target - stock counted March twice.

import logging
import sys

from analytics.params import SERVICE_LEVEL_PCT
from backend.data_notes import OPENING_COUNT_RULINGS, PLANNING_NOTES
from scripts.run_lp import STOCK_AND_COST_QUERY, check_stock_periods, opening_counts, run_notes, run_record

_COUNTED_2026_03_02 = datetime.date(2026, 3, 2)
_COUNTED_2026_04_06 = datetime.date(2026, 4, 6)
_OPENING_COUNT = {"period": "2026-02", "counted_on": "2026-03-02", "counted_on_note": None,
                  "row_count": 812, "flag": None, "available": True}


def _count_row(row_count, counted_on):
    return {"row_count": row_count, "first_date": counted_on, "last_date": counted_on}


def test_a_cycle_plans_only_from_the_count_that_opens_it():
    """The look-ahead guard: cycle 2026-03 takes the 2026-02 count. A later
    count (the bug) and an older one are both refused, not planned from."""
    args = _args()
    assert plan_cycle([_product(1, stock_period="2026-02")], args, CYCLE).orders is not None
    for wrong in ("2026-03", "2026-04", "2026-01", None):
        with pytest.raises(ValueError, match="stock count of 2026-02"):
            plan_cycle([_product(1, stock_period=wrong)], args, CYCLE)
    with pytest.raises(ValueError):
        check_stock_periods([_product(1, stock_period="2026-02"), _product(2, stock_period="2026-03")], CYCLE)


def test_the_stock_query_is_bound_to_one_count_never_the_latest():
    normalized = " ".join(STOCK_AND_COST_QUERY.split())
    assert "WHERE inv._period = %(stock_period)s" in normalized
    assert "MAX(_period)" not in normalized


def test_a_principal_without_an_opening_count_is_refused_with_the_reason():
    usable, refused = opening_counts(CYCLE, {"unilever", "delmonte"},
                                     {"unilever": _count_row(812, _COUNTED_2026_03_02)})
    assert list(usable) == ["unilever"]
    assert (usable["unilever"]["period"], usable["unilever"]["counted_on"]) == ("2026-02", "2026-03-02")
    assert refused == {"delmonte": "no opening stock count for March 2026: delmonte has no stock count for February 2026"}


def test_january_opens_with_the_previous_decembers_count():
    usable, refused = opening_counts(datetime.date(2026, 1, 1), {"unilever"},
                                     {"unilever": _count_row(775, datetime.date(2026, 1, 1))})
    assert usable["unilever"]["period"] == "2025-12" and refused == {}


def test_run_record_names_the_stock_count_and_any_refusal():
    args = _args("--allocation-pct", "103")
    plan = plan_cycle([_product(1, stock_period="2026-02")], args, CYCLE)
    record = run_record(args, plan, CYCLE, {"unilever": _OPENING_COUNT},
                        {"delmonte": "no opening stock count for March 2026: delmonte has no stock count for February 2026"})
    assert record["inputs"]["stock_counts"] == {"unilever": {
        "period": "2026-02", "counted_on": "2026-03-02", "counted_on_note": None, "row_count": 812, "flag": None}}
    assert record["inputs"]["stock_refused"]["delmonte"].startswith("no opening stock count for March 2026")
    assert record["inputs"]["allocation_pct"] == 103.0
    assert record["model"]["service_level_pct"] == SERVICE_LEVEL_PCT


def test_run_notes_carry_the_ruling_and_the_principals_caveat():
    """A count without a ruling adds no ruling line; Unilever's territory
    caveat goes with every Unilever plan; Del Monte has no caveat on file."""
    march = {**_OPENING_COUNT, "period": "2026-01", "counted_on": "2026-02-03"}
    assert run_notes({"unilever": march}) == [f"unilever: {PLANNING_NOTES['unilever']}"]
    assert run_notes({"delmonte": {**_OPENING_COUNT, "counted_on": None}}) == []
    assert run_notes({"unilever": _OPENING_COUNT})[0].startswith(
        "unilever stock count 2026-02 (counted 2026-03-02): accepted for planning, pending SSM confirmation")


class _FakeDB:
    """psycopg2 stand-in for main(): one connection and cursor that answer
    run_lp's queries from memory and record every statement sent.
    counts: {period: [(principal, row_count, counted_on)]};
    stock: {period: {product_key: pieces}}."""

    def __init__(self, counts, stock, candidates=((1, "SKU1", "unilever"),), packs=None, pack_columns=True):
        self.counts, self.stock = counts, stock
        self.packs, self.pack_columns = packs or {}, pack_columns
        self.candidates = [(k, sku, who, CYCLE, 1200.0, 0.5) for k, sku, who in candidates]
        self.statements: list[tuple[str, object]] = []
        self.description = None
        self.rowcount = -1
        self._rows: list = []

    # connection
    def set_session(self, **kwargs):
        pass

    def cursor(self):
        return self

    def close(self):
        pass

    # cursor
    def execute(self, sql, params=None):
        flat = " ".join(sql.split())
        self.statements.append((flat, params))
        self.description, self._rows, self.rowcount = None, [], -1
        if "to_regclass('lp_run')" in flat:
            self._rows = [(True,)]
        elif "column_name IN ('q_i_before_pack_rounding', 'pack_size')" in flat:
            self._rows = [(self.pack_columns,)]
        elif "pd_pack.pack_size::numeric" in flat and "AS in_stock_file" not in flat:
            self._rows = [(k, v) for k, v in self.packs.items() if k in params[0]]
        elif "FROM Forecast_Result fr" in flat:
            self._rows = list(self.candidates)
        elif "FROM SellOut_Fact_Real" in flat:
            months = [f"2025-{m:02d}" for m in range(1, 13)] + ["2026-01", "2026-02"]
            self._rows = [(1, "SKU1", "unilever", p, 1000.0 + 10 * i, 50_000.0) for i, p in enumerate(months)]
        elif "GROUP BY inv.principal, inv._period" in flat:
            self.description = [(c,) for c in ("principal", "period", "row_count", "first_date", "last_date")]
            period = params["count_period"]
            self._rows = [(who, period, n, on, on) for who, n, on in self.counts.get(period, [])]
        elif "AS in_stock_file" in flat:
            pieces = self.stock.get(params["stock_period"], {})
            self._rows = [(k, k in pieces, pieces.get(k), 10.0) for k in params["product_keys"]]
        elif flat.startswith("INSERT INTO lp_run"):
            self._rows = [(41,)]
        elif flat.startswith("INSERT INTO LP_Recommendation"):
            self.rowcount = 1

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0]


def _run_main(monkeypatch, db, *flags):
    import scripts.run_lp as run_lp

    monkeypatch.setattr(run_lp.psycopg2, "connect", lambda url: db)
    monkeypatch.setattr(run_lp, "load_dotenv", lambda **kwargs: None)
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://fake")
    monkeypatch.setattr(sys, "argv", ["run_lp.py", *flags])
    run_lp.main()


def test_main_refuses_a_cycle_without_its_opening_count(monkeypatch, caplog):
    """Only the later count (2026-03, counted 2026-04-06) exists: the cycle
    is refused with the reason, nothing is written, and no stock is read
    at all, so the later count can't stand in."""
    db = _FakeDB(counts={"2026-03": [("unilever", 785, _COUNTED_2026_04_06)]}, stock={"2026-03": {1: 500.0}})
    with caplog.at_level(logging.INFO, logger="scripts.run_lp"):
        _run_main(monkeypatch, db)
    sent = [s for s, _ in db.statements]
    assert not any(s.startswith("INSERT") for s in sent)  # no lp_run row, no plan row
    assert not any("AS in_stock_file" in s for s in sent)
    assert [p["count_period"] for s, p in db.statements if "GROUP BY inv.principal" in s] == ["2026-02"]
    assert "no opening stock count for March 2026: unilever has no stock count for February 2026" in caplog.text


def test_a_refusal_in_the_cycle_retires_nothing(monkeypatch, caplog):
    """Unilever has its opening count, Del Monte doesn't. Unilever is
    planned; Del Monte's pending rows weren't replanned, so
    --retire-stale-pending must not treat them as outside the pool."""
    db = _FakeDB(counts={"2026-02": [("unilever", 812, _COUNTED_2026_03_02)]}, stock={"2026-02": {1: 2000.0}},
                 candidates=((1, "SKU1", "unilever"), (2, "DM2", "delmonte")))
    with caplog.at_level(logging.INFO, logger="scripts.run_lp"):
        _run_main(monkeypatch, db, "--retire-stale-pending")
    sent = [s for s, _ in db.statements]
    assert any(s.startswith("INSERT INTO LP_Recommendation") for s in sent)  # Unilever planned
    assert not any(s.startswith("SELECT * FROM LP_Recommendation") or s.startswith("DELETE") for s in sent)
    assert "no opening stock count for March 2026: delmonte has no stock count for February 2026" in caplog.text
    assert "--retire-stale-pending skipped" in caplog.text


def test_main_plans_from_the_opening_count_and_links_its_rows_to_the_run(monkeypatch, tmp_path, caplog):
    """Both counts exist and disagree (2,000 pieces opening March, 500 at
    the end of it): the plan takes the opening one, writes its lp_run row
    first and points every plan row at it, all in one transaction."""
    db = _FakeDB(
        counts={"2026-02": [("unilever", 812, _COUNTED_2026_03_02)],
                "2026-03": [("unilever", 785, _COUNTED_2026_04_06)]},
        stock={"2026-02": {1: 2000.0}, "2026-03": {1: 500.0}},
    )
    csv_path = tmp_path / "plan.csv"
    with caplog.at_level(logging.INFO, logger="scripts.run_lp"):
        _run_main(monkeypatch, db, "--allocation-pct", "103", "--csv", str(csv_path))
    # The 2026-02 count is a reviewed outlier: planned from, and said so.
    assert any(r.levelno == logging.WARNING and "that count is flagged" in r.getMessage() for r in caplog.records)

    assert [p["stock_period"] for s, p in db.statements if "AS in_stock_file" in s] == ["2026-02"]
    sent = [s for s, _ in db.statements]
    run_at = next(i for i, s in enumerate(sent) if s.startswith("INSERT INTO lp_run"))
    upserts = [(i, p) for i, (s, p) in enumerate(db.statements) if s.startswith("INSERT INTO LP_Recommendation")]
    assert len(upserts) == 1 and upserts[0][1][5] == 41  # the row carries the run's key
    assert sent.index("BEGIN") < run_at < upserts[0][0] < sent.index("COMMIT")

    cycle, scope, inputs, model, code_version = db.statements[run_at][1]
    assert (cycle, scope) == (CYCLE, "both")
    count = inputs.adapted["stock_counts"]["unilever"]
    assert (count["period"], count["counted_on"], count["row_count"]) == ("2026-02", "2026-03-02", 812)
    # The team's ruling on that count travels with the plan, with the
    # territory caveat, in lp_run's notes.
    assert count["flag"] == OPENING_COUNT_RULINGS[("unilever", "2026-02")][1]
    assert inputs.adapted["notes"] == [
        f"unilever stock count 2026-02 (counted 2026-03-02): {OPENING_COUNT_RULINGS[('unilever', '2026-02')][1]}",
        f"unilever: {PLANNING_NOTES['unilever']}",
    ]
    assert inputs.adapted["allocation_pct"] == 103.0
    assert model.adapted["service_level_pct"] == SERVICE_LEVEL_PCT
    assert code_version is None or len(code_version) >= 40  # a full commit hash, '+dirty' when uncommitted

    plan = pd.read_csv(csv_path)
    assert plan.loc[0, "stock_on_hand"] == 2000.0
    assert (plan.loc[0, "stock_period"], plan.loc[0, "stock_counted_on"]) == ("2026-02", "2026-03-02")


# --- refuse_empty_demo_plan (2026-10-20): demo run 10 was written with every order at 0.0 because solve_lp
# returned None (falsely Infeasible) and the writer turned None into zeros. ---

def test_demo_plan_with_no_solution_is_refused_not_written_as_zeros():
    import pytest
    from scripts.run_lp import refuse_empty_demo_plan
    with pytest.raises(SystemExit, match="no solution"):
        refuse_empty_demo_plan("demo", None, ["stock on hand is above warehouse_capacity"])


def test_demo_plan_with_every_order_zero_is_refused_and_says_whether_there_was_need():
    import pytest
    from scripts.run_lp import refuse_empty_demo_plan
    with pytest.raises(SystemExit, match="solver or input defect"):
        refuse_empty_demo_plan("demo", {"a": 0.0, "b": 0.0}, need=500.0)
    with pytest.raises(SystemExit, match="already at or above target"):
        refuse_empty_demo_plan("demo", {"a": 0.0}, need=0.0)


def test_demo_plan_with_at_least_one_order_passes():
    from scripts.run_lp import refuse_empty_demo_plan
    refuse_empty_demo_plan("demo", {"a": 0.0, "b": 12.5}, need=500.0)


def test_unilever_demo_writer_never_defaults_a_missing_order_to_zero():
    src = (Path(__file__).resolve().parents[2] / "scripts/run_lp.py").read_text(encoding="utf-8")
    body = src[src.index("def _run_demo_lp_unilever"):src.index("def main()")]
    assert "(plan.orders or {})" not in body
    assert "refuse_empty_demo_plan(" in body


# --- case-pack rounding (migration 0066) ---

def _opening_db(**kwargs):
    return _FakeDB(counts={"2026-02": [("unilever", 812, _COUNTED_2026_03_02)]}, stock={"2026-02": {1: 2000.0}}, **kwargs)


def test_a_real_run_keeps_the_order_before_rounding_and_the_pack_size(monkeypatch):
    db = _opening_db(packs={1: 24.0})
    _run_main(monkeypatch, db, "--allocation-pct", "103")
    (params,) = [p for s, p in db.statements if s.startswith("INSERT INTO LP_Recommendation")]
    q_i, before, pack = params[2], params[6], params[7]
    assert pack == 24.0 and q_i % 24.0 == 0 and abs(q_i - before) < 24.0


def test_a_real_run_without_the_0066_columns_refuses_and_writes_nothing(monkeypatch, caplog):
    db = _opening_db(packs={1: 24.0}, pack_columns=False)
    with caplog.at_level(logging.INFO, logger="scripts.run_lp"):
        _run_main(monkeypatch, db)
    assert not any(s.startswith("INSERT") for s, _ in db.statements)
    assert "0066_lp_case_pack_rounding.sql" in caplog.text


def test_without_the_0066_columns_the_old_behaviour_is_available_by_flag(monkeypatch):
    db = _opening_db(packs={1: 24.0}, pack_columns=False)
    _run_main(monkeypatch, db, "--no-case-pack-rounding")
    (params,) = [p for s, p in db.statements if s.startswith("INSERT INTO LP_Recommendation")]
    assert len(params) == 6   # the pre-0066 upsert: no extra columns

