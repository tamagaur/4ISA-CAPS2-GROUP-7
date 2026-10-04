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
    periods = _periods(2023, 1, 42)
    values = [0.0] * 6 + [100 + 10 * math.sin(i) for i in range(36)]
    s = stl_summary(periods, values)
    assert s["available"] is True
    assert s["months"] == 36
    assert s["periods"][0] == "2023-07"


def test_two_cycles_are_not_enough_to_call_seasonality():
    """Robust STL on 24-30 months read pure noise as "Strong" seasonality
    most of the time (2026-09-29), so a series needs three full cycles."""
    assert MIN_MONTHS == 36
    s = stl_summary(_periods(2023, 1, 30), [100 + 10 * math.sin(i) for i in range(30)])
    assert s["available"] is False
    assert s["months"] == 30
    assert "36 months" in s["reason"]


def test_never_sold_is_not_decomposed():
    assert stl_summary(_periods(2023, 1, 30), [0.0] * 30)["available"] is False


# ---- the seasonality label: yearly_pattern (2026-10-04) --------------------
from analytics.forecasting.decomposition import (  # noqa: E402
    LABEL_NO_PATTERN, LABEL_REPEATS, LABEL_SHORT, yearly_pattern,
)


def test_a_clean_yearly_cycle_repeats_yearly():
    values = [1000 + 300 * math.cos(2 * math.pi * (i - 11) / 12) for i in range(38)]
    y = yearly_pattern(values)
    assert y["label"] == LABEL_REPEATS and y["repeats_yearly"] is True
    assert y["acf_lag12"] > y["acf_bound"] == round(1.96 / math.sqrt(38), 3)


def test_under_24_months_from_the_first_sale_is_not_enough_history():
    # 30 months on record, but the first 8 are before the first sale.
    values = [0.0] * 8 + [100 + 50 * math.cos(2 * math.pi * i / 12) for i in range(22)]
    y = yearly_pattern(values)
    assert y["label"] == LABEL_SHORT == "Not enough history (needs 24 months)"
    assert y["repeats_yearly"] is None and y["months"] == 22


def test_a_flat_or_anti_yearly_series_does_not_repeat_yearly():
    assert yearly_pattern([50.0] * 30)["label"] == LABEL_NO_PATTERN
    # Each month runs opposite to the same month a year earlier: a strong
    # NEGATIVE ACF(12) passes |ACF| but is not a yearly repeat.
    flip = [100 + (40 if (i // 12) % 2 == 0 else -40) * math.cos(2 * math.pi * i / 12) for i in range(38)]
    y = yearly_pattern(flip)
    assert y["acf_lag12"] < -y["acf_bound"]
    assert y["label"] == LABEL_NO_PATTERN and y["repeats_yearly"] is False
