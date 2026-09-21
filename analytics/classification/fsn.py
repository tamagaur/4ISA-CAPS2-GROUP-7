"""
analytics.classification.fsn — FSN (fast / slow / non-moving) by movement
frequency: the analytical mapping's D3, "how do these SKUs differ in
movement frequency — fast, slow, or non-moving?".

Per product, over the last FSN_WINDOW_MONTHS OBSERVED months up to a
reference month:

  N  non-moving  no sale in the last NON_MOVING_MONTHS observed months — the
                 same six-month rule the forecast runner uses for a dead SKU
                 (Forecast_Result.status = 'dead_sku').
  F  fast        sells regularly: ADI <= FAST_ADI_MAX, with at least
                 MIN_FAST_SALES_MONTHS months of sales. ADI (average demand
                 interval) = observed months since the first sale in the
                 window / months with a sale — sku_traits.adi's definition,
                 restricted to the window. 1.32 is the Syntetos–Boylan
                 cut-off between regular and intermittent demand.
  S  slow        everything else that sold in the window: intermittent, or
                 too few sales months to call regular.

"Observed" months are the months the principal has ANY data for. Del
Monte's sell-out files are missing for whole months; counting those as
zero-sale months would call a category slow for a gap in the files, so the
caller leaves unobserved months out of the array.

Pure functions, no DB — the caller builds the arrays (the convention of
classify_abc and analytics.segmentation.traits).
"""
from __future__ import annotations

import numpy as np

FSN_WINDOW_MONTHS = 12
NON_MOVING_MONTHS = 6
FAST_ADI_MAX = 1.32
MIN_FAST_SALES_MONTHS = 3

FSN_LABELS = {"F": "Fast-moving", "S": "Slow-moving", "N": "Non-moving"}


def classify_fsn(qty) -> dict:
    """Classify one product from its quantities in the window's observed
    months, oldest first (zeros are real zero-sale months).

    Returns {fsn, adi, months_with_sales, months_observed}; adi is None for
    a non-moving product (no recent sale, so no interval to measure)."""
    q = np.asarray(qty, dtype=float)
    months_observed = int(len(q))
    sold = q > 0
    months_with_sales = int(sold.sum())
    if months_observed == 0 or not sold[-NON_MOVING_MONTHS:].any():
        return {"fsn": "N", "adi": None, "months_with_sales": months_with_sales, "months_observed": months_observed}
    active = months_observed - int(np.argmax(sold))
    adi = active / months_with_sales
    fast = adi <= FAST_ADI_MAX and months_with_sales >= MIN_FAST_SALES_MONTHS
    return {
        "fsn": "F" if fast else "S",
        "adi": round(adi, 3),
        "months_with_sales": months_with_sales,
        "months_observed": months_observed,
        # Observed months from the first sale in the window — ADI's
        # denominator's partner, so a reader can see "6 of 6 since launch".
        "active_months": active,
    }
