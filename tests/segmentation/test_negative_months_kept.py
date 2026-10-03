"""tests/segmentation/test_negative_months_kept.py — item 13: a negative
month (returns exceeding sales) reaches the traits as it is (DEC-15:
flagged, never clamped). Both segmentation paths clipped it to 0 before."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from analytics.segmentation.traits import average_demand_interval, coefficient_of_variation, history_months
from backend import data_mode

REPO = Path(__file__).resolve().parents[2]


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _Db:
    def execute(self, stmt, params=None):
        return _Rows([
            {"product_key": 1, "period": "2025-01", "qty": 10.0},
            {"product_key": 1, "period": "2025-02", "qty": -4.0},
            {"product_key": 1, "period": "2025-03", "qty": 12.0},
        ])


def test_preview_matrix_keeps_a_negative_month():
    matrices, periods = data_mode.demand_matrix(_Db(), [1], "2025-01", "2025-03", data_mode.REAL)
    assert periods == ["2025-01", "2025-02", "2025-03"]
    assert list(matrices[1]) == [10.0, -4.0, 12.0]


def test_the_batch_run_no_longer_clips():
    source = (REPO / "analytics/segmentation/orchestrate_segment.py").read_text(encoding="utf-8")
    assert "max(qty, 0.0)" not in source


def test_sales_month_traits_do_not_move_the_cv_does():
    kept, clipped = np.array([10.0, -4.0, 12.0]), np.array([10.0, 0.0, 12.0])
    assert history_months(kept) == history_months(clipped) == 2
    assert average_demand_interval(kept) == average_demand_interval(clipped)
    assert coefficient_of_variation(kept) > coefficient_of_variation(clipped)
