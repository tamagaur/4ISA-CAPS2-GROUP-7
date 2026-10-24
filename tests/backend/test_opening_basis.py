"""opening_basis reaches the API: GET /recommendations and GET /dashboard stock_counts say whether a plan started from a
count or from a projection (backend/stock_units.with_opening_basis, scripts/run_lp.py, migration 0069)."""
from __future__ import annotations

import datetime

from backend.stock_units import stock_count_info, with_opening_basis

CYCLE = datetime.date(2026, 4, 1)
COUNT_ROW = {"row_count": 785, "first_date": datetime.date(2026, 4, 6), "last_date": datetime.date(2026, 4, 6)}
RECORDED_PROJECTED = {"period": "2026-02", "counted_on": "2026-03-02", "opening_basis": "projected", "row_count": 812,
                      "projection": {"sales_actual_products": 700, "expected_receipt_pieces": 1500.0}}


def test_a_plan_made_from_the_opening_count_says_count():
    info = with_opening_basis(stock_count_info("unilever", "2026-03", COUNT_ROW, CYCLE),
                              {"opening_basis": "count", "period": "2026-03"})
    assert info["opening_basis"] == "count" and info["period"] == "2026-03" and info["available"]


def test_a_cycle_with_no_count_and_no_plan_says_nothing():
    info = with_opening_basis(stock_count_info("unilever", "2026-03", None, CYCLE), None)
    assert info["opening_basis"] is None and info["available"] is False


def test_a_projected_plan_says_projected_and_never_presents_the_earlier_count_as_the_opening_months():
    info = with_opening_basis(stock_count_info("unilever", "2026-03", None, CYCLE), RECORDED_PROJECTED)
    assert info["opening_basis"] == "projected" and info["available"] and info["reason"] is None
    assert info["period"] == "2026-02" and info["projected_from_period"] == "2026-02"
    assert info["counted_on"] == "2026-03-02"                 # the earlier count's date, labelled projected
    assert info["count_now_loaded"] is False
    assert info["projection"]["expected_receipt_pieces"] == 1500.0


def test_a_projected_plan_says_so_when_the_opening_count_has_arrived_since():
    info = with_opening_basis(stock_count_info("unilever", "2026-03", COUNT_ROW, CYCLE), RECORDED_PROJECTED)
    assert info["opening_basis"] == "projected" and info["count_now_loaded"] is True
    assert info["period"] == "2026-02"                         # still what the plan used, not the count that came after
