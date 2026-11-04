"""
scripts.run_lp — Phase 5: plan each gated Category A product's monthly order
with analytics/optimization/lp.py and save it to LP_Recommendation.

Reworked 2026-09-29 (reports/LP_CLIENT_ALIGNMENT_PLAN_2026-09-29.md, Step B,
agreed with Yuan) to order the way SSM does: net of stock on hand, up to a
target stock, within the supplier allocation (Sir Abe's rule). lp.py's
module docstring has the model. This script fetches its inputs, solves one LP
per planning cycle, and writes (or, with --dry-run, reports) one row per
product:
  q_i         the month's order, in pieces: one figure, not split into weekly POs by
              any code. The 8-business-day window assumes SSM's own stated practice of
              ordering weekly, which the system neither implements nor verifies.
  rop_i       the target stock T_i
  ss_i        the safety stock
  lp_run_key  the lp_run row (migration 0037) holding every input the run
              used, which is what the app shows (backend/lp_cycle.stored_run)

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
(the same analytics.params.MASE_GATE), so the dashboard card and this candidate pool
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
  stock on hand   pieces, at the stock count that OPENS the planning month:
                  the principal's count with _period = the month before
                  (backend/stock_units.opening_period). A product with no
                  row in that count counts as 0: the file lists no zero-stock
                  rows (0 of 785 Unilever rows in 2026-03), so no row means
                  nothing on hand. Flagged in the log and the CSV.

STOCK TIMING (2026-10-03, reports/diagnostics/lp_logic_check_2026-10-03).
Until this date the stock was each principal's LATEST count, whatever the
cycle: cycle 2026-03 used the count of 2026-04-06, the stock left after
March's sales, so need = forecast + target - stock counted March's demand
twice. Now a cycle plans from the count of the month before it or not at all:
a principal with no such count (or one backend/data_notes.OPENING_COUNT_RULINGS
sets aside) is refused for that cycle, logged with the reason the app shows
(backend/stock_units.missing_opening_count_reason), and nothing is written for
it. No older or later count is substituted. plan_cycle() refuses a product
carrying any other month's stock (check_stock_periods). The count used, its
date and any flag on it are recorded in lp_run.inputs.stock_counts.

OPENING STOCK (2026-10-24, migration 0069, docs/ROLLOVER_DESIGN.md). Stock on hand is read from the view
stock_opening_v, not straight from the count: the count that opens the cycle PLUS the receipts of accepted orders of
EARLIER cycles that are still on the way (state expected, expected_on after the count date). A cycle's own accepted
orders never change its plan. With nothing decided that is exactly the count and the plan is unchanged.

SAFETY PROPERTY RELAXED, DELIBERATELY (decision of 2026-10-24). Until then this script refused to plan a cycle that
had no stock count for the month before it, and no other month's stock was ever used. It now PLANS ON A PROJECTED
OPENING when that count is simply not loaded yet: the month-before-that count, plus the receipts on the way, minus
that month's sales (the real month if loaded, else the stored forecast). A projection is not a count. Every plan
built that way is labelled opening_basis = 'projected' in lp_run.inputs (stock_counts.<principal>.opening_basis and
the run's opening_basis), in the run notes, and through GET /recommendations and GET /dashboard (stock_counts[]
.opening_basis); the screens say "projected". The look-ahead guard is kept: a later count than the opening month is
still never used (check_stock_periods). A count a team ruling sets aside (backend/data_notes.OPENING_COUNT_RULINGS)
is still refused, never projected over. --require-count restores the old refusal for a missing count.
  cost per piece  the stock file's unit cost per case ÷ pack size, from the
                  product's latest row that has one. It prices the order and
                  values stock for the cover rule. Falls back to
                  --default-procurement-cost-per-unit.
  last year       the calendar year before the planning month. Its sales in
                  pieces set the allocation (× --allocation-pct ÷ 12, summed
                  per principal); its revenue share is the product's priority
                  when the allocation is short.

PLACEHOLDERS (agreed with Yuan, 2026-09-29; the four cost and capacity inputs are DEC-44, 2026-11-02): the allocation %, review and
lead days, target weeks, cover rule, warehouse capacity and the two costs
have no source in SSM's data yet. Their defaults are
analytics/params.PLACEHOLDERS, the same dict
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
rows for products that fell out of the pool, unless --retire-stale-pending
is given: then those rows are saved to reports/lp_runs/ and deleted in the
same transaction as the cycle's upserts (retire_stale_pending).
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import subprocess
import sys
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import Json, execute_values

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from analytics.etl.granularity import business_days_in_month, resolve_delmonte_category_grain, resolve_unilever_sku_grain
from analytics.allocation import basis_year, monthly_allocation
from analytics.config import long_read_db_url
from scripts.report_target import PRACTICE_MARKER, is_practice_target, report_path
from scripts.run_guards import cycles_with_a_plan, stale_abc_refusal
from analytics.demo.prescriptive import plan_category, sigma_d_for_category
from analytics.optimization.lp import (
    SKUInput, build_lp_model, compute_safety_stock, constraint_slacks, round_to_case_packs, solve_lp, target_stock,
    weekly_demand,
)
from analytics.params import (
    COVER_RULES, LP_WEIGHTS, MASE_GATE, PLACEHOLDERS, SAFETY_STOCK_ASSUMPTION, SERVICE_LEVEL_PCT, SERVICE_Z,
    abc_method_sql,
)
from backend.data_notes import PLANNING_NOTES, opening_count_ruling
from backend.stock_units import (
    PACK_SIZE_NUMERIC, STOCK_AT_PERIOD_SQL, STOCK_COUNTS_SQL, opening_period, stock_count_info,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

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
#
# lp_run_key moves with the numbers: a refreshed row points at this run, a
# decided row keeps the run it was decided on.
UPSERT_QUERY = """
    INSERT INTO LP_Recommendation
    (product_key, planning_cycle_date, q_i, rop_i, ss_i, status, lp_run_key)
    VALUES (%s, %s, %s, %s, %s, 'pending', %s)
    ON CONFLICT (product_key, planning_cycle_date)
    DO UPDATE SET
        q_i = EXCLUDED.q_i,
        rop_i = EXCLUDED.rop_i,
        ss_i = EXCLUDED.ss_i,
        lp_run_key = EXCLUDED.lp_run_key,
        status = 'pending',
        generated_at = now()
    WHERE LP_Recommendation.status = 'pending'
"""

# The same upsert for a database that has migration 0066: it also keeps the order before
# case-pack rounding and the pack size, so the rounding stays auditable row by row.
UPSERT_QUERY_PACK = """
    INSERT INTO LP_Recommendation
    (product_key, planning_cycle_date, q_i, rop_i, ss_i, status, lp_run_key, q_i_before_pack_rounding, pack_size)
    VALUES (%s, %s, %s, %s, %s, 'pending', %s, %s, %s)
    ON CONFLICT (product_key, planning_cycle_date)
    DO UPDATE SET
        q_i = EXCLUDED.q_i,
        rop_i = EXCLUDED.rop_i,
        ss_i = EXCLUDED.ss_i,
        lp_run_key = EXCLUDED.lp_run_key,
        q_i_before_pack_rounding = EXCLUDED.q_i_before_pack_rounding,
        pack_size = EXCLUDED.pack_size,
        status = 'pending',
        generated_at = now()
    WHERE LP_Recommendation.status = 'pending'
"""
PACK_COLUMNS_PRESENT_QUERY = """
    SELECT count(*) = 2 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'lp_recommendation'
      AND column_name IN ('q_i_before_pack_rounding', 'pack_size')
"""

# Pack size in pieces per case, only where backend/stock_units trusts it (a positive number).
PACK_SIZE_QUERY = f"""
    SELECT pd_pack.product_key, pd_pack.pack_size::numeric
    FROM Product_Dimension pd_pack
    WHERE pd_pack.product_key = ANY(%s) AND {PACK_SIZE_NUMERIC}
"""

# --retire-stale-pending. The cycle's rows, read inside the cycle's
# transaction; a real run adds FOR UPDATE so no planner can accept or dismiss
# one between this read and the DELETE (a dry run can't: a READ ONLY
# transaction refuses row locks). rows_to_retire() picks from them.
CYCLE_ROWS_QUERY = "SELECT * FROM LP_Recommendation WHERE planning_cycle_date = %s ORDER BY product_key"

# Keyed on exactly the rows just saved to the CSV, and still guarded on the
# cycle and 'pending', so it can never remove a decided row or another
# cycle's.
RETIRE_QUERY = """
    DELETE FROM LP_Recommendation
    WHERE recommendation_key = ANY(%s)
      AND planning_cycle_date = %s
      AND status = 'pending'
"""

RETIRED_DIR = Path(__file__).resolve().parent.parent / "reports" / "lp_runs"

# What one planning cycle's run used (migration 0037). RETURNING the key the
# cycle's rows then carry.
LP_RUN_INSERT_QUERY = """
    INSERT INTO lp_run (planning_cycle_date, principal_scope, inputs, model, code_version)
    VALUES (%s, %s, %s, %s, %s)
    RETURNING run_key
