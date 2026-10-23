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

DATA MARTS + THE SELECTED RANGE (2026-10-04, migration 0041). Every sales,
stock, flow, Pareto, accuracy and idle-stock figure here reads the `mart`
schema (backend/marts.py) — pre-summed product x month / product x count
tables rebuilt after each load, fill, forecast and LP run — instead of
summing the fact tables per request. Each mart row is real / filled /
generated: KPIs, the Pareto and accuracy read real rows only; the sales vs
stock chart also carries *_estimated points (filled; generated too in
preview) where a real one is missing (coverage hole H1), and returns (H4).
And every card answers for the selected range (the Technical Adviser's main
request): kpis.sales_cumulative (the range's total) beside the end-month
snapshot; stock, its safety-stock check and dead stock at the count at the
range's END (not the latest count); the ABC ring ranked on the range
itself; forecast_accuracy and idle_stock for the range. Sections below that
describe the old per-request sources keep their reasoning; the numbers they
compute are the same, read from the marts.

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
symptom). All three now pin the method; since migration 0044 to each
principal's Tier A basis (analytics.params.abc_method_sql).

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
    — real: COUNT(*) of the PLAN's LP_Recommendation rows (pending + accepted + dismissed, the current
    cycle: a decided row stays in the plan, the Reorder page's count). The still-pending subset is
    reorder_preview.pending_count. Needs no price,
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
    Sep 2026). Since 2026-10-04 (DEC-36) it reads the stock card's own
    count, the one at the range's end; from 2026-09-29 to then it read the
    latest count whatever the range. caveat names where stock and sales
    come from when they differ (Unilever: Ilocos Sur stock, La Union sales).
      Stock on hand is that count's valuation (UNILEVER_SOH_UNIT_CONFIRMED
        is inherited automatically, not re-checked here).
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
  sales_vs_stock[].stock_count_date / kpis.soh_count_date /
  tier_stock_count_date
    — display only: the day the snapshot behind each stock figure was
    counted (MAX(Inventory_Fact_Real.snapshot_date) for that `_period`,
    when the scope's rows share one count day — _stock_count_dates). A
    `_period` is not a count date: "2026-03" is Unilever's 2026-04-06
    count. No figure is computed from these.
  sales_vs_stock[].received
    — SUPPLIER-ALLOCATION PROXY, not a fabricated fixed_allocation
    constant: no supplier allocation schedule exists anywhere in the
    schema or the source files — SSM has never provided one. Purchase_Fact_Real
    pesos per period (same axis as sales/stock_on_hand), via
    _received_by_period(), on the same tax basis as that principal's sales
    line since 2026-10-01 — Del Monte's ex-VAT (net_amount - tax_amount),
    Unilever's VAT-inclusive; sales_vs_stock_basis names it for the legend.
    Null (a real gap, never 0) for any period Purchase_Fact_Real has no
    matching rows for.
  sales_vs_stock[].stock_on_hand flags
    — stock_on_hand_flags lists the chart's stock counts the team reviewed
    and judged unusual (backend/data_notes.py), with the reason. The points
    stay; the chart marks them, and neither the stock card's change nor the
    chart's sentence is measured from one.
    Deliberately isolated in its own function (_received_by_period, one
    call site) so a future swap to a real Supplier_Allocation table is a
    source change inside that one function, not a rewrite of this
    endpoint — see that function's own docstring.

  abc_mix[].revenue_share_pct / abc_mix[].revenue
    — real: each class's revenue (the ranked products' own net_amount for
    the classification_period, summed unrounded — _abc_class_revenue) and
    its share of the ranked total, since 2026-10-01. Falls back to
    SUM(revenue_share) * 100 with revenue null if a ranked product's
    revenue can no longer be found.

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
    Never fabricated into a clean synchronized run. A bucket's band is the
    SKUs' half-widths combined as a root-sum-of-squares (an approximate 90%
    range if the SKUs' misses are independent), not their bounds summed —
    see the comment at the bucket loop.
    gated_sku_count is computed from the same gated-row set. Null/empty
    across the board (gated_sku_count=0, series=[]) when nothing passes
    the gate.

  reorder_preview
    — real: top 5 pending LP_Recommendation rows by urgency (decided rows stay in the counts and totals, not in the preview), reusing
    backend.routers.recommendations._to_item / _SELECT_ONE verbatim
    (imported, not reimplemented) for the exact same urgency derivation
    GET /recommendations uses (backend/stock_status.py). critical_count /
    low_count (urgent_count: the same number under its old name) /
    total_order_qty are computed over the FULL set (not just the
    5 previewed rows): critical/urgent/no_data, total_order_qty and plan_count
    over the plan, pending_order_qty / pending_count over the pending rows only — a portfolio-wide summary next to a 5-row preview,
    same relationship ABC's tier_summary has to its own items list.
    Stock is the count that opens the LP's cycle (since 2026-10-03, DEC-32),
    named with its date in reorder_preview.stock_counts; the stock card
    keeps the latest count (kpis.stock_counts).
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
    — {period, total, ranked_total, blocked_reason}. total is SUM(net_amount)
    for the resolved abc_period, from the same per-principal demand facts
    kpis.sales reads (_sales_by_period). ranked_total is the revenue the
    ring's shares are shares OF: only the products
    analytics/classification/orchestrate_abc.py ranked (net revenue > 0), so
    it is total plus the net returns of the products it left out.
    Null under 'all' unless both principals have a real figure (the
    both-sides-real rule), or when no ABC run exists.
  safety_stock_exposure
    — {tier_a_count, comparable_count, below_count, below_revenue_share,
    below_items, blocked_reason}. Same rows and same "both figures or excluded" rule as
    kpis.safety_stock_rate, plus each product's revenue_share, so "N of M
    measurable Category A SKUs are below safety stock, X% of revenue" is
    one query, not two that could disagree. below_revenue_share is the sum
    of revenue_share over the below-SS products (a share of the WHOLE
    period's revenue, not of Tier A's). below_items is those same below-SS
    products, most revenue first — [{sku_id, product_name, current_stock,
    ss_i, short_by, target_stock, order_qty, revenue_share}], pieces
    throughout — the list behind the count, built from the rows the count
    was taken from so the two can never disagree (2026-10-03).
  policy_comparison
    — {cycle_date, sku_count, lp_target_stock_units, lp_safety_stock_units,
    rule_stock_units, target_vs_rule_pct, lp_target_weeks, skus_above_rule,
    rule_weeks, window_business_days,
    inputs_are_placeholders, blocked_reason} (rule_safety_stock_units is
    rule_stock_units under its pre-2026-09-30 name). target_vs_rule_pct is
    the headline: how much less stock the LP's per-SKU targets (rop_i, the
    order-up-to level T_i since the 2026-09-30 run) hold than the rule, as a
    percent of the rule (negative = more). There is no safety-stock-vs-rule
    percent (lp_vs_rule_pct, removed): SSM's 3 weeks is a target for all stock,
    not a buffer, so it was not like-for-like and read "less" when the targets
    hold more. lp_safety_stock_units stays as a plain sum.
    The per-SKU rows behind these sums are GET /policy-comparison
    (policy_comparison.py) — keep the two queries in step. Sums, over the latest pending planning
    cycle, the LP's rop_i and ss_i against what SSM's own stock policy would hold
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
from sqlalchemy.orm import Session

