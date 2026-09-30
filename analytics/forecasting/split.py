"""
analytics.forecasting.split — the temporal train/holdout split every
forecast evaluation shares (the runner, the router preview, the dev viewer).

Moved here from the retired analytics/forecasting/sarima.py (2026-09-30), so
live code no longer imports the retired module (or statsmodels) just to
split a series. sarima.py re-exports it unchanged. The fraction is
analytics.params.HOLDOUT_FRACTION (reports/BAKEOFF_8020_PROTOCOL.md).
"""
from __future__ import annotations

import pandas as pd

from analytics.params import HOLDOUT_FRACTION


def train_holdout_split(
    series: pd.Series, holdout_fraction: float = HOLDOUT_FRACTION
) -> tuple[pd.Series, pd.Series]:
    """Step 14: strictly temporal 80/20 split. First 80% (by position, on
    a series already sorted ascending by date) is training; last 20% is
    holdout. NEVER a random split — a shuffled split would leak future
    information into training and invalidate every downstream metric.

    Raises ValueError if the series isn't sorted ascending by index, or
    if either resulting half would be empty.
    """
    if not series.index.is_monotonic_increasing:
        raise ValueError(
            "train_holdout_split requires series sorted ascending by date; "
            "sort the series before calling (do not silently re-sort here — "
            "an unsorted input usually signals an upstream bug)."
        )
    if not 0 < holdout_fraction < 1:
        raise ValueError(f"holdout_fraction must be in (0, 1); got {holdout_fraction}")

    n_holdout = max(1, round(len(series) * holdout_fraction))
    split_idx = len(series) - n_holdout

    if split_idx < 1:
        raise ValueError(
            f"Series too short to split: {len(series)} points, "
            f"holdout_fraction={holdout_fraction} leaves no training data."
        )

    train, holdout = series.iloc[:split_idx], series.iloc[split_idx:]

    # Belt-and-suspenders: confirm no temporal overlap (Step 14's "validate
    # split boundaries" checkpoint), not just trust the positional slice.
    if train.index.max() >= holdout.index.min():
        raise ValueError(
            "train_holdout_split produced overlapping boundaries — the "
            "input series likely has duplicate or unsorted timestamps."
        )

    return train, holdout
