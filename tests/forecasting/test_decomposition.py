"""tests/forecasting/test_decomposition.py — analytics/forecasting/decomposition.py (STL)."""
from __future__ import annotations

import math

from analytics.forecasting.decomposition import MIN_MONTHS, stl_summary


def _periods(start_year: int, start_month: int, n: int) -> list[str]:
    out = []
    y, m = start_year, start_month
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def test_strong_seasonality_is_found_with_its_peak_month():
    periods = _periods(2023, 1, 36)
    # Peaks every December (month index 11), gentle upward trend, tiny noise.
    values = [1000 + 5 * i + 300 * math.cos(2 * math.pi * (i - 11) / 12) + (3 if i % 2 else -3) for i in range(36)]
    s = stl_summary(periods, values)
    assert s["available"] is True
    assert s["seasonal_strength"] > 0.8
    assert s["peak_month"] == "Dec"
    assert s["trough_month"] == "Jun"
    assert s["seasonal_swing_pct"] > 30
    assert len(s["trend"]) == len(s["seasonal"]) == len(s["resid"]) == 36


def test_series_shorter_than_two_cycles_is_not_decomposed():
    s = stl_summary(_periods(2024, 1, 20), [10.0] * 20)
    assert s["available"] is False
    assert str(MIN_MONTHS) in s["reason"]


def test_months_before_first_sale_are_dropped():
    periods = _periods(2023, 1, 30)
    values = [0.0] * 6 + [100 + 10 * math.sin(i) for i in range(24)]
    s = stl_summary(periods, values)
    assert s["available"] is True
    assert s["months"] == 24
    assert s["periods"][0] == "2023-07"


def test_never_sold_is_not_decomposed():
    assert stl_summary(_periods(2023, 1, 30), [0.0] * 30)["available"] is False
