"""tests/forecasting/test_category_trend.py — analytics/forecasting/category_trend.py."""
from __future__ import annotations

import pytest

from analytics.forecasting.category_trend import MIN_POINTS, project_category


def test_steadily_growing_category():
    values = [1000 + 20 * i for i in range(24)]
    p = project_category(values)
    assert p["available"] is True
    assert p["direction"] == "growing"
    assert p["slope_per_month"] == pytest.approx(20.0)
    # Next 12 months on the line vs the last 12 on the same line: +240 per month.
    last12 = sum(1000 + 20 * i for i in range(12, 24))
    next12 = sum(1000 + 20 * i for i in range(24, 36))
    assert p["change_pct"] == pytest.approx(round((next12 - last12) / last12 * 100, 1))
    assert p["change_pct_low"] <= p["change_pct"] <= p["change_pct_high"]
    assert len(p["projection"]) == 12


def test_declining_category():
    p = project_category([5000 - 60 * i for i in range(24)])
    assert p["direction"] == "declining"
    assert p["change_pct"] < 0


def test_trendless_noise_is_flat():
    values = [1000, 1040, 980, 1010, 995, 1030, 970, 1005, 1020, 990, 1000, 1015] * 2
    assert project_category(values)["direction"] == "flat"


def test_only_the_last_24_months_are_used():
    old_boom = [9000] * 12
    recent = [1000 + 10 * i for i in range(24)]
    p = project_category(old_boom + recent)
    assert p["points"] == 24
    assert p["direction"] == "growing"


def test_too_few_months_gives_the_reason_not_a_line():
    p = project_category([10.0] * (MIN_POINTS - 1))
    assert p["available"] is False
    assert str(MIN_POINTS) in p["reason"]


def test_projection_never_goes_negative():
    p = project_category([1200 - 100 * i for i in range(12)])
    assert min(p["projection"]) >= 0


def test_line_starts_at_the_first_sale():
    """Months before a category existed are not zero demand: the line and the
    Mann–Kendall test both start at the first sale (MINI MEALS, 2026-09-25)."""
    ramp = [100 + 10 * i for i in range(18)]
    p = project_category([0.0] * 6 + ramp)
    assert p["available"] is True
    assert p["points"] == 18
    assert len(p["fitted"]) == 18
    assert p["slope_per_month"] == pytest.approx(10.0)


def test_no_sales_in_the_window_is_labelled_not_flat():
    p = project_category([500.0] * 6 + [0.0] * 24)
    assert p["available"] is False
    assert p["points"] == 0
    assert p["label"] == "No recent sales"


def test_young_category_counts_months_from_its_first_sale():
    p = project_category([0.0] * 20 + [10.0, 12.0, 14.0, 16.0])
    assert p["available"] is False
    assert p["points"] == 4
    assert p["label"] == "Not enough months"


def test_method_constants_are_the_ones_applied():
    from analytics.forecasting.category_trend import PROJECTION_MONTHS, TREND_WINDOW_MONTHS, method_constants
    m = method_constants()
    assert m["window_months"] == TREND_WINDOW_MONTHS
    assert m["projection_months"] == PROJECTION_MONTHS
    assert m["min_points"] == MIN_POINTS
    assert {"trailing_months", "significance_alpha", "slope_confidence"} <= m.keys()


def test_projection_band_brackets_the_line_and_never_goes_negative():
    """projection_low/high are the slope-confidence lines extended over the
    projection months: ordered, clipped at zero, one value per month."""
    p = project_category([1000 + 20 * i + (5 if i % 2 else -5) for i in range(24)])
    assert len(p["projection_low"]) == len(p["projection"]) == len(p["projection_high"]) == 12
    for lo, hi in zip(p["projection_low"], p["projection_high"]):
        assert 0 <= lo <= hi


def test_projection_band_collapses_onto_a_noiseless_line():
    """With zero noise the slope CI is the slope itself, so the band IS the
    projection — no invented uncertainty."""
    p = project_category([1000.0 + 20 * i for i in range(24)])
    for lo, mid, hi in zip(p["projection_low"], p["projection"], p["projection_high"]):
        assert lo == pytest.approx(mid, abs=0.05)
        assert hi == pytest.approx(mid, abs=0.05)


def test_projection_band_clips_at_zero_for_a_steep_decline():
    p = project_category([2400 - 200 * i for i in range(12)])
    assert p["available"] is True
    assert min(p["projection_low"]) == 0.0
    assert all(v >= 0 for v in p["projection_high"])
