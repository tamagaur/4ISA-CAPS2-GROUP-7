import numpy as np
import pytest

from analytics.segmentation.traits import (
    history_months, first_sale_index, longest_positive_run,
    mann_kendall_trend, coefficient_of_variation, has_restart, stability_group,
)


def test_history_months_counts_only_positive():
    assert history_months(np.array([0, 5, 0, 3, 0])) == 2


def test_first_sale_index_finds_first_positive():
    assert first_sale_index(np.array([0, 0, 4, 0, 2])) == 2


def test_first_sale_index_none_if_never_sold():
    assert first_sale_index(np.array([0, 0, 0])) is None


def test_longest_positive_run():
    assert longest_positive_run(np.array([1, 1, 0, 1, 1, 1, 0])) == 3


def test_longest_positive_run_all_positive():
    assert longest_positive_run(np.array([1, 1, 1])) == 3


def test_longest_positive_run_all_zero():
    assert longest_positive_run(np.array([0, 0, 0])) == 0


def test_mann_kendall_detects_up_trend():
    x = np.arange(1, 25, dtype=float)
    assert mann_kendall_trend(x) == "up"


def test_mann_kendall_detects_down_trend():
    x = np.arange(24, 0, -1, dtype=float)
    assert mann_kendall_trend(x) == "down"


def test_mann_kendall_flat_series_is_none():
    x = np.full(24, 10.0)
    assert mann_kendall_trend(x) == "none"


def test_mann_kendall_too_short_is_none():
    assert mann_kendall_trend(np.array([5.0])) == "none"


def test_mann_kendall_noisy_series_with_no_trend_is_none():
    rng = np.random.default_rng(0)
    x = rng.normal(10, 3, size=30)
    assert mann_kendall_trend(x) == "none"


def test_cv_computed_over_full_series():
    x = np.array([10.0, 10.0, 10.0, 10.0])
    assert coefficient_of_variation(x) == pytest.approx(0.0)


def test_cv_none_for_nonpositive_mean():
    assert coefficient_of_variation(np.array([0.0, 0.0])) is None


def test_restart_true_after_gap_following_a_sale():
    x = np.array([5, 0, 0, 0, 3])
    assert has_restart(x) is True


def test_restart_false_for_leading_zeros_before_first_sale():
    x = np.array([0, 0, 0, 0, 5])
    assert has_restart(x) is False


def test_restart_false_for_short_gap():
    x = np.array([5, 0, 0, 3])
    assert has_restart(x) is False


def test_stability_group_all_38():
    assert stability_group(38, 38) == "all_38"


def test_stability_group_at_least_30():
    assert stability_group(30, 38) == "at_least_30"
    assert stability_group(37, 38) == "at_least_30"


def test_stability_group_churn():
    assert stability_group(0, 38) == "churn"
    assert stability_group(29, 38) == "churn"
