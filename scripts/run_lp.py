"""
scripts.run_lp — Phase 5: plan each gated Category A product's monthly order
with analytics/optimization/lp.py and save it to LP_Recommendation.

Reworked 2026-09-29 (reports/LP_CLIENT_ALIGNMENT_PLAN_2026-09-29.md, Step B,
agreed with Yuan) to order the way SSM does: net of stock on hand, up to a
target stock, within the supplier allocation (Sir Abe's rule). lp.py's
module docstring has the model. This script fetches its inputs, solves one LP
per planning cycle, and writes (or, with --dry-run, reports) one row per
product. The columns are reused, so no migration:
  q_i    the month's order, in pieces (the app splits it into weekly POs)
  rop_i  the target stock T_i
  ss_i   the safety stock

Mirrors scripts/run_baseline_forecast.py's structure (argparse ->
load_dotenv -> psycopg2 connect -> fetch queries -> a per-item loop -> a
closing summary). The forecast fits one SKU at a time; this LP is a single
shared optimization PER PLANNING CYCLE (the allocation and warehouse
constraints are portfolio-wide), so the outer loop is over planning cycles.
plan_cycle() holds everything between the fetches and the writes, and takes
no database, so tests drive it directly.

Candidate pool: Category A products (latest ABC_Classification
classification_period) with a Forecast_Result row at the latest
forecast_date where status='ok' AND mase < MASE_GATE. The
latest-classification_period join is REQUIRED, not optional — ABC_
Classification keeps one row per (product, classification_period), so
joining on product_key alone fans a single Forecast_Result row out across
every historical period that product was ever tier A in (confirmed
empirically while building this script: an unfiltered join produced 80+
duplicate rows for a single product_key).

Gate is mase < MASE_GATE (1.0). reports/MODEL_BAKEOFF_UNILEVER.md's
real-data run found only ~15% of Tier A SKUs ever clear mape < 20% under
any method tested, MA3 included, while ~50-56% clear mase < 1.0 — the
report's own conclusion was to move off the mape gate. Since 2026-09-29
backend/routers/dashboard.py's portfolio_forecast applies this same gate
(MASE_UNRELIABLE_GATE), so the dashboard card and this candidate pool
describe the same SKUs.

Forecast_Result.forecast_date is confirmed (scripts/run_baseline_forecast.py's
_write_forecast_result) to be IDENTICAL across every row in one write —
the single planning month (MAX real calendar_month + 1), not a per-product
date as it was under the retired SARIMA writer. "The latest forecast_date"
below (MAX(forecast_date) across the table) is still correct under this
new behavior, just no longer doing the per-product-date reconciliation
work it was originally written for.

INPUTS, per product:
  forecast        Forecast_Result.forecast_value: the planning month's demand.
  sigma_d         demand variability per business day, from the sales
                  history (_sigma_d_for_product). The safety stock scales it
                  to the review period + lead time (safety_stock_for).
  stock on hand   pieces, at the principal's latest stock snapshot
                  (backend/stock_units.STOCK_AT_LATEST_SQL). A product with no
                  row in that file counts as 0: the file lists no zero-stock
                  rows (0 of 785 Unilever rows in 2026-03), so no row means
                  nothing on hand. Flagged in the log and the CSV.
  cost per piece  the stock file's unit cost per case ÷ pack size, from the
                  product's latest row that has one. It prices the order and
                  values stock for the cover rule. Falls back to
                  --default-procurement-cost-per-unit.
  last year       the calendar year before the planning month. Its sales in
                  pieces set the allocation (× --allocation-pct ÷ 12, summed
                  per principal); its revenue share is the product's priority
                  when the allocation is short.

PLACEHOLDERS (agreed with Yuan, 2026-09-29): the allocation %, review and
lead days, target weeks, cover rule, warehouse capacity and the two costs
have no source in SSM's data yet. Their defaults are
analytics/optimization/lp_inputs.PLACEHOLDERS, the same dict
backend/lp_cycle.lp_model_info() serves to the app, and they are printed
loudly at startup. They are realistic values, not SSM's figures. Step F of
the plan swaps in Sir Abe's answers.

Infeasible cycles: the target and the cover rule are both soft, so the only
way this LP is infeasible is stock on hand already above the warehouse
capacity (_diagnose_infeasibility). Nothing is written for such a cycle and
no constraint is relaxed to force a solution.

--dry-run runs everything inside one READ ONLY transaction (transaction-
scoped, never set_session — that leaks through the :6543 pooler; see the
connect() comment in main()) and reports what a real run would write,
including the rows it would leave alone. A rerun keeps accepted/rejected rows
exactly as they are (UPSERT_QUERY) and reports, but never deletes, pending
rows for products that fell out of the pool.
"""
from __future__ import annotations

import argparse
import logging
import math
import os
import sys
from dataclasses import dataclass

