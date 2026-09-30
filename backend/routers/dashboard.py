"""
backend.routers.dashboard — GET /dashboard

Feeds the Dashboard page's four original KPI cards + weeks-of-cover chart
(frontend/src/api/dashboard.js's getDashboardData), PLUS the five widgets
the Dashboard overview page currently renders from hardcoded MOCK_* data
(frontend/src/components/Dashboard.jsx) — kpis.sales/soh_value/
safety_stock_rate/weeks_of_cover, sales_vs_stock, abc_mix, tier_stock,
portfolio_forecast, reorder_preview. Response shape is additive only —
every original key (principal, period, inventory, recommendations,
forecast, cover_series) is unchanged.

BOTH PRINCIPALS (2026-09-17): `?principal=` is back (see
backend/principals.py), reversing the 2026-09 Unilever-only pass — omit it
or pass 'all' for both, 'unilever'/'delmonte' for one.

Two different mechanisms are in play, and the difference matters:
  - A straight WHERE filter, where both principals share one table
    (Inventory_Fact_Real, Purchase_Fact_Real, ABC_Classification,
    Product_Dimension).
  - A SOURCE DISPATCH, where they don't: sales reads
    Unilever_SKU_Demand_Fact_Real for Unilever and SellOut_Fact_Real for
    Del Monte. Sales_Fact is deliberately NOT used — it is Del Monte-only
    INVOICE grain (DEC-10) with no per-period demand-comparable shape.

PREVIEW (2026-09-23): the X-Data-Mode: preview header adds Unilever's
2021-22 placeholder months to the descriptive figures — kpis.sales,
sales_vs_stock.sales, abc_mix / abc_coverage / abc_revenue / tier_stock
(tiers computed on request for a placeholder end month, since no stored run
covers one). Everything LP- or forecast-based stays real, and the payload's
data_mode.real_only lists those fields. See backend/data_mode.py.

Under 'all', per-period figures are combined by _combine_principal_sums:
a period reports a total only when BOTH principals have a real value for
it, never one side's number presented as the whole portfolio. Unilever's
demand runs to 2026-02 and Del Monte's sellout to 2025-12, so 'all' is
legitimately null for the months where only one side exists.

Known per-principal source gaps, live as of 2026-09-17 (real gaps, not
filter artefacts): Del Monte has 0% unit_cost_per_case and 0%
stock_status, so soh_value and the dead-stock split are Unilever-only;
Purchase_Fact_Real holds Del Monte rows ONLY, so `received` is null for
Unilever; and ABC_Classification/Forecast_Result/LP_Recommendation have
no Del Monte rows at all yet.

Fixed 2026-09-17: migration 0017 added ABC_Classification.method
('single'/'t3m') so both classification bases can coexist per
(product_key, classification_period) — every ABC_Classification query in
this file (safety_stock_rate, abc_mix, tier_stock) had no method filter,
so each product_key was double-counted the moment t3m rows landed in
public (abc_mix's revenue_share summing past 100% was the visible
symptom). All three now filter to method = 'single', the deployed basis.

Honest-null policy (matches the frontend's null-handling contract — a null
value means "cannot honestly compute this", never a guess or a fabricated
zero):

  ORIGINAL FIELDS:
  inventory.value
    — real since 2026-09-23: the same figure as kpis.soh_value, from the
      same source. It was hardcoded null on the grounds that "inventory_fact
      has no valuation/price column anywhere (confirmed against the live
      schema)" — that claim was already out of date when written.
      Inventory_Fact.valuation exists (migration 0004) and is populated on
      every row of the current snapshot, and unit_cost_per_case has been
      there since the Unilever SOH load. Having a null field documented as
      impossible sitting beside a populated one that measures the same
      thing is the kind of contradiction an adviser finds first.
  inventory.weeks_of_cover / cover_series[].weeks_of_cover
    — still null: this is the PER-PERIOD cover series, which needs a
      per-period demand denominator this endpoint does not compute.
      kpis.weeks_of_cover is the real, single-figure version.
  recommendations.order_value
    — always null. lp_recommendation has no runner yet, and even once one
    exists, Q_i * unit_price needs a cost column that doesn't exist.
  recommendations.product_count
    — real: COUNT(*) of pending LP_Recommendation rows. Needs no price,
    so it's honestly computable even though order_value isn't.
  forecast.unreliable_count / forecast.evaluated_count / forecast.total_count
    — real: from Forecast_Result at its most recent forecast_date.
    total_count is every row; evaluated_count the rows with a holdout MASE
    (status 'ok' — provisional and no-order rows have none); unreliable_count
    the evaluated rows that FAIL the pass gate MASE < 1
    (analytics.params.MASE_GATE), i.e. whose served model did no better on its
    rolling one-step holdout than a naive last-value forecast. The gate was
    `mape >= 20` until 2026-09-21: that flagged 100 of 132 Tier A SKUs
    whatever the model, so it told the user nothing; MASE < 1 is also the
    LP's own gate (scripts/run_lp.py). unreliable_count is null (not 0)
    when total_count is 0, matching this app's "null = no data source
    yet" convention everywhere else, rather than claiming "0 unreliable"
    when there's no forecast run to judge at all.
  latest_data_period / latest_data_period_by_principal
    — real: the most recent 'YYYY-MM' with real sales, overall (the later
    of the two principals) and per principal (_latest_sales_period). The
    frontend hard-codes the same month (frontend/src/dataCoverage.js) as
    its date picker's ceiling; this is the value to read instead.

  NEW FIELDS (this pass) — every *_Real view read, is_demo=false is
  guaranteed by the view definition itself (schema.sql SECTION 8), never
  re-checked here:

  kpis.sales
    — real: SUM(net_amount) from Unilever_SKU_Demand_Fact_Real for the
    CURRENT calendar month (the last entry of the same 12-month list
    sales_vs_stock uses) — "this period's total sales", matching the KPI
    card's own label. Null (with sales_blocked_reason) when there's no row
    for that month — a real gap (data usually lags the current calendar
    month), not a bug.
  kpis.soh_value
    — real: SUM(quantity_on_hand * unit_cost_per_case) from
    Inventory_Fact_Real. This REQUIRED confirming quantity_on_hand is in
    CASES for Unilever SOH rows before multiplying by a per-case price —
    verified, not assumed:
      - config/column_maps/ssis_soh.yaml's "Stock Quantity (CS/PC)" parse
        splits the raw cell into stock_qty_cases / stock_qty_pieces.
      - analytics/etl/transform_ssis_soh.py's own column-mapping docstring
        and code (`"quantity_on_hand": df["stock_qty_cases"]`) confirm
        quantity_on_hand is loaded from stock_qty_cases specifically — the
        CASES component, not the pieces remainder and not the combined
        total-units-in-pieces figure.
      - unit_cost_per_case is loaded from "Last Purchase Price(GSV/CS)" —
        schema.sql's own comment on that column confirms the source
        header states it is a per-CASE price.
    quantity_on_hand (cases) x unit_cost_per_case (pesos/case) is
    therefore unit-consistent. SUPERSEDED 2026-09-23: that product is now
    only the FALLBACK. The source file's own extended total,
    Inventory_Fact.valuation, is used when present — it equals
    cases x unit_cost + pieces x (unit_cost / pack_size) on 689 of 689 rows
    of the 2026-03 snapshot, i.e. it prices the loose-piece remainder this
    app was dropping. The old "known limitation" of under-counting that
    remainder was worth PHP 709,344 (21,991,481 vs the file's 22,700,826,
    3.2%) and is closed: the dashboard now agrees with the SOH file rather
    than quietly disagreeing with it. Null (with
    soh_value_blocked_reason) only when Inventory_Fact_Real has no rows
    at all for the resolved period — NOT when the unit is unconfirmed (it
    is confirmed, see above). If a future change to ssis_soh's
    Extract/Transform ever changes what quantity_on_hand holds,
    UNILEVER_SOH_UNIT_CONFIRMED below is the single switch that re-blocks
    this whole computation (soh_value AND every sales_vs_stock.
    stock_on_hand point) rather than silently multiplying the wrong unit.
  kpis.safety_stock_rate
    — real: among Category A products (latest ABC_Classification period),
    the share whose current_stock (latest Inventory_Fact_Real period) is
    >= ss_i from their own latest PENDING LP_Recommendation. A product
    missing either figure is excluded from both the numerator and the
    denominator (excluded, not counted as failing — we cannot judge what
    we cannot measure). Null (with safety_stock_rate_blocked_reason) when
    no Category A product has both figures available — this is what
    "LP_Recommendation is empty" degrades to in practice, since an empty
    LP_Recommendation makes ss_i unavailable for every product.
  kpis.weeks_of_cover
    — {value, blocked_reason, coverage, months_used, stock_period,
    sales_window}. Formula: current stock on hand / average weekly demand.
    The figure SSM's 3-week stock policy is judged by (client meeting,
    Sep 2026), so it does NOT follow the date picker (since 2026-09-29).
      Stock on hand reuses kpis.soh_value's own figure verbatim — the
        latest snapshot, never the picker's (UNILEVER_SOH_UNIT_CONFIRMED is
        inherited automatically, not re-checked here).
      Average weekly demand is the mean of whatever non-null months exist
        in the 12 months of sales ending at the stock count's month (or
        at the last month with sales before it) — sales_window names them
        (a real gap stays excluded, never averaged in as 0 demand) —
        converted from a monthly to a weekly rate via AVG_WEEKS_PER_MONTH
        (average days/month / 7 — a documented convention, not a
        fabricated number, same spirit as analytics/etl/granularity.py's
        business_days_in_month()). It used to average the picker's months,
        so one stock count read 3.0–3.5 weeks depending on the range on
        screen.
    Null (with blocked_reason) whenever either stock or average weekly
    demand is unavailable, or weekly demand is exactly 0 (division by
    zero, not "0 weeks").

  sales_vs_stock[].sales
    — same SUM(net_amount) computation as kpis.sales, one point per
    period in the same last-12-calendar-months list as cover_series.
    Null for any period Unilever_SKU_Demand_Fact_Real has no row for.
  sales_vs_stock[].stock_on_hand
    — same computation as kpis.soh_value, PESOS (not units — plotted on
    the same axis as sales), one point per Inventory_Fact_Real period
    matching each of the 12 calendar months. If
    UNILEVER_SOH_UNIT_CONFIRMED is ever flipped to False, every point in
    this series is null, per the note on kpis.soh_value above.
  sales_vs_stock[].received
    — SUPPLIER-ALLOCATION PROXY, not a fabricated fixed_allocation
    constant: no supplier allocation schedule exists anywhere in the
    schema or the source files — SSM has never provided one. SUM(
    Purchase_Fact_Real.net_amount) per period, in pesos (same axis as
    sales/stock_on_hand), via _received_by_period(). Null (a real gap,
    never 0) for any period Purchase_Fact_Real has no matching rows for.
    Deliberately isolated in its own function (_received_by_period, one
    call site) so a future swap to a real Supplier_Allocation table is a
    source change inside that one function, not a rewrite of this
    endpoint — see that function's own docstring.

  abc_mix[].revenue_share_pct
    — real: SUM(revenue_share) * 100 per tier at the latest
    classification_period.

  tier_stock[]
    — real: per-tier counts of PRODUCTS by dead-stock status, from
    Inventory_Fact_Real.stock_status at the latest inventory period (NOT
    the reorder-point-derived in_stock/low/critical split
    backend.routers.abc._stock_status computes for GET /abc — a
    different, genuinely-populated column, chosen per this dashboard
    widget's own "dead stock" framing). A product with ANY row that
    period flagged stock_status='Inactive' counts as dead_stock; else ANY
    row flagged 'Active' counts as in_stock; a product with no
    Inventory_Fact_Real row that period, or rows with stock_status still
    NULL, counts toward `no_data` — never guessed into either bucket. No
    allocation bar — no supplier allocation table exists anywhere in the
    schema, and Purchase_Fact (the proxy sales_vs_stock.received uses
    instead) has no product_key at all, so there is no grain to break an
    allocation proxy down by ABC tier even proximately.

  tier_stock[].pending_reorder_count
    — real: COUNT(DISTINCT product_key) per tier with a pending
    LP_Recommendation row, at the SAME classification_period as the rest
    of tier_stock. Deliberately a different source table (LP_Recommendation,
    not Inventory_Fact_Real) than in_stock/dead_stock/no_data above — chosen
    specifically so this bar doesn't restate the ABC donut's own
    count/revenue-share view under a different name; it answers "how many
    products in this tier need reordering right now", not "how big is
    this tier". Never null — 0 is a real, meaningful answer here (no
    pending recommendations for that tier), unlike the honest-null fields
    elsewhere in this file.

  portfolio_forecast
    — real, but structurally different from the old mock's clean 4-period
    horizon: scripts/run_baseline_forecast.py serves one model per
    history-length bin (MA3, TSB or the XGBoost + MA3 average, see
    analytics/forecasting/router.py) and forecasts ONE step ahead per
    product, and forecast_date is that product's OWN latest actual
    period + 1 month — there is no shared, synchronized multi-period
    horizon anywhere in Forecast_Result to report (neither SARIMA's
    retirement nor the per-bin routing changed that one-step-per-product
    shape, so no aggregation logic below needed to change, only this
    wording). The portfolio gate is MASE < 1 (analytics.params.MASE_GATE) since
    2026-09-29 — the same gate forecast.unreliable_count and the LP's
    candidate pool apply (the same analytics.params.MASE_GATE), so every screen
    calls the same SKUs reliable. It was `mape < 20` before, which passed
    19 of 132 Tier A SKUs against the LP's 73 and made the card describe
    a different population than the reorder plan (the MODEL_BAKEOFF
    report's own conclusion was to move off the mape gate).
    series covers the SAME `period`/
    `start_period`-derived window as kpis.sales / sales_vs_stock above
    (summed quantity_sold across the gated product set, i.e. products with
    a forecast_date row where status='ok' AND mase < 1 at the most recent
    forecast_date in the table) — the date-range picker's applied range,
    not a hardcoded trailing window — followed by however many distinct
    real forecast_date buckets exist among those gated rows (usually one,
    sometimes a few if products' own latest periods differ), which land
    past the picker's range whenever its end predates the forecast month.
    Never fabricated into a clean synchronized run.
    gated_sku_count is computed from the same gated-row set. Null/empty
    across the board (gated_sku_count=0, series=[]) when nothing passes
    the gate.

  reorder_preview
    — real: top 5 pending LP_Recommendation rows by urgency, reusing
    backend.routers.recommendations._to_item / _SELECT_ONE verbatim
    (imported, not reimplemented) for the exact same urgency derivation
    GET /recommendations uses. critical_count / urgent_count /
    total_order_qty are computed over the FULL pending set (not just the
    5 previewed rows) — a portfolio-wide summary next to a 5-row preview,
    same relationship ABC's tier_summary has to its own items list.
  reorder_preview.lp_weights
    — {cost, service_level, storage} fractions, always present (never
    null): a straight mirror of analytics/optimization/lp.py's W1/W2/W3
    module constants (LP_WEIGHT_* below), not derived from any row or
    query. Read-only display value, not an adjustable control — there is
    no warehouse-capacity/supplier-ceiling/storage-cost data anywhere in
    the schema to re-solve the LP against (see
    frontend/src/components/Charts.jsx's ReorderRecommendationWidget for
    the display side of this same note).

  NARRATIVE-BAND FIELDS (2026-09-18) — the Dashboard now reads as four
  bands, each headed by a takeaway sentence GENERATED from these fields
  (never hardcoded; a null here becomes an honest "not available" line):

  abc_revenue
    — {period, total, blocked_reason}. SUM(net_amount) for the resolved
    abc_period, from the same per-principal demand facts kpis.sales reads
    (_sales_by_period) — the same net_amount basis
    analytics/classification/orchestrate_abc.py classifies on, so the
    donut's centre figure is the revenue the ring's shares are shares OF.
    Null under 'all' unless both principals have a real figure (the
    both-sides-real rule), or when no ABC run exists.
  safety_stock_exposure
    — {tier_a_count, comparable_count, below_count, below_revenue_share,
    blocked_reason}. Same rows and same "both figures or excluded" rule as
    kpis.safety_stock_rate, plus each product's revenue_share, so "N of M
    measurable Category A SKUs are below safety stock, X% of revenue" is
    one query, not two that could disagree. below_revenue_share is the sum
    of revenue_share over the below-SS products (a share of the WHOLE
    period's revenue, not of Tier A's).
  policy_comparison
    — {cycle_date, sku_count, lp_safety_stock_units, rule_safety_stock_units,
    lp_vs_rule_pct, rule_weeks, blocked_reason}. lp_vs_rule_pct is how much
    less buffer the LP holds, as a percent of the rule (negative = more).
    The per-SKU rows behind these sums are GET /policy-comparison
    (policy_comparison.py) — keep the two queries in step. Sums, over the latest pending planning
    cycle, the LP's ss_i against what SSM's own stock policy would hold
    (keep three weeks of sales in stock — client meeting, Sep 2026):
    POLICY_WEEKS x (that product's own Forecast_Result.forecast_value for
    the same month / AVG_WEEKS_PER_MONTH). Both sides are on the demand
    series' unit (pieces), so they are directly comparable; deliberately
    NOT converted to pesos — no agreed cost per piece exists
    (Product_Dimension.unit_price is empty; the stock file's
    unit_cost_per_case / pack_size is only the LP plan's placeholder).
    Products with no forecast for the cycle month are excluded from BOTH
    sums, never from one. Null with blocked_reason when no cycle or no
    comparable product exists.
"""
from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.data_mode import (
    PREVIEW,
    REAL,
    REAL_UNILEVER_DEMAND,
    abc_relation,
    abc_single,
    forecast_source,
    get_data_mode,
    lp_source,
    placeholder_window,
    predictive_preview,
    preview_block,
    unilever_demand,
)
from analytics.classification.abc import abc_rules
from analytics.params import MASE_GATE
from backend.chart_insights import kpi_trend, portfolio_forecast_insight, sales_vs_stock_insight
from backend.deps import TokenPayload, get_current_user, get_db
from backend.lp_cycle import CURRENT_CYCLE_CLAUSE, LP_WEIGHTS, current_cycle
from backend.lp_cycle import freshness as lp_freshness
from backend.principals import PrincipalQuery, latest_abc_period, normalize_principal
from backend.routers.recommendations import select_one as _recommendation_select_one
from backend.routers.recommendations import _to_item as _to_recommendation_item
from backend.routers.recommendations import whole_units
from backend.stock_units import STOCK_AT_PERIOD_SQL

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

