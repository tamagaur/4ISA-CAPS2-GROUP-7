"""
analytics.demo.stock — Del Monte demonstration stock on hand (CLAUDE.md hard rule 2; migration 0056).

Pure functions, no database. Unlike sales, Del Monte has NO real stock count at category grain anywhere in SSM's
data: Inventory_Fact_Real is SKU grain only (597 products, confirmed live 2026-10-16) and none of those SKU rows
carries a category_path (0 of 597 join to a category-grain Product_Dimension row — category_path is NULL on every
Del Monte SKU-grain row). So this generator has no real anchor at all: there is no 'real_copy' origin for stock,
and every row's origin is 'generated_months_of_cover'.

Method (Kelvin, 2026-10-16): months_of_cover_i,t is a seeded draw centred on SSM's own stated policy — "about 3
weeks of sales in stock" (Sir Abe; analytics.params.POLICY_COVER_WEEKS, the same constant the real LP's
--target-weeks default uses) — jittered by the series' own coefficient of variation (same JITTER_SCALE as the
sales generator, so a steady category's stock wobbles little and a volatile one more). quantity_on_hand is that
draw multiplied by the category's OWN demonstration demand for that month (real, interpolated, bridged or
backcast — whichever the sales generator produced), never a draw around some portfolio-wide number.
"""
from __future__ import annotations

from dataclasses import dataclass

from analytics.demo.dm_interpolate import JITTER_SCALE, SEED, series_rng
from analytics.params import POLICY_COVER_WEEKS, WEEKS_PER_MONTH

CENTER_MONTHS_OF_COVER = POLICY_COVER_WEEKS / WEEKS_PER_MONTH
ORIGIN = "generated_months_of_cover"


@dataclass
class StockPoint:
    period: str
    quantity_on_hand: float
    months_of_cover: float


def generate_category_stock(
    category_path: str,
    demand_by_period: dict[str, float | None],
    cv: float,
    seed: int = SEED,
    jitter_scale: float = JITTER_SCALE,
    center: float = CENTER_MONTHS_OF_COVER,
) -> list[StockPoint]:
    """One stock point per period that has a demand value (a blank-capture month, demand=None, gets no stock
    point either: there is nothing to draw a cover ratio against). `cv` is the SAME coefficient of variation
    already computed for that category's sales (analytics.demo.dm_interpolate._cv) — not recomputed here, so the
    two generators can never silently drift apart on what the series' own variability is. Each category has its
    own seeded stream (series_rng(seed, 'stock|' + category_path)), independent of the sales stream for the same
    category, so regenerating sales does not change stock and vice versa."""
    rng = series_rng(seed, "stock|" + category_path)
    out: list[StockPoint] = []
    for period in sorted(demand_by_period):
        demand = demand_by_period[period]
        if demand is None:
            continue
        cover = max(0.0, center + rng.gauss(0.0, jitter_scale * cv * center))
        out.append(StockPoint(period, round(cover * float(demand), 2), round(cover, 4)))
    return out