import pandas as pd
import psycopg2
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from analytics.etl.granularity import business_days_in_month, resolve_delmonte_category_grain, resolve_unilever_sku_grain
from analytics.optimization.lp import (
    SKUInput, build_lp_model, compute_safety_stock, solve_lp, target_stock, weekly_demand,
)
from analytics.optimization.lp_inputs import COVER_RULES, PLACEHOLDERS
from backend.stock_units import PACK_SIZE_NUMERIC, STOCK_AT_LATEST_SQL

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

MASE_GATE = 1.0  # MASE < 1 beats the naive benchmark — see analytics/forecasting/baseline.py's
                 # own MASE_GATE and reports/MODEL_BAKEOFF_UNILEVER.md for why mape < 20 was dropped here.
LOUD_RULE = "=" * 78

# Re-running a cycle refreshes only rows still awaiting a decision. The
# WHERE on DO UPDATE leaves an accepted/rejected row untouched: without it a
# rerun silently put a planner's decision back to 'pending' and replaced the
# quantities they had accepted.
#
# generated_at is restamped on refresh because its DEFAULT now() fires only
# on INSERT, and backend/lp_cycle.py dates the run from it: a refreshed row
# that kept its first-insert time made a rerun look like it never happened,
# so the dashboard's stale-LP banner could not clear.
UPSERT_QUERY = """
    INSERT INTO LP_Recommendation
    (product_key, planning_cycle_date, q_i, rop_i, ss_i, status)
    VALUES (%s, %s, %s, %s, %s, 'pending')
    ON CONFLICT (product_key, planning_cycle_date)
    DO UPDATE SET
        q_i = EXCLUDED.q_i,
        rop_i = EXCLUDED.rop_i,
        ss_i = EXCLUDED.ss_i,
        status = 'pending',
        generated_at = now()
    WHERE LP_Recommendation.status = 'pending'
"""

# Category A (latest classification_period) with a Forecast_Result row at
# the latest forecast_date, status='ok', mase < MASE_GATE. Both "latest"
# joins are load-bearing — see the module docstring's fan-out note.
CANDIDATE_QUERY = """
    WITH latest_forecast AS (SELECT MAX(forecast_date) AS d FROM Forecast_Result),
         -- Per-principal, method-pinned. An unscoped MAX() would let one
         -- principal's latest period gate the other's, and an unpinned one
         -- would resolve against the unapproved 't3m' rows (migration 0017).
         latest_abc AS (
             SELECT principal, MAX(classification_period) AS p
             FROM ABC_Classification
             WHERE method = 'single'
             GROUP BY principal
         )
    SELECT pd.product_key, COALESCE(pd.sku_code, pd.category_path) AS sku_id, pd.principal,
           fr.forecast_date, fr.forecast_value, fr.mase
    FROM Forecast_Result fr
    JOIN Product_Dimension pd ON pd.product_key = fr.product_key
    JOIN ABC_Classification ac ON ac.product_key = fr.product_key
    JOIN latest_forecast lf ON fr.forecast_date = lf.d
    JOIN latest_abc la ON la.principal = ac.principal AND ac.classification_period = la.p
    WHERE fr.status = 'ok' AND fr.mase < %s
      AND ac.method = 'single'
      AND ac.tier = 'A'
"""

# Monthly sales per product (pieces and pesos): sigma_d, and last year's
# totals for the allocation and the priority.
DEMAND_QUERY = """
    SELECT pd.product_key, pd.sku_code, pd.principal, d.period,
           SUM(d.quantity) AS total_quantity, SUM(d.net_amount) AS total_amount
    FROM (
        SELECT sf.product_key, sf._period AS period, sf.quantity, sf.net_amount
        FROM SellOut_Fact_Real sf
        JOIN Product_Dimension p ON sf.product_key = p.product_key
        WHERE p.principal = 'delmonte'

        UNION ALL

        SELECT product_key, calendar_month AS period, quantity_sold AS quantity, net_amount
        FROM Unilever_SKU_Demand_Fact_Real
    ) d
    JOIN Product_Dimension pd ON d.product_key = pd.product_key
    WHERE pd.product_key = ANY(%s)
    GROUP BY pd.product_key, pd.sku_code, pd.principal, d.period
    ORDER BY pd.product_key, d.period ASC
"""

# Stock on hand in pieces at the principal's latest snapshot (in_stock_file
# is false when that file has no row for the product), and the cost per
# piece from the product's latest row that carries a cost. pd_pack is the
# alias backend/stock_units.PACK_SIZE_NUMERIC expects.
STOCK_AND_COST_QUERY = f"""
    SELECT pd_pack.product_key,
           s.product_key IS NOT NULL AS in_stock_file,
           s.stock_pieces,
           CASE WHEN {PACK_SIZE_NUMERIC}
                THEN c.cost_per_case / pd_pack.pack_size::numeric
           END AS cost_per_piece
    FROM Product_Dimension pd_pack
    LEFT JOIN ({STOCK_AT_LATEST_SQL}) s ON s.product_key = pd_pack.product_key
    LEFT JOIN LATERAL (
        SELECT AVG(inv.unit_cost_per_case) AS cost_per_case
        FROM inventory_fact_real inv
        WHERE inv.product_key = pd_pack.product_key AND inv.unit_cost_per_case > 0
        GROUP BY inv._period
        ORDER BY inv._period DESC
        LIMIT 1
    ) c ON true
    WHERE pd_pack.product_key = ANY(%s)
"""