POLICY_WEEKS = 3
# The ONE forecast-reliability gate this page applies: MASE < 1 passes
# (the served model beat a naive last-value forecast on its holdout), so
# >= 1 is unreliable. Shared by forecast.unreliable_count AND
# portfolio_forecast's gated SKU set, and it is the LP's own candidate
# gate too (scripts/run_lp.py) — since 2026-09-29 every screen
# calls the same SKUs reliable. portfolio_forecast gated on mape < 20
# before, a stale gate the MODEL_BAKEOFF report concluded against.
# The value is analytics.params.MASE_GATE (Hyndman & Koehler 2006's MASE < 1).

# Sir Abe's allocation rule (client meeting, Sep 2026): the principal sets
# the year's allocation from the previous year's total sales — minimum
# x103%, mid x105%, maximum x108%, revised in Q4 on how the market went.
ALLOCATION_LEVELS = (103, 105, 108)

# Step 19's LP objective weights (analytics/optimization/lp.py's W1/W2/W3:
# 0.45/0.35/0.20) — hardcoded module constants there, not stored per-
# recommendation anywhere in the schema. Mirrored once, in
# backend/lp_cycle.LP_WEIGHTS (lp.py pulls in the pulp solver, a batch-job
# dependency this always-on API shouldn't require just to read three
# floats), and pinned to lp.py by tests/backend/test_recommendations.py. See
# reorder_preview.lp_weights's docstring section above for why this is
# read-only, not an adjustable control.
LP_WEIGHT_COST = LP_WEIGHTS["cost"]
LP_WEIGHT_SERVICE_LEVEL = LP_WEIGHTS["service_level"]
LP_WEIGHT_STORAGE = LP_WEIGHTS["storage"]
assert abs((LP_WEIGHT_COST + LP_WEIGHT_SERVICE_LEVEL + LP_WEIGHT_STORAGE) - 1.00) < 1e-9

