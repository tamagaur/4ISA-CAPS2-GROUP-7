"""analytics.demo.dm_interpolate: the fill rules of the labelled Del Monte demonstration (CLAUDE.md rule 2)."""
from analytics.demo.dm_interpolate import MIN_MONTHS, fill_series, month_index, months_between

Q = {"2025-03": 100.0, "2025-04": 120.0, "2025-06": 90.0, "2025-09": 150.0, "2025-12": 110.0}
A = {p: v * 20.0 for p, v in Q.items()}


def test_every_generated_month_sits_between_two_real_months():
    r = fill_series("/X", Q, A)
    interp = [p for p in r.points if p.origin == "interpolated"]
    assert [p.period for p in interp] == ["2025-05", "2025-07", "2025-08", "2025-10", "2025-11"]
    assert r.interpolated_months == 5 and r.real_months == 5
    first, last = min(Q), max(Q)
    assert all(first < p.period < last for p in interp)


def test_never_extrapolates_before_first_or_after_last_real_month():
    r = fill_series("/X", Q, A, window_end="2026-02")
    periods = [p.period for p in r.points]
    assert min(periods) == "2025-03" and max(periods) == "2025-12"
    assert [p.origin for p in r.points if p.period in Q] == ["real_copy"] * 5


def test_months_after_window_end_are_ignored():
    r = fill_series("/X", {**Q, "2026-02": 9999.0}, {**A, "2026-02": 1.0}, window_end="2025-12")
    assert max(p.period for p in r.points) == "2025-12"


def test_same_seed_same_series_and_other_series_do_not_move_it():
    a = fill_series("/X", Q, A, seed=7)
    b = fill_series("/X", Q, A, seed=7)
    _ = fill_series("/Y", {"2025-01": 1.0, "2025-03": 5.0, "2025-05": 2.0}, {}, seed=7)
    assert [(p.period, p.quantity, p.net_amount) for p in a.points] == [(p.period, p.quantity, p.net_amount) for p in b.points]
    c = fill_series("/X", Q, A, seed=8)
    assert [p.quantity for p in a.points] != [p.quantity for p in c.points]


def test_jitter_comes_from_the_series_own_cv_so_a_flat_series_is_a_straight_line():
    flat = {"2025-01": 50.0, "2025-02": 50.0, "2025-04": 50.0, "2025-05": 50.0}
    r = fill_series("/F", flat, {}, seed=1)
    assert r.cv == 0.0
    assert [p.quantity for p in r.points if p.origin == "interpolated"] == [50.0]


def test_interpolation_follows_the_local_trend_not_the_overall_mean():
    s = {"2025-01": 10.0, "2025-02": 20.0, "2025-03": 30.0, "2025-05": 50.0, "2025-06": 60.0}  # trend, gap at 04
    r = fill_series("/T", s, {}, seed=3, jitter_scale=0.0)
    v = {p.period: p.quantity for p in r.points}
    assert v["2025-04"] == 40.0  # midpoint of its two anchors, not the series mean (34)


def test_too_few_months_is_named_and_left_out():
    r = fill_series("/S", {"2025-03": 4.0, "2025-04": 5.0}, {})
    assert r.excluded_reason and str(MIN_MONTHS) in r.excluded_reason and r.points == []


def test_anchoring_run_lengths():
    r = fill_series("/X", Q, A)
    first = r.fills[0]  # gap 2025-05: left run 2025-03..04 = 2, right run 2025-06 = 1
    assert (first.start, first.n_months, first.left_run, first.right_run) == ("2025-05", 1, 2, 1)
    assert first.anchoring_run == 2


def test_month_helpers():
    assert months_between("2025-11", "2026-02") == ["2025-12", "2026-01"]
    assert month_index("2026-01") - month_index("2025-12") == 1