@dataclass
class ProductInput:
    """One product's fetched inputs, before any planning rule is applied."""
    product_key: int
    sku_id: str
    principal: str
    forecast: float               # the planning month's demand, pieces
    sigma_d: float                # per business day (_sigma_d_for_product)
    stock_on_hand: float          # pieces; 0 when the stock file has no row
    in_stock_file: bool
    cost_per_piece: float | None  # None: use --default-procurement-cost-per-unit
    prior_year_pieces: float
    prior_year_revenue: float


@dataclass
class CyclePlan:
    """plan_cycle()'s result for one planning cycle."""
    products: list[ProductInput]
    skus: list[SKUInput]              # same order as products
    allocation: dict[str, float]      # principal -> pieces a month
    orders: dict[str, float] | None   # sku_id -> Q_i; None when infeasible
    infeasible_reasons: list[str]
    cover_rule: str
    target_weeks: float
    warehouse_capacity: float

    def summary(self) -> dict:
        """The cycle's totals, for the log and the tests."""
        orders = self.orders or {}
        need = sum(s.need for s in self.skus)
        ordered = sum(orders.get(s.sku_id, 0.0) for s in self.skus)
        short = {s.sku_id: s.need - orders.get(s.sku_id, 0.0) for s in self.skus}
        weekly_value = sum(s.procurement_cost_per_unit * weekly_demand(s.demand) for s in self.skus)
        month_end_value = sum(
            s.procurement_cost_per_unit * (s.stock_on_hand + orders.get(s.sku_id, 0.0) - s.demand)
            for s in self.skus
        )
        by_principal = {
            p: sum(orders.get(s.sku_id, 0.0) for s in self.skus if s.principal == p) for p in self.allocation
        }
        return {
            "need": need,
            "ordered": ordered,
            "shortfall": sum(max(v, 0.0) for v in short.values()),
            "short_skus": sorted(k for k, v in short.items() if v > 0.5),
            "overstocked_skus": sorted(s.sku_id for s in self.skus if s.need == 0),
            "allocation_binds": {p: by_principal[p] >= a - 0.5 for p, a in self.allocation.items()},
            "month_end_stock_value": month_end_value,
            "month_end_cover_weeks": month_end_value / weekly_value if weekly_value > 0 else None,
            "cover_required_value": self.target_weeks * weekly_value,
            "warehouse_used": sum(s.stock_on_hand for s in self.skus) + ordered,
        }


def safety_stock_for(sigma_d: float, protection_days: float) -> float:
    """SS_i = Z x sigma_d x sqrt(protection_days).

    sigma_d is a per-business-day figure (see _sigma_d_for_product), so the
    buffer covers `protection_days` business days of demand variability,
    assuming days are independent (lp_inputs.SAFETY_STOCK_ASSUMPTION).
    plan_cycle() passes the review period + lead time, the window a weekly
    order-up-to policy is exposed for."""
    return compute_safety_stock(sigma_d * math.sqrt(protection_days))


def _positive_float(raw: str) -> float:
    value = float(raw)
    if value <= 0:
        raise argparse.ArgumentTypeError(f"must be > 0, got {raw!r}")
    return value


def _non_negative_float(raw: str) -> float:
    value = float(raw)
    if value < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0, got {raw!r}")
    return value


