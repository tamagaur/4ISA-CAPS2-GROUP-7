"""
analytics.demo.prescriptive — Del Monte demonstration safety stock, target stock (reorder point) and order
quantity (CLAUDE.md hard rule 2; migration 0056). Pure functions except sigma_d_for_category, which touches no
database (it reconstructs daily rows from monthly figures already in memory, exactly as
backend/routers/recommendations.py's _sigma_d_for_product does for the real Del Monte path).

Reuses the REAL formulas unchanged (analytics.optimization.lp.compute_safety_stock / target_stock, the same
SERVICE_Z and the same review/lead-day placeholders scripts/run_lp.py applies on the real path,
analytics.params.PLACEHOLDERS) over the demonstration's own forecast and stock. The arithmetic is not new; only
the inputs are generated.

NO allocation or warehouse ceiling is applied. Del Monte has neither an SSM-confirmed yearly supplier allocation
nor a warehouse capacity (CLAUDE.md "LP blocked on 4 missing cost params from SSM"), and reusing Unilever's real
warehouse_capacity (3.8M pieces, measured from Unilever's own stock history) would conflate two different
businesses and quantity units (DEC-31: Del Monte's quantity unit is unconfirmed). order_qty is therefore a plain
order-up-to: max(0, target_stock - stock_on_hand) — the 'need' layer of analytics.optimization.lp.net_need with
no allocation/warehouse cap, floored at target_weeks of the month's own demand (the 'per-sku' cover rule) since
there is no portfolio-wide LP here to enforce SSM's "3 weeks of cover" softly instead.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from analytics.etl.granularity import resolve_delmonte_category_grain
from analytics.optimization.lp import compute_safety_stock
from analytics.optimization.lp import target_stock as _target_stock
from analytics.params import PLACEHOLDERS, SERVICE_Z


@dataclass
class CategoryPlan:
    category_path: str
    forecast_quantity: float
    stock_on_hand: float
    sigma_d: float
    safety_stock: float
    target_stock: float
    order_qty: float


def sigma_d_for_category(monthly_quantity: dict[str, float]) -> float | None:
    """Per-business-day demand variability, the same granularity reconstruction the real Del Monte path uses
    (resolve_delmonte_category_grain: evenly distributes each month's total across that month's business days —
    the only allocation that does not fabricate a shape the data doesn't support). Needs >= 2 months; returns
    None otherwise (never a fabricated sigma)."""
    if len(monthly_quantity) < 2:
        return None
    df = pd.DataFrame({"_period": list(monthly_quantity), "quantity": list(monthly_quantity.values())})
    daily_df, _validation = resolve_delmonte_category_grain(df, amount_col="quantity")
    if daily_df.empty:
        return None
    return float(daily_df["quantity"].std(ddof=1))


def plan_category(
    category_path: str,
    forecast_quantity: float,
    stock_on_hand: float,
    sigma_d: float,
    review_days: float = PLACEHOLDERS["review_days"],
    lead_days: float = PLACEHOLDERS["lead_days"],
    target_weeks: float = PLACEHOLDERS["target_weeks"],
    z: float = SERVICE_Z,
) -> CategoryPlan:
    """Mirrors scripts/run_lp.py's safety_stock_for + target_stock exactly (same window = review_days +
    lead_days), then orders up to the target with no allocation/warehouse cap (see module docstring)."""
    window = review_days + lead_days
    ss = compute_safety_stock(sigma_d * math.sqrt(window), z=z)
    target = _target_stock(forecast_quantity, ss, review_days, lead_days, floor_weeks=target_weeks)
    order_qty = max(0.0, target - stock_on_hand)
    return CategoryPlan(category_path, forecast_quantity, stock_on_hand, sigma_d, ss, target, order_qty)
