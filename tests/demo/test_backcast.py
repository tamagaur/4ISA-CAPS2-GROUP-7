"""analytics.demo.backcast: the 2021-01..2022-12 back-cast (flat, own level and CV, own origin, anchored on 2023-01)."""
import statistics

from analytics.demo.backcast import ANCHOR_PERIOD, backcast_series, months

REAL = {"2023-01": 100.0, "2023-02": 110.0, "2023-03": 90.0, "2023-04": 120.0, "2023-05": 80.0}
AMT = {p: v * 5 for p, v in REAL.items()}


def test_covers_exactly_2021_01_to_2022_12_and_nothing_else():
    r = backcast_series("/A", REAL, AMT)
    assert [p for p, _, _ in r.points] == months() and len(r.points) == 24
    assert r.points[0][0] == "2021-01" and r.points[-1][0] == "2022-12"
    assert all(p < ANCHOR_PERIOD for p, _, _ in r.points)


def test_flat_has_no_trend_whatever_order_the_real_months_come_in():
    up = {"2023-01": 10.0, "2023-02": 20.0, "2023-03": 30.0, "2023-04": 40.0}
    down = {"2023-01": 40.0, "2023-02": 30.0, "2023-03": 20.0, "2023-04": 10.0}
    a, b = backcast_series("/T", up, {}, jitter_scale=0.0), backcast_series("/T", down, {}, jitter_scale=0.0)
    assert [q for _, q, _ in a.points] == [25.0] * 24 == [q for _, q, _ in b.points]


def test_level_is_the_series_own_mean_and_jitter_uses_its_own_cv():
    r = backcast_series("/A", REAL, AMT)
    assert r.level == statistics.fmean(REAL.values())
    assert abs(r.cv - statistics.stdev(REAL.values()) / r.level) < 1e-12
    flat = backcast_series("/F", {p: 50.0 for p in REAL}, {})
    assert flat.cv == 0.0 and {q for _, q, _ in flat.points} == {50.0}


def test_same_seed_same_output_and_series_are_independent():
    a = backcast_series("/A", REAL, AMT, seed=7)
    _ = backcast_series("/B", REAL, AMT, seed=7)
    b = backcast_series("/A", REAL, AMT, seed=7)
    assert a.points == b.points and a.points != backcast_series("/A", REAL, AMT, seed=8).points


def test_series_first_seen_after_the_start_of_records_is_not_projected_back():
    later = {"2023-06": 5.0, "2023-07": 6.0, "2023-08": 7.0, "2023-09": 8.0}
    r = backcast_series("/L", later, {})
    assert r.points == [] and "after the start of SSM's records" in r.excluded_reason


def test_too_few_months_with_sales_is_named_not_back_cast():
    r = backcast_series("/S", {"2023-01": 4.0, "2023-02": 0.0, "2023-03": 5.0}, {})
    assert r.points == [] and "need" in r.excluded_reason


def test_unilever_in_span_zero_months_lower_the_level_blank_months_do_not():
    q = {"2023-01": 10.0, "2023-02": 10.0, "2023-05": 10.0, "2023-06": 10.0}  # 2023-03/04 have no row: real zeros
    zero = backcast_series("/U", q, {}, zero_months_in_span=True, jitter_scale=0.0)
    assert zero.level == 40.0 / 6
    blank = backcast_series("/U", {**q, "2023-03": None, "2023-04": None}, {}, zero_months_in_span=True, jitter_scale=0.0)
    assert blank.level == 10.0  # a blank capture is neither a sale nor a zero