"""
LP_RUN_PRESENT_QUERY = "SELECT to_regclass('lp_run') IS NOT NULL"

# Category A (latest classification_period) with a Forecast_Result row at
# the latest forecast_date, status='ok', mase < MASE_GATE. Both "latest"
# joins are load-bearing — see the module docstring's fan-out note.
CANDIDATE_QUERY = """
    WITH latest_forecast AS (SELECT MAX(forecast_date) AS d FROM Forecast_Result),
         -- Per-principal, method-pinned. An unscoped MAX() would let one
         -- principal's latest period gate the other's, and an unpinned one
         -- would resolve against another basis's rows (migration 0017).
         -- Each principal's Tier A basis: analytics.params.abc_method_sql
         -- (Unilever TIER_A_BASIS, Del Monte 'single').
         latest_abc AS (
             SELECT principal, MAX(classification_period) AS p
             FROM ABC_Classification
             WHERE {basis}
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
      AND {ac_basis}
      AND ac.tier = 'A'
""".format(basis=abc_method_sql(), ac_basis=abc_method_sql("ac"))

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

# backend/stock_units binds SQLAlchemy-style (:name); psycopg2 takes %(name)s.
_STOCK_AT_OPENING_SQL = STOCK_AT_PERIOD_SQL.replace(":inv_period", "%(stock_period)s")
assert _STOCK_AT_OPENING_SQL.count("%(stock_period)s") == 1 and ":inv_period" not in _STOCK_AT_OPENING_SQL
STOCK_COUNT_QUERY = STOCK_COUNTS_SQL.replace(":count_period", "%(count_period)s")
assert STOCK_COUNT_QUERY.count("%(count_period)s") == 1 and ":count_period" not in STOCK_COUNT_QUERY

# Stock on hand in pieces at the cycle's opening count, %(stock_period)s
# (in_stock_file is false when that count has no row for the product), and
# the cost per piece from the product's latest row that carries a cost.
# pd_pack is the alias backend/stock_units.PACK_SIZE_NUMERIC expects.
STOCK_AND_COST_QUERY = f"""
    SELECT pd_pack.product_key,
           s.product_key IS NOT NULL AS in_stock_file,
           s.stock_pieces,
           CASE WHEN {PACK_SIZE_NUMERIC}
                THEN c.cost_per_case / pd_pack.pack_size::numeric
           END AS cost_per_piece
    FROM Product_Dimension pd_pack
    LEFT JOIN ({_STOCK_AT_OPENING_SQL}) s ON s.product_key = pd_pack.product_key
    LEFT JOIN LATERAL (
        SELECT AVG(inv.unit_cost_per_case) AS cost_per_case
        FROM inventory_fact_real inv
        WHERE inv.product_key = pd_pack.product_key AND inv.unit_cost_per_case > 0
        GROUP BY inv._period
        ORDER BY inv._period DESC
        LIMIT 1
    ) c ON true
    WHERE pd_pack.product_key = ANY(%(product_keys)s)
"""


# Stock on hand per product at the cycle's opening, from the view of migration 0069 (stock_opening_v): the opening
# count plus the receipts still on the way, or the labelled projection when that count is not loaded. in_stock_file is
# whether the product has a row in the count used. The same three columns as STOCK_AND_COST_QUERY.
STOCK_OPENING_PRESENT_QUERY = "SELECT to_regclass('stock_opening_v') IS NOT NULL"
STOCK_AND_COST_FROM_VIEW_QUERY = f"""
    SELECT pd_pack.product_key,
           COALESCE(s.in_stock_file, false) AS in_stock_file,
           s.opening_pieces AS stock_pieces,
           CASE WHEN {PACK_SIZE_NUMERIC}
                THEN c.cost_per_case / pd_pack.pack_size::numeric
           END AS cost_per_piece
    FROM Product_Dimension pd_pack
    LEFT JOIN (SELECT product_key, in_stock_file, opening_pieces FROM stock_opening_v
               WHERE principal = 'unilever' AND cycle = %(cycle)s) s ON s.product_key = pd_pack.product_key
    LEFT JOIN LATERAL (
        SELECT AVG(inv.unit_cost_per_case) AS cost_per_case
        FROM inventory_fact_real inv
        WHERE inv.product_key = pd_pack.product_key AND inv.unit_cost_per_case > 0
        GROUP BY inv._period
        ORDER BY inv._period DESC
        LIMIT 1
    ) c ON true
    WHERE pd_pack.product_key = ANY(%(product_keys)s)
"""
# One row per principal planned on a projection or carrying receipts, for lp_run.inputs and the log.
OPENING_BASIS_QUERY = """
    SELECT principal, opening_basis, MIN(count_period) AS count_period, MIN(count_date) AS count_date,
           COUNT(*) AS products, COALESCE(SUM(expected_receipt_pieces), 0) AS expected_receipt_pieces,
           COALESCE(SUM(expected_receipts), 0) AS expected_receipts,
           COUNT(*) FILTER (WHERE sales_basis = 'actual') AS sales_actual,
           COUNT(*) FILTER (WHERE sales_basis = 'forecast') AS sales_forecast,
           COUNT(*) FILTER (WHERE sales_basis = 'none') AS sales_none
    FROM stock_opening_v WHERE cycle = %(cycle)s GROUP BY principal, opening_basis
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
    stock_period: str | None = None  # the _period of the count stock_on_hand came from
    pack_size: float | None = None   # pieces per case; None = unknown, the order is not rounded
    opening_basis: str = "count"     # 'count', or 'projected' (migration 0069): stock_period is then the count projected from


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
    # Case-pack rounding (round_to_case_packs). orders above are the rounded
    # quantities; these keep what the LP solved before it and one audit row per SKU.
    orders_before_pack_rounding: dict[str, float] | None = None
    pack_audit: list[dict] = field(default_factory=list)
    slacks_before_pack_rounding: dict[str, float] = field(default_factory=dict)
    slacks_after_pack_rounding: dict[str, float] = field(default_factory=dict)

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
        # What the LP solved, before case-pack rounding: rounding down can leave a ceiling that is cutting orders
        # a few pieces short of itself, which must still read as binding.
        solved = self.orders_before_pack_rounding or orders
        by_principal = {
            p: sum(solved.get(s.sku_id, 0.0) for s in self.skus if s.principal == p) for p in self.allocation
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
    assuming days are independent (analytics.params.SAFETY_STOCK_ASSUMPTION).
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


def _sigma_d_for_product(
    demand_df: pd.DataFrame, principal: str, end_period: str | None = None,
) -> tuple[float | None, str | None]:
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

    A month whose row has a blank quantity (total_quantity NaN) is a blank
    capture, not a zero: it is left out of sigma here (the same rule as
    analytics/classification/orchestrate_abc.py, which drops a blank
    net_amount), and counted in the log.

    Unilever only: a month with NO row between the product's first row and
    `end_period` (the latest real demand month; the product's last row when
    None) is a real zero-sale month and enters sigma as 0 (freeze package 1b;
    the zero-sale evidence is in CLAUDE.md "Why data is missing"). Del
    Monte's missing months are collection failures and are never filled.
    """
    has_row = set(demand_df["period"])
    blank = demand_df["total_quantity"].isna()
    if blank.any():
        logger.info(f"    {int(blank.sum())} blank-capture month(s) excluded from sigma (not zero sales).")
        demand_df = demand_df[~blank]
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
        if len(sku_daily_df):
            last = max([max(has_row)] + ([end_period] if end_period else []))
            absent = [str(m) for m in pd.period_range(min(has_row), last, freq="M") if str(m) not in has_row]
            if absent:
                sku_daily_df = pd.concat([sku_daily_df, pd.DataFrame({
                    "sku_code": sku_daily_df["sku_code"].iloc[0], "calendar_month": absent, "quantity_sold": 0.0})],
                    ignore_index=True)
                logger.info(f"    {len(absent)} month(s) with no sales row enter sigma as zero-sale months.")
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
    total_quantity (pieces), total_amount (pesos). A month whose row has a
    blank quantity keeps total_quantity NaN (a blank capture, never a zero):
    _sigma_d_for_product leaves it out, and the prior-year sum skips it."""
    cur.execute(DEMAND_QUERY, (product_keys,))
    df = pd.DataFrame(cur.fetchall(), columns=["product_key", "sku_code", "principal", "period", "total_quantity", "total_amount"])
    df["total_quantity"] = pd.to_numeric(df["total_quantity"], errors="coerce")
    df["total_amount"] = pd.to_numeric(df["total_amount"], errors="coerce").fillna(0)
    return df


def stock_opening_present(cur) -> bool:
    cur.execute(STOCK_OPENING_PRESENT_QUERY)
    return bool(cur.fetchone()[0])


def fetch_stock_and_cost(cur, product_keys: list[int], stock_period: str,
                         cycle=None) -> dict[int, tuple[bool, float | None, float | None]]:
    """product_key -> (in_stock_file, stock_pieces, cost_per_piece), stock
    at the count of `stock_period` only. With `cycle` and migration 0069 applied the stock is the cycle's opening
    from stock_opening_v (the count plus receipts on the way, or the labelled projection); without either it is the
    count alone, as before."""
    if cycle is not None and stock_opening_present(cur):
        cur.execute(STOCK_AND_COST_FROM_VIEW_QUERY, {"product_keys": product_keys, "cycle": cycle})
    else:
        cur.execute(STOCK_AND_COST_QUERY, {"product_keys": product_keys, "stock_period": stock_period})
    return {
        int(k): (bool(in_file), None if pieces is None else float(pieces), None if cost is None else float(cost))
        for k, in_file, pieces, cost in cur.fetchall()
    }


def fetch_pack_sizes(cur, product_keys: list[int]) -> dict[int, float]:
    """product_key -> pieces per case, for the products whose pack size is a positive number."""
    cur.execute(PACK_SIZE_QUERY, (list(product_keys),))
    return {int(k): float(v) for k, v in cur.fetchall()}


def fetch_stock_counts(cur, period: str) -> dict[str, dict]:
    """principal -> its STOCK_COUNTS_SQL row at `period` (row_count,
    first_date, last_date); a principal with no count there is absent."""
    cur.execute(STOCK_COUNT_QUERY, {"count_period": period})
    columns = [d[0] for d in cur.description]
    return {r["principal"]: r for r in (dict(zip(columns, row)) for row in cur.fetchall())}


def month_before(period: str) -> str:
    """'2026-03' -> '2026-02' (January -> the previous December)."""
    year, month = int(period[:4]), int(period[5:7])
    return f"{year - 1}-12" if month == 1 else f"{year}-{month - 1:02d}"


def fetch_opening_basis(cur, planning_cycle_date) -> dict[str, dict]:
    """principal -> its stock_opening_v summary for the cycle (basis, the count behind it, receipts counted, how the
    projected month's sales were known). {} where migration 0069 is not applied or the cycle has no row."""
    if not stock_opening_present(cur):
        return {}
    cur.execute(OPENING_BASIS_QUERY, {"cycle": planning_cycle_date})
    columns = [d[0] for d in cur.description]
    return {r["principal"]: r for r in (dict(zip(columns, row)) for row in cur.fetchall())}


def projected_info(principal: str, planning_cycle_date, row: dict) -> dict:
    """The stock_count_info of a cycle planned on a PROJECTED opening: the count it starts from (the month before
    the opening month), labelled opening_basis = 'projected'. Never presented as a count of the opening month."""
    year, month = planning_cycle_date.year, planning_cycle_date.month
    return {"cycle": f"{year}-{month:02d}-01", "principal": principal, "period": row["count_period"],
            "role": "opening", "available": True, "counted_on": row["count_date"].isoformat(),
            "counted_on_note": None, "row_count": int(row["products"]), "flag": None, "reason": None,
            "opening_basis": "projected",
            "projection": {"from_count": row["count_period"], "opening_month": opening_period(planning_cycle_date),
                           "sales_actual_products": int(row["sales_actual"]),
                           "sales_forecast_products": int(row["sales_forecast"]),
                           "sales_unknown_products": int(row["sales_none"]),
                           "expected_receipt_pieces": float(row["expected_receipt_pieces"])}}


def opening_counts(planning_cycle_date, principals, count_rows: dict[str, dict], basis_rows: dict[str, dict] | None = None,
                   require_count: bool = False) -> tuple[dict[str, dict], dict[str, str]]:
    """({principal: stock_count_info} for the principals that can be planned,
    {principal: reason} for those refused). A principal with the count of the month before the cycle plans from it
    (opening_basis 'count'). One with NO such count loaded plans on a projected opening when stock_opening_v has one
    (basis_rows, fetch_opening_basis) unless require_count: the safety property relaxed deliberately on 2026-10-24,
    see the module docstring. A count that is set aside (backend/data_notes.OPENING_COUNT_RULINGS) is refused and
    never projected over. No later month's count is ever tried."""
    period = opening_period(planning_cycle_date)
    usable: dict[str, dict] = {}
    refused: dict[str, str] = {}
    for principal in sorted(principals):
        info = stock_count_info(principal, period, count_rows.get(principal), cycle=planning_cycle_date)
        if info["available"]:
            info["opening_basis"] = "count"
            usable[principal] = info
            continue
        basis = (basis_rows or {}).get(principal)
        if (count_rows.get(principal) is None and basis is not None and basis["opening_basis"] == "projected"
                and not require_count):
            usable[principal] = projected_info(principal, planning_cycle_date, basis)
        else:
            refused[principal] = info["reason"]
    return usable, refused


def check_stock_periods(products: list[ProductInput], planning_cycle_date) -> None:
    """The look-ahead guard: a cycle plans only from the count that opens it.
    Raises on any product whose stock came from another month's count,
    a later one above all (the bug of 2026-10-03)."""
    want = opening_period(planning_cycle_date)
    earlier = month_before(want)   # the count a PROJECTED opening starts from, never a later one
    wrong = sorted({(p.sku_id, str(p.stock_period)) for p in products
                    if p.stock_period != (earlier if p.opening_basis == "projected" else want)})
    if wrong:
        raise ValueError(f"cycle {planning_cycle_date} plans from the stock count of {want}, the month before it "
                         f"(or, projected, the count of {earlier}); "
                         f"{len(wrong)} product(s) carry another month's stock: {wrong[:5]}")


def _practice_labelled(df: pd.DataFrame) -> pd.DataFrame:
    """A file from a run on the practice copy says so on every row. Anywhere else, df untouched."""
    return df.assign(practice_marker=PRACTICE_MARKER) if is_practice_target() else df


def rows_to_retire(rows: list[dict], planning_cycle_date, solved_keys: set[int]) -> list[dict]:
    """The rows --retire-stale-pending removes: this cycle's pending rows for
    products this run did not solve. Accepted and dismissed rows, and every
    other cycle's rows, are never among them."""
    return [r for r in rows
            if r["planning_cycle_date"] == planning_cycle_date
            and r["status"] == "pending"
            and int(r["product_key"]) not in solved_keys]


def retire_stale_pending(
    cur, planning_cycle_date, solved_keys: set[int], dry_run: bool, out_dir: Path = RETIRED_DIR,
) -> tuple[list[dict], Path | None]:
    """Delete this cycle's pending rows for products outside the run, after
    saving them, every column, to out_dir/retired_<cycle>_<UTC time>.csv.
    Returns (rows, csv path). A dry run only reads: it returns the rows it
    would retire and no path. Called inside cycle_transaction(), after the
    upserts, so the refresh and the retirement land together or not at all."""
    cur.execute(CYCLE_ROWS_QUERY + ("" if dry_run else " FOR UPDATE"), (planning_cycle_date,))
    columns = [d[0] for d in cur.description]
    rows = rows_to_retire([dict(zip(columns, r)) for r in cur.fetchall()], planning_cycle_date, solved_keys)
    if dry_run or not rows:
        return rows, None
    path = report_path(out_dir / f"retired_{planning_cycle_date}_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    _practice_labelled(pd.DataFrame(rows, columns=columns)).to_csv(path, index=False)
    cur.execute(RETIRE_QUERY, ([int(r["recommendation_key"]) for r in rows], planning_cycle_date))
    if cur.rowcount != len(rows):
        raise RuntimeError(f"retiring cycle {planning_cycle_date} deleted {cur.rowcount} row(s), expected "
                           f"{len(rows)}; the cycle is rolled back, so {path} lists rows that were NOT retired")
    return rows, path


@contextmanager
def cycle_transaction(cur, dry_run: bool):
    """One planning cycle's writes as one transaction: its upserts and, with
    --retire-stale-pending, its retirements commit together or not at all.
    A real run's connection is autocommit, so this opens the transaction
    itself. A dry run is already inside its single READ ONLY transaction
    (see main()) and gets nothing here."""
    if dry_run:
        yield
        return
    cur.execute("BEGIN")
    try:
        yield
    except BaseException:
        cur.execute("ROLLBACK")
        raise
    cur.execute("COMMIT")


def product_input(
    product_key: int, sku_id: str, principal: str, forecast: float, sigma_d: float,
    stock_and_cost: dict, history: pd.DataFrame, prior_year: int, stock_period: str | None = None,
    pack_sizes: dict | None = None, opening_basis: str = "count",
) -> tuple[ProductInput | None, str | None]:
    """(ProductInput, None), or (None, reason) when the stock can't be put in
    pieces. stock_period is the count stock_and_cost was read at."""
    in_file, pieces, cost = stock_and_cost.get(int(product_key), (False, None, None))
    if in_file and pieces is None:
        return None, "its stock is in cases and it has no usable pack size, so it can't be put in pieces"
    year = history[(history["product_key"] == product_key)
                   & history["period"].astype(str).str.startswith(f"{prior_year}-")]
    return ProductInput(
        product_key=int(product_key), sku_id=str(sku_id), principal=principal,
        forecast=float(forecast), sigma_d=sigma_d,
        # not in the count: 0 on hand, plus any receipts on the way (a product with a view row but no count row)
        stock_on_hand=pieces if (in_file or pieces is not None) else 0.0, in_stock_file=in_file, cost_per_piece=cost,
        prior_year_pieces=float(year["total_quantity"].sum()),
        prior_year_revenue=float(year["total_amount"].sum()),
        stock_period=stock_period,
        pack_size=(pack_sizes or {}).get(int(product_key)),
        opening_basis=opening_basis,
    ), None


def allocation_ceilings(products: list[ProductInput], allocation_pct: float) -> dict[str, float]:
    """Sir Abe's rule (analytics/allocation.py, the dashboard card's own), pro
    rata to the planned products: the basis year's sales in pieces ×
    allocation % ÷ 12, per principal. Pieces a month."""
    totals: dict[str, float] = {}
    for p in products:
        totals[p.principal] = totals.get(p.principal, 0.0) + max(p.prior_year_pieces, 0.0)
    return {principal: monthly_allocation(total, allocation_pct, unit="pieces") for principal, total in totals.items()}


def _diagnose_infeasibility(skus: list[SKUInput], warehouse_capacity: float) -> list[str]:
    """The target and the cover rule are soft and 0 <= Q_i <= need_i always
    holds, so the only hard constraint that can fail is the warehouse:
    stock on hand alone already above its capacity. An exact diagnosis."""
    stock = sum(s.stock_on_hand for s in skus)
    if stock > warehouse_capacity:
        return [f"stock on hand ({stock:,.0f} pieces) is already above warehouse_capacity ({warehouse_capacity:,.0f})"]
    return ["no bound identified — unexpected; check build_lp_model's constraints directly"]


def plan_cycle(products: list[ProductInput], args: argparse.Namespace, planning_cycle_date=None) -> CyclePlan:
    """One planning cycle, from fetched inputs to the solved orders. Uses
    args.allocation_pct, review_days, lead_days, target_weeks, cover_rule,
    warehouse_capacity, storage_cost_per_unit and
    default_procurement_cost_per_unit. No database. With planning_cycle_date
    (main() always passes it), every product's stock must come from the
    count that opens that month (check_stock_periods)."""
    if planning_cycle_date is not None:
        check_stock_periods(products, planning_cycle_date)
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
    before = None
    audit: list[dict] = []
    slacks_before: dict[str, float] = {}
    slacks_after: dict[str, float] = {}
    if orders is not None and getattr(args, "case_pack_rounding", True):
        before = dict(orders)
        slacks_before = constraint_slacks(skus, before, args.warehouse_capacity, allocation)
        orders, audit = round_to_case_packs(
            skus, before, {p.sku_id: p.pack_size for p in products}, args.warehouse_capacity, allocation)
        slacks_after = constraint_slacks(skus, orders, args.warehouse_capacity, allocation)
    return CyclePlan(
        products=products, skus=skus, allocation=allocation, orders=orders,
        infeasible_reasons=[] if orders is not None else _diagnose_infeasibility(skus, args.warehouse_capacity),
        cover_rule=args.cover_rule, target_weeks=args.target_weeks, warehouse_capacity=args.warehouse_capacity,
        orders_before_pack_rounding=before, pack_audit=audit,
        slacks_before_pack_rounding=slacks_before, slacks_after_pack_rounding=slacks_after,
    )


def plan_rows(plan: CyclePlan, planning_cycle_date, stock_counts: dict[str, dict] | None = None) -> list[dict]:
    """The per-product plan, for the CSV (--csv). stock_counts is
    opening_counts()' first result: each principal's count and its date."""
    rows = []
    for p, s in zip(plan.products, plan.skus):
        q = (plan.orders or {}).get(s.sku_id)
        count = (stock_counts or {}).get(p.principal) or {}
        rows.append({
            "planning_cycle_date": planning_cycle_date, "product_key": p.product_key, "sku_id": s.sku_id,
            "principal": s.principal, "cover_rule": plan.cover_rule,
            "forecast": round(s.demand, 2), "weekly_demand": round(weekly_demand(s.demand), 2),
            "stock_period": p.stock_period, "stock_counted_on": count.get("counted_on"),
            "stock_on_hand": round(s.stock_on_hand, 2), "in_stock_file": p.in_stock_file,
            "safety_stock": round(s.safety_stock, 2), "target_stock": round(s.target_stock, 2),
            "target_weeks_of_sales": round(s.target_stock / weekly_demand(s.demand), 2) if s.demand > 0 else None,
            "need": round(s.need, 2), "order": None if q is None else round(q, 2),
            "order_before_pack_rounding": (None if plan.orders_before_pack_rounding is None
                                           else round(plan.orders_before_pack_rounding[s.sku_id], 2)),
            "pack_size": p.pack_size, "opening_basis": p.opening_basis,
            "short": None if q is None else round(s.need - q, 2),
            "cost_per_piece": round(s.procurement_cost_per_unit, 4),
            "cost_source": "stock file" if p.cost_per_piece is not None else "placeholder",
            "revenue_weight": round(s.revenue_weight, 6), "prior_year_pieces": round(p.prior_year_pieces, 2),
        })
    return rows


def _code_version() -> str | None:
    """The git commit this run came from, or None when it can't be read.
    '+dirty' when a tracked file under the code the run executes (scripts/,
    analytics/, backend/, config/) differs from that commit, so a run from
    uncommitted code is never recorded as the commit alone."""
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10, cwd=here)
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no", "--",
                                "scripts", "analytics", "backend", "config"],
                               capture_output=True, text=True, timeout=10, cwd=os.path.dirname(here))
    except (OSError, subprocess.SubprocessError):
        return None
    commit = out.stdout.strip() if out.returncode == 0 else ""
    if not commit:
        return None
    return f"{commit}+dirty" if dirty.returncode != 0 or dirty.stdout.strip() else commit


