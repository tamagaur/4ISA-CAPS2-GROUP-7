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
