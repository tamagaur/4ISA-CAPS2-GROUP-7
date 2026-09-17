"""
analytics.segmentation.traits — pure, principal-agnostic per-SKU trait
functions for Phase 2 binning (reports/BINNING_ROUND1_2026-09.md).

BINS ONLY: nothing here runs a forecasting model or touches MASE. Every
function takes a plain zero-filled monthly quantity array (ascending by
period, no gaps) and returns one trait value — the caller (orchestrate_
segment.py) is responsible for building that array from whichever
principal's demand source is wired up, same "caller decides the grain"
precedent as analytics.classification.abc.classify_abc().
"""
from __future__ import annotations

import numpy as np
from scipy import stats

MANN_KENDALL_ALPHA = 0.05
RESTART_GAP_MONTHS = 3


def history_months(qty: np.ndarray) -> int:
    """Months with quantity_sold > 0 (not calendar span)."""
    return int(np.sum(qty > 0))


def first_sale_index(qty: np.ndarray) -> int | None:
    """Index of the first month with quantity_sold > 0, or None if the
    SKU never sold in the observed window."""
    nz = np.nonzero(qty > 0)[0]
    return int(nz[0]) if len(nz) else None


def longest_positive_run(qty: np.ndarray) -> int:
    """Longest unbroken run of consecutive quantity_sold > 0 months."""
    longest = current = 0
    for v in qty:
        if v > 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def mann_kendall_trend(qty: np.ndarray, alpha: float = MANN_KENDALL_ALPHA) -> str:
    """Mann-Kendall trend test on the full series. 'up'/'down' only if
    p < alpha; otherwise 'none' (including series too short or constant,
    where the test itself is uninformative rather than silently 'none'
    by coincidence)."""
    n = len(qty)
    if n < 2:
        return "none"
    s = 0
    for i in range(n - 1):
        s += np.sum(np.sign(qty[i + 1:] - qty[i]))
    var_s = n * (n - 1) * (2 * n + 5) / 18.0
    if var_s <= 0:
        return "none"
    if s > 0:
        z = (s - 1) / np.sqrt(var_s)
    elif s < 0:
        z = (s + 1) / np.sqrt(var_s)
    else:
        return "none"
    p = 2 * (1 - stats.norm.cdf(abs(z)))
    if p >= alpha:
        return "none"
    return "up" if z > 0 else "down"


def coefficient_of_variation(qty: np.ndarray) -> float | None:
    """std/mean over the full series. None if the mean is not positive
    (a CV of a non-positive-mean series is not meaningful, never
    fabricated as 0 or inf)."""
    mean = qty.mean()
    if mean <= 0:
        return None
    return float(qty.std(ddof=1) / mean) if len(qty) > 1 else None


def has_restart(qty: np.ndarray, gap_months: int = RESTART_GAP_MONTHS) -> bool:
    """True if the SKU had `gap_months` or more consecutive zero months
    AFTER its first sale, then sold again. Leading zeros before the first
    sale are newness, not a restart, so they never count toward the gap."""
    started = False
    zero_run = 0
    restarted = False
    for v in qty:
        if v > 0:
            if started and zero_run >= gap_months:
                restarted = True
            started = True
            zero_run = 0
        elif started:
            zero_run += 1
    return restarted


def stability_group(tier_a_periods: int, total_periods: int) -> str:
    """Absolute-count stability groups (not membership frequency — see
    reports/ABC_PHASE2_2026-09.md's core/pool discussion for why a
    frequency ratio was set aside there in favor of this simpler,
    already-reported grouping)."""
    if tier_a_periods == total_periods:
        return "all_38"
    if tier_a_periods >= 30:
        return "at_least_30"
    return "churn"