# Average days/month (365.25/12) / 7 — converts an average MONTHLY figure to
# a weekly rate for kpis.weeks_of_cover. A documented convention, not a
# fabricated number — same "defensible default, not fact" spirit as
# analytics/etl/granularity.py's business_days_in_month().
AVG_WEEKS_PER_MONTH = 365.25 / 12 / 7

# See kpis.soh_value's docstring section above for the full evidence trail.
# Flip to False (and nothing else) if a future Extract/Transform change to
# ssis_soh ever redefines what quantity_on_hand holds for Unilever rows —
# that alone re-blocks both kpis.soh_value and every sales_vs_stock
# stock_on_hand point, rather than requiring this file to be re-audited.
UNILEVER_SOH_UNIT_CONFIRMED = True
_UNILEVER_SOH_UNIT_UNCONFIRMED_REASON = (
    "quantity_on_hand's unit for Unilever SOH rows is no longer confirmed as "
    "cases — see UNILEVER_SOH_UNIT_CONFIRMED in backend/routers/dashboard.py."
)

_URGENCY_RANK = {"CRITICAL": 0, "URGENT": 1, "PLANNED": 2}


def _scope_label(principal: str) -> str:
    """Human wording for blocked_reason strings, so a null explains WHICH
    scope produced it ('...for delmonte' vs a bare '...for unilever' that
    used to be hardcoded and would now be a lie under another scope)."""
    return "all principals" if principal == "all" else principal


def _combine_principal_sums(
    periods: list[str],
    unilever: dict[str, float | None],
    delmonte: dict[str, float | None],
    principal: str,
) -> dict[str, float | None]:
    """Combines two independently-sourced per-principal period dicts.

    Restored verbatim from the pre-2026-09 Del Monte implementation
    (commit c4be61c^) — the rule it encodes is the reason it exists:

    principal='unilever'/'delmonte': pass that source straight through.
    principal='all': a period's combined value requires BOTH sides to be
    real (non-None) — if either principal has no honest figure for a
    period, the 'all' total for that period is None too, NOT the other
    side's number treated as if it were the whole portfolio. Silently
    summing whichever side happens to have data would misrepresent a
    partial total as complete (the exact fabrication this app's
    honest-null convention exists to prevent)."""
    if principal == "unilever":
        return dict(unilever)
    if principal == "delmonte":
        return dict(delmonte)
    combined: dict[str, float | None] = {}
    for period in periods:
        u, d = unilever.get(period), delmonte.get(period)
        combined[period] = (u + d) if (u is not None and d is not None) else None
    return combined


def _latest_sales_period(db: Session, principal: str = "all") -> str | None:
    """The most recent real 'YYYY-MM' of sales for `principal` — the anchor
    _last_12_periods() uses. The two principals have DIFFERENT source
    tables (DEC-03/DEC-10), so this is a source dispatch, not a filter:
    Unilever_SKU_Demand_Fact_Real for Unilever, SellOut_Fact_Real for Del
    Monte. Under 'all' the anchor is the later of the two, so a scope that
    includes Unilever never silently rewinds to Del Monte's shorter
    coverage (real through 2026-02 vs 2025-12 as of 2026-09-17)."""
    candidates: list[str] = []
    if principal in ("all", "unilever"):
        row = db.execute(text(
            "SELECT MAX(calendar_month) AS p FROM Unilever_SKU_Demand_Fact_Real"
        )).mappings().first()
        if row and row["p"]:
            candidates.append(row["p"])
    if principal in ("all", "delmonte"):
        row = db.execute(text(
            "SELECT MAX(_period) AS p FROM SellOut_Fact_Real"
        )).mappings().first()
        if row and row["p"]:
            candidates.append(row["p"])
    return max(candidates) if candidates else None


def _resolve_sales_anchor(db: Session, end_override: str | None, principal: str = "all") -> str:
    """The 'YYYY-MM' to treat as the sales/stock trend's END: end_override
    (the date-range picker's applied end month/year) if given, else the
    most recent real sales period (_latest_sales_period), else today's
    wall-clock date as a last resort. Centralizes the one fallback chain
    both _last_12_periods and the explicit-range window below need, so
    it's defined in exactly one place.

    Falls back to today's date only if _latest_sales_period finds no sales
    data anywhere yet — never silently defaults to "today" over a real
    anchor that exists."""
    anchor = end_override or _latest_sales_period(db, principal)
    if anchor:
        return anchor
    today = datetime.date.today()
    return f"{today.year:04d}-{today.month:02d}"


def _last_12_periods(db: Session, anchor_override: str | None = None, principal: str = "all") -> list[str]:
    """Last 12 calendar months as 'YYYY-MM', oldest first, ENDING AT
    _resolve_sales_anchor's result (real sales data, not today's wall-clock
    date, unless anchor_override or a real anchor is unavailable — see that
    function's docstring).

    anchor_override, when given (the frontend date-range picker's applied
    *end* month/year — same "picker's end maps onto the anchor" convention
    backend/routers/abc.py's classification_period already uses), is used
    as the window's end instead of _latest_sales_period. This makes
    kpis.sales / sales_vs_stock respond to the shared date filter instead
    of always showing the latest-data window regardless of what the user
    picked. (kpis.weeks_of_cover deliberately does not — see its section.)

    Only ever called for the picker's END when no START was also applied
    (see get_dashboard: an applied start uses _month_range instead, the
    picker's actual full width) — this function's job is purely "no start
    given yet, what's a reasonable single-anchor default."""
    anchor = _resolve_sales_anchor(db, anchor_override, principal)
    today = datetime.date(int(anchor[:4]), int(anchor[5:7]), 1)
    periods = []
    for i in range(11, -1, -1):
        month_index = today.month - 1 - i
        year = today.year + month_index // 12
        month = month_index % 12 + 1
        periods.append(f"{year:04d}-{month:02d}")
    return periods


def _month_range(start: str, end: str) -> list[str]:
    """Every 'YYYY-MM' from start through end inclusive, oldest first.

    Used instead of _last_12_periods once the frontend date-range picker's
    applied START is also present (not just its end) — the picker exposes
    a full start+end range, and the chart/KPIs should honor the width the
    user actually picked (which may be longer OR shorter than 12 months),
    not silently clip to a fixed trailing 12.

    Swapped if start is after end: DateFilter.jsx's start and end
    month/year are four independent <select> elements with no ordering
    constraint between them, so an inverted pick is reachable from the UI
    and should still render something sensible rather than an empty chart
    or a crash."""
    sy, sm = int(start[:4]), int(start[5:7])
    ey, em = int(end[:4]), int(end[5:7])
    if (sy, sm) > (ey, em):
        sy, sm, ey, em = ey, em, sy, sm
    periods = []
    y, m = sy, sm
    while (y, m) <= (ey, em):
        periods.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return periods


def _to_float(val) -> float | None:
    if val is None:
        return None
    return float(val)


def _query_period_sums(db: Session, sql: str, periods: list[str]) -> dict[str, float | None]:
    """Runs a `SELECT <period-col> AS period, SUM(...) AS total ... GROUP BY
    <period-col>` query restricted to `periods` via `= ANY(:periods)` and
    returns a period -> float|None dict covering every requested period
    (missing/NULL stays None — SQL SUM already returns no row, or a NULL
    total, for a period with zero matching or all-NULL rows)."""
    rows = db.execute(text(sql), {"periods": periods}).mappings().all()
    result: dict[str, float | None] = {p: None for p in periods}
    for r in rows:
        if r["total"] is not None:
            result[r["period"]] = float(r["total"])
    return result


def _sales_by_period(
    db: Session, periods: list[str], principal: str = "unilever", mode: str = REAL
) -> dict[str, float | None]:
    """SUM(net_amount) per period, from each principal's own product-mart
    demand fact: Unilever_SKU_Demand_Fact_Real for Unilever,
    SellOut_Fact_Real for Del Monte.

    Del Monte deliberately reads SellOut_Fact_Real and NOT Sales_Fact —
    Sales_Fact is Del Monte-only INVOICE grain (DEC-10) with no
    per-period demand-comparable shape. That choice is inherited from the
    pre-2026-09 implementation, not re-litigated here.

    mode='preview' adds Unilever's 2021-22 placeholder months
    (backend/data_mode.py); Del Monte is real in either mode."""
    unilever = (
        _query_period_sums(db, f"""
            SELECT calendar_month AS period, SUM(net_amount) AS total
            FROM {unilever_demand(mode)}
            WHERE calendar_month = ANY(:periods)
            GROUP BY calendar_month
        """, periods)
        if principal in ("all", "unilever") else {p: None for p in periods}
    )
    delmonte = (
        _query_period_sums(db, """
            SELECT _period AS period, SUM(net_amount) AS total
            FROM SellOut_Fact_Real
            WHERE _period = ANY(:periods)
            GROUP BY _period
        """, periods)
        if principal in ("all", "delmonte") else {p: None for p in periods}
    )
    return _combine_principal_sums(periods, unilever, delmonte, principal)


# SUPPLIER-ALLOCATION PROXY — see sales_vs_stock[].received's docstring
# section for the full reasoning. This is the ONE function to change (SQL
# body only — signature and call site stay the same) the day a real
# Supplier_Allocation table exists: swap Purchase_Fact_Real for that table,
# drop the "(proxy for allocation)" wording at the two frontend call sites
# that reference it (frontend/src/components/Charts.jsx's
# SalesVsStockWidget), and nothing else in this file needs to change.
def _received_by_period(
    db: Session, periods: list[str], principal: str = "unilever"
) -> dict[str, float | None]:
    """SUM(Purchase_Fact_Real.net_amount) per period. Unlike sales/soh,
    both principals live in ONE table here (Purchase_Fact.principal), so
    this is a straight WHERE filter rather than a source swap — but the
    combine rule under 'all' is identical (both sides real, or null).

    LIVE CAVEAT (2026-09-17): purchase_fact_real holds 499 Del Monte rows
    and ZERO Unilever rows, so the Unilever side of this is null for every
    period today. That is a genuine source gap, not a filter mistake — and
    it means 'all' is null here too, by the both-sides-real rule."""
    unilever = (
        _query_period_sums(db, """
            SELECT _period AS period, SUM(net_amount) AS total
            FROM Purchase_Fact_Real
            WHERE principal = 'unilever' AND _period = ANY(:periods)
            GROUP BY _period
        """, periods)
        if principal in ("all", "unilever") else {p: None for p in periods}
    )
    delmonte = (
        _query_period_sums(db, """
            SELECT _period AS period, SUM(net_amount) AS total
            FROM Purchase_Fact_Real
            WHERE principal = 'delmonte' AND _period = ANY(:periods)
            GROUP BY _period
        """, periods)
        if principal in ("all", "delmonte") else {p: None for p in periods}
    )
    return _combine_principal_sums(periods, unilever, delmonte, principal)