from backend import batch, marts
from backend.data_mode import (
    PREVIEW,
    REAL,
    demo_data_enabled,
    forecast_source,
    get_data_mode,
    lp_source,
    placeholder_window,
    predictive_preview,
    preview_block,
    unilever_demand,
)
from analytics.allocation import allocation_levels, basis_year as allocation_basis_year, planning_month_after
from analytics.classification.abc import abc_rules
from analytics.params import abc_method_sql
from backend.abc_basis import dashboard_basis
from analytics.params import (
    ALLOCATION_DEFAULT_PCT,
    COVER_KPI_HISTORY_MONTHS,
    DEAD_SKU_MONTHS,
    MASE_GATE,
    PLACEHOLDERS,
    REVIEW_OVER_RUN_MONTHS,
)
# SSM's "keep 3 weeks of sales" and the weeks-per-month convention, under
# the names this module and policy_comparison.py already use.
from analytics.params import POLICY_COVER_WEEKS as POLICY_WEEKS
from analytics.params import WEEKS_PER_MONTH as AVG_WEEKS_PER_MONTH
from backend.chart_insights import kpi_trend, portfolio_forecast_insight, sales_vs_stock_insight
from backend.data_notes import COVER_CAVEATS, flagged_count_note, unusual_stock_snapshots
from backend.deps import TokenPayload, get_db
from backend.permissions import can_see_lp, require_permission
from backend.lp_cycle import (
    CURRENT_CYCLE_CLAUSE, LP_RUN_PRESENT_SQL, LP_WEIGHTS, PLAN_STATUS_SQL, current_cycle, current_cycle_query,
    forecast_generated_query, freshness_query, lp_run_present, lp_run_present_known, stored_run,
    stored_run_query, superseded_count_query,
)
from backend.lp_cycle import freshness as lp_freshness
from backend.principals import (
    PrincipalQuery,
    abc_period_params,
    abc_period_pred,
    abc_periods_from_rows,
    latest_abc_period_query,
    tier_a_periods,
    normalize_principal,
)
from backend.routers.recommendations import select_one as _recommendation_select_one
from backend.routers.recommendations import _to_item as _to_recommendation_item
from backend.routers.recommendations import whole_units
from backend.stock_status import CRITICAL, NO_DATA, URGENCY_RANK, URGENT
from backend.stock_units import STOCK_COUNTS_SQL, opening_period, stock_counts
from backend.response_cache import cached
from backend import demo_data
from backend.series_gaps import (
    REASON_NO_DATA_BEFORE_2023, REASON_NOT_COLLECTED, gap_note as series_gap_note,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

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
# One definition with the LP's ceiling: analytics/allocation.py.

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

# AVG_WEEKS_PER_MONTH (imported above, analytics.params.WEEKS_PER_MONTH):
# average days/month (365.25/12) / 7, converting an average MONTHLY figure
# to a weekly rate for kpis.weeks_of_cover. A documented convention, not a
# fabricated number.

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

_URGENCY_RANK = URGENCY_RANK  # backend/stock_status.py: CRITICAL, URGENT, PLANNED
_PRINCIPAL_LABELS = {"unilever": "Unilever", "delmonte": "Del Monte"}


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
    coverage (real through 2026-02 vs 2025-12 as of 2026-09-17).

    Read from mart.sales_month's real rows (migration 0041), the same source
    every sales figure on this page now sums."""
    candidates = [
        p for p in (marts.latest_sales_period(db, who) for who in ("unilever", "delmonte")
                    if principal in ("all", who))
        if p
    ]
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
    (backend/data_mode.py); Del Monte is real in either mode.

    Since migration 0041 both sides are mart.sales_month (the same rows,
    summed once per refresh): real rows only, plus the placeholder months
    the mart marks preview_placeholder in preview."""
    unilever = (
        marts.sales_by_period(db, periods, "unilever", mode)
        if principal in ("all", "unilever") else {p: None for p in periods}
    )
    delmonte = (
        marts.sales_by_period(db, periods, "delmonte", mode)
        if principal in ("all", "delmonte") else {p: None for p in periods}
    )
    return _combine_principal_sums(periods, unilever, delmonte, principal)


def _not_real_sales_months(db: Session, periods: list[str], principal: str, mode: str) -> set[str]:
    """The months whose sales figure holds rows that are not SSM's own (filled or
    generated), for any principal in scope: marts.COUNT_FILLED_AND_GENERATED counts
    them as sales, and every card and chart that shows the figure must say so."""
    out: set[str] = set()
    for who in ("unilever", "delmonte"):
        if principal in ("all", who):
            sources = marts.sales_sources_by_period(db, periods, who, mode)
            out |= {p for p, kinds in sources.items() if any(k != "real" for k in kinds)}
    return out


# The Annual View card shows this many calendar years, ending at the latest
# year with sales (its title: "5-Year Trend").
ANNUAL_SALES_YEARS = 5


def _annual_sales(db: Session, scope: str, mode: str) -> dict:
    """Total sales per calendar year for the Annual View card (Audrey,
    2026-10-12): each year is the sum of its months' sales from
    _sales_by_period, the same per-month figures the sales cards, the
    allocation card and the Sales vs Inventory chart read, so a year here
    can never disagree with them. Nothing is projected and nothing is
    scaled up: a year with fewer than 12 months on record is the sum of
    the months it has, and `months` says how many.

    Fixed like the allocation card: it does not follow the date range.
    Fiscal year = calendar year, as on that card ("FY 2026 sales, Jan-Feb").

    years[]: {year, sales, months, first_month, last_month,
    synthetic_months}. `sales` is null (never 0) for a year in the window
    with no month on record. `synthetic_months` are the months counted in
    `sales` that are not SSM's own figures (_not_real_sales_months); the
    card must mark them. earlier_years: years with sales that fall before
    the window, so the card can say they exist."""
    out: dict = {"years": [], "window_years": ANNUAL_SALES_YEARS, "earlier_years": [], "blocked_reason": None}
    span = marts.sales_month_span(db, scope)
    if span is None:
        out["blocked_reason"] = f"No sales rows for {_scope_label(scope)} at all."
        return out
    first_year, last_year = int(span[0][:4]), int(span[1][:4])
    periods = [f"{y:04d}-{m:02d}" for y in range(first_year, last_year + 1) for m in range(1, 13)]
    by_period = _sales_by_period(db, periods, scope, mode)
    not_real = _not_real_sales_months(db, periods, scope, mode)
    counted = sorted(p for p in periods if by_period.get(p) is not None)
    if not counted:
        out["blocked_reason"] = f"No month has a sales figure for {_scope_label(scope)}."
        return out
    # The window ends at the latest year a month is counted in, not at the
    # last row: generated months after the last real month are not sales.
    end_year = int(counted[-1][:4])
    start_year = end_year - ANNUAL_SALES_YEARS + 1
    for year in range(start_year, end_year + 1):
        months = [p for p in counted if p.startswith(f"{year:04d}-")]
        out["years"].append({
            "year": year,
            "sales": round(sum(by_period[p] for p in months), 2) if months else None,
            "months": len(months),
            "first_month": months[0] if months else None,
            "last_month": months[-1] if months else None,
            "synthetic_months": [p for p in months if p in not_real],
        })
    out["earlier_years"] = sorted({int(p[:4]) for p in counted if int(p[:4]) < start_year})
    return out


def _estimate_points(periods: list[str], real: dict, by_principal: dict[str, dict], principal: str) -> dict[str, dict]:
    """A chart's estimated point per month: only where the real value is missing, from the
    principal's non-real rows ({period: {value, kind}}, backend/marts.py). Under 'all' a
    month gets an estimate when each principal has a real or an estimated figure and at
    least one is estimated, so the point still covers both principals."""
    out: dict[str, dict] = {}
    for p in periods:
        if real.get(p) is not None:
            continue
        if principal != "all":
            est = by_principal[principal].get(p)
            if est is not None:
                out[p] = est
            continue
        parts, kinds = [], set()
        for who in ("unilever", "delmonte"):
            real_side = by_principal[f"{who}_real"].get(p)
            est = by_principal[who].get(p)
            if real_side is not None:
                parts.append(real_side)
            elif est is not None:
                parts.append(est["value"])
                kinds.add(est["kind"])
        if len(parts) == 2 and kinds:
            out[p] = {"value": sum(parts), "kind": "/".join(sorted(kinds))}
    return out


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
    """Purchases received per period, in pesos, on the SAME tax basis as
    that principal's sales line. Unlike sales/soh, both principals live in
    ONE table here (Purchase_Fact.principal), so this is a straight WHERE
    filter rather than a source swap — but the combine rule under 'all' is
    identical (both sides real, or null).

    TAX BASIS (2026-10-01). Purchase_Fact.net_amount is the purchase file's
    "Net Amount" (config/column_maps/purchase_order.yaml), which INCLUDES
    VAT: tax_amount / net_amount is 12/112 on all 499 Del Monte rows
    (0.107140-0.107146 live). Del Monte's sell-out sales are ex-VAT ("Total
    Without Tax"), so the line was plotted ~12% high against the sales it
    sits beside — Dec 2025 read ₱23.0M of purchases against ₱22.1M of sales
    when the ex-VAT purchases were ₱20.5M. Del Monte is therefore
    net_amount - tax_amount (a NULL tax_amount counts as 0: none live).
    Unilever's sales are VAT-inclusive ("Total Sales Amt Inc. Tax"), so its
    branch keeps net_amount as is, on the same basis — but there is no
    Unilever purchase source at all (the purchase map is Del Monte's file;
    0 Unilever rows live), so whoever loads one must confirm its Net Amount
    includes VAT before this branch is trusted.

    LIVE CAVEAT (2026-09-17, still true 2026-10-01): purchase_fact_real
    holds 499 Del Monte rows and ZERO Unilever rows, so the Unilever side
    of this is null for every period today. That is a genuine source gap,
    not a filter mistake — and it means 'all' is null here too, by the
    both-sides-real rule.

    Since migration 0041: mart.flow_month's 'purchases' real rows, built
    with exactly this tax rule (Del Monte net_amount - tax_amount)."""
    def side(who: str) -> dict[str, float | None]:
        if principal not in ("all", who):
            return {p: None for p in periods}
        return {p: v["real"] for p, v in marts.flow_by_period(db, periods, who, "purchases").items()}
    return _combine_principal_sums(periods, side("unilever"), side("delmonte"), principal)


# DEC-31 item 1 (2026-10-02): Unilever has no purchase records, so the chart may
# show an ESTIMATE next to `received` - SUM(derived_receipt_fact.receipt_value)
# per period (closing - opening stock + sales, at cost; scripts/fill_missing.py).
# Never folded into `received`, never summed under 'all' (that would mix an
# estimate into a real total), Unilever scope only. The frontend draws it as a
# labelled estimate ("Estimated from stock and sales"); negative_skus is the
# month's count of SKUs whose stock balance came out negative (flagged, counted
# as zero receipts) for the tooltip. Absent table (public before migration
# 0038) = every period null.
def _estimated_received_by_period(
    db: Session, periods: list[str], principal: str = "unilever"
) -> dict[str, dict]:
    empty = {p: {"value": None, "negative_skus": None, "skus": None} for p in periods}
    if principal != "unilever":
        return empty
    out = dict(empty)
    for p, v in marts.flow_by_period(db, periods, "unilever", "estimated_receipts").items():
        if v["estimated"] is not None:
            out[p] = {"value": v["estimated"], "negative_skus": v["negative_rows"], "skus": v["products"]}
    return out


def _point_provenance(point: dict, synthetic_sales: bool) -> dict[str, str | None]:
    """Per-point source of each value on the sales/stock chart: 'real',
    'derived' (an estimate from real data), 'synthetic' (preview placeholder),
    'filled' / 'generated' (a mart row of that data kind, drawn as an estimate),
    or None (a gap - render null, never 0)."""
    def tag(value, kind):
        return None if value is None else kind
    return {
        "sales": tag(point["sales"], "synthetic" if synthetic_sales else "real"),
        "stock_on_hand": tag(point["stock_on_hand"], "real"),
        "received": tag(point["received"], "real"),
        "received_estimated": tag(point["received_estimated"], "derived"),
        "sales_estimated": point.get("sales_estimated_kind"),
        "stock_on_hand_estimated": point.get("stock_on_hand_estimated_kind"),
        "returns": tag(point.get("returns"), "real"),
        "returns_estimated": point.get("returns_estimated_kind"),
    }


def _latest_inventory_period(db: Session, principal: str = "unilever", end: str | None = None) -> str | None:
    """Latest real stock count month within the selected scope — on or before
    `end` when given (the stock at the date range's end, 2026-10-04), else the
    latest overall (weeks of cover's count). Both principals share the table,
    so the scope is applied here, not just at the row query. mart.inventory_count
    since migration 0041."""
    return marts.stock_period_at_or_before(db, end, principal)


def _stock_count_dates(db: Session, periods: list[str], principal: str = "unilever") -> dict[str, str]:
    """The day each stock snapshot was physically counted, keyed by the
    `_period` the rest of this endpoint files it under ('YYYY-MM-DD'). Display
    only — no figure is computed from it.

    A snapshot's `_period` is not the day it was counted: Unilever's
    "2026-03" stock is the count taken on 2026-04-06. A period gets a date
    only when its rows in scope share ONE count day; Del Monte's stored day is
    a 1st-of-month placeholder (DEC-12), so a period holding a Del Monte count
    gets none and the page names the month instead. (Audrey's field,
    group7/UIFixes_Audrey 3825d02, read from mart.inventory_count.)"""
    return marts.count_dates(db, periods, principal)


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
    # Inventory_Fact.valuation is the SOURCE FILE's own extended peso total
    # and already prices the loose-piece remainder; the multiplication is
    # only a fallback for rows without it. Verified 2026-09-23 against the
    # live 2026-03 snapshot: valuation = cases x unit_cost + pieces x
    # (unit_cost / pack_size) for 689 of 689 rows. Computing it here instead
    # under-reported stock by the remainder — PHP 21,991,481 against the
    # file's own 22,700,826, a 3.2% gap this app had no reason to invent.
    # mart.inventory_mart carries exactly that sum per product and count.
    return marts.stock_by_period(db, periods, principal)


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
    return marts.stock_coverage(db, period, principal)


def _latest_abc_periods(db: Session, principal: str = "unilever") -> dict[str, str]:
    """Latest ABC_Classification.classification_period PER PRINCIPAL in the
    selected scope ({principal: period}). ABC_Classification carries both
    principals with different latest runs (Unilever 2026-02, Del Monte
    2025-12), so under 'all' one MAX across both would leave Del Monte on a
    period it has no rows for.

    The method pin is REQUIRED (migration 0017): several bases are live,
    and an unpinned MAX can resolve to a period only another basis produced
    — which would then read back zero rows. Pinned to each principal's Tier A
    basis (analytics.params.abc_method_sql, migration 0044)."""
    return abc_periods_from_rows(batch.rows(db, *_latest_abc_period_query(principal)))


def _latest_abc_period_query(principal: str = "unilever") -> tuple[str, dict]:
    return latest_abc_period_query(principal)


def _nearest_abc_periods_at_or_before(
    db: Session, period: str, principal: str = "unilever"
) -> dict[str, str]:
    """Each in-scope principal's latest classification_period <= `period`
    (a principal with no ABC run that old is absent). The classification batch
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
    return abc_periods_from_rows(batch.rows(db, *_nearest_abc_period_query(period, principal)))


def _nearest_abc_period_query(period: str, principal: str = "unilever") -> tuple[str, dict]:
    return latest_abc_period_query(principal, period)


def _cycle_abc_periods(db: Session, scope: str, lp_cycle) -> dict[str, str]:
    """The Reorder page's anchor: each principal's latest run at or before the
    LP cycle's month. The prefetched latest run IS that run unless one postdates
    the cycle month, so the capped query is asked only then."""
    latest = _latest_abc_periods(db, scope)
    if lp_cycle is None:
        return latest
    month = str(lp_cycle)[:7]
    if all(v <= month for v in latest.values()):
        return latest
    return _nearest_abc_periods_at_or_before(db, month, scope)


def _abc_periods_for(db: Session, period: str | None, scope: str) -> dict[str, str]:
    return _nearest_abc_periods_at_or_before(db, period, scope) if period is not None else _latest_abc_periods(db, scope)


def _range_pareto(db: Session, start: str, end: str, scope: str, mode: str = REAL) -> dict[str, list[dict]]:
    """Every product ranked on its net sales over the selected range, per principal
    (backend/marts.pareto: the ABC run's rules on the range's total; Del Monte ranks
    product categories, DEC-03). Each principal is ranked against its own revenue."""
    return {who: marts.pareto(db, start, end, who, mode) for who in ("unilever", "delmonte") if scope in ("all", who)}


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


# ---------------------------------------------------------------------------
# The route's own queries. Built here, not inline, so _prefetch can ask for exactly
# the statements get_dashboard will read (backend/batch.py).
# ---------------------------------------------------------------------------

def _principal_filter(scope: str) -> str:
    # `scope` is already allowlisted by normalize_principal (the literal 'unilever'
    # or 'delmonte'), which is why it can be interpolated.
    return "" if scope == "all" else f"AND pd.principal = '{scope}'"


def _lp_cycle_filter(lp_cycle) -> str:
    return CURRENT_CYCLE_CLAUSE if lp_cycle is not None else " AND 1=0"


def _product_count_query(scope: str, mode: str, lp_cycle) -> tuple[str, dict]:
    lp_src, lp_params = lp_source(mode)
    return f"""
            SELECT COUNT(*) AS product_count,
                   COUNT(*) FILTER (WHERE lr.status = 'pending') AS pending_count
            FROM {lp_src} lr
            JOIN Product_Dimension pd ON pd.product_key = lr.product_key
            WHERE {PLAN_STATUS_SQL} {_principal_filter(scope)} {_lp_cycle_filter(lp_cycle)}
        """, {"current_cycle": lp_cycle, **lp_params}


def _forecast_counts_query(scope: str, mode: str) -> tuple[str, dict]:
    fc_src, fc_params = forecast_source(mode)
    return f"""
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
            WHERE 1=1 {_principal_filter(scope)}
        """, {"mase_gate": MASE_GATE, **fc_params}


def _plan_rows_query(scope: str, mode: str, lp_cycle, abc_periods: dict[str, str]) -> tuple[str, dict]:
    lp_src, lp_params = lp_source(mode)
    # Same scope against ABC_Classification's own alias. Paired with
    # the Tier A basis at every ABC read: migration 0017 put a live 't3m' run
    # alongside 'single', so an unpinned query returns each SKU once per basis.
    abc_scope = "" if scope == "all" else f"AND ac.principal = '{scope}'"
    return f"""
                SELECT
                    ac.product_key,
                    pd.sku_code AS sku_id,
                    pd.product_name AS product_name,
                    ac.revenue_share AS revenue_share,
                    rop.ss_i AS ss_i,
                    rop.rop_i AS rop_i,
                    rop.q_i AS q_i
                FROM ABC_Classification ac
                LEFT JOIN product_dimension pd ON pd.product_key = ac.product_key
                LEFT JOIN (
                    SELECT DISTINCT ON (lr.product_key) lr.product_key, lr.ss_i, lr.rop_i, lr.q_i
                    FROM {lp_src} lr
                    WHERE {PLAN_STATUS_SQL} {_lp_cycle_filter(lp_cycle)}
                    ORDER BY lr.product_key, lr.planning_cycle_date DESC
                ) rop ON rop.product_key = ac.product_key
                WHERE {abc_period_pred("=", "ac")} AND ac.tier = 'A'
                      AND {abc_method_sql("ac")} {abc_scope}
            """, {**abc_period_params(abc_periods), "current_cycle": lp_cycle, **lp_params}


def _pending_keys_query(mode: str, lp_cycle) -> tuple[str, dict]:
    lp_src, lp_params = lp_source(mode)
    return (f"SELECT DISTINCT lr.product_key FROM {lp_src} lr WHERE lr.status = 'pending' {_lp_cycle_filter(lp_cycle)}",
            {"current_cycle": lp_cycle, **lp_params})


def _latest_forecast_date_query(mode: str) -> tuple[str, dict]:
    fc_src, fc_params = forecast_source(mode)
    return f"SELECT MAX(forecast_date) AS d FROM {fc_src}", fc_params


def _gated_rows_query(scope: str, mode: str, forecast_date) -> tuple[str, dict]:
    fc_src, fc_params = forecast_source(mode)
    return f"""
                SELECT fr.product_key, fr.forecast_date, fr.forecast_value,
                       fr.confidence_lower, fr.confidence_upper, pd.principal
                FROM {fc_src} fr
                JOIN Product_Dimension pd ON pd.product_key = fr.product_key
                WHERE fr.forecast_date = :forecast_date
                  AND fr.status = 'ok'
                  AND fr.mase < :mase_gate
                  {_principal_filter(scope)}
            """, {"forecast_date": forecast_date, "mase_gate": MASE_GATE, **fc_params}


def _scoped_forecast_count_query(scope: str, mode: str, forecast_date) -> tuple[str, dict]:
    fc_src, fc_params = forecast_source(mode)
    return f"""
                SELECT COUNT(*) FROM {fc_src} fr
                JOIN Product_Dimension pd ON pd.product_key = fr.product_key
                WHERE fr.forecast_date = :forecast_date {_principal_filter(scope)}
            """, {"forecast_date": forecast_date, **fc_params}


def _portfolio_actuals_query(mode: str, keys: list) -> tuple[str, dict]:
    # The history the forecasts were made from: five years in a preview
    # built from it, the real months otherwise (mart.sales_mart_real,
    # migration 0041 — the same rows, summed per product and month).
    if predictive_preview(mode):
        actual_sql = f"""
                SELECT calendar_month AS period, SUM(quantity_sold) AS qty
                FROM {unilever_demand(mode)}
                WHERE product_key = ANY(:keys)
                GROUP BY calendar_month
            """
    else:
        actual_sql = """
                SELECT period, SUM(pieces) AS qty
                FROM mart.sales_mart_real
                WHERE level = 'product' AND product_key = ANY(:keys)
                GROUP BY period
            """
    return actual_sql, {"keys": keys}


def _reorder_preview_query(scope: str, mode: str, lp_cycle, stock_period, abc_periods: dict[str, str]) -> tuple[str, dict]:
    rp_select, rp_select_params = _recommendation_select_one(mode)
    return rp_select + f" WHERE {PLAN_STATUS_SQL} {_principal_filter(scope)} {_lp_cycle_filter(lp_cycle)}", {
        "inv_period": stock_period,
        **abc_period_params(abc_periods),
        "current_cycle": lp_cycle,
        **rp_select_params,
    }


def _policy_rows_query(scope: str, mode: str, lp_cycle) -> tuple[str, dict]:
    lp_src, lp_params = lp_source(mode)
    fc_src, fc_params = forecast_source(mode)
    return f"""
            SELECT lr.planning_cycle_date, lr.ss_i, lr.rop_i, fr.forecast_value
            FROM {lp_src} lr
            JOIN Product_Dimension pd ON pd.product_key = lr.product_key
            JOIN {fc_src} fr
              ON fr.product_key = lr.product_key AND fr.forecast_date = lr.planning_cycle_date
            WHERE {PLAN_STATUS_SQL}
              {_lp_cycle_filter(lp_cycle)}
              {_principal_filter(scope)}
        """, {"current_cycle": lp_cycle, **lp_params, **fc_params}


def _range_periods(db: Session, period: str | None, start_period: str | None, scope: str) -> list[str]:
    """The months the page covers: the picker's exact range when its start is given,
    else the trailing 12 months ending at its end (or the latest sales month)."""
    return (
        _month_range(start_period, _resolve_sales_anchor(db, period, scope))
        if start_period is not None
        else _last_12_periods(db, period, scope)
    )


def _prefetch(db: Session, scope: str, mode: str, period: str | None, start_period: str | None) -> None:
    """Every statement get_dashboard reads, in three round trips instead of ~29
    (backend/batch.py). Each wave holds the queries whose parameters the waves
    before it settle: wave 1 needs only the request, wave 2 the LP cycle, the
    range and the counts the month-level marts name, wave 3 the product keys wave
    2 returns. A query missing here still runs, on its own, when the route asks."""
    wave1 = [
        (marts.snapshot_sql(), {}),
        current_cycle_query(scope, mode),
        forecast_generated_query(mode),
        _forecast_counts_query(scope, mode),
        _latest_forecast_date_query(mode),
        _nearest_abc_period_query(period, scope) if period is not None else _latest_abc_period_query(scope),
        _latest_abc_period_query(scope),
    ]
    # Whether 0041's marts and 0037's lp_run exist is remembered after the first
    # request; until then it is asked here, and the refresh status follows in wave 2.
    wave1.append((marts.REFRESH_STATUS_SQL, {}) if marts.present_known() else (marts.REFRESH_PRESENT_SQL, {}))
    if mode == REAL and not lp_run_present_known():
        wave1.append((LP_RUN_PRESENT_SQL, {}))
    batch.prefetch(db, wave1)

    lp_cycle = current_cycle(db, scope, mode)
    fc_at = batch.scalar(db, *forecast_generated_query(mode))
    periods = _range_periods(db, period, start_period, scope)
    range_start, range_end = periods[0], periods[-1]
    inventory_period = _latest_inventory_period(db, scope, end=range_end)
    abc_periods = _abc_periods_for(db, period, scope)
    abc_period = max(abc_periods.values()) if abc_periods else None  # the response field / gate only
    latest_forecast = batch.first(db, *_latest_forecast_date_query(mode))
    forecast_date = latest_forecast["d"] if latest_forecast else None
    rp_stock_period = opening_period(lp_cycle) if lp_cycle is not None else None
    idle_period = marts.stock_period_at_or_before(db, range_end, "unilever") if scope != "delmonte" else None

    wave2 = [
        freshness_query(lp_cycle, fc_at, scope, mode),
        _product_count_query(scope, mode, lp_cycle),
        _pending_keys_query(mode, lp_cycle),
        _reorder_preview_query(scope, mode, lp_cycle, rp_stock_period, _cycle_abc_periods(db, scope, lp_cycle)),
        _policy_rows_query(scope, mode, lp_cycle),
    ]
    wave2 += [marts.pareto_query(range_start, range_end, who, mode)
              for who in ("unilever", "delmonte") if scope in ("all", who)]
    if lp_cycle is not None:
        wave2.append(superseded_count_query(lp_cycle, scope, mode))
        if mode == REAL and lp_run_present(db):
            wave2.append(stored_run_query(lp_cycle, scope))
    wave2 += [(STOCK_COUNTS_SQL, {"count_period": p}) for p in {inventory_period, rp_stock_period} if p]
    if abc_period is not None:
        wave2.append(_plan_rows_query(scope, mode, lp_cycle, abc_periods))
    if forecast_date is not None:
        wave2 += [_gated_rows_query(scope, mode, forecast_date),
                  _scoped_forecast_count_query(scope, mode, forecast_date)]
    if scope != "delmonte":
        wave2.append(marts.accuracy_summary_query(range_start, range_end))
    if idle_period is not None:
        wave2 += [marts.idle_head_query(idle_period), marts.idle_items_query(idle_period, 10)]
    if marts.present(db):
        wave2.append((marts.REFRESH_STATUS_SQL, {}))
    batch.prefetch(db, wave2)

    wave3 = []
    if abc_period is not None and inventory_period is not None:
        plan = batch.rows(db, *_plan_rows_query(scope, mode, lp_cycle, abc_periods))
        keys = [int(r["product_key"]) for r in plan]
        if keys:
            wave3.append(marts.stock_pieces_query(inventory_period, keys))
    if inventory_period is not None:
        ranked = _range_pareto(db, range_start, range_end, scope, mode)
        class_of = {r["product_key"]: r["class"] for rows in ranked.values() for r in rows}
        if class_of:
            wave3.append(marts.stock_status_query(inventory_period, list(class_of)))
    if forecast_date is not None:
        gated = batch.rows(db, *_gated_rows_query(scope, mode, forecast_date))
        if gated:
            wave3.append(_portfolio_actuals_query(mode, sorted({r["product_key"] for r in gated})))
    batch.prefetch(db, wave3)


@router.get("")
@cached("GET /dashboard")
def get_dashboard(
    period: str | None = Query(
        None,
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
        description=(
            "'YYYY-MM'. The shared date-range picker's applied end month/year. "
            "Anchors the sales/stock trend window kpis.sales / sales_vs_stock "
            "are computed over (a fixed trailing 12 months when start_period "
            "is omitted, or the end of the exact range when it's given; "
            "kpis.weeks_of_cover reads the stock count at it), AND is used as an exact "
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
    current_user: TokenPayload = Depends(require_permission("dashboard.view")),
):
    # Both principals again (2026-09-17) — see backend/principals.py.
    # normalize_principal() maps None/'all' -> None and validates the rest;
    # this file's helpers take the literal string 'all' rather than None,
    # so it is re-widened to 'all' here and passed down explicitly.
    scope = normalize_principal(principal) or "all"
    # Every statement below, fetched up front in three round trips.
    _prefetch(db, scope, mode, period, start_period)

    # ---- ORIGINAL FIELDS (unchanged) ----------------------------------

    # The LP's CURRENT cycle only (2026-09-23, backend/lp_cycle.py). This
    # counted every pending row regardless of cycle, so it read 429 — 250
    # current rows plus 179 leftovers from 33 runs going back to 2023-05 —
    # under a card captioned "awaiting a decision". Resolved once here and
    # reused by every LP read below so they can never disagree about which
    # cycle the page is showing.
    lp_freshness_info = lp_freshness(db, scope, mode)
    lp_cycle = current_cycle(db, scope, mode)
    lp_run = stored_run(db, lp_cycle, scope, mode)
    # The LP's rows and the forecasts: the stored tables, or in preview with
    # built outputs the five-year what-if's (backend/data_mode.py). Every
    # predictive and prescriptive read below goes through lp_source() and
    # forecast_source(), inside the _*_query builders above.

    reco_row = batch.first(db, *_product_count_query(scope, mode, lp_cycle))
    product_count = int(reco_row["product_count"])

    forecast_row = batch.first(db, *_forecast_counts_query(scope, mode))
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

    periods = _range_periods(db, period, start_period, scope)
    sales_by_period = _sales_by_period(db, periods, scope, mode)
    not_real_sales = _not_real_sales_months(db, periods, scope, mode)
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
    # The same card two ways (Technical Adviser, 2026-10: every card answers for
    # the selected range): the range's total, cumulative over every month with
    # real sales in it, and the snapshot at its end — kpis.sales itself, the
    # last month with real sales. Pieces only where the unit is confirmed
    # (Unilever; Del Monte's sell-out quantity unit is not).
    range_months = [p for p in periods if sales_by_period.get(p) is not None]
    range_missing = [p for p in periods if sales_by_period.get(p) is None]
    pieces_by_period = (
        marts.pieces_by_period(db, periods, "unilever", mode) if scope == "unilever" else {p: None for p in periods}
    )
    range_pieces = [pieces_by_period[p] for p in range_months if pieces_by_period.get(p) is not None]
    sales_cumulative = {
        "value": round(sum(sales_by_period[p] for p in range_months), 2) if range_months else None,
        "pieces": round(sum(range_pieces), 2) if range_pieces and len(range_pieces) == len(range_months) else None,
        "start_period": periods[0],
        "end_period": periods[-1],
        "label": marts.range_label(periods[0], periods[-1]),
        "months_in_range": len(periods),
        "months_with_data": len(range_months),
        "missing_months": range_missing,
        # Months of the total that are not SSM's own data (filled or generated rows,
        # counted since 2026-10-11): the card says how many.
        "synthetic_months": [p for p in range_months if p in not_real_sales],
        "blocked_reason": None if range_months else sales_blocked_reason,
    }
    sales_snapshot = {
        "value": _to_float(sales),
        "pieces": pieces_by_period.get(current_period) if sales is not None else None,
        "period": current_period,
        "label": marts.month_label(current_period),
        "is_range_end": current_period == periods[-1],
        "blocked_reason": sales_blocked_reason,
    }
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
    dm_tax_inclusive = marts.tax_inclusive_months(db)

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
        # The basis year's sales over the same calendar months as ytd (Jan-Feb
        # 2025 against Jan-Feb 2026): the card's like-for-like year-over-year.
        "prior_ytd_sales": None, "prior_ytd_months": 0,
        # The latest month with sales and the 12 months up to it (kpi_trend's
        # shape): the annual card's "latest month", fixed like the rest of it.
        "latest_sales": None, "trend": None,
        "levels": [], "vat_basis": None, "blocked_reason": None,
        # analytics/allocation.py: the basis is the calendar year before the
        # planning month (the month after the latest sales month), in pesos
        # here (Del Monte has no pieces); default_pct is the placeholder level.
        "planning_month": None, "allocation_year": None,
        "unit": "pesos", "default_pct": ALLOCATION_DEFAULT_PCT,
    }
    if scope == "all":
        allocation["blocked_reason"] = (
            "Allocations are set per principal, so they are not combined — "
            "pick one principal to compare its sales with its allocation."
        )
    elif latest_by_principal.get(scope) is None:
        allocation["blocked_reason"] = f"No sales rows for {_scope_label(scope)} at all."
    else:
        # The card does NOT follow the date range (Audrey, 2026-10-09): the
        # allocation is the year being planned — the planning month is the
        # one after the latest sales month — and its basis is ONE previous
        # calendar year, whatever the range's length (a 2-5 year range still
        # reads only the year before). It reverses 0a0756f, which moved the
        # year with the range's end. Sales so far run Jan to the latest month
        # in the allocation year; a January plan (latest data in December)
        # has none yet, and the card shows the allocation alone.
        latest_month = latest_by_principal[scope]
        planning_month = planning_month_after(latest_month)
        allocation_year = int(planning_month[:4])
        basis_year = allocation_basis_year(planning_month)
        basis_periods = [f"{basis_year:04d}-{m:02d}" for m in range(1, 13)]
        ytd_periods = (
            [f"{allocation_year:04d}-{m:02d}" for m in range(1, int(latest_month[5:7]) + 1)]
            if int(latest_month[:4]) == allocation_year else []
        )
        # Reuse the months the page already summed (same scope, same mode),
        # and fetch only the rest in ONE call — basis and YTD are disjoint.
        missing = [p for p in basis_periods + ytd_periods if p not in sales_by_period]
        by_period = {**sales_by_period, **(_sales_by_period(db, missing, scope, mode) if missing else {})}
        basis_values = [by_period[p] for p in basis_periods if by_period.get(p) is not None]
        ytd_values = [by_period[p] for p in ytd_periods if by_period.get(p) is not None]
        # The same calendar months a year earlier, from the basis year's own
        # months (already fetched): Jan-Feb 2025 for Jan-Feb 2026.
        prior_values = [
            by_period[p] for p in basis_periods[:len(ytd_periods)] if by_period.get(p) is not None
        ]
        basis_sales = sum(basis_values) if basis_values else None
        allocation["basis_year"] = basis_year
        allocation["latest_month"] = latest_month
        allocation["planning_month"] = planning_month
        allocation["allocation_year"] = allocation_year
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
            basis_months = len(basis_values)
            allocation.update({
                "basis_sales": round(basis_sales, 2),
                # 12 real months make a true calendar-year basis; fewer and
                # the card must say the basis is partial, not imply a year.
                "basis_months": basis_months,
                "ytd_sales": round(ytd_sales, 2) if ytd_sales is not None else None,
                "ytd_months": len(ytd_values),
                "prior_ytd_sales": round(sum(prior_values), 2) if prior_values else None,
                "prior_ytd_months": len(prior_values),
                "latest_sales": (
                    round(by_period[latest_month], 2) if by_period.get(latest_month) is not None else None
                ),
                "trend": kpi_trend(
                    {
                        p: by_period.get(p)
                        for p in sorted(q for q in set(basis_periods + ytd_periods) if q <= latest_month)[-12:]
                    },
                    latest_month,
                ),
                # monthly = an average month of the basis x pct, and annual
                # only when the basis IS a year (null otherwise; the footnote
                # already calls the basis partial) — analytics/allocation.py's
                # allocation_levels, see its docstring for why.
                "levels": allocation_levels(basis_sales, unit="pesos", basis_months=basis_months),
                # The tax basis the pesos above are on (see vat_note's sources),
                # naming any Del Monte month in the basis or YTD recorded with tax.
                "vat_basis": (
                    "selling price, VAT-inclusive" if scope == "unilever"
                    else "selling price, ex-VAT" + _dm_tax_exception(basis_periods + ytd_periods)
                ),
            })

    # ---- kpis.soh_value / sales_vs_stock.stock_on_hand ----------------

    # The stock AT THE RANGE'S END (2026-10-04, the Technical Adviser's "every
    # card answers for the selected range"): the latest real count whose month
    # is on or before the range's last month. It used to be the latest count
    # overall whatever the range (2026-10-03), which the picker can never reach
    # (its ceiling is the last sales month, the count after it is the next
    # month's). Weeks of cover reads the same count (2026-10-04, DEC-36).
    range_end = periods[-1]
    inventory_period = _latest_inventory_period(db, scope, end=range_end)
    soh_periods = sorted(set(periods) | ({inventory_period} if inventory_period else set()))
    # The chart's stock line. Under 'all' only months where both principals
    # have stock (_soh_value_by_period).
    soh_by_period = _soh_value_by_period(db, soh_periods, scope)
    # The card and its sparkline describe the principals that actually have
    # stock at that count. Under 'all' at 2026-02 that is Unilever alone, and the
    # card says so (kpis.soh_coverage) instead of going blank because Del
    # Monte's last count before it is 2025-12.
    stock_coverage = _stock_valuation_coverage(db, inventory_period, scope)
    card_scope = stock_coverage[0] if len(stock_coverage) == 1 else scope
    soh_card_by_period = (
        soh_by_period if card_scope == scope else _soh_value_by_period(db, soh_periods, card_scope)
    )
    soh_value = soh_card_by_period.get(inventory_period) if inventory_period is not None else None
    # The day each count was taken (Audrey's stock_count_date fields): the
    # chart's points on the chart's scope, the card's on the card's principals.
    stock_count_dates = _stock_count_dates(db, soh_periods, scope)
    soh_count_date = (
        None if inventory_period is None
        else stock_count_dates.get(inventory_period) if card_scope == scope
        else _stock_count_dates(db, [inventory_period], card_scope).get(inventory_period)
    )
    # The count the stock card and the safety-stock card are read at, and when
    # it was counted; the order plan reads the count that opens its cycle
    # (reorder_preview below, GET /recommendations).
    latest_stock_counts = stock_counts(
        db, inventory_period, stock_coverage or ([] if scope == "all" else [scope]),
    )
    if inventory_period is None:
        soh_value_blocked_reason = (
            f"No stock count for {_scope_label(scope)} on or before {marts.month_label(range_end)}."
        )
    elif not UNILEVER_SOH_UNIT_CONFIRMED:
        soh_value_blocked_reason = _UNILEVER_SOH_UNIT_UNCONFIRMED_REASON
    elif soh_value is None:
        soh_value_blocked_reason = (
            f"No stock valuation recorded for {_scope_label(scope)} in the {inventory_period} count."
        )
    else:
        soh_value_blocked_reason = None
    soh_snapshot = {
        "value": _to_float(soh_value),
        # Pieces only for Unilever: Del Monte's stock files carry no pack size.
        "pieces": marts.stock_pieces_at(db, inventory_period, card_scope) if soh_value is not None else None,
        "period": inventory_period,
        "count_date": soh_count_date,
        "label": marts.month_label(inventory_period),
        "is_range_end": inventory_period == range_end,
        "pesos_basis": marts.PESOS_BASIS_LABEL["last_purchase_price"],
        "pieces_note": (None if card_scope == "unilever"
                        else "pesos only: Del Monte's stock files have no pack size"),
        "blocked_reason": soh_value_blocked_reason,
    }
    # The card keeps the range-end count even when the team flagged it (Yuan,
    # 2026-10-04) and says so: "Counted 2 Mar 2026: unusually high (₱46.6M),
    # accepted pending SSM confirmation" (backend/data_notes.flagged_count_note),
    # one note per flagged principal on the card.
    count_notes = []
    if inventory_period is not None and soh_value is not None:
        card_principals = stock_coverage or ([] if scope == "all" else [scope])
        for who in card_principals:
            own = marts.stock_by_period(db, [inventory_period], who).get(inventory_period)
            note = flagged_count_note(
                who, inventory_period, own, marts.neighbour_counts(db, inventory_period, who),
                _stock_count_dates(db, [inventory_period], who).get(inventory_period),
            )
            if note:
                count_notes.append(f"{_PRINCIPAL_LABELS[who]}: {note}" if len(card_principals) > 1 else note)
    soh_count_note = " · ".join(count_notes) or None
    soh_snapshot["note"] = soh_count_note

    # ---- kpis.safety_stock_rate ----------------------------------------

    # The cohort is a stored ABC run: the nearest real ABC_Classification run
    # AT OR BEFORE the range's end month (_nearest_abc_period_at_or_before) —
    # the Tier A the LP plans — named on the card (safety_stock_exposure.
    # tier_a_period). The ABC ring above it ranks the range itself.
    abc_periods = _abc_periods_for(db, period, scope)
    abc_period = max(abc_periods.values()) if abc_periods else None  # the response field / gate only
    # The LP's safety stock belongs to its current cycle; it is compared only
    # with counts from the one that opens that cycle onward. An earlier count
    # (a range ending before the plan's opening count) is not judged against a
    # later plan's safety stock.
    lp_opening_period = opening_period(lp_cycle) if lp_cycle is not None else None
    # A range ending before that count (Option A, Audrey 2026-10-08): the card
    # does not go blank. Like the pending-reorder card, it reads the current
    # plan — the plan's own opening count and the ABC run at or before it —
    # and says so (safety_stock_exposure.pinned_to_plan), instead of
    # comparing an earlier count with a later plan's safety stock.
    ss_pinned_to_plan = (
        lp_opening_period is not None and inventory_period is not None and inventory_period < lp_opening_period
    )
    ss_stock_period = inventory_period
    if ss_pinned_to_plan:
        ss_stock_period = _latest_inventory_period(db, scope, end=lp_opening_period)
        abc_periods = _nearest_abc_periods_at_or_before(db, lp_opening_period, scope)
        abc_period = max(abc_periods.values()) if abc_periods else None
    safety_stock_rate = None
    safety_stock_rate_blocked_reason = f"ABC_Classification has no rows for {_scope_label(scope)} yet."
    ss_rows: list = []
    comparable: list = []
    if abc_period is not None:
        # current_stock is PIECES (mart.inventory_mart, the same cases x pack
        # size + loose rule as backend/stock_units.py), the unit of ss_i. ss_i,
        # rop_i and q_i are pinned to the LP's current cycle, so a
        # three-year-old pending row can't supply them.
        plan_rows = batch.rows(db, *_plan_rows_query(scope, mode, lp_cycle, abc_periods))
        stock_at_count = marts.stock_pieces_by_product(
            db, ss_stock_period, [int(r["product_key"]) for r in plan_rows]
        )
        ss_rows = [{**r, "current_stock": stock_at_count.get(int(r["product_key"]))} for r in plan_rows]
        # Only when the plan's own count is missing too (pinning found none
        # at or after the plan opens): then nothing is compared.
        count_before_plan = (
            lp_opening_period is not None and ss_stock_period is not None and ss_stock_period < lp_opening_period
        )
        comparable = [] if count_before_plan else [
            r for r in ss_rows
            if r["current_stock"] is not None and r["ss_i"] is not None
        ]
        if comparable:
            at_or_above = sum(1 for r in comparable if float(r["current_stock"]) >= float(r["ss_i"]))
            safety_stock_rate = round(at_or_above / len(comparable), 4)
            safety_stock_rate_blocked_reason = None
        elif count_before_plan:
            safety_stock_rate_blocked_reason = (
                f"The stock at this range's end was counted for {marts.month_label(ss_stock_period)}, before the "
                f"count the {marts.month_label(str(lp_cycle)[:7])} plan starts from "
                f"({marts.month_label(lp_opening_period)}); its safety stock is not compared with an earlier count."
            )
        else:
            # Shown on the card as is, so it names what a planner sees, not
            # table names. The LP has never planned Del Monte (no SKU-level
            # sales to forecast), which is the usual reason under that filter.
            safety_stock_rate_blocked_reason = (
                "The LP does not plan Del Monte, so it has no safety stock to compare against."
                if scope == "delmonte"
                else "No Category A SKU has both a stock record and a safety stock in the LP's current cycle."
            )
    if mode == PREVIEW and period is not None and abc_period is None:
        window = placeholder_window(db)
        if window and period >= window["start"]:
            safety_stock_rate_blocked_reason = (
                f"{period} is a placeholder month. Safety stock belongs to the LP's current planning "
                f"cycle, not to a past month — pick an end month from {window['first_real_month']} on."
            )

    # ---- safety_stock_exposure (band 2 headline) --------------------------
    # Same `comparable` rows as the rate above, so the headline and the KPI
    # card can never disagree about which products were measurable.
    if abc_period is not None and comparable:
        below = [r for r in comparable if float(r["current_stock"]) < float(r["ss_i"])]
        below_share = sum(float(r.get("revenue_share") or 0) for r in below)

        # The products behind the count, most revenue first: the list a reader
        # opens from "N below safety stock" (Technical Adviser, 2026-10-02:
        # detail one click behind every aggregate). Built from `below` itself,
        # so the list and the count are the same rows. Pieces throughout.
        # (Audrey's field, group7/UIFixes_Audrey 3825d02.)
        def _pieces(value):
            return round(float(value), 2) if value is not None else None

        below_items = [
            {
                "sku_id": r.get("sku_id"),
                "product_name": r.get("product_name"),
                "current_stock": _pieces(r["current_stock"]),
                "ss_i": _pieces(r["ss_i"]),
                "short_by": _pieces(float(r["ss_i"]) - float(r["current_stock"])),
                "target_stock": _pieces(r.get("rop_i")),
                "order_qty": _pieces(r.get("q_i")),
                "revenue_share": float(r["revenue_share"]) if r.get("revenue_share") is not None else None,
            }
            for r in sorted(below, key=lambda row: -float(row.get("revenue_share") or 0))
        ]
        safety_stock_exposure = {
            "tier_a_count": len(ss_rows),
            "comparable_count": len(comparable),
            "below_count": len(below),
            "below_revenue_share": round(below_share, 4),
            "below_items": below_items,
            "blocked_reason": None,
        }
    else:
        safety_stock_exposure = {
            "tier_a_count": len(ss_rows) if abc_period is not None else 0,
            "comparable_count": 0,
            "below_count": None,
            "below_revenue_share": None,
            "below_items": [],
            "blocked_reason": safety_stock_rate_blocked_reason,
        }
    # The count the stock is read at (the range's end) and when it was taken,
    # the Tier A run the cohort comes from, and the count the plan opens from.
    safety_stock_exposure["stock_period"] = ss_stock_period
    safety_stock_exposure["stock_counts"] = (
        stock_counts(db, ss_stock_period, stock_coverage or ([] if scope == "all" else [scope]))
        if ss_pinned_to_plan else latest_stock_counts
    )
    safety_stock_exposure["tier_a_period"] = abc_period
    # Per principal ({display name: 'YYYY-MM'}); tier_a_period above is unchanged.
    safety_stock_exposure["tier_a_periods"] = tier_a_periods(abc_periods)
    safety_stock_exposure["plan_opening_period"] = lp_opening_period
    # True when the range ends before the plan's count: the figures are the
    # current plan's, not the range's (the card says it does not follow it).
    safety_stock_exposure["pinned_to_plan"] = bool(ss_pinned_to_plan)

    # ---- kpis.weeks_of_cover ---------------------------------------------
    # current stock on hand / average weekly demand — see the docstring
    # section above for the full reasoning. The stock side is the stock
    # card's own count, the one at the range's end (DEC-36), and the sales
    # side is always the 12 months of sales ending at that count's month, or
    # at the last month with sales before it — never the picker's months.
    # Until 2026-09-29 it averaged the picker's months,
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
    def cover_at(count_period: str | None) -> dict:
        """Weeks of cover at one count: that count's stock / the average weekly
        sales of the 12 months ending at it (or at the last month with sales
        before it), on the principals the count covers."""
        coverage = _stock_valuation_coverage(db, count_period, scope)
        cover_scope = coverage[0] if len(coverage) == 1 else scope
        stock = (_soh_value_by_period(db, [count_period], cover_scope).get(count_period)
                 if count_period is not None else None)
        cover_latest_sales = (
            max(filter(None, latest_by_principal.values()), default=None)
            if cover_scope == "all" else latest_by_principal.get(cover_scope)
        )
        cover_end = (
            min(cover_latest_sales, count_period)
            if cover_latest_sales is not None and count_period is not None
            else cover_latest_sales
        )
        cover_periods: list[str] = []
        if cover_end is not None:
            end_index = int(cover_end[:4]) * 12 + int(cover_end[5:7]) - 1
            # COVER_KPI_HISTORY_MONTHS (12) ending at the stock month: the
            # portfolio KPI's window, which the range picker does not move.
            start_index = end_index - (COVER_KPI_HISTORY_MONTHS - 1)
            cover_periods = _month_range(f"{start_index // 12:04d}-{start_index % 12 + 1:02d}", cover_end)
        # The page's own sums are reused where they are the same scope's; only
        # the months they lack are fetched, in one call.
        # Unilever: stock and sales are both in PIECES. Stock was valued at purchase cost and
        # sales at selling price, so the peso ratio understated cover by the margin (freeze
        # package 1a: 3.0285 -> 3.1321 weeks). Del Monte has no pack size, so no pieces: its
        # ratio stays in pesos (stock at cost / sales at selling price) and says so in `basis`.
        in_pieces = cover_scope == "unilever"
        if in_pieces:
            cover_demand = marts.pieces_by_period(db, cover_periods, "unilever", mode)
            stock_pieces = marts.stock_pieces_at(db, count_period, "unilever")
        else:
            cover_known = sales_by_period if cover_scope == scope else {}
            cover_missing = [p for p in cover_periods if p not in cover_known]
            cover_fetched = _sales_by_period(db, cover_missing, cover_scope, mode) if cover_missing else {}
            cover_demand = {p: cover_known[p] if p in cover_known else cover_fetched.get(p) for p in cover_periods}
            stock_pieces = None
        stock_reason = (
            f"No stock count for {_scope_label(scope)} at all." if count_period is None
            else _UNILEVER_SOH_UNIT_UNCONFIRMED_REASON if not UNILEVER_SOH_UNIT_CONFIRMED
            else f"No stock valuation for {_scope_label(scope)} in the {count_period} count."
        )
        weekly_demand, demand_reason = _avg_weekly_demand(cover_demand)
        value, reason = _weeks_of_cover(
            (stock_pieces if in_pieces else stock) if UNILEVER_SOH_UNIT_CONFIRMED else None, stock_reason,
            weekly_demand, demand_reason)
        return {
            "value": value,
            "blocked_reason": reason,
            # The principals this ratio describes, which under 'all' is NOT
            # necessarily both — see _stock_valuation_coverage.
            "coverage": coverage,
            # Months that actually carried a demand figure — a 12-month window
            # with 6 real months averages over 6, and the card can say so.
            "months_used": sum(1 for v in cover_demand.values() if v is not None),
            "stock_period": count_period,
            "stock_value": _to_float(stock),
            "basis": "pieces" if in_pieces else "pesos",
            "stock_count_date": (_stock_count_dates(db, [count_period], cover_scope).get(count_period)
                                 if count_period is not None else None),
            # The 12 months the average weekly sales came from — fixed to the
            # stock count, never the picker's range.
            "sales_window": {"start": cover_periods[0], "end": cover_periods[-1]} if cover_periods else None,
            # Where the stock and the sales come from different places (data_notes.COVER_CAVEATS).
            "caveat": " · ".join(COVER_CAVEATS[p] for p in coverage if p in COVER_CAVEATS) or None,
        }

    # The stock card's own count — the one at the range's end — over the 12
    # months of sales ending at it (Yuan, 2026-10-04, DEC-36): the card's value
    # and its cover line name one count. Supersedes the 2026-09-29 rule (the
    # latest count, whatever the range); the denominator still never follows
    # the range's width, so one count always gives the same weeks.
    # weeks_of_cover_range_end is the same object, under the name it had first.
    weeks_of_cover = cover_at(inventory_period)
    weeks_of_cover_range_end = weeks_of_cover

    # ---- sales_vs_stock series -------------------------------------------

    received_by_period = _received_by_period(db, periods, scope)
    estimated_received = _estimated_received_by_period(db, periods, scope)
    # Preview's placeholder sales months (Unilever, before the first real month).
    placeholder = placeholder_window(db) if mode == PREVIEW and scope in ("all", "unilever") else None

    # Coverage hole H1 (reports/diagnostics/coverage_check_2026-10-03.md) used to fill sales,
    # stock and returns gaps from mart's filled/generated rows. Retired 2026-10-16 (rule 2,
    # B1): every one of those rows traces to the old synthetic_v2 family, which `demo.*`
    # superseded as the single display source for anything generated — so
    # estimated_sales_by_period and estimated_stock_by_period now always return {} and
    # flow_by_period never estimates 'returns'. sales_estimated / stock_on_hand_estimated /
    # returns_estimated below stay in the response shape (None when there's nothing to
    # estimate) so the frontend doesn't need a contract change. Sales still shows demo.*'s
    # 2021-22 back-cast in preview, but through the plain `sales` field (sales_by_period
    # widens 'real' to include preview_placeholder rows) — not through sales_estimated.
    # Stock and returns have no demo.* analog wired into this series at all.
    in_scope = [who for who in ("unilever", "delmonte") if scope in ("all", who)]

    def by_principal(estimate_fn, real_fn) -> dict:
        out = {}
        for who in in_scope:
            out[who] = estimate_fn(who)
            out[f"{who}_real"] = real_fn(who) if scope == "all" else {}
        return out

    sales_estimated = _estimate_points(periods, sales_by_period, by_principal(
        lambda who: marts.estimated_sales_by_period(db, periods, who, mode),
        lambda who: marts.sales_by_period(db, periods, who, mode),
    ), scope)
    stock_estimated = _estimate_points(periods, soh_by_period, by_principal(
        lambda who: marts.estimated_stock_by_period(db, periods, who, mode),
        lambda who: marts.stock_by_period(db, periods, who),
    ), scope)
    returns_flows = {who: marts.flow_by_period(db, periods, who, "returns") for who in in_scope}
    returns_real = _combine_principal_sums(
        periods,
        {p: v["real"] for p, v in returns_flows.get("unilever", {}).items()} or {p: None for p in periods},
        {p: v["real"] for p, v in returns_flows.get("delmonte", {}).items()} or {p: None for p in periods},
        scope,
    )
    returns_estimated = _estimate_points(periods, returns_real, {
        **{who: {p: {"value": v["estimated"], "kind": v["estimated_kind"], "source": v["estimated_source"]}
                 for p, v in returns_flows[who].items() if v["estimated"] is not None} for who in in_scope},
        **{f"{who}_real": ({p: v["real"] for p, v in returns_flows[who].items()} if scope == "all" else {})
           for who in in_scope},
    }, scope)

    sales_vs_stock = []
    for p in periods:
        point = {
            "period": p,
            "sales": sales_by_period[p],
            "stock_on_hand": soh_by_period.get(p),
            # The day this point's stock was counted ('YYYY-MM-DD'), or None
            # when there is no count or (under 'all') two principals counted on
            # different days — _stock_count_dates. (Audrey's field.)
            "stock_count_date": stock_count_dates.get(p) if soh_by_period.get(p) is not None else None,
            "received": received_by_period.get(p),
            "received_estimated": estimated_received[p]["value"],
            "received_estimated_negative_skus": estimated_received[p]["negative_skus"],
            "sales_estimated": round(sales_estimated[p]["value"], 2) if p in sales_estimated else None,
            "sales_estimated_kind": sales_estimated[p]["kind"] if p in sales_estimated else None,
            "stock_on_hand_estimated": round(stock_estimated[p]["value"], 2) if p in stock_estimated else None,
            "stock_on_hand_estimated_kind": stock_estimated[p]["kind"] if p in stock_estimated else None,
            "returns": returns_real.get(p),
            "returns_estimated": round(returns_estimated[p]["value"], 2) if p in returns_estimated else None,
            "returns_estimated_kind": returns_estimated[p]["kind"] if p in returns_estimated else None,
        }
        point["provenance"] = _point_provenance(
            point, bool(placeholder and placeholder["start"] <= p <= placeholder["end"]) or p in not_real_sales
        )
        # Why a month has no sales value (backend/series_gaps.py): the series is never zero-filled, a month with
        # no rows for the whole scope is null, and now says so. Added only where there is a reason; a point with a
        # value, or one that is also an estimate, carries no key.
        if point["sales"] is None and point["sales_estimated"] is None:
            point["sales_reason"] = REASON_NO_DATA_BEFORE_2023 if p < "2023-01" else REASON_NOT_COLLECTED
        sales_vs_stock.append(point)

    # The tax basis of the chart's flow lines, for its legend and tooltip.
    # Purchases are put on the sales line's basis per principal
    # (_received_by_period), so one phrase per line is true. Under 'all' the
    # combined pesos mix both bases and vat_note says so instead. Sales read
    # "selling price, ..." (Audrey, 3 Oct 2026 analysis); returns are the
    # returns file's Net Amount as recorded.
    sales_vs_stock_basis = (
        {"sales": "selling price, VAT-inclusive", "received": "incl. VAT"} if scope == "unilever"
        else {"sales": "selling price, ex-VAT" + _dm_tax_exception(periods), "received": "ex-VAT"} if scope == "delmonte"
        else {"sales": None, "received": None}
    )
    sales_vs_stock_basis["stock_on_hand"] = marts.PESOS_BASIS_LABEL["last_purchase_price"]
    sales_vs_stock_basis["returns"] = marts.PESOS_BASIS_LABEL["net_amount_as_recorded"]

    # Stock counts the team has reviewed and judged unusual (backend/
    # data_notes.py), for the chart's own principals: marked on the chart,
    # passed over as a comparison point. Only points the chart actually
    # draws are listed — under 'all' a month without both principals' counts
    # has no point to mark.
    chart_unusual_stock = {
        p: reason for p, reason in unusual_stock_snapshots(scope, periods).items()
        if soh_by_period.get(p) is not None
    }
    stock_on_hand_flags = [{"period": p, "reason": chart_unusual_stock[p]} for p in sorted(chart_unusual_stock)]

    # ---- chart story fields (backend/chart_insights.py) -----------------
    # The hero chart's one-sentence takeaway + its peak/low sales months,
    # and each value card's sparkline points + month-over-month delta —
    # all computed from the SAME dicts the chart/cards above read, so a
    # sentence can never disagree with the plot under it.
    svs_insight = sales_vs_stock_insight(sales_vs_stock, chart_unusual_stock)
    sales_trend = kpi_trend(sales_by_period, current_period)
    # The card's own series, so its sparkline and delta cover the same
    # principals as its value — and the same principals' unusual counts,
    # which the delta skips: Mar 2026 vs Unilever's Feb 2026 outlier read
    # "−51.3%"; against Jan 2026, the last ordinary count, it is −6.7%.
    soh_trend = kpi_trend(
        {p: soh_card_by_period.get(p) for p in soh_periods}, inventory_period,
        unusual=unusual_stock_snapshots(card_scope, soh_periods),
    )

    # ---- abc_mix: the range's Pareto ----------------------------------
    # Ranked on the SELECTED RANGE (2026-10-04, the Technical Adviser's main
    # request), not on a stored single-month run: each product's (Del Monte:
    # category's) net sales over the range, with the ABC run's own rules
    # (backend/marts.pareto). Each principal is ranked against its own
    # revenue, so under 'all' with both ranked the counts stay and the shares
    # are withheld (two principals' shares are fractions of two totals:
    # summed, Class A came to ~151% for 2025-12, 2026-09-29).
    range_start = periods[0]
    ranked = _range_pareto(db, range_start, range_end, scope, mode)
    abc_coverage = sorted(who for who, rows in ranked.items() if rows)
    ranked_rows = [r for rows in ranked.values() for r in rows]
    ranked_total = sum(r["revenue"] for r in ranked_rows)
    abc_mix: list[dict] = []
    for tier in ("A", "B", "C"):
        members = [r for r in ranked_rows if r["class"] == tier]
        if not members:
            continue
        revenue = sum(r["revenue"] for r in members)
        abc_mix.append({
            "tier": tier,
            "count": len(members),
            "revenue_share_pct": round(revenue / ranked_total * 100, 2) if ranked_total > 0 else None,
            "revenue": round(revenue, 2),
        })
    if len(abc_coverage) > 1:
        for row in abc_mix:
            row["revenue_share_pct"] = None
            row["revenue"] = None

    # ---- abc_revenue (donut centre) -------------------------------------
    # `total` is the range's NET sales (returns included, the sales card's own
    # sum); `ranked_total` is what the ring's shares are shares OF — the
    # products that sold more than they took back over the range. The card
    # multiplies shares by ranked_total, never total.
    range_text = marts.range_label(range_start, range_end)
    if not abc_coverage:
        # One reason per principal in scope (B3, 2026-10-16): a principal with no real sales
        # row at all in the range (Del Monte: not collected; Unilever: nothing sold) is a
        # different cause from one with rows that never net-sold above zero, and the old
        # single message named the wrong one for Del Monte's taxonomy-break gap.
        reasons = dict.fromkeys(marts.pareto_blocked_reason(db, range_start, range_end, who, mode) for who in ranked)
        abc_revenue = {"period": range_end, "start_period": range_start, "end_period": range_end, "label": range_text,
                       "basis": "range", "total": None, "ranked_total": None,
                       "blocked_reason": " ".join(reasons)}
    elif len(abc_coverage) > 1:
        abc_revenue = {"period": range_end, "start_period": range_start, "end_period": range_end, "label": range_text,
                       "basis": "range", "total": None, "ranked_total": None,
                       "blocked_reason": "Each principal's tiers are shares of its own revenue, so they are "
                                         "not combined — pick one principal to see them."}
    else:
        revenue_scope = abc_coverage[0]
        abc_total = marts.net_sales_total(db, range_start, range_end, revenue_scope, mode)
        abc_revenue = {
            "period": range_end, "start_period": range_start, "end_period": range_end, "label": range_text,
            "basis": "range",
            "total": _to_float(abc_total),
            "ranked_total": round(ranked_total, 2),
            "blocked_reason": None,
        }

    # ---- tier_stock ----------------------------------------------------
    # Per class of the range's ranking: products by dead-stock status at the
    # count at the range's end (mart.inventory_mart's Active / Inactive flags;
    # a product flagged Inactive even once is dead stock, no row or no flag is
    # no_data — never guessed), and how many have a pending reorder in the
    # LP's current cycle (never null: 0 is a real answer here).
    tier_stock: list[dict] = []
    if ranked_rows:
        class_of = {r["product_key"]: r["class"] for r in ranked_rows}
        status_at_count = marts.stock_status_by_product(db, inventory_period, list(class_of))
        pending_keys = {int(r["product_key"]) for r in batch.rows(db, *_pending_keys_query(mode, lp_cycle))}
        buckets: dict[str, dict[str, int]] = {}
        for key, tier in class_of.items():
            b = buckets.setdefault(tier, {"in_stock": 0, "dead_stock": 0, "no_data": 0, "pending_reorder_count": 0})
            active, inactive = status_at_count.get(key, (False, False))
            if inactive:
                b["dead_stock"] += 1
            elif active:
                b["in_stock"] += 1
            else:
                b["no_data"] += 1
            if key in pending_keys:
                b["pending_reorder_count"] += 1
        tier_stock = [{"tier": tier, **counts} for tier, counts in sorted(buckets.items())]

    # ---- portfolio_forecast --------------------------------------------

    latest_forecast_date_row = batch.first(db, *_latest_forecast_date_query(mode))
    latest_forecast_date = latest_forecast_date_row["d"] if latest_forecast_date_row else None

    gated_rows: list = []
    if latest_forecast_date is not None:
        gated_rows = batch.rows(db, *_gated_rows_query(scope, mode, latest_forecast_date))

    gated_sku_count = len({r["product_key"] for r in gated_rows})
    # "No forecasts exist for this scope" and "forecasts exist but none pass
    # the gate" are different facts. Del Monte is the live case of the
    # first: Forecast_Result has no Del Monte rows at all (its Sales
    # Register is invoice-grain with no SKU column, so no SKU-level
    # forecast is run), and reporting that as a failed reliability gate
    # would imply forecasts were made and judged unreliable.
    scoped_forecast_count = 0
    if latest_forecast_date is not None and not gated_rows:
        scoped_forecast_count = batch.scalar(
            db, *_scoped_forecast_count_query(scope, mode, latest_forecast_date)
        ) or 0
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
        rows = batch.rows(db, *_portfolio_actuals_query(mode, gated_product_keys))
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

        # The portfolio band combines the SKUs' bands as a root-sum-of-
        # squares, not a sum. Each SKU's band is forecast ± 1.645 x its own
        # holdout RMSE (scripts/run_baseline_forecast.py, ~90%), so its
        # half-width is upper - forecast — the upper side, because the lower
        # one is floored at 0 per SKU. Adding the bounds assumed every SKU
        # misses as far as it can, in the same direction, in the same month:
        # 443,592-1,763,518 around 1,085,193 (±62%) for Mar 2026. If the
        # SKUs' misses are independent the spread of the total is
        # sqrt(sum of half-width²), ±159k (±15%). Independence is an
        # assumption — a seasonal swing that hits every SKU at once makes the
        # true range wider — and the card says so. The lower bound is floored
        # at 0 like each SKU's. A SKU with no band (no holdout RMSE) adds
        # nothing to it; none of the 73 gated SKUs lacks one (2026-10-01).
        forecast_buckets: dict[str, dict] = {}
        for r in gated_rows:
            d = r["forecast_date"]
            p = f"{d.year:04d}-{d.month:02d}" if hasattr(d, "year") else str(d)[:7]
            b = forecast_buckets.setdefault(p, {"forecast": 0.0, "half_width_sq": 0.0, "band_seen": False})
            value = float(r["forecast_value"] or 0)
            b["forecast"] += value
            if r["confidence_upper"] is not None:
                b["half_width_sq"] += (float(r["confidence_upper"]) - value) ** 2
                b["band_seen"] = True

        for p, b in forecast_buckets.items():
            entry = series_by_period.setdefault(
                p, {"period": p, "actual": None, "forecast": None, "confidence_lower": None, "confidence_upper": None}
            )
            entry["forecast"] = b["forecast"]
            half_width = b["half_width_sq"] ** 0.5
            entry["confidence_lower"] = round(max(0.0, b["forecast"] - half_width), 2) if b["band_seen"] else None
            entry["confidence_upper"] = round(b["forecast"] + half_width, 2) if b["band_seen"] else None

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
    # Both anchors are bound, not inlined, so reorder_preview resolves them
    # under the SAME scope as the rows it shows. The stock anchor is the
    # count that opens the LP's cycle (2026-10-03), the one the plan was made
    # from and GET /recommendations shows, not the stock card's latest. The
    # ABC anchor is the LP cycle's month (the Reorder page's rule), deliberately
    # not the page's `abc_period` — that one is rewound to the picker's applied
    # end month, and reorder_preview answers "order now".
    rp_stock_period = opening_period(lp_cycle) if lp_cycle is not None else None
    rp_rows = batch.rows(
        db, *_reorder_preview_query(scope, mode, lp_cycle, rp_stock_period, _cycle_abc_periods(db, scope, lp_cycle))
    )
    # The whole plan: a decided row stays in it (backend/lp_cycle.PLAN_STATUSES), so the total and the
    # count below agree with GET /recommendations after an accept. What is still open work is rp_open.
    rp_items = [_to_recommendation_item(r) for r in rp_rows]
    rp_open = [it for it in rp_items if it.status == "pending"]
    rp_stock_counts = (
        stock_counts(db, rp_stock_period, sorted({r["principal"] for r in rp_rows}), cycle=lp_cycle)
        if lp_cycle is not None else []
    )
    # Within an urgency, highest priority first — the Reorder page's own
    # ranking (revenue share x units below the reorder point). Urgency alone
    # left the order to the query, so the card showed an arbitrary five of
    # the 183 CRITICAL rows (2026-09-29).
    rp_items_sorted = sorted(
        rp_items,
        key=lambda it: (_URGENCY_RANK.get(it.urgency, 99), -(it.priority_score or 0)),
    )
    rp_open_sorted = [it for it in rp_items_sorted if it.status == "pending"]

    reorder_preview = {
        # The five to act on first: open (pending) rows only. Every count and total below is the plan
        # (one definition, as GET /recommendations); pending_* is the still-undecided part of it.
        "rows": [item.model_dump() for item in rp_open_sorted[:5]],
        "critical_count": sum(1 for it in rp_items if it.urgency == CRITICAL),
        # Below the target stock (backend/stock_status.py's LOW, URGENT on the
        # reorder page). Both names, the same number: the frontend reads
        # urgent_count; low_count is params consolidation's (2026-09-30).
        "urgent_count": sum(1 for it in rp_items if it.urgency == URGENT),
        "low_count": sum(1 for it in rp_items if it.urgency == URGENT),
        # Products whose stock can't be known: no usable pack size, no stock
        # count for their principal at this snapshot, or missing from a count
        # that does list zero-stock items (Del Monte). Missing from a Unilever
        # count reads as 0 on hand, as the LP treats it, and is ranked like
        # any other (recommendations._to_item, backend/stock_status.py).
        "no_data_count": sum(1 for it in rp_items if it.urgency == NO_DATA),
        # Whole units per row, summed over the PLAN (pending + accepted + dismissed, at q_i) — the Reorder
        # page's own total, so the two screens agree before and after a decision (they differed by 123.6
        # units 2026-09-29, and by one accepted row's pieces until 2026-10-23). pending_* is the second,
        # separately named number: what is still awaiting a decision.
        "total_order_qty": sum(whole_units(it.q_i) for it in rp_items) if rp_items else 0,
        "plan_count": len(rp_items),
        "pending_count": len(rp_open),
        "pending_order_qty": sum(whole_units(it.q_i) for it in rp_open),
        # The weights the run behind this cycle used (lp_run), else the
        # current constants; lp_weights_source says which.
        "lp_weights": (lp_run["model"]["weights"] if lp_run else {
            "cost": LP_WEIGHT_COST,
            "service_level": LP_WEIGHT_SERVICE_LEVEL,
            "storage": LP_WEIGHT_STORAGE,
        }),
        "lp_weights_source": "run" if lp_run else "defaults",
        # The count these rows' stock comes from — the one that opens the
        # cycle — and when it was counted, or why there is none
        # (backend/stock_units.stock_count_info).
        "stock_counts": rp_stock_counts,
    }

    # ---- policy_comparison (band 4: LP target stock vs SSM's 3-week policy) --
    # One row per product in the latest pending cycle that ALSO has a
    # Forecast_Result for that same month (fr.forecast_date =
    # lr.planning_cycle_date); products missing the forecast drop out of
    # both sums. Both sides are in the demand series' unit — see the
    # docstring section above for why this stays in units, not pesos.
    policy_rows = batch.rows(db, *_policy_rows_query(scope, mode, lp_cycle))
    policy_rows = [
        r for r in policy_rows
        if r["forecast_value"] is not None and r["ss_i"] is not None and r["rop_i"] is not None
    ]
    if policy_rows:
        cycle = policy_rows[0]["planning_cycle_date"]
        lp_units = sum(float(r["ss_i"]) for r in policy_rows)
        # rop_i holds the LP's per-SKU target stock since the 2026-09-30 run
        # (scripts/run_lp.py: order up to T_i = demand over review + lead
        # days + safety stock). SSM's 3 weeks is a target for ALL stock,
        # not a buffer on top of it, so target-vs-rule is the like-for-like
        # headline; safety stock alone against the rule's whole 3 weeks read
        # 35.2% "less" when the targets actually hold 18.2% more.
        target_units = sum(float(r["rop_i"]) for r in policy_rows)
        forecast_units = sum(float(r["forecast_value"]) for r in policy_rows)
        rule_units = POLICY_WEEKS * forecast_units / AVG_WEEKS_PER_MONTH
        policy_comparison = {
            "cycle_date": cycle.isoformat() if hasattr(cycle, "isoformat") else str(cycle),
            "sku_count": len(policy_rows),
            "lp_target_stock_units": round(target_units, 2),
            "lp_safety_stock_units": round(lp_units, 2),
            # What SSM's policy holds: 3 weeks of each SKU's forecast. Kept
            # under its old name too, for any caller still reading it.
            "rule_stock_units": round(rule_units, 2),
            "rule_safety_stock_units": round(rule_units, 2),
            # How much less (positive) or more (negative) stock the LP's
            # targets hold than the rule, as a percent of the rule — the
            # one-number headline IMPLEMENTATION_PLAN Phase 1.1 asks for.
            "target_vs_rule_pct": round((rule_units - target_units) / rule_units * 100, 1) if rule_units > 0 else None,
            # The targets as weeks of the same forecast, beside rule_weeks.
            "lp_target_weeks": round(target_units / (forecast_units / AVG_WEEKS_PER_MONTH), 2) if forecast_units > 0 else None,
            "skus_above_rule": sum(
                1 for r in policy_rows
                if float(r["rop_i"]) > POLICY_WEEKS * float(r["forecast_value"]) / AVG_WEEKS_PER_MONTH
            ),
            "rule_weeks": POLICY_WEEKS,
            # The window the safety stock covers, from the same placeholder
            # dict the run takes its defaults from (lp_model_info).
            "window_business_days": PLACEHOLDERS["review_days"] + PLACEHOLDERS["lead_days"],
            "inputs_are_placeholders": True,
            "blocked_reason": None,
        }
    else:
        policy_comparison = {
            "cycle_date": None,
            "sku_count": 0,
            "lp_target_stock_units": None,
            "lp_safety_stock_units": None,
            "rule_stock_units": None,
            "rule_safety_stock_units": None,
            "target_vs_rule_pct": None,
            "lp_target_weeks": None,
            "skus_above_rule": None,
            "rule_weeks": POLICY_WEEKS,
            "window_business_days": PLACEHOLDERS["review_days"] + PLACEHOLDERS["lead_days"],
            "inputs_are_placeholders": True,
            "blocked_reason": (
                f"No pending LP_Recommendation for {_scope_label(scope)} has a Forecast_Result "
                "for its own planning-cycle month, so the two policies can't be compared."
            ),
        }

    # ---- forecast_accuracy (the error card) -------------------------------
    # Every scored forecast in the range: each month from the recreated 29-month
    # backtest (Tier A the month before, the figure the team quotes) where it
    # covers the month, else from the newest stored run that forecast it
    # (backend/marts.accuracy_summary_query, summed by the database). Actuals are real sales only. Del Monte has
    # no product-level forecasts (its sales are category grain).
    if scope == "delmonte":
        forecast_accuracy = marts.accuracy_summary([], range_start, range_end, REVIEW_OVER_RUN_MONTHS)
        forecast_accuracy["blocked_reason"] = (
            "No product-level forecasts exist for Del Monte: its sales data is category grain, "
            "so no per-product forecast is made to check."
        )
    else:
        forecast_accuracy = marts.accuracy_summary_from(
            marts.accuracy_aggregates_from_query(batch.rows(db, *marts.accuracy_summary_query(range_start, range_end))),
            range_start, range_end, REVIEW_OVER_RUN_MONTHS,
        )
    forecast_accuracy["coverage"] = [] if scope == "delmonte" else ["unilever"]

    # ---- idle_stock ---------------------------------------------------------
    # Unilever only: Del Monte has no product-level real sales to show a product
    # went unsold. At Unilever's own count at the range's end.
    if scope == "delmonte":
        idle = marts.idle_stock(db, None)
        idle["blocked_reason"] = (
            "Del Monte's sales are by product category, so no product can be shown to have gone unsold."
        )
    else:
        idle = marts.idle_stock(db, marts.stock_period_at_or_before(db, range_end, "unilever"), limit=10)
    idle["window_rule_months"] = DEAD_SKU_MONTHS
    idle["coverage"] = [] if scope == "delmonte" else ["unilever"]

    mart_status = marts.status(db)

    payload = {
        "principal": scope,  # the scope this payload answers: 'all' | 'unilever' | 'delmonte'
        "period": None,
        "inventory": {
            "value": _to_float(soh_value),
            "weeks_of_cover": None,
            "policy_weeks": POLICY_WEEKS,
            # The count `value` is the stock of (2026-10-23): the same entries as kpis.stock_counts.
            "count_date": soh_count_date,
            "stock_counts": latest_stock_counts,
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
            # The sales card both ways, with the period each covers (2026-10-04):
            # the range's total over every month with real sales, and the end
            # month's snapshot (the same figure as kpis.sales / sales_period).
            "sales_cumulative": sales_cumulative,
            "sales_snapshot": sales_snapshot,
            # Stock at the count at the RANGE'S END (latest real count on or
            # before its last month), no longer the latest count overall.
            "soh_value": _to_float(soh_value),
            "soh_value_blocked_reason": soh_value_blocked_reason,
            "soh_period": inventory_period,
            # The day soh_period's stock was physically counted ('YYYY-MM-DD'):
            # Unilever's "2026-02" is the 2026-03-02 count. Null when unknown
            # (Del Monte's count day is not loaded). (Audrey's field.)
            "soh_count_date": soh_count_date,
            # Non-null when that count is one the team flagged as unusual: the card
            # keeps it and says so (data_notes.flagged_count_note).
            "soh_count_note": soh_count_note,
            "soh_snapshot": soh_snapshot,
            # [{principal, period, role: 'latest', counted_on, counted_on_note,
            #   flag, ...}] for soh_period: when the stock this card and
            # safety_stock_exposure read was counted.
            "stock_counts": latest_stock_counts,
            "soh_coverage": stock_coverage,
            "safety_stock_rate": safety_stock_rate,
            "safety_stock_rate_blocked_reason": safety_stock_rate_blocked_reason,
            # Sparkline + month-over-month delta for the two value cards
            # (backend/chart_insights.py). Points are real months only; a
            # missing month is dropped, never zero-filled. Null when the
            # scope has nothing real to plot.
            "sales_trend": sales_trend,
            "soh_trend": soh_trend,
            # {value, blocked_reason, coverage, months_used, stock_period,
            # stock_value, stock_count_date, sales_window, caveat} at the stock
            # card's own count, the range's end (DEC-36, 2026-10-04).
            "weeks_of_cover": weeks_of_cover,
            "weeks_of_cover_range_end": weeks_of_cover_range_end,
        },
        # Non-null only under 'all': the combined pesos mix Unilever's
        # VAT-inclusive amounts with Del Monte's VAT-exclusive ones, and
        # the sales card and hero chart say so from this one field.
        "vat_note": vat_note,
        # Sales against SSM's allocation rule (prior-year sales x 103/105/
        # 108% — client meeting, Sep 2026), per principal.
        "allocation": allocation,
        # Total sales per calendar year, for the Annual View card beside the
        # Sales vs Inventory chart (_annual_sales). Fixed, like allocation.
        "annual_sales": _annual_sales(db, scope, mode),
        # Which LP run the page is showing, and whether it can still be
        # trusted (backend/lp_cycle.py). Every LP-derived figure above is
        # pinned to this cycle; superseded_pending_count says how many
        # older pending rows were withheld.
        "lp": lp_freshness_info,
        "sales_vs_stock": sales_vs_stock,
        # {sales, received}: the tax basis of each flow line ('incl. VAT' /
        # 'ex-VAT'), for the chart's legend and tooltip. Null under 'all',
        # where vat_note says the combined pesos mix the two.
        "sales_vs_stock_basis": sales_vs_stock_basis,
        # [{period, reason}]: stock counts on the chart the team reviewed
        # and judged unusual (backend/data_notes.py). The point stays; the
        # chart marks it and gives the reason in its tooltip.
        "stock_on_hand_flags": stock_on_hand_flags,
        # {text, peak, low} — the hero chart's takeaway sentence and the
        # sales months it should label, from the same rows it plots.
        "sales_vs_stock_insight": svs_insight,
        "abc_mix": abc_mix,
        # What abc_mix and tier_stock were ranked on (backend/abc_basis.py): the range's plain Pareto, not the
        # t12m_new basis the ABC page and the plan use. Labelled, not changed (audit 2026-10-23, finding 1).
        "abc_basis": dashboard_basis(range_text),
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
        # The day that count was taken ('YYYY-MM-DD'), so the card can say
        # "counted 2 Mar 2026" rather than a month. (Audrey's field.)
        "tier_stock_count_date": stock_count_dates.get(inventory_period) if tier_stock and inventory_period else None,
        "portfolio_forecast": portfolio_forecast,
        "reorder_preview": reorder_preview,
        # The forecast-error card for the range (mart.accuracy_mart): pieces and
        # pesos, surplus vs shortage, each month's direction, the over-forecast runs.
        "forecast_accuracy": forecast_accuracy,
        # Products in the count at the range's end with no sale in the 6 sales
        # months up to it (mart.idle_stock), the 10 largest by value; the full
        # list is GET /dashboard/idle-stock.
        "idle_stock": idle,
        # When the marts were last rebuilt, and whether a source changed since.
        "marts": mart_status,
    }
    # Preview only, so a real-mode payload is exactly what it was. Stock and
    # purchases have no placeholder rows to add; the rest are predictive or
    # prescriptive, which read real data only (backend/data_mode.py).
    if mode == PREVIEW:
        real_only = ["kpis.soh_value", "sales_vs_stock.stock_on_hand", "sales_vs_stock.received", "latest_data_period",
                     "forecast_accuracy", "idle_stock"]
        if not predictive_preview(mode):
            real_only += ["kpis.safety_stock_rate", "safety_stock_exposure", "recommendations", "forecast",
                          "portfolio_forecast", "reorder_preview", "policy_comparison", "lp"]
        payload["data_mode"] = preview_block(db, real_only=real_only)
    # LP figures follow lp.view everywhere (Yuan's permissions proposal):
    # without it they are left out here, not only hidden behind the Reorder
    # tab.
    payload["lp_hidden"] = False
    if not can_see_lp(db, current_user):
        _strip_lp_fields(payload)
    # Gap semantics (backend/series_gaps.py): a note, only when a point above carries a reason.
    note = series_gap_note(pt["sales_reason"] for pt in sales_vs_stock if "sales_reason" in pt)
    if note:
        payload["gap_note"] = note
    # The labelled Del Monte demonstration, behind DM_DEMO_ENABLED (default off). Its own block, with its own
    # data_source: the rest of this payload is real and stays labelled as it was.
    if demo_data_enabled(mode) and scope in ("all", "delmonte"):
        payload["demonstration"] = demo_data.label({
            "principal": "delmonte",
            "index": demo_data.index(db, "delmonte")["series"],
            "monthly_totals": demo_data.monthly_totals(db)["months"],
            "forecasts": demo_data.forecasts(db),
            "stock": demo_data.stock(db),
            "order_plan": demo_data.order_plan(db),
            "policy_comparison": demo_data.policy_comparison(db),
            "dead_stock": demo_data.dead_stock(db),
        })
    return payload


LP_HIDDEN_REASON = "Needs the reorder-recommendation permission (lp.view)."


def _strip_lp_fields(payload: dict) -> None:
    """Blanks every figure GET /dashboard derives from LP_Recommendation
    (the sections the module docstring sources to it) and says so with
    `lp_hidden`, so the page shows a dash, not a zero."""
    payload["lp_hidden"] = True
    payload["reorder_preview"] = None
    payload["policy_comparison"] = None
    payload["lp"] = None
    payload["safety_stock_exposure"] = None
    payload["recommendations"] = {"order_value": None, "product_count": None}
    kpis = payload.get("kpis") or {}
    kpis["safety_stock_rate"] = None
    kpis["safety_stock_rate_blocked_reason"] = LP_HIDDEN_REASON
    for tier in payload.get("tier_stock") or []:
        tier["pending_reorder_count"] = None
