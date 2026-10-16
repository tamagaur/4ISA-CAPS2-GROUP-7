"""
analytics.demo.stock — Del Monte demonstration stock on hand (CLAUDE.md hard rule 2; migration 0056).

Pure functions, no database. Unlike sales, Del Monte has NO real stock count at category grain anywhere in SSM's
data: Inventory_Fact_Real is SKU grain only (597 products, confirmed live 2026-10-16) and none of those SKU rows
carries a category_path (0 of 597 join to a category-grain Product_Dimension row — category_path is NULL on every
Del Monte SKU-grain row). So this generator has no real anchor at all: there is no 'real_copy' origin for stock,
and every row's origin is 'generated_months_of_cover'.

Method (Kelvin, 2026-10-15/16): months_of_cover_i,t is a seeded draw centred on SSM's own stated policy — "about 3
weeks of sales in stock" (Sir Abe; analytics.params.POLICY_COVER_WEEKS, the same constant the real LP's
--target-weeks default uses). quantity_on_hand is that draw multiplied by the category's OWN demonstration demand
for that month (real, interpolated, bridged, forward-filled or backcast — whichever the sales generator
produced), never a draw around some portfolio-wide number.

STOCK_SPREAD (0.45, declared 2026-10-16, not measured — there is nothing real to measure a stocking-variability
figure against): the spread is NOT tied to the category's own demand CV (the first version did this and every
category's cover sat so close to the policy center that the order plan had no work — 3 of 4 forecastable
categories always ordered 0). Demand variability and STOCKING variability (replenishment timing, order
lumpiness, how close the last delivery landed to the target) are different things; a draw this wide is declared
specifically so a meaningful share of months land below their reorder point, which is the entire point of
generating a stock figure for a demonstration order plan to act on.
"""
from __future__ import annotations

from dataclasses import dataclass

from analytics.demo.dm_interpolate import SEED, series_rng
from analytics.params import POLICY_COVER_WEEKS, WEEKS_PER_MONTH

CENTER_MONTHS_OF_COVER = POLICY_COVER_WEEKS / WEEKS_PER_MONTH
STOCK_SPREAD = 0.45  # relative sd on the cover draw: sd = STOCK_SPREAD x center. Declared, not measured.
ORIGIN = "generated_months_of_cover"


@dataclass
class StockPoint:
    period: str
    quantity_on_hand: float
    months_of_cover: float


def generate_category_stock(
    category_path: str,
    demand_by_period: dict[str, float | None],
    seed: int = SEED,
    spread: float = STOCK_SPREAD,
    center: float = CENTER_MONTHS_OF_COVER,
) -> list[StockPoint]:
    """One stock point per period that has a demand value (a blank-capture month, demand=None, gets no stock
    point either: there is nothing to draw a cover ratio against). Each category has its own seeded stream
    (series_rng(seed, 'stock|' + category_path)), independent of the sales stream for the same category, so
    regenerating sales does not change stock and vice versa."""
    rng = series_rng(seed, "stock|" + category_path)
    out: list[StockPoint] = []
    for period in sorted(demand_by_period):
        demand = demand_by_period[period]
        if demand is None:
            continue
        cover = max(0.0, center + rng.gauss(0.0, spread * center))
        out.append(StockPoint(period, round(cover * float(demand), 2), round(cover, 4)))
    return out
