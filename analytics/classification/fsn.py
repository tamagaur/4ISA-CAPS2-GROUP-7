"""
analytics.classification.fsn — FSN (fast / slow / non-moving) by movement
frequency: the analytical mapping's D3, "how do these SKUs differ in
movement frequency — fast, slow, or non-moving?".

Per product, over the last FSN_WINDOW_MONTHS OBSERVED months up to a
reference month:

  N  non-moving  no sale in the last NON_MOVING_MONTHS observed months — the
                 same six-month rule the forecast runner uses for a dead SKU
                 (Forecast_Result.status = 'dead_sku').
  F  fast        sells regularly: ADI < 1.32 (not intermittent), with at least
                 MIN_FAST_SALES_MONTHS months of sales. ADI (average demand
                 interval) = observed months since the first sale in the
                 window / months with a sale — traits.average_demand_
                 interval, the one ADI definition, restricted to the
                 window. ADI >= 1.32 is intermittent (Syntetos, Boylan &
                 Croston 2005; traits.is_intermittent_adi), so a tie is slow.
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

from analytics.params import DEAD_SKU_MONTHS, FSN_MIN_FAST_SALES_MONTHS, FSN_WINDOW_MONTHS, SBC_ADI_CUT
from analytics.segmentation.traits import average_demand_interval, is_intermittent_adi

NON_MOVING_MONTHS = DEAD_SKU_MONTHS
FAST_ADI_BELOW = SBC_ADI_CUT  # fast needs ADI < this (a tie is intermittent)
MIN_FAST_SALES_MONTHS = FSN_MIN_FAST_SALES_MONTHS

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
    adi = average_demand_interval(q)
    fast = not is_intermittent_adi(adi) and months_with_sales >= MIN_FAST_SALES_MONTHS
    return {
        "fsn": "F" if fast else "S",
        "adi": round(adi, 3),
        "months_with_sales": months_with_sales,
        "months_observed": months_observed,
        # Observed months from the first sale in the window — ADI's
        # denominator's partner, so a reader can see "6 of 6 since launch".
        "active_months": active,
    }