def _latest_inventory_period(db: Session, principal: str = "unilever") -> str | None:
    """Latest Inventory_Fact_Real._period within the selected scope.
    Inventory_Fact_Real carries both principals, so an unfiltered MAX
    could resolve to a period the selected principal has no rows for at
    all — hence the scope is applied here, not just at the row query."""
    sql = "SELECT MAX(_period) AS p FROM Inventory_Fact_Real"
    params: dict = {}
    if principal != "all":
        sql += " WHERE principal = :principal"
        params["principal"] = principal
    row = db.execute(text(sql), params).mappings().first()
    return row["p"] if row else None


def _soh_value_by_period(
    db: Session, periods: list[str], principal: str = "unilever"
) -> dict[str, float | None]:
    """Peso stock-on-hand valuation per Inventory_Fact_Real period — see
    kpis.soh_value's docstring section for the unit-confirmation evidence.

    Both principals carry a valuation now (Del Monte's is the source file's
    own, e.g. PHP 6,683,837.26 at 2025-12), but their snapshots cover
    different months. Under 'all' a period therefore gets a figure only when
    BOTH sides have one (_combine_principal_sums, the rule sales already
    follows). Summing whatever rows existed mixed two-principal months with
    Unilever-only ones and drew a drop that never happened (PHP 43.0M ->
    24.3M from 2025-12 to 2026-01, measured 2026-09-29). `principal` is
    interpolated (not bound) because it is already validated against a
    fixed allowlist by normalize_principal() at the endpoint boundary — it
    can only ever be the literal 'unilever' or 'delmonte' by the time it
    reaches the query."""
    if not UNILEVER_SOH_UNIT_CONFIRMED:
        # Structurally blocked — every period stays None.
        return {p: None for p in periods}
    if principal == "all":
        return _combine_principal_sums(
            periods,
            _soh_value_by_period(db, periods, "unilever"),
            _soh_value_by_period(db, periods, "delmonte"),
            "all",
        )
    scope = f" AND principal = '{principal}'"
    # Inventory_Fact.valuation is the SOURCE FILE's own extended peso total
    # and already prices the loose-piece remainder; the multiplication is
    # only a fallback for rows without it. Verified 2026-09-23 against the
    # live 2026-03 snapshot: valuation = cases x unit_cost + pieces x
    # (unit_cost / pack_size) for 689 of 689 rows. Computing it here instead
    # under-reported stock by the remainder — PHP 21,991,481 against the
    # file's own 22,700,826, a 3.2% gap this app had no reason to invent.
    return _query_period_sums(db, f"""
        SELECT _period AS period,
               SUM(COALESCE(valuation, quantity_on_hand * unit_cost_per_case)) AS total
        FROM Inventory_Fact_Real
        WHERE _period = ANY(:periods){scope}
        GROUP BY _period
    """, periods)


def _stock_valuation_coverage(db: Session, period: str | None, principal: str = "unilever") -> list[str]:
    """Which principals actually contribute a peso stock valuation at
    `period`, within `principal`'s scope.

    Exists because 'all' is not the same as 'both' here. Del Monte's latest
    snapshot is 2025-12 while Unilever's is 2026-03, so at the latest
    snapshot an 'all' stock figure is Unilever's alone. kpis.weeks_of_cover used to divide
    that Unilever-only stock by BOTH principals' demand — 2.24 weeks
    against Unilever's own 2.93, a number that belonged to neither scope.
    Returning the covered set lets the caller line the denominator up with
    the numerator and say which principals the answer is about."""
    if period is None:
        return []
    rows = db.execute(
        text("""
            SELECT principal
            FROM Inventory_Fact_Real
            WHERE _period = :period
            GROUP BY principal
            HAVING SUM(COALESCE(valuation, quantity_on_hand * unit_cost_per_case)) IS NOT NULL
        """),
        {"period": period},
    ).mappings().all()
    covered = sorted(r["principal"] for r in rows if r["principal"])
    # Narrowed in Python rather than in the HAVING clause so the scoped and
    # unscoped answers come from one query with identical semantics.
    return covered if principal == "all" else [p for p in covered if p == principal]


def _latest_abc_period(db: Session, principal: str = "unilever") -> str | None:
    """Latest ABC_Classification.classification_period within the selected
    scope. ABC_Classification carries both principals, so an unfiltered MAX
    could resolve to a period the selected principal has no rows for.

    method='single' is REQUIRED (migration 0017): a 't3m' run is live
    alongside 'single', and an unpinned MAX can resolve to a period only
    t3m produced — which would then read back zero 'single' rows."""
    sql = "SELECT MAX(classification_period) AS p FROM ABC_Classification WHERE method = 'single'"
    params: dict = {}
    if principal != "all":
        sql += " AND principal = :principal"
        params["principal"] = principal
    row = db.execute(text(sql), params).mappings().first()
    return row["p"] if row else None


def _nearest_abc_period_at_or_before(
    db: Session, period: str, principal: str = "unilever"
) -> str | None:
    """Latest UNILEVER classification_period <= `period`, or None if the
    ETL hasn't produced any ABC run that old yet. The classification batch
    runs roughly monthly and lags the sales data it's derived from, and
    each principal's data ends in a different month, so the date-range
    picker's applied end month (DashboardLayout's "today", the latest month
    with ANY principal's sales — see dataCoverage.js) routinely has no
    exact ABC_Classification row of its own for a given principal (Del
    Monte's latest run is 2025-12 against today's 2026-02). Falling back to the
    nearest earlier real run (instead of the exact-match dead end this
    replaced) keeps kpis.safety_stock_rate/abc_mix/tier_stock populated
    for that common case, while still going genuinely blocked if `period`
    predates every ABC run that exists."""
    sql = (
        "SELECT MAX(classification_period) AS p FROM ABC_Classification "
        "WHERE method = 'single' AND classification_period <= :period"
    )
    params: dict = {"period": period}
    if principal != "all":
        sql += " AND principal = :principal"
        params["principal"] = principal
    row = db.execute(text(sql), params).mappings().first()
    return row["p"] if row else None


def _avg_weekly_demand(period_values: dict[str, float | None]) -> tuple[float | None, str | None]:
    """Mean of whatever non-null months exist in `period_values` (already
    scoped to the trailing 12-month window by the caller), converted to a
    weekly rate via AVG_WEEKS_PER_MONTH. A period with no source row stays
    excluded — a real gap, never averaged in as 0 demand."""
    non_null = [v for v in period_values.values() if v is not None]
    if not non_null:
        return None, "no sales data in the trailing 12 months to compute average weekly demand"
    avg_monthly = sum(non_null) / len(non_null)
    return avg_monthly / AVG_WEEKS_PER_MONTH, None


def _weeks_of_cover(
    stock: float | None, stock_reason: str | None, weekly_demand: float | None, demand_reason: str | None
) -> tuple[float | None, str | None]:
    if stock is None:
        return None, stock_reason or "no stock-on-hand valuation available"
    if weekly_demand is None:
        return None, demand_reason or "no average weekly demand available"
    if weekly_demand == 0:
        return None, "average weekly demand is zero — cannot compute weeks of cover"
    return round(stock / weekly_demand, 2), None


