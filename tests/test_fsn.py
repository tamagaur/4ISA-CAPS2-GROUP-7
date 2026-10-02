"""tests/test_fsn.py — analytics/classification/fsn.py (FSN by movement frequency)."""
from __future__ import annotations

import pytest

from analytics.classification.fsn import FAST_ADI_BELOW, classify_fsn


def test_sold_every_month_is_fast():
    result = classify_fsn([5] * 12)
    assert result == {"fsn": "F", "adi": 1.0, "months_with_sales": 12, "months_observed": 12, "active_months": 12}


def test_ten_of_twelve_is_fast_nine_is_slow():
    # ADI 12/10 = 1.2 < 1.32; 12/9 = 1.333 >= 1.32 (the Syntetos–Boylan cut-off).
    assert classify_fsn([1, 0, 1, 1, 0, 1, 1, 1, 1, 1, 1, 1])["fsn"] == "F"
    nine = classify_fsn([1, 0, 1, 0, 1, 0, 1, 1, 1, 1, 1, 1])
    assert nine["fsn"] == "S"
    assert nine["adi"] >= FAST_ADI_BELOW


def test_no_sale_in_last_six_observed_months_is_non_moving():
    result = classify_fsn([9, 9, 9, 9, 9, 9, 0, 0, 0, 0, 0, 0])
    assert result["fsn"] == "N"
    assert result["adi"] is None
    assert result["months_with_sales"] == 6


def test_intermittent_seller_is_slow():
    assert classify_fsn([1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 1])["fsn"] == "S"


def test_new_product_needs_three_sales_months_to_be_fast():
    # First sale two months ago, sold both: ADI 1.0 but only 2 sales months.
    assert classify_fsn([0] * 10 + [4, 4])["fsn"] == "S"
    assert classify_fsn([0] * 9 + [4, 4, 4])["fsn"] == "F"


@pytest.mark.parametrize("qty", [[], [0] * 12])
def test_nothing_sold_is_non_moving(qty):
    assert classify_fsn(qty)["fsn"] == "N"


def test_adi_counts_only_from_first_sale_in_window():
    # 6 observed months, first sale at month 3, then every month: ADI 1.0.
    result = classify_fsn([0, 0, 0, 2, 2, 2])
    assert result["adi"] == 1.0 and result["months_observed"] == 6
