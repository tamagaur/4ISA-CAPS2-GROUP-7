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
import math

import pandas as pd
import pytest

from analytics.optimization.lp import Z_SCORE, weekly_demand
from analytics.optimization.lp_inputs import PLACEHOLDERS
from scripts.run_lp import (
    UPSERT_QUERY,
    ProductInput,
    _non_negative_float,
    _positive_float,
    allocation_ceilings,
    build_parser,
    plan_cycle,
    product_input,
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