# What lp_run keeps of each stock count a plan started from (stock_count_info).
_RECORDED_COUNT_KEYS = ("period", "counted_on", "counted_on_note", "row_count", "flag", "opening_basis")


def recorded_counts(stock_counts: dict[str, dict]) -> dict[str, dict]:
    """opening_counts()' usable counts as a run records them, per principal. A projected opening also records how it
    was projected (the count it started from, how the month's sales were known, the receipts counted)."""
    out = {}
    for principal, info in sorted(stock_counts.items()):
        out[principal] = {k: info.get(k) for k in _RECORDED_COUNT_KEYS}
        if info.get("projection") is not None:
            out[principal]["projection"] = info["projection"]
        if info.get("expected_receipts") is not None:
            out[principal]["expected_receipts"] = info["expected_receipts"]
    return out


def run_notes(stock_counts: dict[str, dict]) -> list[str]:
    """What a plan must be read with, per principal planned: the team's
    ruling on its opening count, if any (backend/data_notes.
    OPENING_COUNT_RULINGS), and the principal's standing caveats
    (PLANNING_NOTES)."""
    notes = []
    for principal, info in sorted(stock_counts.items()):
        ruling = opening_count_ruling(principal, info["period"])
        if ruling is not None and ruling[0] == "use":
            counted = info["counted_on"] or "date not recorded"
            notes.append(f"{principal} stock count {info['period']} (counted {counted}): {ruling[1]}")
        if info.get("opening_basis") == "projected":
            projection = info.get("projection") or {}
            notes.append(f"{principal}: PROJECTED OPENING, NOT A COUNT. The count of {info['period']} "
                         f"(counted {info['counted_on'] or 'date not recorded'}) plus receipts on the way "
                         f"({projection.get('expected_receipt_pieces', 0):,.0f} pieces) less the month's sales "
                         f"({projection.get('sales_actual_products', 0)} products from actual sales, "
                         f"{projection.get('sales_forecast_products', 0)} from the stored forecast). "
                         "Re-plan from the count when it is loaded.")
        if principal in PLANNING_NOTES:
            notes.append(f"{principal}: {PLANNING_NOTES[principal]}")
    return notes


