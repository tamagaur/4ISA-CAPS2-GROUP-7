"""scripts.build_unilever_demo.build(): the one-step MA3 forecast added by migration 0056 — each SKU's own last
3 real months (real_copy + real in-span zeros), named and left out when there are fewer than 3 or one is blank."""
from scripts.build_unilever_demo import build


def _rows(pk, code, by_month):
    return [(pk, code, m, q, (q * 5 if q is not None else None)) for m, q in by_month.items()]


def test_forecasts_the_month_after_the_last_real_month_from_its_own_last_three():
    rows = _rows(1, "A", {"2025-01": 10.0, "2025-02": 20.0, "2025-03": 30.0})
    _series, _excluded, forecasts, forecast_excluded = build(rows)
    assert forecast_excluded == []
    [(pk, code, period, qty, method, history)] = forecasts
    assert (pk, code, period, qty, method, history) == (1, "A", "2025-04", 20.0, "ma3", 3)


def test_an_in_span_gap_counts_as_a_real_zero_in_the_window():
    rows = _rows(1, "A", {"2025-01": 30.0, "2025-02": 30.0, "2025-04": 30.0})  # 2025-03 has no row: real zero
    _series, _excluded, forecasts, forecast_excluded = build(rows)
    assert forecast_excluded == []
    assert forecasts[0][2:4] == ("2025-05", 20.0)  # last 3 real-window months: 30, 0, 30 -> avg 20


def test_fewer_than_three_real_months_is_named_and_left_out():
    rows = _rows(1, "A", {"2025-01": 10.0, "2025-02": 20.0})
    _series, _excluded, forecasts, forecast_excluded = build(rows)
    assert forecasts == []
    assert forecast_excluded[0][1] == "2 real month(s); 3 needed for MA3"


def test_a_blank_capture_in_the_last_three_months_is_named_and_left_out():
    rows = _rows(1, "A", {"2025-01": 10.0, "2025-02": None, "2025-03": 30.0})
    _series, _excluded, forecasts, forecast_excluded = build(rows)
    assert forecasts == []
    assert forecast_excluded[0][1] == "a blank-capture month falls in the last 3 real months"
