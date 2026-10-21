"""kpi_trend (backend/chart_insights.py): the comparison count may not sit more than a year back (audit FE-3)."""
from backend.chart_insights import MAX_COMPARE_GAP_MONTHS, kpi_trend


def test_a_comparison_22_months_back_gives_no_percentage_and_names_the_gap():
    # Del Monte's real stock counts: Feb 2024, then Dec 2025 (nothing between).
    trend = kpi_trend({"2024-02": 13_325_350.0, "2025-12": 6_683_837.0}, "2025-12")
    assert trend["delta_pct"] is None
    assert trend["months_apart"] == 22
    assert "Feb 2024" in trend["delta_blocked_reason"] and "22 months" in trend["delta_blocked_reason"]


def test_a_comparison_within_a_year_is_unchanged():
    trend = kpi_trend({"2025-03": 100.0, "2025-12": 150.0}, "2025-12")
    assert trend["delta_pct"] == 50.0
    assert trend["delta_blocked_reason"] is None


def test_exactly_the_limit_is_still_compared():
    trend = kpi_trend({"2025-01": 100.0, f"2026-01": 110.0}, "2026-01")
    assert trend["months_apart"] == MAX_COMPARE_GAP_MONTHS and trend["delta_pct"] == 10.0