def _sigma_d_for_product(demand_df: pd.DataFrame, principal: str) -> tuple[float | None, str | None]:
    """Reconstructs this product's demand series via analytics.etl.granularity
    (per DEC-03: Unilever real SKU-grain passthrough+validate, Del Monte
    category-grain even business-day distribution) and returns
    (sigma_d, None) or (None, reason) if it cannot be honestly computed.

    Del Monte: resolve_delmonte_category_grain() genuinely produces one row
    per business day, so its std is a real per-day figure — with a caveat
    (documented, not hidden): even distribution makes every day WITHIN a
    month identical, so all of this sigma's variance comes from month-to-
    month differences in the monthly total, not real day-to-day demand
    swings. It is a real number, just not a richer daily signal than the
    source data actually contains.

    Unilever: resolve_unilever_sku_grain() is confirmed (its own docstring)
    to NOT disaggregate — Unilever's only real demand source is monthly.
    There is no real daily Unilever series to take a std of. Rather than
    either (a) feeding compute_safety_stock() a monthly-scale sigma
    mislabeled as daily — which would overstate SS_i, since monthly
    variance is numerically much larger than daily — or (b) refusing to
    compute Unilever safety stock at all, this applies the standard i.i.d.
    scaling identity Var(monthly) = n * Var(daily) => sigma_daily =
    sigma_monthly / sqrt(avg business days per month). This is a disclosed
    STATISTICAL TRANSFORMATION of real, measured data (the same kind of
    documented-assumption move granularity.business_days_in_month() itself
    makes for "business day" = weekday), not a fabricated number — but it
    IS an assumption, so it is logged per-product, not silently applied.
    """
    if principal == "delmonte":
        monthly_df = demand_df.rename(columns={"period": "_period", "total_quantity": "quantity"})[["_period", "quantity"]]
        if len(monthly_df) < 2:
            return None, f"insufficient demand history ({len(monthly_df)} period(s), need >= 2)"
        daily_df, validation = resolve_delmonte_category_grain(monthly_df, amount_col="quantity")
        if daily_df.empty:
            return None, "granularity reconstruction produced no daily rows"
        if not validation.ok:
            logger.warning(f"    granularity validation flagged gaps/mismatch for this product: {validation.date_gaps[:3]}{'...' if len(validation.date_gaps) > 3 else ''}, total_mismatch={validation.total_mismatch}")
        sigma = float(daily_df["quantity"].std(ddof=1))
        return sigma, None

    if principal == "unilever":
        sku_daily_df = demand_df.rename(columns={"period": "calendar_month", "total_quantity": "quantity_sold"})
        sku_daily_df = sku_daily_df[["sku_code", "calendar_month", "quantity_sold"]]
        if len(sku_daily_df) < 2:
            return None, f"insufficient demand history ({len(sku_daily_df)} period(s), need >= 2)"
        passthrough_df, validation = resolve_unilever_sku_grain(sku_daily_df)
        if not validation.ok:
            logger.warning(f"    Unilever continuity check flagged gaps for this product: {validation.date_gaps[:3]}{'...' if len(validation.date_gaps) > 3 else ''}")
        sigma_monthly = float(passthrough_df["quantity_sold"].std(ddof=1))
        avg_bdays = sum(len(business_days_in_month(p)) for p in passthrough_df["calendar_month"].unique()) / passthrough_df["calendar_month"].nunique()
        if avg_bdays <= 0:
            return None, "could not compute an average business-day count for this product's periods"
        sigma_d = sigma_monthly / math.sqrt(avg_bdays)
        logger.info(f"    sigma_d derived from monthly sigma {sigma_monthly:.3f} / sqrt({avg_bdays:.1f} avg business days) = {sigma_d:.3f} (no real daily Unilever series exists — see module docstring)")
        return sigma_d, None

    return None, f"unknown principal {principal!r}"


