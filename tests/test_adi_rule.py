"""
tests/test_adi_rule.py — item 4: one ADI definition, one comparison.

ADI = months from the first sale / months with a sale, principal-wide gap
months dropped (Yuan, 2026-09-30), and ADI >= 1.32 is intermittent in every
caller: traits (sku_traits.adi), baseline.demand_class and FSN.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analytics.classification.fsn import classify_fsn
from analytics.forecasting.baseline import demand_class
from analytics.segmentation.traits import average_demand_interval, is_intermittent_adi


def _monthly(values, start="2023-01-01"):
    return pd.Series(np.asarray(values, dtype=float), index=pd.date_range(start, periods=len(values), freq="MS"))


def _tie_33_over_25():
    """33 months, 25 with a (constant) sale, the first and last months sold:
    ADI = 33/25 = 1.32 exactly, CV² = 0."""
    q = np.ones(33)
    q[[2, 5, 8, 11, 14, 17, 20, 23]] = 0.0
    return q


def test_tie_is_intermittent_in_every_caller():
    q = _tie_33_over_25()
    adi = average_demand_interval(q)
    assert adi == pytest.approx(1.32) and is_intermittent_adi(adi)
    assert demand_class(_monthly(q)) == "intermittent"
    assert classify_fsn(q)["fsn"] == "S"


def test_just_below_the_cut_is_regular_in_every_caller():
    q = np.ones(12)
    q[[3, 7]] = 0.0  # 12/10 = 1.2
    assert not is_intermittent_adi(average_demand_interval(q))
    assert demand_class(_monthly(q)) == "smooth"
    assert classify_fsn(q)["fsn"] == "F"


def test_months_before_the_first_sale_are_not_counted():
    # 4 leading zeros then 8 sold months: from the first sale, ADI = 8/8.
    # The old demand_class counted every row: 12/8 = 1.5, intermittent.
    q = [0, 0, 0, 0] + [5.0] * 8
    assert average_demand_interval(np.asarray(q)) == 1.0
    assert demand_class(_monthly(q)) == "smooth"


def test_a_principal_wide_gap_month_is_not_a_zero_sale_month():
    q = np.array([5.0, 0.0, 5.0, 0.0, 5.0, 5.0])  # months 2 and 4 read as zero sales
    assert average_demand_interval(q) == pytest.approx(6 / 4)
    observed = np.array([True, False, True, False, True, True])  # ...but no product had a row
    assert average_demand_interval(q, observed) == 1.0

    series = _monthly(q)
    gaps = [series.index[1], series.index[3]]
    assert demand_class(series) == "intermittent"
    assert demand_class(series, gaps) == "smooth"


def test_a_real_zero_month_still_counts():
    q = np.array([5.0, 0.0, 5.0, 5.0])
    assert average_demand_interval(q, np.ones(4, dtype=bool)) == pytest.approx(4 / 3)
