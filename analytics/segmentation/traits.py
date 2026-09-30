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

from analytics.params import SBC_ADI_CUT

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


def from_first_sale(qty: np.ndarray) -> np.ndarray:
    """The series from the first quantity_sold > 0 month onward (empty if
    the SKU never sold). Zeros BEFORE the first sale are "not launched
    yet", not zero demand — a trait computed across them measures how new
    the SKU is, not how it sells (2026-09-20: over the full zero-padded
    series 45 of 47 Tier A SKUs with <24 sales months read trend='up';
    from first sale, 4 do). Zeros AFTER the first sale are genuine
    zero-demand months and stay in."""
    idx = first_sale_index(qty)
    return qty[idx:] if idx is not None else qty[:0]


def active_months(qty: np.ndarray) -> int:
    """Calendar months from first sale to the end of the window."""
    return len(from_first_sale(qty))


def average_demand_interval(qty: np.ndarray, observed: np.ndarray | None = None) -> float | None:
    """ADI = months from the first sale to the end of the window / months
    with a sale (1.0 = sold every month). None if the SKU never sold.

    `observed` (bool, same length as qty) marks the months the PRINCIPAL
    has any demand rows for. A month no product has a row for is a data
    gap, not a zero-sale month (Yuan, 2026-09-30), so it is dropped before
    counting; otherwise one missing file makes every SKU look
    intermittent. None = every month observed.

    The one ADI definition: baseline.demand_class and classification.fsn
    call this, and is_intermittent_adi is the one comparison."""
    qty = np.asarray(qty, dtype=float)
    if observed is not None:
        qty = qty[np.asarray(observed, dtype=bool)]
    n_pos = history_months(qty)
    return active_months(qty) / n_pos if n_pos else None


def is_intermittent_adi(adi: float) -> bool:
    """Syntetos, Boylan & Croston (2005): ADI >= 1.32 is intermittent. The
    tie goes to intermittent, the same side everywhere in this codebase."""
    return adi >= SBC_ADI_CUT


def trend_stats(qty: np.ndarray, alpha: float = MANN_KENDALL_ALPHA) -> tuple[str, float | None, float | None]:
    """(label, mann_kendall_p, theil_sen_slope) from first sale onward.
    label is 'up'/'down' only if p < alpha; otherwise 'none' (including
    series too short or constant, where the test itself is uninformative
    rather than silently 'none' by coincidence — p and slope are None
    there). Significance is Mann-Kendall; Theil-Sen is its paired slope
    estimator (median of pairwise slopes, units/month) and carries the
    magnitude, not a second vote on significance."""
    qty = from_first_sale(qty)
    n = len(qty)
    if n < 2:
        return "none", None, None
    s = 0
    for i in range(n - 1):
        s += np.sum(np.sign(qty[i + 1:] - qty[i]))
    var_s = n * (n - 1) * (2 * n + 5) / 18.0
    if var_s <= 0:
        return "none", None, None
    slope = float(stats.theilslopes(qty, np.arange(n))[0])
    if s > 0:
        z = (s - 1) / np.sqrt(var_s)
    elif s < 0:
        z = (s + 1) / np.sqrt(var_s)
    else:
        return "none", 1.0, slope
    p = float(2 * (1 - stats.norm.cdf(abs(z))))
    if p >= alpha:
        return "none", p, slope
    return ("up" if z > 0 else "down"), p, slope


def mann_kendall_trend(qty: np.ndarray, alpha: float = MANN_KENDALL_ALPHA) -> str:
    """Mann-Kendall trend label from first sale onward — see trend_stats."""
    return trend_stats(qty, alpha)[0]


def coefficient_of_variation(qty: np.ndarray) -> float | None:
    """std/mean from first sale onward (see from_first_sale). None if the
    mean is not positive (a CV of a non-positive-mean series is not
    meaningful, never fabricated as 0 or inf)."""
    qty = from_first_sale(qty)
    if len(qty) == 0:
        return None
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