@router.get("")
def get_dashboard(
    period: str | None = Query(
        None,
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
        description=(
            "'YYYY-MM'. The shared date-range picker's applied end month/year. "
            "Anchors the sales/stock trend window kpis.sales / sales_vs_stock "
            "are computed over (a fixed trailing 12 months when start_period "
            "is omitted, or the end of the exact range when it's given; "
            "kpis.weeks_of_cover never follows it), AND is used as an exact "
            "ABC_Classification.classification_period match for "
            "kpis.safety_stock_rate / abc_mix / tier_stock. Omit to anchor "
            "sales at the latest real sales period and ABC at the latest "
            "classification run, independently."
        ),
    ),
    start_period: str | None = Query(
        None,
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
        description=(
            "'YYYY-MM'. The shared date-range picker's applied START month/"
            "year. When given, kpis.sales / sales_vs_stock "
            "cover every month from here through `period` "
            "(or through the latest real sales period if `period` is also "
            "omitted) inclusive, instead of a fixed trailing 12 months — the "
            "exact width the user picked, not clipped to 12. Ignored (falls "
            "back to the fixed trailing-12 window) if omitted."
        ),
    ),
    principal: str | None = PrincipalQuery,
    mode: str = Depends(get_data_mode),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
):
    # Both principals again (2026-09-17) — see backend/principals.py.
    # normalize_principal() maps None/'all' -> None and validates the rest;
    # this file's helpers take the literal string 'all' rather than None,
    # so it is re-widened to 'all' here and passed down explicitly.
    scope = normalize_principal(principal) or "all"
    principal_filter = "" if scope == "all" else f"AND pd.principal = '{scope}'"
    # Same scope expressed against ABC_Classification's own alias. Paired
    # with method='single' at every ABC read: migration 0017 put a live
    # 't3m' run alongside 'single', so an unpinned query returns each SKU
    # TWICE — doubling counts and summing revenue_share past 100%.
    abc_scope = "" if scope == "all" else f"AND ac.principal = '{scope}'"
    abc_scope_bare = "" if scope == "all" else f"AND principal = '{scope}'"

    # ---- ORIGINAL FIELDS (unchanged) ----------------------------------

    # The LP's CURRENT cycle only (2026-09-23, backend/lp_cycle.py). This
    # counted every pending row regardless of cycle, so it read 429 — 250
    # current rows plus 179 leftovers from 33 runs going back to 2023-05 —
    # under a card captioned "awaiting a decision". Resolved once here and
    # reused by every LP read below so they can never disagree about which
    # cycle the page is showing.
    lp_freshness_info = lp_freshness(db, scope, mode)
    lp_cycle = current_cycle(db, scope, mode)
    lp_cycle_filter = CURRENT_CYCLE_CLAUSE if lp_cycle is not None else " AND 1=0"
    # The LP's rows and the forecasts: the stored tables, or in preview with
    # built outputs the five-year what-if's (backend/data_mode.py). Every
    # predictive and prescriptive read below goes through these two.
    lp_src, lp_params = lp_source(mode)
    fc_src, fc_params = forecast_source(mode)

    reco_row = db.execute(
        text(f"""
            SELECT COUNT(*) AS product_count
            FROM {lp_src} lr
            JOIN Product_Dimension pd ON pd.product_key = lr.product_key
            WHERE lr.status = 'pending' {principal_filter} {lp_cycle_filter}
        """),
        {"current_cycle": lp_cycle, **lp_params},
    ).mappings().first()
    product_count = int(reco_row["product_count"])

    forecast_row = db.execute(
        text(f"""
            WITH latest AS (
                SELECT MAX(forecast_date) AS forecast_date FROM {fc_src}
            )
            SELECT
                COUNT(*) AS total_count,
                COUNT(fr.mase) AS evaluated_count,
                COUNT(*) FILTER (WHERE fr.mase >= :mase_gate) AS unreliable_count
            FROM {fc_src} fr
            JOIN Product_Dimension pd ON pd.product_key = fr.product_key
            JOIN latest ON fr.forecast_date = latest.forecast_date
            WHERE 1=1 {principal_filter}
        """),
        {"mase_gate": MASE_GATE, **fc_params},
    ).mappings().first()
    total_count = int(forecast_row["total_count"])
    evaluated_count = int(forecast_row["evaluated_count"])
    unreliable_count = int(forecast_row["unreliable_count"]) if total_count > 0 else None

    # latest_data_period(_by_principal): the most recent real sales month per
    # principal, whatever scope was asked for — the date picker spans both.
    latest_by_principal = {
        "unilever": _latest_sales_period(db, "unilever"),
        "delmonte": _latest_sales_period(db, "delmonte"),
    }

    # ---- kpis.sales / sales_vs_stock.sales ----------------------------

    periods = (
        _month_range(start_period, _resolve_sales_anchor(db, period, scope))
        if start_period is not None
        else _last_12_periods(db, period, scope)
    )
    sales_by_period = _sales_by_period(db, periods, scope, mode)
    # Walk backward from the picker's applied end month to the nearest
    # period WITHIN the selected range that actually has a real sales row,
    # rather than requiring an exact match on the range's literal end —
    # the end month is routinely one a principal has no sales row for
    # (the pinned "today" is the latest month with ANY principal's sales,
    # 2026-02, while Del Monte's end in 2025-12 — see
    # _nearest_abc_period_at_or_before's docstring), which was blanking this
    # card even when the rest of the selected range had plenty of real data.
    current_period = next(
        (p for p in reversed(periods) if sales_by_period.get(p) is not None),
        periods[-1],
    )
    sales = sales_by_period[current_period]
    sales_blocked_reason = (
        None if sales is not None
        else (
            f"No sales rows for {_scope_label(scope)} "
            f"(Unilever_SKU_Demand_Fact_Real / SellOut_Fact_Real) "
            f"anywhere from {periods[0]} through {periods[-1]} yet."
        )
    )
    # The two principals' pesos are on different tax bases: Unilever's
    # net_amount is "Total Sales Amt Inc. Tax" (config/column_maps/
    # unilever_sku.yaml, migration 0010) while Del Monte's sell-out
    # net_amount is "Total Without Tax" — EXCEPT where a sheet had only a
    # tax-inclusive total: Kelvin's X2 rule (commit 7cd47a5, migration 0027)
    # loads that one and flags the row net_amount_tax_inclusive (live: the
    # 122 rows of 2023-08). A combined 'all' figure therefore mixes
    # VAT-inclusive and VAT-exclusive pesos — true of kpis.sales, the
    # sales_vs_stock sales line, and weeks_of_cover's demand denominator
    # whenever its cover_scope stays 'all'. Said here once so every card
    # drawn from these sums can label it instead of implying one basis, and
    # the exception is named whenever the months in question include it.
    dm_tax_inclusive = {
        r["p"] for r in db.execute(text(
            "SELECT DISTINCT _period AS p FROM SellOut_Fact_Real WHERE net_amount_tax_inclusive"
        )).mappings().all()
    }

    def _dm_tax_exception(months: list[str]) -> str:
        hit = sorted(p for p in months if p in dm_tax_inclusive)
        if not hit:
            return ""
        labels = ", ".join(
            datetime.date(int(p[:4]), int(p[5:7]), 1).strftime("%b %Y") for p in hit
        )
        return f" (except {labels}, recorded with tax)"

    vat_note = (
        f"Unilever pesos include VAT; Del Monte pesos exclude it{_dm_tax_exception(periods)} — "
        "combined totals mix the two tax bases."
        if scope == "all" else None
    )

    # ---- allocation (SSM's rule: prior-year sales x 103/105/108%) -------
    # Client meeting, Sep 2026 (Sir Abe): the principal sets the year's
    # allocation from the PREVIOUS year's total sales — minimum x103%, mid
    # x105%, maximum x108% — revised in Q4 on how the market went. Computed
    # per principal (each principal sets its own allocation), from the same
    # _sales_by_period sums every other peso figure on this page reads, on
    # that principal's own tax basis. Under 'all' it is withheld: the two
    # principals' pesos are on different tax bases (vat_note above) and a
    # combined allocation would be against SSM's own per-principal rule.
    # One shape whatever the state: every key present, null when withheld,
    # and only blocked_reason saying why.
    allocation: dict = {
        "basis_year": None, "basis_sales": None, "basis_months": 0,
        "latest_month": None, "ytd_sales": None, "ytd_months": 0,
        "levels": [], "vat_basis": None, "blocked_reason": None,
    }
    if scope == "all":
        allocation["blocked_reason"] = (
            "Allocations are set per principal, so they are not combined — "
            "pick one principal to compare its sales with its allocation."
        )
    elif latest_by_principal.get(scope) is None:
        allocation["blocked_reason"] = f"No sales rows for {_scope_label(scope)} at all."
    else:
        latest_month = latest_by_principal[scope]
        latest_year = int(latest_month[:4])
        basis_year = latest_year - 1
        basis_periods = [f"{basis_year:04d}-{m:02d}" for m in range(1, 13)]
        ytd_periods = [f"{latest_year:04d}-{m:02d}" for m in range(1, int(latest_month[5:7]) + 1)]
        # Reuse the months the page already summed (same scope, same mode),
        # and fetch only the rest in ONE call — basis and YTD are disjoint.
        missing = [p for p in basis_periods + ytd_periods if p not in sales_by_period]
        by_period = {**sales_by_period, **(_sales_by_period(db, missing, scope, mode) if missing else {})}
        basis_values = [by_period[p] for p in basis_periods if by_period.get(p) is not None]
        ytd_values = [by_period[p] for p in ytd_periods if by_period.get(p) is not None]
        basis_sales = sum(basis_values) if basis_values else None
        allocation["basis_year"] = basis_year
        allocation["latest_month"] = latest_month
        if not basis_values:
            allocation["blocked_reason"] = (
                f"No {basis_year} sales rows for {_scope_label(scope)}, so the prior-year "
                f"basis SSM's allocation rule needs doesn't exist yet."
            )
        elif basis_sales <= 0:
            allocation["blocked_reason"] = (
                f"{_scope_label(scope).capitalize()}'s {basis_year} sales net to ₱0 or less "
                f"(returns and credits), so the allocation rule has nothing to scale."
            )
        else:
            ytd_sales = sum(ytd_values) if ytd_values else None
            allocation.update({
                "basis_sales": round(basis_sales, 2),
                # 12 real months make a true calendar-year basis; fewer and
                # the card must say the basis is partial, not imply a year.
                "basis_months": len(basis_values),
                "ytd_sales": round(ytd_sales, 2) if ytd_sales is not None else None,
                "ytd_months": len(ytd_values),
                "levels": [
                    {
                        "pct": pct,
                        "annual": round(basis_sales * pct / 100.0, 2),
                        "monthly": round(basis_sales * pct / 100.0 / 12.0, 2),
                    }
                    for pct in ALLOCATION_LEVELS
                ],
                # The tax basis the pesos above are on (see vat_note's sources),
                # naming any Del Monte month in the basis or YTD recorded with tax.
                "vat_basis": (
                    "incl. VAT" if scope == "unilever"
                    else "ex-VAT" + _dm_tax_exception(basis_periods + ytd_periods)
                ),
            })

    # ---- kpis.soh_value / sales_vs_stock.stock_on_hand ----------------

    inventory_period = _latest_inventory_period(db, scope)
    soh_periods = periods if inventory_period is None else sorted(set(periods) | {inventory_period})
    # The chart's stock line. Under 'all' only months where both principals
    # have stock (_soh_value_by_period).
    soh_by_period = _soh_value_by_period(db, soh_periods, scope)
    # The card, its sparkline and weeks of cover describe the principals that
    # actually have stock at the latest snapshot. Under 'all' at 2026-03 that
    # is Unilever alone, and the card says so (kpis.soh_coverage) instead of
    # going blank because Del Monte's latest snapshot is 2025-12.
    stock_coverage = _stock_valuation_coverage(db, inventory_period, scope)
    cover_scope = stock_coverage[0] if len(stock_coverage) == 1 else scope
    soh_card_by_period = (
        soh_by_period if cover_scope == scope else _soh_value_by_period(db, soh_periods, cover_scope)
    )
    soh_value = soh_card_by_period.get(inventory_period) if inventory_period is not None else None
    if inventory_period is None:
        soh_value_blocked_reason = f"Inventory_Fact_Real has no rows for {_scope_label(scope)} at all."
    elif not UNILEVER_SOH_UNIT_CONFIRMED:
        soh_value_blocked_reason = _UNILEVER_SOH_UNIT_UNCONFIRMED_REASON
    elif soh_value is None:
        soh_value_blocked_reason = (
            f"No Inventory_Fact_Real rows with quantity_on_hand x unit_cost_per_case "
            f"populated for {_scope_label(scope)} in {inventory_period}."
        )
    else:
        soh_value_blocked_reason = None

    # ---- kpis.safety_stock_rate ----------------------------------------

    # Resolves to the nearest real ABC_Classification run AT OR BEFORE the
    # picker's applied end month/year (_nearest_abc_period_at_or_before),
    # not an exact match against it — the picker's end is routinely a
    # month the classification batch hasn't run for yet (see that
    # function's docstring), and an exact-match dead end there blanked
    # this card even when the selected range's earlier months had a real
    # run to show. Falls back to the latest run overall when no override
    # is given at all. Feeds kpis.safety_stock_rate, abc_mix, AND
    # tier_stock below — all three go empty/null together only if
    # ABC_Classification genuinely has no run that old.
    abc_period = (
        _nearest_abc_period_at_or_before(db, period, scope) if period is not None
        else _latest_abc_period(db, scope)
    )
    safety_stock_rate = None
    safety_stock_rate_blocked_reason = f"ABC_Classification has no rows for {_scope_label(scope)} yet."
    ss_rows: list = []
    comparable: list = []
    if abc_period is not None:
        # current_stock is PIECES (backend/stock_units.py), the same unit as
        # ss_i. Until 2026-09-23 this summed quantity_on_hand — CASES —
        # and compared it with a piece-scale safety stock, which reported
        # 109 of 120 measurable Category A SKUs as below safety stock when
        # 36 are. ss_i is pinned to the LP's current cycle too, so a
        # three-year-old pending row can't supply it.
        ss_rows = db.execute(
            text(f"""
                SELECT
                    ac.product_key,
                    ac.revenue_share AS revenue_share,
                    inv.stock_pieces AS current_stock,
                    rop.ss_i AS ss_i
                FROM ABC_Classification ac
                LEFT JOIN (
                    {STOCK_AT_PERIOD_SQL}
                ) inv ON inv.product_key = ac.product_key
                LEFT JOIN (
                    SELECT DISTINCT ON (lr.product_key) lr.product_key, lr.ss_i
                    FROM {lp_src} lr
                    WHERE lr.status = 'pending' {lp_cycle_filter}
                    ORDER BY lr.product_key, lr.planning_cycle_date DESC
                ) rop ON rop.product_key = ac.product_key
                WHERE ac.classification_period = :period AND ac.tier = 'A'
                      AND ac.method = 'single' {abc_scope}
            """),
            {"period": abc_period, "inv_period": inventory_period, "current_cycle": lp_cycle, **lp_params},
        ).mappings().all()
        comparable = [
            r for r in ss_rows
            if r["current_stock"] is not None and r["ss_i"] is not None
        ]
        if comparable:
            at_or_above = sum(1 for r in comparable if float(r["current_stock"]) >= float(r["ss_i"]))
            safety_stock_rate = round(at_or_above / len(comparable), 4)
            safety_stock_rate_blocked_reason = None
        else:
            # Shown on the card as is, so it names what a planner sees, not
            # table names. The LP has never planned Del Monte (no SKU-level
            # sales to forecast), which is the usual reason under that filter.
            safety_stock_rate_blocked_reason = (
                "The LP does not plan Del Monte, so it has no safety stock to compare against."
                if scope == "delmonte"
                else "No Category A SKU has both a stock record and a safety stock in the LP's current cycle."
            )

    # ---- preview: the ABC month the descriptive widgets show --------------
    # abc_period is the stored run the LP-based figures above and below
    # (safety stock, its exposure) are pinned to, and preview leaves it
    # alone. abc_mix, abc_coverage, abc_revenue and tier_stock read
    # abc_source at abc_display_period instead. Those are ABC_Classification
    # and abc_period in real mode, and in preview for any month a stored run
    # covers. Only a preview end month inside the placeholder window — no
    # stored run covers one — gets tiers computed now from the placeholder
    # demand (backend/data_mode.abc_single, the ABC run's own steps).
    abc_display_period = abc_period
    abc_source, abc_source_params = "ABC_Classification", {}
    if mode == PREVIEW and scope in ("all", "unilever") and abc_period is None and period is not None:
        window = placeholder_window(db)
        if window and period >= window["start"]:
            month = min(period, window["end"])
            computed = abc_single(db, [month], PREVIEW)
            if not computed.empty:
                abc_display_period = month
                abc_source, abc_source_params = abc_relation(computed, with_stored=False)
                safety_stock_rate_blocked_reason = (
                    f"{month} is a placeholder month. Safety stock belongs to the LP's current planning "
                    f"cycle, not to a past month — pick an end month from {window['first_real_month']} on."
                )

    # ---- safety_stock_exposure (band 2 headline) --------------------------
    # Same `comparable` rows as the rate above, so the headline and the KPI
    # card can never disagree about which products were measurable.
    if abc_period is not None and comparable:
        below = [r for r in comparable if float(r["current_stock"]) < float(r["ss_i"])]
        below_share = sum(float(r.get("revenue_share") or 0) for r in below)
        safety_stock_exposure = {
            "tier_a_count": len(ss_rows),
            "comparable_count": len(comparable),
            "below_count": len(below),
            "below_revenue_share": round(below_share, 4),
            "blocked_reason": None,
        }
    else:
        safety_stock_exposure = {
            "tier_a_count": len(ss_rows) if abc_period is not None else 0,
            "comparable_count": 0,
            "below_count": None,
            "below_revenue_share": None,
            "blocked_reason": safety_stock_rate_blocked_reason,
        }

    # ---- kpis.weeks_of_cover ---------------------------------------------
    # current stock on hand / average weekly demand — see the docstring
    # section above for the full reasoning. It is the figure SSM's 3-week
    # stock policy is judged by, so it does NOT follow the date picker: the
    # stock side is the stock card's own latest snapshot (already carrying
    # UNILEVER_SOH_UNIT_CONFIRMED), and the sales side is always the 12
    # months of sales ending at that snapshot's month, or at the last month
    # with sales before it. Until 2026-09-29 it averaged the picker's months,
    # so the same stock read 3.0-3.5 weeks depending on the range on screen,
    # and moving the end month back divided March 2026's stock by months-old
    # sales (2.9 weeks for Apr-Oct 2025). A year, not the latest month: Sir
    # Abe's rule is "a month's sales x 3/4", and the latest single month
    # (Feb 2026, a seasonal trough) or a 3-month window (holding December
    # 2025's 0.59x dip) both overstate cover at ~3.5 weeks; twelve months
    # average to one typical month with every season in it.
    # Numerator and denominator must describe the SAME principals. Under
    # 'all' the latest stock snapshot is Unilever's alone (Del Monte's latest
    # is 2025-12), so the demand side is read for exactly the principals the
    # stock figure covers instead of both — see _stock_valuation_coverage.
    # `cover_scope` (resolved with the stock card above) is what the answer
    # is about, and is returned so the card can say so rather than implying
    # 'all'.
    stock = soh_value
    cover_latest_sales = (
        max(filter(None, latest_by_principal.values()), default=None)
        if cover_scope == "all" else latest_by_principal.get(cover_scope)
    )
    cover_end = (
        min(cover_latest_sales, inventory_period)
        if cover_latest_sales is not None and inventory_period is not None
        else cover_latest_sales
    )
    cover_periods: list[str] = []
    if cover_end is not None:
        end_index = int(cover_end[:4]) * 12 + int(cover_end[5:7]) - 1
        start_index = end_index - 11
        cover_periods = _month_range(f"{start_index // 12:04d}-{start_index % 12 + 1:02d}", cover_end)
    # The page's own sums are reused where they are the same scope's; only
    # the months they lack are fetched, in one call.
    cover_known = sales_by_period if cover_scope == scope else {}
    cover_missing = [p for p in cover_periods if p not in cover_known]
    cover_fetched = _sales_by_period(db, cover_missing, cover_scope, mode) if cover_missing else {}
    cover_demand = {p: cover_known[p] if p in cover_known else cover_fetched.get(p) for p in cover_periods}
    stock_reason = (
        f"Inventory_Fact_Real has no rows for {_scope_label(scope)} at all." if inventory_period is None
        else _UNILEVER_SOH_UNIT_UNCONFIRMED_REASON if not UNILEVER_SOH_UNIT_CONFIRMED
        else f"No Inventory_Fact_Real rows with a stock valuation for {_scope_label(scope)} in {inventory_period}."
    )
    weekly_demand, demand_reason = _avg_weekly_demand(cover_demand)
    weeks_of_cover_value, weeks_of_cover_reason = _weeks_of_cover(
        stock, stock_reason, weekly_demand, demand_reason
    )
    # Months that actually carried a demand figure — a 12-month window with
    # 6 real months averages over 6, and the card should be able to say so.
    cover_months_used = sum(1 for v in cover_demand.values() if v is not None)

    # ---- sales_vs_stock series -------------------------------------------

    received_by_period = _received_by_period(db, periods, scope)

    sales_vs_stock = [
        {
            "period": p,
            "sales": sales_by_period[p],
            "stock_on_hand": soh_by_period.get(p),
            "received": received_by_period.get(p),
        }
        for p in periods
    ]

    # ---- chart story fields (backend/chart_insights.py) -----------------
    # The hero chart's one-sentence takeaway + its peak/low sales months,
    # and each value card's sparkline points + month-over-month delta —
    # all computed from the SAME dicts the chart/cards above read, so a
    # sentence can never disagree with the plot under it.
    svs_insight = sales_vs_stock_insight(sales_vs_stock)
    sales_trend = kpi_trend(sales_by_period, current_period)
    # The card's own series, so its sparkline and delta cover the same
    # principals as its value.
    soh_trend = kpi_trend(
        {p: soh_card_by_period.get(p) for p in soh_periods}, inventory_period
    )

    # ---- abc_mix -----------------------------------------------------

    # Which principals the ABC period actually contains. The latest run
    # (2026-02) holds Unilever rows only, so under 'all' the donut, its
    # centre total and tier_stock are one principal's — true, but it never
    # said so. Returned so the card can label itself.
    abc_coverage: list[str] = []
    if abc_display_period is not None:
        abc_coverage = sorted(
            r["principal"] for r in db.execute(
                text(f"""
                    SELECT principal FROM {abc_source}
                    WHERE classification_period = :period AND method = 'single'
                    GROUP BY principal
                """),
                {"period": abc_display_period, **abc_source_params},
            ).mappings().all() if r["principal"]
        )
        if scope != "all":
            abc_coverage = [p for p in abc_coverage if p == scope]

    abc_mix: list[dict] = []
    if abc_display_period is not None:
        mix_rows = db.execute(
            text(f"""
                SELECT tier, COUNT(*) AS cnt, SUM(revenue_share) AS rev_share_sum
                FROM {abc_source}
                WHERE classification_period = :period AND method = 'single' {abc_scope_bare}
                GROUP BY tier
            """),
            {"period": abc_display_period, **abc_source_params},
        ).mappings().all()
        abc_mix = [
            {
                "tier": r["tier"],
                "count": int(r["cnt"]),
                "revenue_share_pct": round(float(r["rev_share_sum"] or 0) * 100, 2),
            }
            for r in sorted(mix_rows, key=lambda r: r["tier"])
        ]

    # Two principals' revenue shares are fractions of two different totals,
    # so a month both principals were ranked in cannot be read as one ring:
    # summed, Class A came to ~151% under 'all' for 2025-12 (2026-09-29).
    # The counts stay; the shares are withheld.
    if len(abc_coverage) > 1:
        for row in abc_mix:
            row["revenue_share_pct"] = None

    # ---- abc_revenue (donut centre) -------------------------------------
    # The revenue the ring's shares are shares of — same per-principal
    # source as kpis.sales, for the ABC period, and for the principals the
    # ring actually covers: under 'all' the ranked run is usually Unilever's
    # alone, and the both-sides rule then left the centre "Revenue not
    # available" beside an 80% share. The card labels the coverage.
    if abc_display_period is None:
        abc_revenue = {"period": None, "total": None,
                       "blocked_reason": f"ABC_Classification has no rows for {_scope_label(scope)} yet."}
    elif len(abc_coverage) > 1:
        abc_revenue = {"period": abc_display_period, "total": None,
                       "blocked_reason": "Each principal's tiers are shares of its own revenue, so they are "
                                         "not combined — pick one principal to see them."}
    else:
        revenue_scope = abc_coverage[0] if abc_coverage else scope
        abc_total = _sales_by_period(db, [abc_display_period], revenue_scope, mode).get(abc_display_period)
        abc_revenue = {
            "period": abc_display_period,
            "total": _to_float(abc_total),
            "blocked_reason": (
                None if abc_total is not None
                else f"No sales rows for {_scope_label(revenue_scope)} in {abc_display_period} to total."
            ),
        }

    # ---- tier_stock ----------------------------------------------------

    tier_stock: list[dict] = []
    if abc_display_period is not None:
        ts_rows = db.execute(
            text(f"""
                SELECT
                    ac.tier,
                    inv.any_active AS any_active,
                    inv.any_inactive AS any_inactive
                FROM {abc_source} ac
                LEFT JOIN (
                    SELECT
                        product_key,
                        BOOL_OR(stock_status = 'Active') AS any_active,
                        BOOL_OR(stock_status = 'Inactive') AS any_inactive
                    FROM Inventory_Fact_Real
                    WHERE _period = :inv_period
                    GROUP BY product_key
                ) inv ON inv.product_key = ac.product_key
                WHERE ac.classification_period = :period AND ac.method = 'single' {abc_scope}
            """),
            {"period": abc_display_period, "inv_period": inventory_period, **abc_source_params},
        ).mappings().all()
        buckets: dict[str, dict[str, int]] = {}
        for r in ts_rows:
            tier = r["tier"]
            b = buckets.setdefault(tier, {"in_stock": 0, "dead_stock": 0, "no_data": 0})
            # Dead stock takes priority if a product has both an Active and
            # an Inactive row for the period (multiple snapshot_dates/
            # regions) — flagged Inactive even once is the signal worth
            # surfacing, same "don't average away a bad signal" reasoning
            # tier_stock's own no_data bucket already applies elsewhere.
            if r["any_inactive"]:
                b["dead_stock"] += 1
            elif r["any_active"]:
                b["in_stock"] += 1
            else:
                b["no_data"] += 1

        pending_rows = db.execute(
            text(f"""
                SELECT ac.tier, COUNT(DISTINCT lr.product_key) AS cnt
                FROM {abc_source} ac
                JOIN {lp_src} lr ON lr.product_key = ac.product_key AND lr.status = 'pending'
                WHERE ac.classification_period = :period AND ac.method = 'single' {abc_scope}
                      {lp_cycle_filter}
                GROUP BY ac.tier
            """),
            {"period": abc_display_period, "current_cycle": lp_cycle, **abc_source_params, **lp_params},
        ).mappings().all()
        pending_by_tier = {r["tier"]: int(r["cnt"]) for r in pending_rows}

        tier_stock = [
            {"tier": tier, **counts, "pending_reorder_count": pending_by_tier.get(tier, 0)}
            for tier, counts in sorted(buckets.items())
        ]

    # ---- portfolio_forecast --------------------------------------------

    latest_forecast_date_row = db.execute(
        text(f"SELECT MAX(forecast_date) AS d FROM {fc_src}"), fc_params
    ).mappings().first()
    latest_forecast_date = latest_forecast_date_row["d"] if latest_forecast_date_row else None

    gated_rows: list = []
    if latest_forecast_date is not None:
        gated_rows = db.execute(
            text(f"""
                SELECT fr.product_key, fr.forecast_date, fr.forecast_value,
                       fr.confidence_lower, fr.confidence_upper, pd.principal
                FROM {fc_src} fr
                JOIN Product_Dimension pd ON pd.product_key = fr.product_key
                WHERE fr.forecast_date = :forecast_date
                  AND fr.status = 'ok'
                  AND fr.mase < :mase_gate
                  {principal_filter}
            """),
            {"forecast_date": latest_forecast_date, "mase_gate": MASE_GATE, **fc_params},
        ).mappings().all()

    gated_sku_count = len({r["product_key"] for r in gated_rows})
    # "No forecasts exist for this scope" and "forecasts exist but none pass
    # the gate" are different facts. Del Monte is the live case of the
    # first: Forecast_Result has no Del Monte rows at all (its Sales
    # Register is invoice-grain with no SKU column, so no SKU-level
    # forecast is run), and reporting that as a failed reliability gate
    # would imply forecasts were made and judged unreliable.
    scoped_forecast_count = 0
    if latest_forecast_date is not None and not gated_rows:
        scoped_forecast_count = db.execute(
            text(f"""
                SELECT COUNT(*) FROM {fc_src} fr
                JOIN Product_Dimension pd ON pd.product_key = fr.product_key
                WHERE fr.forecast_date = :forecast_date {principal_filter}
            """),
            {"forecast_date": latest_forecast_date, **fc_params},
        ).scalar() or 0
    if gated_rows:
        # Says which principals the figure actually covers, from the rows
        # themselves. Under 'all' it used to read "Unilever only (...)" —
        # word for word what the Unilever filter shows — so the card's
        # All / Unilever switch looked broken when it was working: Del Monte
        # simply has no SKU-level forecasts to add.
        covered = sorted({r["principal"] for r in gated_rows if r.get("principal")})
        names = {"unilever": "Unilever", "delmonte": "Del Monte"}
        if scope == "all" and len(covered) == 1:
            only = names.get(covered[0], covered[0])
            scope_label = (
                f"All principals — only {only} has SKU-level forecasts that beat a naive "
                f"baseline (MASE < 1, the LP's own gate), so this matches the {only} view."
            )
        else:
            who = "All principals" if scope == "all" else names.get(scope, scope)
            scope_label = f"{who} (SKU-level forecasts that beat a naive baseline — MASE < 1, the LP's own gate)."
    elif scoped_forecast_count == 0:
        scope_label = (
            "No SKU-level forecasts exist for Del Monte — its sales data is invoice-grain "
            "with no SKU column, so no per-SKU forecast is run."
            if scope == "delmonte"
            else f"No SKU-level forecasts exist for {_scope_label(scope)}."
        )
    else:
        scope_label = (
            f"No forecasts for this scope currently beat the naive baseline "
            f"(MASE < {MASE_GATE:g})."
        )

    series_by_period: dict[str, dict] = {}
    if gated_rows:
        gated_product_keys = sorted({r["product_key"] for r in gated_rows})

        actual_totals: dict[str, float] = {}
        # The history the forecasts were made from: five years in a preview
        # built from it, the real months otherwise.
        forecast_demand = unilever_demand(mode) if predictive_preview(mode) else REAL_UNILEVER_DEMAND
        rows = db.execute(
            text(f"""
                SELECT calendar_month AS period, SUM(quantity_sold) AS qty
                FROM {forecast_demand}
                WHERE product_key = ANY(:keys)
                GROUP BY calendar_month
            """),
            {"keys": gated_product_keys},
        ).mappings().all()
        for r in rows:
            actual_totals[r["period"]] = actual_totals.get(r["period"], 0.0) + float(r["qty"] or 0)

        # Follows the picker's selected range (the same `periods` window
        # kpis.sales / sales_vs_stock above are computed over) instead of a
        # hardcoded trailing 8 months, so this chart moves with the
        # dashboard's date filter like every other one does. Every period
        # in the picked range gets an entry — actual_totals.get(p) is None
        # (not omitted) for a period with no real sales among the gated
        # SKUs, so a genuine gap breaks the line (connectNulls={false} on
        # the frontend) instead of silently being skipped over.
        for p in periods:
            series_by_period[p] = {"period": p, "actual": actual_totals.get(p), "forecast": None,
                                    "confidence_lower": None, "confidence_upper": None}

        forecast_buckets: dict[str, dict] = {}
        for r in gated_rows:
            d = r["forecast_date"]
            p = f"{d.year:04d}-{d.month:02d}" if hasattr(d, "year") else str(d)[:7]
            b = forecast_buckets.setdefault(p, {"forecast": 0.0, "lower": None, "upper": None,
                                                 "lower_seen": False, "upper_seen": False})
            b["forecast"] += float(r["forecast_value"] or 0)
            if r["confidence_lower"] is not None:
                b["lower"] = (b["lower"] or 0.0) + float(r["confidence_lower"])
                b["lower_seen"] = True
            if r["confidence_upper"] is not None:
                b["upper"] = (b["upper"] or 0.0) + float(r["confidence_upper"])
                b["upper_seen"] = True

        for p, b in forecast_buckets.items():
            entry = series_by_period.setdefault(
                p, {"period": p, "actual": None, "forecast": None, "confidence_lower": None, "confidence_upper": None}
            )
            entry["forecast"] = b["forecast"]
            entry["confidence_lower"] = b["lower"] if b["lower_seen"] else None
            entry["confidence_upper"] = b["upper"] if b["upper_seen"] else None

    portfolio_series = [series_by_period[p] for p in sorted(series_by_period.keys())]
    portfolio_forecast = {
        "series": portfolio_series,
        "gated_sku_count": gated_sku_count,
        "scope_label": scope_label,
        # The gate the count above was filtered by — the same value as
        # forecast.mase_gate, stated here too so the card never hardcodes it.
        "mase_gate": MASE_GATE,
        # One sentence comparing the forecast bucket with the last actual
        # month — the card renders it verbatim (backend/chart_insights.py).
        "insight": portfolio_forecast_insight(portfolio_series),
    }

    # ---- reorder_preview -------------------------------------------------

    # Current cycle only, like every other LP read on this page — the
    # critical/urgent counts below are a portfolio summary and must not
    # include rows superseded by a later run.
    rp_select, rp_select_params = _recommendation_select_one(mode)
    rp_query = rp_select + f" WHERE lr.status = 'pending' {principal_filter} {lp_cycle_filter}"
    # Both anchors are bound, not inlined, so reorder_preview resolves them
    # under the SAME scope as the rows it shows. `inventory_period` is the
    # already-scoped value from :763. The ABC anchor is the scoped LATEST,
    # deliberately not the page's `abc_period` — that one is rewound to the
    # picker's applied end month, and reorder_preview answers "order now".
    rp_rows = db.execute(
        text(rp_query),
        {
            "inv_period": inventory_period,
            "abc_period": latest_abc_period(db, scope),
            "current_cycle": lp_cycle,
            **rp_select_params,
        },
    ).mappings().all()
    rp_items = [_to_recommendation_item(r) for r in rp_rows]
    # Within an urgency, highest priority first — the Reorder page's own
    # ranking (revenue share x units below the reorder point). Urgency alone
    # left the order to the query, so the card showed an arbitrary five of
    # the 183 CRITICAL rows (2026-09-29).
    rp_items_sorted = sorted(
        rp_items,
        key=lambda it: (_URGENCY_RANK.get(it.urgency, 99), -(it.priority_score or 0)),
    )

    reorder_preview = {
        "rows": [item.model_dump() for item in rp_items_sorted[:5]],
        "critical_count": sum(1 for it in rp_items if it.urgency == "CRITICAL"),
        "urgent_count": sum(1 for it in rp_items if it.urgency == "URGENT"),
        # Products with no Inventory_Fact_Real row at the latest snapshot —
        # reported as their own count, never folded into critical.
        "no_data_count": sum(1 for it in rp_items if it.urgency == "NO DATA"),
        # Whole units per row, summed — the Reorder page's own total, so the
        # two screens agree (they differed by 123.6 units, 2026-09-29).
        "total_order_qty": sum(whole_units(it.q_i) for it in rp_items) if rp_items else 0,
        "lp_weights": {
            "cost": LP_WEIGHT_COST,
            "service_level": LP_WEIGHT_SERVICE_LEVEL,
            "storage": LP_WEIGHT_STORAGE,
        },
    }

    # ---- policy_comparison (band 4: LP safety stock vs SSM's 3-week policy) --
    # One row per product in the latest pending cycle that ALSO has a
    # Forecast_Result for that same month (fr.forecast_date =
    # lr.planning_cycle_date); products missing the forecast drop out of
    # both sums. Both sides are in the demand series' unit — see the
    # docstring section above for why this stays in units, not pesos.
    policy_rows = db.execute(
        text(f"""
            SELECT lr.planning_cycle_date, lr.ss_i, fr.forecast_value
            FROM {lp_src} lr
            JOIN Product_Dimension pd ON pd.product_key = lr.product_key
            JOIN {fc_src} fr
              ON fr.product_key = lr.product_key AND fr.forecast_date = lr.planning_cycle_date
            WHERE lr.status = 'pending'
              {lp_cycle_filter}
              {principal_filter}
        """),
        {"current_cycle": lp_cycle, **lp_params, **fc_params},
    ).mappings().all()
    policy_rows = [r for r in policy_rows if r["forecast_value"] is not None and r["ss_i"] is not None]
    if policy_rows:
        cycle = policy_rows[0]["planning_cycle_date"]
        lp_units = sum(float(r["ss_i"]) for r in policy_rows)
        rule_units = sum(POLICY_WEEKS * float(r["forecast_value"]) / AVG_WEEKS_PER_MONTH for r in policy_rows)
        policy_comparison = {
            "cycle_date": cycle.isoformat() if hasattr(cycle, "isoformat") else str(cycle),
            "sku_count": len(policy_rows),
            "lp_safety_stock_units": round(lp_units, 2),
            "rule_safety_stock_units": round(rule_units, 2),
            # How much less (positive) or more (negative) buffer the LP holds
            # than the rule, as a percent of the rule — the one-number
            # headline IMPLEMENTATION_PLAN Phase 1.1 asks for.
            "lp_vs_rule_pct": round((rule_units - lp_units) / rule_units * 100, 1) if rule_units > 0 else None,
            "rule_weeks": POLICY_WEEKS,
            "blocked_reason": None,
        }
    else:
        policy_comparison = {
            "cycle_date": None,
            "sku_count": 0,
            "lp_safety_stock_units": None,
            "rule_safety_stock_units": None,
            "lp_vs_rule_pct": None,
            "rule_weeks": POLICY_WEEKS,
            "blocked_reason": (
                f"No pending LP_Recommendation for {_scope_label(scope)} has a Forecast_Result "
                "for its own planning-cycle month, so the two policies can't be compared."
            ),
        }

    payload = {
        "principal": scope,  # the scope this payload answers: 'all' | 'unilever' | 'delmonte'
        "period": None,
        "inventory": {
            "value": _to_float(soh_value),
            "weeks_of_cover": None,
            "policy_weeks": POLICY_WEEKS,
        },
        "recommendations": {"order_value": None, "product_count": product_count},
        "forecast": {
            "unreliable_count": unreliable_count,
            "evaluated_count": evaluated_count,
            "total_count": total_count,
            # The pass gate unreliable_count was counted against, so the
            # card's "Beat naive (MASE < N)" label states it from here.
            "mase_gate": MASE_GATE,
        },
        "latest_data_period": max(filter(None, latest_by_principal.values()), default=None),
        "latest_data_period_by_principal": latest_by_principal,
        "cover_series": [{"period": p, "weeks_of_cover": None} for p in periods],
        "kpis": {
            "sales": _to_float(sales),
            "sales_blocked_reason": sales_blocked_reason,
            # The month this figure is actually for. The card used to read
            # "This period's total sales" while the value could be any
            # earlier month the walk-back landed on — under 'all' that is
            # 2025-12 (Del Monte's last month) while Unilever alone shows
            # 2026-02, so the same card silently changed month with the
            # principal filter and never said which.
            "sales_period": current_period,
            "soh_value": _to_float(soh_value),
            "soh_value_blocked_reason": soh_value_blocked_reason,
            "soh_period": inventory_period,
            "soh_coverage": stock_coverage,
            "safety_stock_rate": safety_stock_rate,
            "safety_stock_rate_blocked_reason": safety_stock_rate_blocked_reason,
            # Sparkline + month-over-month delta for the two value cards
            # (backend/chart_insights.py). Points are real months only; a
            # missing month is dropped, never zero-filled. Null when the
            # scope has nothing real to plot.
            "sales_trend": sales_trend,
            "soh_trend": soh_trend,
            "weeks_of_cover": {
                "value": weeks_of_cover_value,
                "blocked_reason": weeks_of_cover_reason,
                # The principals this ratio describes, which under 'all' is
                # NOT necessarily both — see _stock_valuation_coverage.
                "coverage": stock_coverage,
                "months_used": cover_months_used,
                "stock_period": inventory_period,
                # The 12 months the average weekly sales came from — fixed to
                # the stock count, never the picker's range — so the card can
                # say which year the "3 weeks" is measured against.
                "sales_window": (
                    {"start": cover_periods[0], "end": cover_periods[-1]} if cover_periods else None
                ),
            },
        },
        # Non-null only under 'all': the combined pesos mix Unilever's
        # VAT-inclusive amounts with Del Monte's VAT-exclusive ones, and
        # the sales card and hero chart say so from this one field.
        "vat_note": vat_note,
        # Sales against SSM's allocation rule (prior-year sales x 103/105/
        # 108% — client meeting, Sep 2026), per principal.
        "allocation": allocation,
        # Which LP run the page is showing, and whether it can still be
        # trusted (backend/lp_cycle.py). Every LP-derived figure above is
        # pinned to this cycle; superseded_pending_count says how many
        # older pending rows were withheld.
        "lp": lp_freshness_info,
        "sales_vs_stock": sales_vs_stock,
        # {text, peak, low} — the hero chart's takeaway sentence and the
        # sales months it should label, from the same rows it plots.
        "sales_vs_stock_insight": svs_insight,
        "abc_mix": abc_mix,
        # The cutoffs the ABC run applied, so the card states them from the
        # source (analytics/classification/abc.py) rather than in its copy.
        "abc_rules": abc_rules(),
        "abc_coverage": abc_coverage,
        "abc_revenue": abc_revenue,
        "safety_stock_exposure": safety_stock_exposure,
        "policy_comparison": policy_comparison,
        "tier_stock": tier_stock,
        # The stock snapshot month tier_stock's Active/Inactive flags were
        # read at — the card's "no dead stock flagged in <month>" line
        # names this, never a month typed in the frontend.
        "tier_stock_period": inventory_period if tier_stock else None,
        "portfolio_forecast": portfolio_forecast,
        "reorder_preview": reorder_preview,
    }
    # Preview only, so a real-mode payload is exactly what it was. Stock and
    # purchases have no placeholder rows to add; the rest are predictive or
    # prescriptive, which read real data only (backend/data_mode.py).
    if mode == PREVIEW:
        real_only = ["kpis.soh_value", "sales_vs_stock.stock_on_hand", "sales_vs_stock.received", "latest_data_period"]
        if not predictive_preview(mode):
            real_only += ["kpis.safety_stock_rate", "safety_stock_exposure", "recommendations", "forecast",
                          "portfolio_forecast", "reorder_preview", "policy_comparison", "lp"]
        payload["data_mode"] = preview_block(db, real_only=real_only)
    return payload
