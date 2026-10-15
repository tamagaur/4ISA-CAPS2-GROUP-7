"""
analytics.demo.backcast — the 2021-01..2022-12 back-cast of the labelled demonstration (CLAUDE.md rule 2).

Pure functions, no database. Third kind of generated month, kept apart from 'interpolated' and 'bridged': there is
NO real observation on either side of it (SSM's records begin 2023-01).

Rules (Kelvin, 2026-10-15):
  * FLAT at the series' own level, with seeded jitter from the series' own coefficient of variation. No trend:
    growth or decline before the data starts would be invented direction.
  * Same fixed seed as the rest of the demonstration (analytics.demo.dm_interpolate.SEED), a stream per series.
  * Only a series with enough real months to establish a level (MIN_MONTHS_WITH_SALES = 3, the team's own floor to be
    forecast or binned, analytics.params) is back-cast; the rest are named, with why.

ONE NARROWING of the instruction, disclosed: a series is back-cast only if its first real month IS the first month
of SSM's records (ANCHOR_PERIOD, 2023-01). A series first seen later may simply not have existed yet (a Del
Monte category created in 2025, a SKU launched in 2024); projecting it flat to 2021 would invent a product's
existence. Loosening it is one constant.

Level and CV come from real months only. `zero_months_in_span=True` (Unilever) also counts each no-row month
between the first and last real month as 0: those are real zero-sale months (CLAUDE.md "Why data is missing"),
part of the series' level. A blank-capture month (quantity NULL) is never counted.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from analytics.demo.dm_interpolate import JITTER_SCALE, SEED, month_index, next_month, series_rng
from analytics.params import MIN_MONTHS_WITH_SALES

ANCHOR_PERIOD = "2023-01"
START, END = "2021-01", "2022-12"
BRIDGE_END = "2025-02"  # the month before the new Del Monte taxonomy's first real month (2025-03)


@dataclass
class Backcast:
    key: str
    points: list[tuple[str, float, float | None]] = field(default_factory=list)  # (period, quantity, net_amount)
    anchor_override: bool = False  # first real month later than ANCHOR_PERIOD: generated before the first observation
    level: float | None = None
    cv: float | None = None
    excluded_reason: str | None = None
    real_months: int = 0
    first_real: str | None = None


def prev_month(p: str) -> str:
    y, m = int(p[:4]), int(p[5:7])
    return f"{y - 1:04d}-12" if m == 1 else f"{y:04d}-{m - 1:02d}"


def months(start: str = START, end: str = END) -> list[str]:
    out, p = [], start
    while p <= end:
        out.append(p)
        p = next_month(p)
    return out


def backcast_series(
    key: str,
    quantity: dict[str, float | None],
    net_amount: dict[str, float | None],
    zero_months_in_span: bool = False,
    seed: int = SEED,
    jitter_scale: float = JITTER_SCALE,
    *,
    anchor_override: bool = False,
    min_real_months: int | None = None,
) -> Backcast:
    """`quantity`: real month -> quantity (None = blank capture). Months before ANCHOR_PERIOD are ignored.

    anchor_override=True (Del Monte only, Kelvin 2026-10-15): a series first seen after ANCHOR_PERIOD is back-cast too,
    from 2021-01 to the month before its first real month, and is flagged anchor_override. min_real_months: the floor
    on real months (default: MIN_MONTHS_WITH_SALES months WITH SALES; the override uses 2 real months, the least from
    which a level and a coefficient of variation exist)."""
    res = Backcast(key=key)
    real = {p: v for p, v in quantity.items() if p >= ANCHOR_PERIOD and v is not None}
    seen = sorted(p for p in quantity if p >= ANCHOR_PERIOD)
    res.real_months = len(real)
    res.first_real = seen[0] if seen else None
    if not seen:
        res.excluded_reason = "no real month"
        return res
    if res.first_real != ANCHOR_PERIOD and not anchor_override:
        res.excluded_reason = (f"first real month is {res.first_real}, after the start of SSM's records ({ANCHOR_PERIOD}): "
                               "it may not have existed before then, so nothing is projected back")
        return res
    res.anchor_override = res.first_real != ANCHOR_PERIOD
    if min_real_months is None:
        sales_months = sum(1 for v in real.values() if v > 0)
        if sales_months < MIN_MONTHS_WITH_SALES:
            res.excluded_reason = (f"{sales_months} month(s) with sales; {MIN_MONTHS_WITH_SALES} are needed to establish a level")
            return res
    elif len(real) < min_real_months:
        res.excluded_reason = (f"{len(real)} real month(s); {min_real_months} are the least from which a level and a "
                               "coefficient of variation exist")
        return res

    values = list(real.values())
    if zero_months_in_span:
        span = month_index(seen[-1]) - month_index(seen[0]) + 1
        # no-row months in the span are real zeros; a blank-capture month is in `seen` and so not one of them
        values += [0.0] * (span - len(seen))
    level = statistics.fmean(values)
    cv = (statistics.stdev(values) / level) if len(values) >= 2 and level > 0 else 0.0
    res.level, res.cv = level, cv

    pairs = [(net_amount.get(p), real[p]) for p in real if net_amount.get(p) and real[p] > 0 and net_amount[p] > 0]
    price = (sum(a for a, _ in pairs) / sum(q for _, q in pairs)) if pairs else None

    rng = series_rng(seed, "backcast|" + key)
    last = prev_month(res.first_real)  # equals END when the first real month is ANCHOR_PERIOD
    for p in months(START, last):
        q = max(0.0, level + rng.gauss(0.0, jitter_scale * cv * level))
        q = round(q, 2)
        res.points.append((p, q, None if price is None else round(q * price, 2)))
    return res


def bridge_series(
    key: str,
    quantity: dict[str, float | None],
    net_amount: dict[str, float | None],
    last_real: str,
    end: str = BRIDGE_END,
    seed: int = SEED,
    jitter_scale: float = JITTER_SCALE,
    min_real_months: int = 2,
) -> list[tuple[str, float, float | None]]:
    """Extend one pre-2025 Del Monte path forward from its last real month to `end` (2025-02), across the taxonomy
    change: flat at the path's own level, seeded jitter from its own CV, no trend. This IS extrapolation (real data on
    one side only); rule 14 is suspended for this window by Kelvin's decision of 2026-10-15. Returns [] when the path
    has too few real months to have a level and a CV. Origin 'bridged', API reason taxonomy_change_bridge."""
    real = [float(v) for p, v in quantity.items() if v is not None and p <= last_real]
    if len(real) < min_real_months or last_real >= end:
        return []
    level = statistics.fmean(real)
    cv = (statistics.stdev(real) / level) if level > 0 else 0.0
    pairs = [(net_amount.get(p), quantity[p]) for p in quantity
             if quantity[p] and quantity[p] > 0 and net_amount.get(p) and net_amount[p] > 0]
    price = (sum(a for a, _ in pairs) / sum(q for _, q in pairs)) if pairs else None
    rng = series_rng(seed, "bridge|" + key)
    out, p = [], next_month(last_real)
    while p <= end:
        q = round(max(0.0, level + rng.gauss(0.0, jitter_scale * cv * level)), 2)
        out.append((p, q, None if price is None else round(q * price, 2)))
        p = next_month(p)
    return out