def forecast_provenance(cur, planning_cycle_date) -> list[dict]:
    """The distinct Forecast_Result.model_params.run stamps of the cycle's forecast rows, with row
    counts and the generated_at span; [] when a row has none."""
    cur.execute("""
        SELECT model_params -> 'run', COUNT(*), MIN(generated_at)::text, MAX(generated_at)::text
        FROM Forecast_Result WHERE forecast_date = %s GROUP BY 1 ORDER BY 2 DESC
    """, (planning_cycle_date,))
    return [{"run": r[0], "rows": r[1], "generated_from": r[2], "generated_to": r[3]} for r in cur.fetchall()]


def run_record(args: argparse.Namespace, plan: CyclePlan, planning_cycle_date,
               stock_counts: dict[str, dict], refused: dict[str, str] | None = None,
               forecast_run: list[dict] | None = None) -> dict:
    """The lp_run row for one solved cycle: every flag as run and the stock
    counts planned from (inputs), and what the code fixed (model). What the
    app shows about this run. stock_counts and refused are opening_counts()'
    two results; a refused principal is recorded with its reason."""
    inputs = {key: getattr(args, key) for key in PLACEHOLDERS}
    inputs["stock_counts"] = recorded_counts(stock_counts)
    inputs["opening_basis"] = ("projected" if any(i.get("opening_basis") == "projected" for i in stock_counts.values())
                               else "count")
    inputs["notes"] = run_notes(stock_counts)
    if refused:
        inputs["stock_refused"] = dict(sorted(refused.items()))
    if forecast_run:
        # Provenance of the forecast this plan used: its commit, whether the calendar factor was on,
        # when it was written (Forecast_Result.model_params.run) and how many rows carry that stamp.
        inputs["forecast_run"] = forecast_run
    return {
        "planning_cycle_date": planning_cycle_date,
        "principal_scope": args.principal,
        "inputs": inputs,
        "model": {
            "weights": dict(LP_WEIGHTS),
            "z_score": SERVICE_Z,
            "service_level_pct": SERVICE_LEVEL_PCT,
            "mase_gate": MASE_GATE,
            "safety_stock_window_days": args.review_days + args.lead_days,
            "allocation": {
                "pct": args.allocation_pct,
                "unit": "pieces",
                "basis_year": basis_year(planning_cycle_date),
                "monthly_ceiling": {p: round(v, 2) for p, v in sorted(plan.allocation.items())},
            },
            "safety_stock_assumption": SAFETY_STOCK_ASSUMPTION,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    p = PLACEHOLDERS
    parser = argparse.ArgumentParser(
        description="Plan the monthly order for gated Category A products (LP) and save it to LP_Recommendation.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--source", choices=["real", "demo"], default="real",
        help="real (default): exactly the run this script has always made. demo: the Del Monte demonstration "
             "order plan only (--principal delmonte; see check_source), reading and writing schema demo only.",
    )
    parser.add_argument(
        "--require-count", action="store_true",
        help="Refuse a cycle whose opening stock count is not loaded (the behaviour before 2026-10-24). Without it the "
             "cycle is planned on a PROJECTED opening and labelled opening_basis = projected.",
    )
    parser.add_argument(
        "--case-pack-rounding", action=argparse.BooleanOptionalAction, default=True,
        help="Round each order to whole case packs inside the warehouse and allocation ceilings (up to the next "
             "pack, down where up would breach a ceiling). Products with no pack size, or 1, are unchanged. "
             "ON by default; --no-case-pack-rounding keeps the LP's quantities as solved.",
    )
    parser.add_argument(
        "--write", action="store_true", default=False,
        help="--source demo only: write demo.dm_category_lp. OFF by default — that run is report-only. "
             "Ignored (the real path's write behavior is --dry-run, unchanged) with --source real.",
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
        "--new-run", action="store_true", default=False,
        help="--source demo --principal unilever --write only: write the plan under a NEW demo.run (a copy of the "
             "latest run's inputs, made in the database) instead of replacing the latest run's own plan rows.",
    )
    parser.add_argument(
        "--csv", metavar="PATH", default=None,
        help="Also write the per-product plan to this CSV (with --dry-run too).",
    )
    parser.add_argument(
        "--retire-stale-pending", action="store_true",
        help="Delete the cycle's pending rows for products this run did not plan (a rerun otherwise leaves "
             "them showing orders solved against older forecasts), in the same transaction as the cycle's "
             "upserts, after saving them to reports/lp_runs/retired_<cycle>_<time>.csv. Accepted and "
             "dismissed rows and other cycles are never touched. With --dry-run, only reports what it would retire.",
    )
    parser.add_argument(
        "--replan", action="store_true",
        help="Plan a cycle that already has a plan (rows from an earlier run). Without it a real run refuses "
             "(exit 2): a second run moves figures that were already reviewed. A dry run only warns.",
    )
    parser.add_argument(
        "--allow-stale-abc", action="store_true",
        help="Go on when the ABC period the plan reads is older than the latest real sales month. Without it "
             "the run refuses (exit 2).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Compute and report everything, write nothing: the database session is read-only.",
    )
    return parser


def _log_inputs(args: argparse.Namespace) -> None:
    logger.warning(LOUD_RULE)
    logger.warning("PLACEHOLDER INPUTS: realistic values the team chose until SSM (Sir Abe) confirms them.")
    logger.warning("They are NOT SSM's figures. Defaults: analytics/params.PLACEHOLDERS.")
    for key, default in PLACEHOLDERS.items():
        value = getattr(args, key)
        changed = "" if value == default else f"   <- flag; the default is {default}"
        logger.warning(f"  {key:<36} = {value}{changed}")
    logger.warning(f"  safety stock window = review + lead = {args.review_days + args.lead_days:g} business days")
    logger.warning(LOUD_RULE)
    if not args.dry_run and any(getattr(args, k) != v for k, v in PLACEHOLDERS.items()):
        logger.warning("A real run with non-default inputs: they are recorded in lp_run, and the app "
                       "shows them for this cycle. The defaults stay analytics/params.PLACEHOLDERS.")
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


def check_source(source: str, principal: str) -> None:
    """--source real (the default) is the plan this script has always made; it never touches schema demo.

    --source demo (Kelvin, 2026-10-16, migrations 0056/0057): --principal delmonte (demo forecast AND demo stock,
    analytics/demo/prescriptive.py) or --principal unilever (demo forecast, REAL stock — _run_demo_lp_unilever).
    'both' + --source demo is refused, before any connection: each principal's demo plan uses a different mix of
    real and generated inputs and must never be silently combined into one run that looks like a normal cycle."""
    if source == "real":
        return
    if principal not in ("delmonte", "unilever"):
        raise SystemExit("run_lp: no order plan is generated for the demonstration outside --principal delmonte "
                         "or --principal unilever. Omit --source, or pass --source real.")


def refuse_empty_demo_plan(label: str, orders: dict[str, float] | None, reasons: list[str] | None = None,
                           need: float | None = None) -> None:
    """A demonstration plan with no order anywhere is never written (Kelvin, 2026-10-20).

    The 2026-10-16 Unilever plan (demo run 10) was written with all 96 orders at 0.0: solve_lp had returned None
    (CBC reported a falsely Infeasible stage, fixed in 136529e) and the writer's `(plan.orders or {}).get(sku, 0.0)`
    turned that None into zeros, silently. None means infeasible, never "order nothing"; and a plan where every
    order is zero is a state to look at, not to publish. Both stop the run, in a dry run too, before anything is
    written. `need` (pieces still needed to reach target, summed) is named when known so a genuinely fully-stocked
    cycle can be told from a solver failure."""
    if orders is None:
        raise SystemExit(f"{label}: the LP returned no solution (infeasible). Nothing written. "
                         + "; ".join(reasons or ["no reason diagnosed"]))
    if orders and all(q <= 0 for q in orders.values()):
        detail = (f"total need is {need:,.0f} pieces, so a solver or input defect is likely" if need
                  else "total need is 0, so every SKU is already at or above target")
        raise SystemExit(f"{label}: all {len(orders)} orders are 0 ({detail}). Nothing written. "
                         "An all-zero demonstration plan is never published silently; inspect it first.")


def _run_demo_lp(write: bool) -> int:
    """--source demo --principal delmonte: analytics/demo/prescriptive.py's order-up-to over the demonstration's
    own forecast and stock (migration 0056). Reads and writes schema demo only; never touches lp_run,
    LP_Recommendation or Forecast_Result. Report-only unless --write."""
    db_url = long_read_db_url()
    conn = psycopg2.connect(db_url, connect_timeout=20)
    try:
        cur = conn.cursor()
        cur.execute("BEGIN")
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute("SELECT run_id, window_end FROM demo.run WHERE principal = 'delmonte' AND label = 'demonstration' "
                    "ORDER BY run_id DESC LIMIT 1")
        row = cur.fetchone()
        if row is None:
            cur.execute("ROLLBACK")
            raise SystemExit("run_lp --source demo: no Del Monte demonstration run exists yet "
                             "(python -m scripts.build_dm_demo --write --replace first).")
        run_id, window_end = row
        cur.execute("SELECT category_path, product_key, forecast_period, forecast_quantity FROM demo.dm_forecast "
                    "WHERE run_id = %s", (run_id,))
        forecasts = cur.fetchall()
        cur.execute("SELECT category_path, quantity_on_hand FROM demo.dm_category_stock "
                    "WHERE run_id = %s AND period = %s", (run_id, window_end))
        stock = dict(cur.fetchall())
        cur.execute("SELECT category_path, period, quantity FROM demo.dm_category_sales "
                    "WHERE run_id = %s AND quantity IS NOT NULL", (run_id,))
        sales_rows = cur.fetchall()
        cur.execute("ROLLBACK")
    finally:
        conn.close()

    sales_by_cat: dict[str, dict[str, float]] = {}
    for cat, period, qty in sales_rows:
        sales_by_cat.setdefault(cat, {})[period] = float(qty)

    plans, skipped = [], []
    for cat, pk, period, fq in forecasts:
        if cat not in stock:
            skipped.append((cat, "no stock row for the opening period " + window_end))
            continue
        sigma_d = sigma_d_for_category(sales_by_cat.get(cat, {}))
        if sigma_d is None:
            skipped.append((cat, "fewer than 2 months of demonstration sales to derive a sigma from"))
            continue
        plan = plan_category(cat, float(fq), float(stock[cat]), sigma_d)
        plans.append((run_id, cat, pk, period, plan))

    refuse_empty_demo_plan("run_lp --source demo --principal delmonte",
                           {c: pl.order_qty for _r, c, _pk, _p, pl in plans},
                           need=sum(max(pl.target_stock - pl.stock_on_hand, 0.0) for _r, _c, _pk, _p, pl in plans))
    print(json.dumps({
        "run_id": run_id, "window_end": window_end, "planned": len(plans), "skipped": skipped,
        "plans": [{"category": c, "period": p, "forecast_quantity": pl.forecast_quantity,
                   "stock_on_hand": pl.stock_on_hand, "sigma_d": round(pl.sigma_d, 4),
                   "safety_stock": round(pl.safety_stock, 2), "target_stock": round(pl.target_stock, 2),
                   "order_qty": round(pl.order_qty, 2)}
                  for _r, c, _pk, p, pl in plans],
    }, indent=1))

    if not write:
        print("[dry] nothing written (pass --write)")
        return EXIT_OK
    if not plans:
        print("[write] nothing to write: the run asked to write and had no plan to write")
        return EXIT_REFUSED
    wconn = psycopg2.connect(db_url, connect_timeout=20)
    try:
        wcur = wconn.cursor()
        wcur.execute("SHOW default_transaction_read_only")
        if wcur.fetchone()[0] != "off":
            raise SystemExit("default_transaction_read_only is on for this connection; refusing to write")
        wcur.execute("SELECT to_regclass('demo.dm_category_lp')")
        if wcur.fetchone()[0] is None:
            raise SystemExit("demo.dm_category_lp is not there: apply migration 0056 first")
        wcur.execute("DELETE FROM demo.dm_category_lp WHERE run_id = %s", (run_id,))
        execute_values(
            wcur,
            "INSERT INTO demo.dm_category_lp (run_id, category_path, product_key, period, forecast_quantity, "
            "stock_on_hand, sigma_d, safety_stock, target_stock, order_qty) VALUES %s",
            [(r, c, pk, p, pl.forecast_quantity, pl.stock_on_hand, pl.sigma_d, pl.safety_stock, pl.target_stock,
              pl.order_qty) for r, c, pk, p, pl in plans],
        )
        wconn.commit()
    except BaseException:
        wconn.rollback()
        raise
    finally:
        wconn.close()
    print(f"[write] demo.dm_category_lp run_id {run_id}: {len(plans)} row(s)")
    return 0


def _run_demo_lp_unilever(write: bool, new_run: bool = False) -> int:
    """--source demo --principal unilever: the dominant forecast cohort of demo.unilever_sku_forecast (the one
    forecast_period most SKUs share — most reach the same last real month) against REAL stock on hand and REAL
    cost (scripts/run_lp.py's own fetchers: fetch_stock_counts, opening_counts, fetch_stock_and_cost — the real
    path's data, untouched) and DEMO sigma (the demonstration's own sales history, including the 2021-22
    back-cast — expected to move sigma; see docs/DEMO_DATA.md). plan_cycle() is the real LP, unchanged, run with
    PLACEHOLDERS' real Unilever defaults (warehouse capacity, allocation %). Writes demo.unilever_sku_lp only;
    never touches lp_run, LP_Recommendation or Forecast_Result. Report-only unless --write.

    --new-run (with --write): the plan is written under a NEW demo.run, a copy of the source run's row, sales,
    backcast exclusions and forecast made inside the database (INSERT ... SELECT), so the source run and its plan
    are left exactly as they were. Without it the plan replaces the source run's own rows (DELETE + INSERT)."""
    db_url = long_read_db_url()
    conn = psycopg2.connect(db_url, connect_timeout=20)
    try:
        cur = conn.cursor()
        cur.execute("BEGIN")
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute("SELECT run_id FROM demo.run WHERE principal = 'unilever' AND label = 'demonstration_unilever' "
                    "ORDER BY run_id DESC LIMIT 1")
        row = cur.fetchone()
        if row is None:
            raise SystemExit("run_lp --source demo --principal unilever: no Unilever demonstration run exists yet "
                             "(python -m scripts.build_unilever_demo --write --replace first).")
        run_id = row[0]
        cur.execute("SELECT forecast_period, COUNT(*) FROM demo.unilever_sku_forecast WHERE run_id = %s "
                    "GROUP BY forecast_period ORDER BY COUNT(*) DESC LIMIT 1", (run_id,))
        dominant = cur.fetchone()
        if dominant is None:
            raise SystemExit("run_lp --source demo --principal unilever: the demonstration run has no forecast rows.")
        forecast_period = dominant[0]
        cur.execute("SELECT product_key, sku_code, forecast_quantity FROM demo.unilever_sku_forecast "
                    "WHERE run_id = %s AND forecast_period = %s", (run_id, forecast_period))
        forecasts = {int(pk): (sku, max(0.0, float(fq))) for pk, sku, fq in cur.fetchall()}   # demand cannot be negative (2a)
        cohort_before_membership_filter = len(forecasts)
        # Membership filter (Kelvin, 2026-10-16): the demo forecast cohort above is every Tier A SKU
        # build_unilever_demo.py could fit an MA3 for -- it has no accuracy metric of its own (rule 2 forbids
        # one in schema demo), so on its own it would plan for SKUs the real system refuses to (demand hard to
        # forecast, not missing 2021-22 data). Read the REAL Forecast_Result's gate instead, at its own latest
        # forecast_date -- the same status='ok' AND mase < MASE_GATE test run_lp.py's own CANDIDATE_QUERY applies
        # -- and keep only SKUs that pass it. The metric itself never crosses into schema demo; only the SKU list
        # does.
        cur.execute(
            "SELECT fr.product_key, fr.status, fr.mase FROM Forecast_Result fr "
            "JOIN (SELECT MAX(forecast_date) AS d FROM Forecast_Result) lf ON fr.forecast_date = lf.d "
            "WHERE fr.product_key = ANY(%s)", (list(forecasts),),
        )
        real_gate = {int(pk): (status, float(mase) if mase is not None else None) for pk, status, mase in cur.fetchall()}
        membership_dropped = []
        for pk in list(forecasts):
            status, mase = real_gate.get(pk, (None, None))
            if not (status == "ok" and mase is not None and mase < MASE_GATE):
                membership_dropped.append((forecasts[pk][0], status, mase))
                del forecasts[pk]
        product_keys = list(forecasts)
        cur.execute("SELECT product_key, period, quantity, net_amount FROM demo.unilever_sku_sales "
                    "WHERE run_id = %s AND product_key = ANY(%s)", (run_id, product_keys))
        demo_sales = cur.fetchall()

        year, month = (int(x) for x in forecast_period.split("-"))
        planning_cycle_date = date(year, month, 1)
        stock_period = opening_period(planning_cycle_date)
        stock_counts = fetch_stock_counts(cur, stock_period)
        usable, refused = opening_counts(planning_cycle_date, {"unilever"}, stock_counts)
        if "unilever" not in usable:
            raise SystemExit(f"run_lp --source demo --principal unilever: {refused.get('unilever')}")
        stock_and_cost = fetch_stock_and_cost(cur, product_keys, stock_period)
        cur.execute("ROLLBACK")
    finally:
        conn.close()

    demand_df = pd.DataFrame(demo_sales, columns=["product_key", "period", "total_quantity", "total_amount"])
    demand_df["total_quantity"] = pd.to_numeric(demand_df["total_quantity"], errors="coerce")
    demand_df["total_amount"] = pd.to_numeric(demand_df["total_amount"], errors="coerce").fillna(0)

    args = argparse.Namespace(**PLACEHOLDERS)
    prior_year = basis_year(planning_cycle_date)
    products, skipped = [], []
    for pk in product_keys:
        sku_id, forecast = forecasts[pk]
        product_demand = demand_df[demand_df["product_key"] == pk].assign(sku_code=sku_id)
        sigma_d, reason = _sigma_d_for_product(product_demand, "unilever", stock_period)
        if sigma_d is None:
            skipped.append((sku_id, reason))
            continue
        product, reason = product_input(pk, sku_id, "unilever", forecast, sigma_d, stock_and_cost,
                                         demand_df, prior_year=prior_year, stock_period=stock_period)
        if product is None:
            skipped.append((sku_id, reason))
            continue
        products.append(product)

    plan = plan_cycle(products, args, planning_cycle_date=None) if products else None
    rows = []
    if plan is not None:
        refuse_empty_demo_plan("run_lp --source demo --principal unilever", plan.orders, plan.infeasible_reasons,
                               need=sum(s.need for s in plan.skus))
        for p, s in zip(plan.products, plan.skus):
            rows.append((run_id, p.product_key, p.sku_id, forecast_period, s.demand, p.stock_on_hand, p.sigma_d,
                        s.safety_stock, s.target_stock, plan.orders[s.sku_id]))

    print(json.dumps({
        "run_id": run_id, "forecast_period": forecast_period, "stock_period": stock_period,
        "membership_filter": "real Forecast_Result, latest forecast_date, status='ok' AND mase < MASE_GATE "
                              "(the real LP's own CANDIDATE_QUERY gate) -- no metric crosses into schema demo, "
                              "only the SKU list",
        "demo_forecast_cohort": cohort_before_membership_filter,
        "membership_passed": len(forecasts), "membership_dropped": len(membership_dropped),
        "membership_dropped_reasons": dict(Counter(
            "no real forecast_result row" if status is None
            else f"status={status}" if status != "ok"
            else f"mase>={MASE_GATE:g}"
            for _sku, status, _mase in membership_dropped)),
        "planned": len(rows), "skipped": len(skipped), "skipped_reasons": dict(Counter(r for _s, r in skipped)),
        "rows": [{"sku_id": r[2], "forecast": round(r[4], 2), "stock_on_hand": round(r[5], 2),
                  "sigma_d": round(r[6], 4), "safety_stock": round(r[7], 2), "target_stock": round(r[8], 2),
                  "order_qty": round(r[9], 2)} for r in rows[:10]],
        "note": "first 10 of %d rows shown" % len(rows),
    }, indent=1, default=str))

    if not write:
        print("[dry] nothing written (pass --write)")
        return EXIT_OK
    if not rows:
        print("[write] nothing to write: the run asked to write and had no plan to write")
        return EXIT_REFUSED
    wconn = psycopg2.connect(db_url, connect_timeout=20)
    try:
        wcur = wconn.cursor()
        wcur.execute("SHOW default_transaction_read_only")
        if wcur.fetchone()[0] != "off":
            raise SystemExit("default_transaction_read_only is on for this connection; refusing to write")
        wcur.execute("SELECT to_regclass('demo.unilever_sku_lp')")
        if wcur.fetchone()[0] is None:
            raise SystemExit("demo.unilever_sku_lp is not there: apply migration 0057 first")
        if new_run:
            source_run = run_id
            wcur.execute(
                "INSERT INTO demo.run (label, principal, seed, generator_version, jitter_scale, window_end, "
                "forecast_target, cost_ratio, cost_ratio_source, approved_by, approved_on, notes) "
                "SELECT label, principal, seed, generator_version, jitter_scale, window_end, forecast_target, "
                "cost_ratio, cost_ratio_source, approved_by, approved_on, "
                "COALESCE(notes, '{}'::jsonb) || jsonb_build_object('cloned_from_run', run_id, "
                "'clone_reason', 'order plan regenerated after the LP solver fix (136529e); inputs copied unchanged') "
                "FROM demo.run WHERE run_id = %s RETURNING run_id", (source_run,))
            run_id = wcur.fetchone()[0]
            for table, columns in (
                ("unilever_sku_sales", "product_key, sku_code, period, quantity, net_amount, origin"),
                ("backcast_excluded", "series_key, reason, real_months, first_real_period"),
                ("unilever_sku_forecast", "product_key, sku_code, forecast_period, forecast_quantity, method, "
                                          "history_months, blank_capture_filled"),
            ):
                wcur.execute(f"INSERT INTO demo.{table} (run_id, {columns}) SELECT %s, {columns} "
                             f"FROM demo.{table} WHERE run_id = %s", (run_id, source_run))
            rows = [(run_id, *r[1:]) for r in rows]
        wcur.execute("DELETE FROM demo.unilever_sku_lp WHERE run_id = %s", (run_id,))
        execute_values(
            wcur,
            "INSERT INTO demo.unilever_sku_lp (run_id, product_key, sku_code, period, forecast_quantity, "
            "stock_on_hand, sigma_d, safety_stock, target_stock, order_qty) VALUES %s", rows,
        )
        wconn.commit()
    except BaseException:
        wconn.rollback()
        raise
    finally:
        wconn.close()
    print(f"[write] demo.unilever_sku_lp run_id {run_id}: {len(rows)} row(s)")
    return 0


# Exit codes (2026-10-31): 0 = the run did what was asked; 2 = a refusal (nothing, or not everything, was planned
# or written, on purpose); 1 = an error (missing configuration, or an uncaught exception / a SystemExit message).
EXIT_OK, EXIT_ERROR, EXIT_REFUSED = 0, 1, 2


def main():
    args = build_parser().parse_args()
    check_source(args.source, args.principal)
    if args.source == "demo":
        if args.new_run and not (args.write and args.principal == "unilever"):
            raise SystemExit("--new-run needs --source demo --principal unilever --write")
        return (_run_demo_lp_unilever(args.write, args.new_run) if args.principal == "unilever"
                else _run_demo_lp(args.write))
    _log_inputs(args)

    load_dotenv(override=False)
    db_url = os.environ.get("SUPABASE_DB_URL")
    if not db_url:
        logger.error("SUPABASE_DB_URL not set in .env")
        return EXIT_ERROR

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

    # Every real run records what it used (lp_run, migration 0037): without
    # the table the app could only state defaults, so a real run refuses.
    cur.execute(LP_RUN_PRESENT_QUERY)
    if not cur.fetchone()[0]:
        if not args.dry_run:
            logger.error("lp_run is missing: apply analytics/db/migrations/0037_lp_run.sql before a real "
                         "run, so the app can show what this run used. Nothing was written.")
            conn.close()
            return EXIT_REFUSED
        logger.warning("lp_run is missing (migration 0037): a real run would refuse until it is applied.")

    # Case-pack rounding keeps the order before it (migration 0066). Without the
    # columns a real run could not show what rounding did, so it refuses.
    cur.execute(PACK_COLUMNS_PRESENT_QUERY)
    pack_columns = bool(cur.fetchone()[0])
    if args.case_pack_rounding and not pack_columns:
        if not args.dry_run:
            logger.error("lp_recommendation.q_i_before_pack_rounding / pack_size are missing: apply "
                         "analytics/db/migrations/0066_lp_case_pack_rounding.sql before a real run, so the rounding "
                         "stays auditable (or pass --no-case-pack-rounding). Nothing was written.")
            conn.close()
            return EXIT_REFUSED
        logger.warning("migration 0066 is not applied: a real run with case-pack rounding would refuse until it is.")

    def save_result(product_key, planning_cycle_date, q_i, rop_i, ss_i, run_key,
                    q_before_rounding=None, pack_size=None) -> bool:
        """Upsert one row. False when it hit a decided row and changed nothing."""
        if pack_columns:
            cur.execute(UPSERT_QUERY_PACK, (int(product_key), planning_cycle_date, float(q_i), float(rop_i),
                                            float(ss_i), int(run_key),
                                            None if q_before_rounding is None else float(q_before_rounding),
                                            None if pack_size is None else float(pack_size)))
        else:
            cur.execute(UPSERT_QUERY, (int(product_key), planning_cycle_date, float(q_i), float(rop_i), float(ss_i),
                                       int(run_key)))
        return cur.rowcount > 0

    def save_run(record: dict) -> int:
        """Insert one lp_run row; its run_key."""
        cur.execute(LP_RUN_INSERT_QUERY, (
            record["planning_cycle_date"], record["principal_scope"],
            Json(record["inputs"]), Json(record["model"]), code_version,
        ))
        return int(cur.fetchone()[0])

    code_version = _code_version()

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
        logger.error("No candidates after gating: no plan was made. Nothing was written.")
        conn.close()
        return EXIT_REFUSED

    # ---- Refusals before anything is computed or written (audit P1, P2; scripts/run_guards.py) ----
    cur.execute("SELECT MAX(classification_period) FROM ABC_Classification WHERE principal = 'unilever' AND "
                + abc_method_sql())
    stale = stale_abc_refusal(cur, cur.fetchone()[0]) if "unilever" in set(candidates_df["principal"]) else None
    if stale:
        if not args.allow_stale_abc:
            logger.error(f"REFUSED: {stale} Nothing was written.")
            conn.close()
            sys.exit(EXIT_REFUSED)
        logger.warning(f"--allow-stale-abc: {stale}")
    planned = cycles_with_a_plan(cur, list(candidates_df["forecast_date"].unique()), set(candidates_df["principal"]))
    if planned:
        said = ", ".join(f"{c} ({n} rows)" for c, n in planned)
        if args.dry_run:
            logger.warning(f"Cycle(s) already planned: {said}. A real run would refuse without --replan.")
        elif not args.replan:
            logger.error(f"REFUSED: cycle(s) already planned: {said}. A second run moves a plan that was reviewed; "
                         "pass --replan to plan again on purpose. Nothing was written.")
            conn.close()
            sys.exit(EXIT_REFUSED)
        else:
            logger.warning(f"--replan: planning again over {said}.")

    # ---- Step B: sales history ------------------------------------------
    product_keys = [int(k) for k in candidates_df["product_key"].unique()]
    demand_df = fetch_demand_history(cur, product_keys)

    # ---- Step C: per cycle, the opening stock count, then per-product inputs
    gated_out: dict[str, int] = {}
    products_by_cycle: dict = {}  # planning_cycle_date -> list[ProductInput]
    counts_by_cycle: dict = {}    # planning_cycle_date -> {principal: stock_count_info} planned from
    refused_by_cycle: dict = {}   # planning_cycle_date -> {principal: reason}
    refused_products = 0

    def gate_out(sku_id, principal, reason):
        gated_out[reason] = gated_out.get(reason, 0) + 1
        logger.warning(f"  {sku_id} ({principal}): gated out — {reason}.")

    for planning_cycle_date in sorted(candidates_df["forecast_date"].unique()):
        cycle_df = candidates_df[candidates_df["forecast_date"] == planning_cycle_date]
        stock_period = opening_period(planning_cycle_date)
        basis_rows = fetch_opening_basis(cur, planning_cycle_date)
        usable, refused = opening_counts(planning_cycle_date, set(cycle_df["principal"]),
                                         fetch_stock_counts(cur, stock_period), basis_rows=basis_rows,
                                         require_count=args.require_count)
        for principal, info in usable.items():   # receipts counted on a count-basis opening, for lp_run.inputs
            row = basis_rows.get(principal)
            if info.get("opening_basis") == "count" and row is not None:
                info["expected_receipts"] = {"pieces": float(row["expected_receipt_pieces"]), "receipts": int(row["expected_receipts"])}
        counts_by_cycle[planning_cycle_date] = usable
        refused_by_cycle[planning_cycle_date] = refused
        for principal, reason in refused.items():
            count = int((cycle_df["principal"] == principal).sum())
            refused_products += count
            logger.error(f"  REFUSED cycle {planning_cycle_date} for {principal} ({count} product(s)): {reason}. "
                         "Nothing is planned for it, and no other month's count is used.")
        for principal, info in usable.items():
            counted = info["counted_on"] or f"date not recorded: {info['counted_on_note']}"
            if info["opening_basis"] == "projected":
                logger.warning(f"  Cycle {planning_cycle_date} · {principal}: NO COUNT FOR {opening_period(planning_cycle_date)} IS LOADED. "
                               f"Planning on a PROJECTED opening from the count of {info['period']} (counted {counted}), "
                               "plus receipts on the way, less that month's sales. opening_basis = projected is recorded "
                               "on the run and shown by the app. Use --require-count to refuse instead.")
            else:
                logger.info(f"  Cycle {planning_cycle_date} · {principal}: opening stock count {info['period']} "
                            f"(counted {counted}; {info['row_count']} rows)")
            if info["flag"]:
                logger.warning(f"  Cycle {planning_cycle_date} · {principal}: that count is flagged: {info['flag']}")
        for note in run_notes(usable):
            logger.warning(f"  Cycle {planning_cycle_date} note: {note}")
        cycle_df = cycle_df[cycle_df["principal"].isin(list(usable))]
        if cycle_df.empty:
            continue
        cycle_keys = [int(k) for k in cycle_df["product_key"].unique()]
        stock_and_cost = fetch_stock_and_cost(cur, cycle_keys, stock_period, cycle=planning_cycle_date)
        pack_sizes = fetch_pack_sizes(cur, cycle_keys)

        for row in cycle_df.itertuples():
            product_demand = demand_df[demand_df["product_key"] == row.product_key]
            if product_demand.empty:
                gate_out(row.sku_id, row.principal, "no demand history at all")
                continue
            sigma_d, reason = _sigma_d_for_product(product_demand, row.principal, opening_period(planning_cycle_date))
            if sigma_d is None:
                gate_out(row.sku_id, row.principal, reason)
                continue
            product, reason = product_input(
                row.product_key, row.sku_id, row.principal, float(row.forecast_value), sigma_d,
                stock_and_cost, demand_df, prior_year=basis_year(row.forecast_date),
                stock_period=usable[row.principal]["period"],     # the count stock came from (earlier if projected)
                pack_sizes=pack_sizes, opening_basis=usable[row.principal]["opening_basis"],
            )
            if product is None:
                gate_out(row.sku_id, row.principal, reason)
                continue
            if not product.in_stock_file:
                logger.warning(f"  {row.sku_id} ({row.principal}): not in the opening stock count ({stock_period}) "
                               "— counted as 0 on hand.")
            products_by_cycle.setdefault(planning_cycle_date, []).append(product)

    # ---- Step D: one LP per planning cycle -------------------------------
    rows_written = 0
    rows_kept_decided = 0
    stale_pending_by_cycle: dict = {}
    retired_by_cycle: dict = {}  # planning_cycle_date -> (rows retired, CSV path or None)
    total_ss_by_cycle: dict = {}
    infeasible_cycles: list[tuple] = []
    csv_rows: list[dict] = []

    for planning_cycle_date, products in sorted(products_by_cycle.items()):
        logger.info(f"Solving LP for planning cycle {planning_cycle_date} ({len(products)} product(s), "
                    f"cover rule {args.cover_rule})...")
        plan = plan_cycle(products, args, planning_cycle_date)
        csv_rows.extend(plan_rows(plan, planning_cycle_date, counts_by_cycle[planning_cycle_date]))

        if plan.orders is None:
            for reason in plan.infeasible_reasons:
                logger.error(f"  INFEASIBLE cycle {planning_cycle_date}: {reason}")
            infeasible_cycles.append((planning_cycle_date, plan.infeasible_reasons))
            logger.error(f"  Writing NOTHING for cycle {planning_cycle_date} — no constraint was relaxed to force a solution.")
            continue
        _log_cycle(plan, args.allocation_pct, basis_year(planning_cycle_date))

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
        with cycle_transaction(cur, args.dry_run):
            # The run's record commits with the rows that point at it: a cycle
            # rolled back (e.g. a retire count mismatch) leaves no lp_run row.
            run_key = None if args.dry_run else save_run(run_record(
                args, plan, planning_cycle_date, counts_by_cycle[planning_cycle_date],
                refused_by_cycle[planning_cycle_date], forecast_provenance(cur, planning_cycle_date),
            ))
            for product, sku in zip(products, plan.skus):
                q_i, ss_i = plan.orders[sku.sku_id], sku.safety_stock
                decided = existing.get(product.product_key, "pending") != "pending"
                if args.dry_run:
                    short = sku.need - q_i
                    logger.info(f"  [dry run] {sku.sku_id}: order {q_i:,.0f} of need {sku.need:,.0f}"
                                f"{f' (short {short:,.0f})' if short > 0.5 else ''} · target {sku.target_stock:,.0f} "
                                f"(SS {ss_i:,.0f}) · stock {sku.stock_on_hand:,.0f} · forecast {sku.demand:,.0f}"
                                f"{'  (decided row — would be kept as is)' if decided else ''}")
                elif not save_result(product.product_key, planning_cycle_date, q_i, sku.target_stock, ss_i, run_key,
                                     None if plan.orders_before_pack_rounding is None
                                     else plan.orders_before_pack_rounding[sku.sku_id], product.pack_size):
                    decided = True
                if decided:
                    cycle_kept += 1
                else:
                    cycle_written += 1
            # A refused principal's rows weren't replanned, so they aren't
            # "outside the pool": with a refusal in the cycle, retire nothing.
            if args.retire_stale_pending and not refused_by_cycle[planning_cycle_date]:
                retired, retired_csv = retire_stale_pending(cur, planning_cycle_date, written_keys, args.dry_run)
                retired_by_cycle[planning_cycle_date] = (len(retired), retired_csv)
            elif args.retire_stale_pending:
                logger.warning(f"  Cycle {planning_cycle_date}: --retire-stale-pending skipped — "
                               f"{', '.join(refused_by_cycle[planning_cycle_date])} refused for want of an opening "
                               "stock count, so no pending row in this cycle is retired.")
                retired_by_cycle[planning_cycle_date] = (0, None)
        rows_written += cycle_written
        rows_kept_decided += cycle_kept
        verb = "would be upserted" if args.dry_run else "upserted into LP_Recommendation (status='pending')"
        logger.info(f"  Cycle {planning_cycle_date}: {cycle_written} row(s) {verb}"
                    f"{f'; {cycle_kept} decided row(s) kept as they were' if cycle_kept else ''}.")
        if args.retire_stale_pending:
            count, retired_csv = retired_by_cycle[planning_cycle_date]
            logger.info(f"  Cycle {planning_cycle_date}: {count} pending row(s) for products outside this run's pool "
                        f"{'would be retired' if args.dry_run else 'retired'}"
                        f"{f', saved first to {retired_csv}' if retired_csv else ''}.")
        elif stale:
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

    # Migration 0041: rebuild the dashboard's marts after a real run (the LP figures
    # themselves are joined per request; the refresh keeps the log and freshness check
    # in step with every LP run).
    if not args.dry_run:
        from analytics.marts import refresh_marts
        refresh_marts(db_url, "run_lp")

    if args.csv:
        _practice_labelled(pd.DataFrame(csv_rows)).to_csv(args.csv, index=False)
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
    logger.info(f"  Products refused (no usable opening stock count): {refused_products}")
    for cycle_date, refused in sorted(refused_by_cycle.items()):
        for principal, reason in refused.items():
            logger.info(f"    - {cycle_date} {principal}: {reason}")
    logger.info(f"  Stock on hand:               {planned - missing_stock} from the opening stock count, "
                f"{missing_stock} not in it (counted as 0)")
    for cycle_date, counts in sorted(counts_by_cycle.items()):
        for principal, info in counts.items():
            logger.info(f"    - {cycle_date} {principal}: count {info['period']}, counted "
                        f"{info['counted_on'] or 'on an unrecorded date'}{' (FLAGGED)' if info['flag'] else ''}")
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
    for cycle_date, (count, retired_csv) in retired_by_cycle.items():
        logger.info(f"  Pending rows {'that would be ' if args.dry_run else ''}retired in {cycle_date} "
                    f"(products outside this run's pool): {count}{f' -> {retired_csv}' if retired_csv else ''}")
    for cycle_date, stale in stale_pending_by_cycle.items():
        if stale and not args.retire_stale_pending:
            logger.info(f"  Pending rows left unchanged in {cycle_date} (products outside this run's pool): {len(stale)}")
    for cycle_date, count in older_pending:
        logger.info(f"  Older cycle still pending: {cycle_date} ({count} row(s))")
    if args.dry_run:
        logger.info("  DRY RUN — nothing was written.")
    logger.info(LOUD_RULE)
    # A cycle with no usable opening count, or no feasible plan, wrote nothing for those products: the run did
    # not do what was asked, so it must not report success (a dry run included: the real run would refuse).
    if refused_products or infeasible_cycles:
        logger.error(f"EXIT {EXIT_REFUSED}: {refused_products} product(s) refused for want of an opening count, "
                     f"{len(infeasible_cycles)} infeasible cycle(s). What was plannable is written; the rest is not.")
        return EXIT_REFUSED
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