def fetch_demand_history(cur, product_keys: list[int]) -> pd.DataFrame:
    """DEMAND_QUERY as a frame: product_key, sku_code, principal, period,
    total_quantity (pieces), total_amount (pesos)."""
    cur.execute(DEMAND_QUERY, (product_keys,))
    df = pd.DataFrame(cur.fetchall(), columns=["product_key", "sku_code", "principal", "period", "total_quantity", "total_amount"])
    for col in ("total_quantity", "total_amount"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df


def fetch_stock_and_cost(cur, product_keys: list[int]) -> dict[int, tuple[bool, float | None, float | None]]:
    """product_key -> (in_stock_file, stock_pieces, cost_per_piece)."""
    cur.execute(STOCK_AND_COST_QUERY, (product_keys,))
    return {
        int(k): (bool(in_file), None if pieces is None else float(pieces), None if cost is None else float(cost))
        for k, in_file, pieces, cost in cur.fetchall()
    }


def product_input(
    product_key: int, sku_id: str, principal: str, forecast: float, sigma_d: float,
    stock_and_cost: dict, history: pd.DataFrame, prior_year: int,
) -> tuple[ProductInput | None, str | None]:
    """(ProductInput, None), or (None, reason) when the stock can't be put in pieces."""
    in_file, pieces, cost = stock_and_cost.get(int(product_key), (False, None, None))
    if in_file and pieces is None:
        return None, "its stock is in cases and it has no usable pack size, so it can't be put in pieces"
    year = history[(history["product_key"] == product_key)
                   & history["period"].astype(str).str.startswith(f"{prior_year}-")]
    return ProductInput(
        product_key=int(product_key), sku_id=str(sku_id), principal=principal,
        forecast=float(forecast), sigma_d=sigma_d,
        stock_on_hand=pieces if in_file else 0.0, in_stock_file=in_file, cost_per_piece=cost,
        prior_year_pieces=float(year["total_quantity"].sum()),
        prior_year_revenue=float(year["total_amount"].sum()),
    ), None


def allocation_ceilings(products: list[ProductInput], allocation_pct: float) -> dict[str, float]:
    """Sir Abe's rule, pro rata to the planned products: last year's sales in
    pieces × allocation % ÷ 12, per principal. Pieces a month."""
    totals: dict[str, float] = {}
    for p in products:
        totals[p.principal] = totals.get(p.principal, 0.0) + max(p.prior_year_pieces, 0.0)
    return {principal: total * allocation_pct / 100.0 / 12.0 for principal, total in totals.items()}


def _diagnose_infeasibility(skus: list[SKUInput], warehouse_capacity: float) -> list[str]:
    """The target and the cover rule are soft and 0 <= Q_i <= need_i always
    holds, so the only hard constraint that can fail is the warehouse:
    stock on hand alone already above its capacity. An exact diagnosis."""
    stock = sum(s.stock_on_hand for s in skus)
    if stock > warehouse_capacity:
        return [f"stock on hand ({stock:,.0f} pieces) is already above warehouse_capacity ({warehouse_capacity:,.0f})"]
    return ["no bound identified — unexpected; check build_lp_model's constraints directly"]


def plan_cycle(products: list[ProductInput], args: argparse.Namespace) -> CyclePlan:
    """One planning cycle, from fetched inputs to the solved orders. Uses
    args.allocation_pct, review_days, lead_days, target_weeks, cover_rule,
    warehouse_capacity, storage_cost_per_unit and
    default_procurement_cost_per_unit. No database."""
    window = args.review_days + args.lead_days
    floor_weeks = args.target_weeks if args.cover_rule == "per-sku" else None
    revenue_total = sum(max(p.prior_year_revenue, 0.0) for p in products)
    skus: list[SKUInput] = []
    for p in products:
        ss = safety_stock_for(p.sigma_d, window)
        skus.append(SKUInput(
            sku_id=p.sku_id,
            principal=p.principal,
            demand=p.forecast,
            target_stock=target_stock(p.forecast, ss, args.review_days, args.lead_days, floor_weeks=floor_weeks),
            stock_on_hand=p.stock_on_hand,
            safety_stock=ss,
            procurement_cost_per_unit=(p.cost_per_piece if p.cost_per_piece is not None
                                       else args.default_procurement_cost_per_unit),
            storage_cost_per_unit=args.storage_cost_per_unit,
            revenue_weight=max(p.prior_year_revenue, 0.0) / revenue_total if revenue_total > 0 else 1.0,
        ))
    allocation = allocation_ceilings(products, args.allocation_pct)
    model = build_lp_model(
        skus, warehouse_capacity=args.warehouse_capacity, supplier_ceilings=allocation,
        min_cover_weeks=args.target_weeks if args.cover_rule == "aggregate" else None,
    )
    orders = solve_lp(model)
    if orders is not None:
        # Solver noise only: Q_i is bounded to [0, need_i] in the model.
        orders = {s.sku_id: min(max(orders[s.sku_id], 0.0), s.need) for s in skus}
    return CyclePlan(
        products=products, skus=skus, allocation=allocation, orders=orders,
        infeasible_reasons=[] if orders is not None else _diagnose_infeasibility(skus, args.warehouse_capacity),
        cover_rule=args.cover_rule, target_weeks=args.target_weeks, warehouse_capacity=args.warehouse_capacity,
    )


def plan_rows(plan: CyclePlan, planning_cycle_date) -> list[dict]:
    """The per-product plan, for the CSV (--csv)."""
    rows = []
    for p, s in zip(plan.products, plan.skus):
        q = (plan.orders or {}).get(s.sku_id)
        rows.append({
            "planning_cycle_date": planning_cycle_date, "product_key": p.product_key, "sku_id": s.sku_id,
            "principal": s.principal, "cover_rule": plan.cover_rule,
            "forecast": round(s.demand, 2), "weekly_demand": round(weekly_demand(s.demand), 2),
            "stock_on_hand": round(s.stock_on_hand, 2), "in_stock_file": p.in_stock_file,
            "safety_stock": round(s.safety_stock, 2), "target_stock": round(s.target_stock, 2),
            "target_weeks_of_sales": round(s.target_stock / weekly_demand(s.demand), 2) if s.demand > 0 else None,
            "need": round(s.need, 2), "order": None if q is None else round(q, 2),
            "short": None if q is None else round(s.need - q, 2),
            "cost_per_piece": round(s.procurement_cost_per_unit, 4),
            "cost_source": "stock file" if p.cost_per_piece is not None else "placeholder",
            "revenue_weight": round(s.revenue_weight, 6), "prior_year_pieces": round(p.prior_year_pieces, 2),
        })
    return rows


def build_parser() -> argparse.ArgumentParser:
    p = PLACEHOLDERS
    parser = argparse.ArgumentParser(
        description="Plan the monthly order for gated Category A products (LP) and save it to LP_Recommendation.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--allocation-pct", type=_positive_float, default=p["allocation_pct"],
        help="Supplier allocation as a %% of last year's sales (Sir Abe: 103 minimum, 105 mid, 108 maximum). "
             "A principal's monthly ceiling is its planned products' sales in the calendar year before the "
             "planning month, times this %%, divided by 12. PLACEHOLDER.",
    )
    parser.add_argument(
        "--review-days", type=_positive_float, default=p["review_days"],
        help="Business days between purchase orders (weekly = 5). PLACEHOLDER.",
    )
    parser.add_argument(
        "--lead-days", type=_non_negative_float, default=p["lead_days"],
        help="Business days from purchase order to delivery. PLACEHOLDER. The safety stock and the "
             "target cover review + lead days.",
    )
    parser.add_argument(
        "--target-weeks", type=_positive_float, default=p["target_weeks"],
        help="SSM's rule: weeks of sales to keep in stock (Sir Abe said 3). PLACEHOLDER.",
    )
    parser.add_argument(
        "--cover-rule", choices=COVER_RULES, default=p["cover_rule"],
        help="How --target-weeks applies. aggregate: the planned products' month-end stock, at cost, "
             "covers that many weeks of their sales (a soft constraint; each target stays statistical). "
             "per-sku: every product's target is at least that many weeks of its own sales.",
    )
    parser.add_argument(
        "--warehouse-capacity", type=_positive_float, default=p["warehouse_capacity"],
        help="Pieces the warehouse holds; stock on hand plus the month's orders must fit. PLACEHOLDER "
             "(the most stock held, Jan 2025).",
    )
    parser.add_argument(
        "--storage-cost-per-unit", type=_non_negative_float, default=p["storage_cost_per_unit"],
        help="Storage cost, pesos per piece per month, every product. PLACEHOLDER.",
    )
    parser.add_argument(
        "--default-procurement-cost-per-unit", type=_positive_float, default=p["default_procurement_cost_per_unit"],
        help="Pesos per piece for a product the stock file gives no cost for. Everything else uses the "
             "stock file's unit cost per case ÷ pack size. PLACEHOLDER.",
    )
    parser.add_argument(
        "--principal", choices=["both", "unilever", "delmonte"], default="both",
        help="Scope this run to one principal, filtered in Python after the gating query, "
              "same convention as scripts/run_baseline_forecast.py's --principal.",
    )
    parser.add_argument(
        "--csv", metavar="PATH", default=None,
        help="Also write the per-product plan to this CSV (with --dry-run too).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Compute and report everything, write nothing: the database session is read-only.",
    )
    return parser


def _log_inputs(args: argparse.Namespace) -> None:
    logger.warning(LOUD_RULE)
    logger.warning("PLACEHOLDER INPUTS: realistic values the team chose until SSM (Sir Abe) confirms them.")
    logger.warning("They are NOT SSM's figures. Defaults: analytics/optimization/lp_inputs.PLACEHOLDERS.")
    for key, default in PLACEHOLDERS.items():
        value = getattr(args, key)
        changed = "" if value == default else f"   <- flag; the default is {default}"
        logger.warning(f"  {key:<36} = {value}{changed}")
    logger.warning(f"  safety stock window = review + lead = {args.review_days + args.lead_days:g} business days")
    logger.warning(LOUD_RULE)
    if not args.dry_run and any(getattr(args, k) != v for k, v in PLACEHOLDERS.items()):
        logger.warning("A real run with non-default inputs: the app's model description (lp_model_info) "
                       "states the defaults, not these. Change lp_inputs.PLACEHOLDERS instead if these are meant.")
    if args.dry_run:
        logger.warning("DRY RUN — one READ ONLY transaction; nothing will be written to LP_Recommendation.")


def _log_cycle(plan: CyclePlan, allocation_pct: float, prior_year: int) -> None:
    s = plan.summary()
    for principal, ceiling in sorted(plan.allocation.items()):
        logger.info(f"  allocation[{principal}] = {ceiling:,.0f} pieces a month ({prior_year} sales of the planned "
                    f"products × {allocation_pct:g}% ÷ 12); {'binds' if s['allocation_binds'][principal] else 'does not bind'}")
    logger.info(f"  need {s['need']:,.0f} · order {s['ordered']:,.0f} · short {s['shortfall']:,.0f} pieces "
                f"across {len(s['short_skus'])} product(s) · {len(s['overstocked_skus'])} overstocked (order 0)")
    weeks = s["month_end_cover_weeks"]
    rule = (f"rule: {plan.target_weeks:g} weeks, "
            + ("met" if s["month_end_stock_value"] >= s["cover_required_value"] - 1.0
               else f"short by PHP {s['cover_required_value'] - s['month_end_stock_value']:,.0f}"))
    logger.info(f"  planned month-end stock at cost PHP {s['month_end_stock_value']:,.0f} = "
                f"{'n/a' if weeks is None else f'{weeks:.2f}'} weeks of these products' sales "
                f"({rule}{'' if plan.cover_rule == 'aggregate' else '; per-sku targets, not a constraint'})")
    logger.info(f"  warehouse: stock + orders = {s['warehouse_used']:,.0f} of {plan.warehouse_capacity:,.0f} pieces")


def main():
    args = build_parser().parse_args()
    _log_inputs(args)

    load_dotenv(override=False)
    db_url = os.environ.get("SUPABASE_DB_URL")
    if not db_url:
        logger.error("SUPABASE_DB_URL not set in .env")
        return

    conn = psycopg2.connect(db_url)
    # Each cycle's upserts commit immediately (autocommit). A dry run instead
    # runs as ONE psycopg2-managed transaction made READ ONLY by its first
    # statement, so a write would fail rather than land; nothing ever commits
    # it, and conn.close() (or the process exiting on an error) discards it —
    # no rollback to remember on any exit path. Transaction-scoped on
    # purpose: set_session(readonly=True) is session-scoped, and through the
    # :6543 transaction pooler it stays on the shared server connection after
    # this script disconnects, so the next client handed that connection
    # can't write — it broke the app's sign-ins on 2026-09-28 (see
    # backend/deps.py's engine comment).
    conn.set_session(autocommit=not args.dry_run)
    cur = conn.cursor()
    if args.dry_run:
        cur.execute("SET TRANSACTION READ ONLY")

    def save_result(product_key, planning_cycle_date, q_i, rop_i, ss_i) -> bool:
        """Upsert one row. False when it hit a decided row and changed nothing."""
        cur.execute(UPSERT_QUERY, (int(product_key), planning_cycle_date, float(q_i), float(rop_i), float(ss_i)))
        return cur.rowcount > 0

    def existing_rows(planning_cycle_date) -> dict:
        """product_key -> status of the rows already stored for this cycle."""
        cur.execute(
            "SELECT product_key, status FROM LP_Recommendation WHERE planning_cycle_date = %s",
            (planning_cycle_date,),
        )
        return {int(k): s for k, s in cur.fetchall()}

    # ---- Step A: gated candidate pool -----------------------------------
    logger.info("Fetching gated Category A candidate pool...")
    cur.execute(CANDIDATE_QUERY, (MASE_GATE,))
    columns = ["product_key", "sku_id", "principal", "forecast_date", "forecast_value", "mase"]
    candidates_df = pd.DataFrame(cur.fetchall(), columns=columns)

    considered = len(candidates_df)
    logger.info(f"{considered} product(s) considered (Category A, status='ok', mase < {MASE_GATE}, at the latest forecast_date).")

    if args.principal != "both":
        before = len(candidates_df)
        candidates_df = candidates_df[candidates_df["principal"] == args.principal]
        logger.info(f"--principal={args.principal}: scoped from {before} to {len(candidates_df)} product(s).")

    if candidates_df.empty:
        logger.warning("No candidates after gating. Nothing to do.")
        conn.close()
        return

    # ---- Step B: sales history, stock on hand, cost per piece -----------
    product_keys = [int(k) for k in candidates_df["product_key"].unique()]
    demand_df = fetch_demand_history(cur, product_keys)
    stock_and_cost = fetch_stock_and_cost(cur, product_keys)

    # ---- Step C: per-product inputs --------------------------------------
    gated_out: dict[str, int] = {}
    products_by_cycle: dict = {}  # planning_cycle_date -> list[ProductInput]

    def gate_out(sku_id, principal, reason):
        gated_out[reason] = gated_out.get(reason, 0) + 1
        logger.warning(f"  {sku_id} ({principal}): gated out — {reason}.")

    for row in candidates_df.itertuples():
        product_demand = demand_df[demand_df["product_key"] == row.product_key]
        if product_demand.empty:
            gate_out(row.sku_id, row.principal, "no demand history at all")
            continue
        sigma_d, reason = _sigma_d_for_product(product_demand, row.principal)
        if sigma_d is None:
            gate_out(row.sku_id, row.principal, reason)
            continue
        product, reason = product_input(
            row.product_key, row.sku_id, row.principal, float(row.forecast_value), sigma_d,
            stock_and_cost, demand_df, prior_year=row.forecast_date.year - 1,
        )
        if product is None:
            gate_out(row.sku_id, row.principal, reason)
            continue
        if not product.in_stock_file:
            logger.warning(f"  {row.sku_id} ({row.principal}): not in the latest stock file — counted as 0 on hand.")
        products_by_cycle.setdefault(row.forecast_date, []).append(product)

    # ---- Step D: one LP per planning cycle -------------------------------
    rows_written = 0
    rows_kept_decided = 0
    stale_pending_by_cycle: dict = {}
    total_ss_by_cycle: dict = {}
    infeasible_cycles: list[tuple] = []
    csv_rows: list[dict] = []

    for planning_cycle_date, products in sorted(products_by_cycle.items()):
        logger.info(f"Solving LP for planning cycle {planning_cycle_date} ({len(products)} product(s), "
                    f"cover rule {args.cover_rule})...")
        plan = plan_cycle(products, args)
        csv_rows.extend(plan_rows(plan, planning_cycle_date))

        if plan.orders is None:
            for reason in plan.infeasible_reasons:
                logger.error(f"  INFEASIBLE cycle {planning_cycle_date}: {reason}")
            infeasible_cycles.append((planning_cycle_date, plan.infeasible_reasons))
            logger.error(f"  Writing NOTHING for cycle {planning_cycle_date} — no constraint was relaxed to force a solution.")
            continue
        _log_cycle(plan, args.allocation_pct, planning_cycle_date.year - 1)

        # What is already stored for this cycle decides what a write would
        # do: decided rows are kept as they are (UPSERT_QUERY), and pending
        # rows for products outside this run's pool are left behind —
        # reported, never deleted, since dropping a recommendation is a
        # planning call, not this script's.
        existing = existing_rows(planning_cycle_date)
        written_keys = {p.product_key for p in products}
        stale = sorted(k for k, status in existing.items() if status == "pending" and k not in written_keys)
        stale_pending_by_cycle[planning_cycle_date] = stale

        cycle_written = cycle_kept = 0
        total_ss_by_cycle[planning_cycle_date] = sum(s.safety_stock for s in plan.skus)
        for product, sku in zip(products, plan.skus):
            q_i, ss_i = plan.orders[sku.sku_id], sku.safety_stock
            decided = existing.get(product.product_key, "pending") != "pending"
            if args.dry_run:
                short = sku.need - q_i
                logger.info(f"  [dry run] {sku.sku_id}: order {q_i:,.0f} of need {sku.need:,.0f}"
                            f"{f' (short {short:,.0f})' if short > 0.5 else ''} · target {sku.target_stock:,.0f} "
                            f"(SS {ss_i:,.0f}) · stock {sku.stock_on_hand:,.0f} · forecast {sku.demand:,.0f}"
                            f"{'  (decided row — would be kept as is)' if decided else ''}")
            elif not save_result(product.product_key, planning_cycle_date, q_i, sku.target_stock, ss_i):
                decided = True
            if decided:
                cycle_kept += 1
            else:
                cycle_written += 1
        rows_written += cycle_written
        rows_kept_decided += cycle_kept
        verb = "would be upserted" if args.dry_run else "upserted into LP_Recommendation (status='pending')"
        logger.info(f"  Cycle {planning_cycle_date}: {cycle_written} row(s) {verb}"
                    f"{f'; {cycle_kept} decided row(s) kept as they were' if cycle_kept else ''}.")
        if stale:
            logger.warning(f"  Cycle {planning_cycle_date}: {len(stale)} existing pending row(s) are for products outside "
                           f"this run's pool and are left unchanged: product_key {stale[:10]}{'...' if len(stale) > 10 else ''}")

    # Older cycles still awaiting a decision: not this run's to close, but a
    # reader of the summary should know they exist.
    cur.execute(
        "SELECT planning_cycle_date, COUNT(*) FROM LP_Recommendation WHERE status = 'pending' "
        "AND planning_cycle_date < (SELECT MAX(planning_cycle_date) FROM LP_Recommendation) "
        "GROUP BY planning_cycle_date ORDER BY planning_cycle_date"
    )
    older_pending = cur.fetchall()

    conn.close()

    if args.csv:
        pd.DataFrame(csv_rows).to_csv(args.csv, index=False)
        logger.info(f"Per-product plan written to {args.csv}")

    # ---- Summary -----------------------------------------------------
    missing_stock = sum(1 for ps in products_by_cycle.values() for p in ps if not p.in_stock_file)
    cost_fallback = sum(1 for ps in products_by_cycle.values() for p in ps if p.cost_per_piece is None)
    planned = sum(len(ps) for ps in products_by_cycle.values())
    logger.info(LOUD_RULE)
    logger.info("RUN SUMMARY")
    logger.info(f"  Products considered:        {considered}")
    logger.info(f"  Products gated out:          {sum(gated_out.values())}")
    for reason, count in sorted(gated_out.items()):
        logger.info(f"    - {reason}: {count}")
    logger.info(f"  Stock on hand:               {planned - missing_stock} from the latest stock file, "
                f"{missing_stock} not in it (counted as 0)")
    logger.info(f"  Cost per piece:              {planned - cost_fallback} from the stock file, "
                f"{cost_fallback} placeholder (--default-procurement-cost-per-unit)")
    logger.info(f"  Planning cycles attempted:   {len(products_by_cycle)}")
    logger.info(f"  Infeasible cycles:           {len(infeasible_cycles)}")
    for cycle_date, reasons in infeasible_cycles:
        logger.info(f"    - {cycle_date}: {'; '.join(reasons)}")
    logger.info(f"  Rows {'that would be ' if args.dry_run else ''}written to LP_Recommendation: {rows_written}")
    logger.info(f"  Decided rows kept as they were (accepted/rejected): {rows_kept_decided}")
    for cycle_date, total_ss in total_ss_by_cycle.items():
        logger.info(f"  Total SS_i in {cycle_date}: {total_ss:,.0f} pieces "
                    f"(review + lead = {args.review_days + args.lead_days:g} business days)")
    for cycle_date, stale in stale_pending_by_cycle.items():
        if stale:
            logger.info(f"  Pending rows left unchanged in {cycle_date} (products outside this run's pool): {len(stale)}")
    for cycle_date, count in older_pending:
        logger.info(f"  Older cycle still pending: {cycle_date} ({count} row(s))")
    if args.dry_run:
        logger.info("  DRY RUN — nothing was written.")
    logger.info(LOUD_RULE)


if __name__ == "__main__":
    main()
