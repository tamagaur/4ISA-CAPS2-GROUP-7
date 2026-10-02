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
from analytics.optimization.lp_inputs import PLACEHOLDERS
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
             sigma_d=50.0, principal="unilever"):
    return ProductInput(product_key=key, sku_id=f"SKU{key}", principal=principal, forecast=forecast,
                        sigma_d=sigma_d, stock_on_hand=stock, in_stock_file=True, cost_per_piece=cost,
                        prior_year_pieces=prior_year_pieces, prior_year_revenue=revenue)


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
    """One place (analytics/optimization/lp_inputs.PLACEHOLDERS) feeds both
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
    it on conn.close() and on any error exit, so no path can leave it open."""
    source = (Path(__file__).resolve().parents[2] / "scripts/run_lp.py").read_text(encoding="utf-8")
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
