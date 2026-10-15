"""
analytics.demo.dm_interpolate — fill the in-span gaps of one Del Monte category series for the
labelled demonstration pipeline (CLAUDE.md hard rule 2; migration 0052).

Pure functions, no database. The rules (Kelvin, 2026-10-15):

  * A generated month sits BETWEEN two real months of the same series: linear interpolation between
    the real value either side, then a small seeded jitter whose size comes from THAT series' own
    coefficient of variation (never a draw around the overall mean, which would discard the trend).
  * No extrapolation: nothing before a series' first real month or after its last.
  * Fixed seed; each series has its own stream derived from (seed, series key), so the same series
    regenerates identically whatever else is in the run.
  * A series with fewer than MIN_MONTHS months between its first and last real month (MA3 needs 3)
    is named and left out, not rescued.
  * Generated rows carry origin 'interpolated'; real months 'real_copy'.

JITTER_SCALE is a declared parameter (0.25), not a measured one: "small" in the decision. It is
recorded in demo.run so the output can be read with it. Quantities are floored at 0 (demand is not
negative; real returns months pass through unchanged as real_copy).
"""
from __future__ import annotations

import hashlib
import random
import statistics
from dataclasses import dataclass, field

SEED = 20261015
JITTER_SCALE = 0.25
MIN_MONTHS = 3  # MA3 window
GENERATOR_VERSION = "dm-demo-1"


def next_month(p: str) -> str:
    y, m = int(p[:4]), int(p[5:7])
    return f"{y + 1:04d}-01" if m == 12 else f"{y:04d}-{m + 1:02d}"


def month_index(p: str) -> int:
    return int(p[:4]) * 12 + int(p[5:7]) - 1


def months_between(a: str, b: str) -> list[str]:
    """Months strictly between a and b."""
    out, p = [], next_month(a)
    while p < b:
        out.append(p)
        p = next_month(p)
    return out


def series_rng(seed: int, key: str) -> random.Random:
    digest = hashlib.sha256(f"{seed}|{key}".encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


@dataclass
class Point:
    period: str
    quantity: float | None
    net_amount: float | None
    origin: str  # 'real_copy' | 'interpolated'


@dataclass
class Fill:
    start: str
    end: str
    n_months: int
    left_run: int   # consecutive real months ending at the left anchor
    right_run: int  # consecutive real months starting at the right anchor

    @property
    def anchoring_run(self) -> int:
        return max(self.left_run, self.right_run)


@dataclass
class SeriesResult:
    key: str
    points: list[Point] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)
    real_months: int = 0
    interpolated_months: int = 0
    cv: float | None = None
    excluded_reason: str | None = None
    first_real: str | None = None
    last_real: str | None = None


def _cv(values: list[float]) -> float:
    """The series' own coefficient of variation (sample sd / |mean|); 0 when it has no spread
    or a non-positive mean (no jitter is better than an invented one)."""
    if len(values) < 2:
        return 0.0
    mean = statistics.fmean(values)
    if mean <= 0:
        return 0.0
    return statistics.stdev(values) / mean


def fill_series(
    key: str,
    quantity: dict[str, float],
    net_amount: dict[str, float | None],
    seed: int = SEED,
    window_end: str = "2025-12",
    jitter_scale: float = JITTER_SCALE,
    min_months: int = MIN_MONTHS,
) -> SeriesResult:
    """`quantity` / `net_amount`: real month -> value (already summed over regions).
    Months after `window_end` are ignored (the demonstration never runs past the real data)."""
    q = {p: float(v) for p, v in quantity.items() if p <= window_end and v is not None}
    res = SeriesResult(key=key)
    if not q:
        res.excluded_reason = "no real month in the window"
        return res
    real = sorted(q)
    res.first_real, res.last_real, res.real_months = real[0], real[-1], len(real)
    span = month_index(real[-1]) - month_index(real[0]) + 1
    if span < min_months:
        res.excluded_reason = (f"{span} month(s) between first and last real month; {min_months} needed to have a "
                               "level and a coefficient of variation of its own to generate from")
        return res

    amt = {p: (None if net_amount.get(p) is None else float(net_amount[p])) for p in real}
    prices = {p: amt[p] / q[p] for p in real if amt[p] is not None and q[p] > 0 and amt[p] > 0}
    price_median = statistics.median(prices.values()) if prices else None
    cv = _cv([q[p] for p in real])
    res.cv = cv
    rng = series_rng(seed, key)

    # consecutive real-run length ending at (or starting from) each real month
    run_end: dict[str, int] = {}
    prev = None
    for p in real:
        run_end[p] = run_end[prev] + 1 if prev is not None and month_index(p) - month_index(prev) == 1 else 1
        prev = p
    run_start: dict[str, int] = {}
    nxt = None
    for p in reversed(real):
        run_start[p] = run_start[nxt] + 1 if nxt is not None and month_index(nxt) - month_index(p) == 1 else 1
        nxt = p

    for left, right in zip(real, real[1:]):
        res.points.append(Point(left, q[left], amt[left], "real_copy"))
        gap = months_between(left, right)
        if not gap:
            continue
        res.fills.append(Fill(gap[0], gap[-1], len(gap), run_end[left], run_start[right]))
        pl, pr = prices.get(left, price_median), prices.get(right, price_median)
        n = len(gap) + 1
        for t, p in enumerate(gap, start=1):
            base = q[left] + (q[right] - q[left]) * t / n
            val = max(0.0, base + rng.gauss(0.0, jitter_scale * cv * abs(base)))
            price = None if pl is None or pr is None else pl + (pr - pl) * t / n
            res.points.append(Point(p, round(val, 2), None if price is None else round(val * price, 2), "interpolated"))
            res.interpolated_months += 1
    last = real[-1]
    res.points.append(Point(last, q[last], amt[last], "real_copy"))
    return res


def ma3_one_step(values: list[float]) -> float:
    """The deployed MA3 (analytics/forecasting/baseline.moving_average_forecast, window 3)."""
    tail = values[-3:]
    return float(sum(tail) / len(tail))


def in_canonical_total(origin: str, anchor_override: bool) -> bool:
    """Whether a Del Monte demonstration row counts in any aggregate (mirrors demo.dm_category_sales.in_canonical_total,
    migration 0055). A back-cast row generated before its series' own first observation is left out: the five live 2025
    categories are the same business as the old paths, which carry 2023-01..2025-02, so counting both doubles it."""
    return not (origin == "backcast" and anchor_override)
