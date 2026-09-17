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

  ORIGINAL FIELDS (unchanged from before this pass):
  inventory.value / inventory.weeks_of_cover / cover_series[].weeks_of_cover
    — always null. inventory_fact has no valuation/price column anywhere
    (confirmed against the live schema). There is nothing honest to
    compute here yet — do not fabricate a value once this file is touched
    again for a different reason.
  recommendations.order_value
    — always null. lp_recommendation has no runner yet, and even once one
    exists, Q_i * unit_price needs a cost column that doesn't exist.
  recommendations.product_count
    — real: COUNT(*) of pending LP_Recommendation rows. Needs no price,
    so it's honestly computable even though order_value isn't.
  forecast.unreliable_count / forecast.total_count
    — real: from Forecast_Result at its most recent forecast_date. mape
    is stored as a PERCENT (see schema.sql's column comment) — the gate
    is `mape >= 20.0`, not `>= 0.20`. unreliable_count is null (not 0)
    when total_count is 0, matching this app's "null = no data source
    yet" convention everywhere else, rather than claiming "0 unreliable"
    when there's no forecast run to judge at all.

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
    therefore unit-consistent. KNOWN LIMITATION (documented, not a
    blocked/null condition): this deliberately excludes quantity_pieces
    (the loose-piece remainder that doesn't make a full case) —
    quantity_on_hand's own defined scope is cases only, so this is
    under-counting a small remainder, not a wrong unit. Null (with
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
    — {value, blocked_reason}. Formula: current stock on hand / average
    weekly demand.
      Stock on hand reuses kpis.soh_value's own figure verbatim
        (soh_by_period, the same _soh_value_by_period() call —
        UNILEVER_SOH_UNIT_CONFIRMED is inherited automatically, not
        re-checked here).
      Average weekly demand reuses kpis.sales' own figures
        (sales_by_period): the mean of whatever non-null months exist in
        the trailing 12-month window (a real gap stays excluded, never
        averaged in as 0 demand), converted from a monthly to a weekly
        rate via AVG_WEEKS_PER_MONTH (average days/month / 7 — a
        documented convention, not a fabricated number, same spirit as
        analytics/etl/granularity.py's business_days_in_month()).
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
    horizon: scripts/run_baseline_forecast.py's deployed MA3 method
    forecasts ONE step ahead per product, and forecast_date is that
    product's OWN latest actual period + 1 month — there is no shared,
    synchronized multi-period horizon anywhere in Forecast_Result to
    report (SARIMA was retired in favor of MA3 — see
    analytics/forecasting/baseline.py's module docstring for the
    evidence — but the one-step-per-product shape this section already
    documented carries over unchanged, so no aggregation logic below
    needed to change, only this wording). series covers the SAME `period`/
    `start_period`-derived window as kpis.sales / sales_vs_stock above
    (summed quantity_sold across the gated product set, i.e. products with
    a forecast_date row where status='ok' AND mape < 20 at the most recent
    forecast_date in the table) — the date-range picker's applied range,
    not a hardcoded trailing window — followed by however many distinct
    real forecast_date buckets exist among those gated rows (usually one,
    sometimes a few if products' own latest periods differ), which land
    past the picker's range whenever its end predates the forecast month.
    Never fabricated into a clean synchronized run.
    gated_sku_count / avg_mape are computed from the same gated-row set.
    Null/empty across the board (gated_sku_count=0, avg_mape=None,
    series=[]) when nothing passes the gate.

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
"""
from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.deps import TokenPayload, get_current_user, get_db
from backend.principals import PrincipalQuery, normalize_principal
from backend.routers.recommendations import _SELECT_ONE as _RECOMMENDATION_SELECT_ONE
from backend.routers.recommendations import _to_item as _to_recommendation_item

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

POLICY_WEEKS = 3
MAPE_UNRELIABLE_GATE = 20.0  # percent — see schema.sql's Forecast_Result.mape comment

# Step 19's LP objective weights (analytics/optimization/lp.py's W1/W2/W3:
# 0.45/0.35/0.20) — hardcoded module constants there, not stored per-
# recommendation anywhere in the schema, so mirrored here BY VALUE rather
# than imported (same "defensible default, not fact" mirroring convention
# AVG_WEEKS_PER_MONTH above uses for analytics/etl/granularity.py's
# constant — not imported directly since lp.py pulls in the pulp solver,
# a batch-job dependency this always-on API router shouldn't require just
# to read three floats). If lp.py's W1/W2/W3 ever change, update these to
# match by hand. See reorder_preview.lp_weights's docstring section above
# for why this is read-only, not an adjustable control.
LP_WEIGHT_COST = 0.45
LP_WEIGHT_SERVICE_LEVEL = 0.35
LP_WEIGHT_STORAGE = 0.20
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
    kpis.sales / sales_vs_stock / kpis.weeks_of_cover respond to the
    shared date filter instead of always showing the latest-data window
    regardless of what the user picked.

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
    db: Session, periods: list[str], principal: str = "unilever"
) -> dict[str, float | None]:
    """SUM(net_amount) per period, from each principal's own product-mart
    demand fact: Unilever_SKU_Demand_Fact_Real for Unilever,
    SellOut_Fact_Real for Del Monte.

    Del Monte deliberately reads SellOut_Fact_Real and NOT Sales_Fact —
    Sales_Fact is Del Monte-only INVOICE grain (DEC-10) with no
    per-period demand-comparable shape. That choice is inherited from the
    pre-2026-09 implementation, not re-litigated here."""
    unilever = (
        _query_period_sums(db, """
            SELECT calendar_month AS period, SUM(net_amount) AS total
            FROM Unilever_SKU_Demand_Fact_Real
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

    LIVE CAVEAT (2026-09-17): unit_cost_per_case is 100% populated for
    Unilever and 0% populated for Del Monte, so the Del Monte side of this
    product is null everywhere today. `principal` is interpolated (not
    bound) because it is already validated against a fixed allowlist by
    normalize_principal() at the endpoint boundary — it can only ever be
    the literal 'unilever' or 'delmonte' by the time it reaches here."""
    if not UNILEVER_SOH_UNIT_CONFIRMED:
        # Structurally blocked — every period stays None.
        return {p: None for p in periods}
    scope = "" if principal == "all" else f" AND principal = '{principal}'"
    return _query_period_sums(db, f"""
        SELECT _period AS period, SUM(quantity_on_hand * unit_cost_per_case) AS total
        FROM Inventory_Fact_Real
        WHERE _period = ANY(:periods){scope}
        GROUP BY _period
    """, periods)


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
    runs roughly monthly and lags the sales data it's derived from, so the
    date-range picker's applied end month (DashboardLayout's "today", one
    month ahead of the latest loaded sales/ABC data by construction — see
    DashboardLayout.jsx's getCurrentRealWorldPeriod comment) routinely has
    no exact ABC_Classification row of its own. Falling back to the
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
            "Anchors the sales/stock trend window kpis.sales / sales_vs_stock / "
            "kpis.weeks_of_cover are computed over (a fixed trailing 12 months "
            "when start_period is omitted, or the end of the exact range when "
            "it's given), AND is used as an exact "
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
            "year. When given, kpis.sales / sales_vs_stock / "
            "kpis.weeks_of_cover cover every month from here through `period` "
            "(or through the latest real sales period if `period` is also "
            "omitted) inclusive, instead of a fixed trailing 12 months — the "
            "exact width the user picked, not clipped to 12. Ignored (falls "
            "back to the fixed trailing-12 window) if omitted."
        ),
    ),
    principal: str | None = PrincipalQuery,
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

    reco_row = db.execute(
        text(f"""
            SELECT COUNT(*) AS product_count
            FROM LP_Recommendation lr
            JOIN Product_Dimension pd ON pd.product_key = lr.product_key
            WHERE lr.status = 'pending' {principal_filter}
        """)
    ).mappings().first()
    product_count = int(reco_row["product_count"])

    forecast_row = db.execute(
        text(f"""
            WITH latest AS (
                SELECT MAX(forecast_date) AS forecast_date FROM Forecast_Result
            )
            SELECT
                COUNT(*) AS total_count,
                COUNT(*) FILTER (WHERE fr.mape >= :mape_gate) AS unreliable_count
            FROM Forecast_Result fr
            JOIN Product_Dimension pd ON pd.product_key = fr.product_key
            JOIN latest ON fr.forecast_date = latest.forecast_date
            WHERE 1=1 {principal_filter}
        """),
        {"mape_gate": MAPE_UNRELIABLE_GATE},
    ).mappings().first()
    total_count = int(forecast_row["total_count"])
    unreliable_count = int(forecast_row["unreliable_count"]) if total_count > 0 else None

    # ---- kpis.sales / sales_vs_stock.sales ----------------------------

    periods = (
        _month_range(start_period, _resolve_sales_anchor(db, period, scope))
        if start_period is not None
        else _last_12_periods(db, period, scope)
    )
    sales_by_period = _sales_by_period(db, periods, scope)
    # Walk backward from the picker's applied end month to the nearest
    # period WITHIN the selected range that actually has a real sales row,
    # rather than requiring an exact match on the range's literal end —
    # the end month is routinely one the sales ETL hasn't loaded yet (see
    # _nearest_abc_period_at_or_before's docstring for why: the app's
    # pinned "today" runs a month ahead of the latest loaded data by
    # construction), which was blanking this card even when the rest of
    # the selected range had plenty of real data to show.
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

    # ---- kpis.soh_value / sales_vs_stock.stock_on_hand ----------------

    inventory_period = _latest_inventory_period(db, scope)
    soh_periods = periods if inventory_period is None else sorted(set(periods) | {inventory_period})
    soh_by_period = _soh_value_by_period(db, soh_periods, scope)
    soh_value = soh_by_period.get(inventory_period) if inventory_period is not None else None
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
    if abc_period is not None:
        ss_rows = db.execute(
            text(f"""
                SELECT
                    ac.product_key,
                    inv.current_stock AS current_stock,
                    rop.ss_i AS ss_i
                FROM ABC_Classification ac
                LEFT JOIN (
                    SELECT product_key, SUM(quantity_on_hand) AS current_stock
                    FROM Inventory_Fact_Real
                    WHERE _period = (SELECT MAX(_period) FROM Inventory_Fact_Real)
                    GROUP BY product_key
                ) inv ON inv.product_key = ac.product_key
                LEFT JOIN (
                    SELECT DISTINCT ON (product_key) product_key, ss_i
                    FROM LP_Recommendation
                    WHERE status = 'pending'
                    ORDER BY product_key, planning_cycle_date DESC
                ) rop ON rop.product_key = ac.product_key
                WHERE ac.classification_period = :period AND ac.tier = 'A'
                      AND ac.method = 'single' {abc_scope}
            """),
            {"period": abc_period},
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
            safety_stock_rate_blocked_reason = (
                "No Category A product has both an inventory figure and a pending "
                "LP_Recommendation to compare (LP_Recommendation may be empty)."
            )

    # ---- kpis.weeks_of_cover ---------------------------------------------
    # current stock on hand / average weekly demand — see the docstring
    # section above for the full reasoning. Reuses soh_by_period (already
    # carrying UNILEVER_SOH_UNIT_CONFIRMED) and sales_by_period — no new
    # queries.
    stock = soh_by_period.get(inventory_period) if inventory_period is not None else None
    stock_reason = (
        "Inventory_Fact_Real has no rows for unilever at all." if inventory_period is None
        else _UNILEVER_SOH_UNIT_UNCONFIRMED_REASON if not UNILEVER_SOH_UNIT_CONFIRMED
        else f"No Inventory_Fact_Real rows with quantity_on_hand x unit_cost_per_case populated for unilever in {inventory_period}."
    )
    weekly_demand, demand_reason = _avg_weekly_demand(sales_by_period)
    weeks_of_cover_value, weeks_of_cover_reason = _weeks_of_cover(
        stock, stock_reason, weekly_demand, demand_reason
    )

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

    # ---- abc_mix -----------------------------------------------------

    abc_mix: list[dict] = []
    if abc_period is not None:
        mix_rows = db.execute(
            text(f"""
                SELECT tier, COUNT(*) AS cnt, SUM(revenue_share) AS rev_share_sum
                FROM ABC_Classification
                WHERE classification_period = :period AND method = 'single' {abc_scope_bare}
                GROUP BY tier
            """),
            {"period": abc_period},
        ).mappings().all()
        abc_mix = [
            {
                "tier": r["tier"],
                "count": int(r["cnt"]),
                "revenue_share_pct": round(float(r["rev_share_sum"] or 0) * 100, 2),
            }
            for r in sorted(mix_rows, key=lambda r: r["tier"])
        ]

    # ---- tier_stock ----------------------------------------------------

    tier_stock: list[dict] = []
    if abc_period is not None:
        ts_rows = db.execute(
            text(f"""
                SELECT
                    ac.tier,
                    inv.any_active AS any_active,
                    inv.any_inactive AS any_inactive
                FROM ABC_Classification ac
                LEFT JOIN (
                    SELECT
                        product_key,
                        BOOL_OR(stock_status = 'Active') AS any_active,
                        BOOL_OR(stock_status = 'Inactive') AS any_inactive
                    FROM Inventory_Fact_Real
                    WHERE _period = (SELECT MAX(_period) FROM Inventory_Fact_Real)
                    GROUP BY product_key
                ) inv ON inv.product_key = ac.product_key
                WHERE ac.classification_period = :period AND ac.method = 'single' {abc_scope}
            """),
            {"period": abc_period},
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
                FROM ABC_Classification ac
                JOIN LP_Recommendation lr ON lr.product_key = ac.product_key AND lr.status = 'pending'
                WHERE ac.classification_period = :period AND ac.method = 'single' {abc_scope}
                GROUP BY ac.tier
            """),
            {"period": abc_period},
        ).mappings().all()
        pending_by_tier = {r["tier"]: int(r["cnt"]) for r in pending_rows}

        tier_stock = [
            {"tier": tier, **counts, "pending_reorder_count": pending_by_tier.get(tier, 0)}
            for tier, counts in sorted(buckets.items())
        ]

    # ---- portfolio_forecast --------------------------------------------

    latest_forecast_date_row = db.execute(text("SELECT MAX(forecast_date) AS d FROM Forecast_Result")).mappings().first()
    latest_forecast_date = latest_forecast_date_row["d"] if latest_forecast_date_row else None

    gated_rows: list = []
    if latest_forecast_date is not None:
        gated_rows = db.execute(
            text(f"""
                SELECT fr.product_key, fr.forecast_date, fr.forecast_value,
                       fr.confidence_lower, fr.confidence_upper, fr.mape
                FROM Forecast_Result fr
                JOIN Product_Dimension pd ON pd.product_key = fr.product_key
                WHERE fr.forecast_date = :forecast_date
                  AND fr.status = 'ok'
                  AND fr.mape < :mape_gate
                  {principal_filter}
            """),
            {"forecast_date": latest_forecast_date, "mape_gate": MAPE_UNRELIABLE_GATE},
        ).mappings().all()

    gated_sku_count = len({r["product_key"] for r in gated_rows})
    avg_mape = (
        round(sum(float(r["mape"]) for r in gated_rows) / len(gated_rows), 2)
        if gated_rows else None
    )
    scope_label = (
        f"No products currently meet the MAPE < {MAPE_UNRELIABLE_GATE:.0f}% gate."
        if not gated_rows
        else "Unilever only (SKU-level MA3 forecasts meeting the MAPE gate)."
    )

    series_by_period: dict[str, dict] = {}
    if gated_rows:
        gated_product_keys = sorted({r["product_key"] for r in gated_rows})

        actual_totals: dict[str, float] = {}
        rows = db.execute(
            text("""
                SELECT calendar_month AS period, SUM(quantity_sold) AS qty
                FROM Unilever_SKU_Demand_Fact_Real
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

    portfolio_forecast = {
        "series": [series_by_period[p] for p in sorted(series_by_period.keys())],
        "gated_sku_count": gated_sku_count,
        "avg_mape": avg_mape,
        "scope_label": scope_label,
    }

    # ---- reorder_preview -------------------------------------------------

    rp_query = _RECOMMENDATION_SELECT_ONE + f" WHERE lr.status = 'pending' {principal_filter}"
    rp_rows = db.execute(text(rp_query)).mappings().all()
    rp_items = [_to_recommendation_item(r) for r in rp_rows]
    rp_items_sorted = sorted(rp_items, key=lambda it: _URGENCY_RANK.get(it.urgency, 99))

    reorder_preview = {
        "rows": [item.model_dump() for item in rp_items_sorted[:5]],
        "critical_count": sum(1 for it in rp_items if it.urgency == "CRITICAL"),
        "urgent_count": sum(1 for it in rp_items if it.urgency == "URGENT"),
        "total_order_qty": round(sum(it.q_i for it in rp_items), 2) if rp_items else 0,
        "lp_weights": {
            "cost": LP_WEIGHT_COST,
            "service_level": LP_WEIGHT_SERVICE_LEVEL,
            "storage": LP_WEIGHT_STORAGE,
        },
    }

    return {
        "principal": "unilever",
        "period": None,
        "inventory": {"value": None, "weeks_of_cover": None, "policy_weeks": POLICY_WEEKS},
        "recommendations": {"order_value": None, "product_count": product_count},
        "forecast": {"unreliable_count": unreliable_count, "total_count": total_count},
        "cover_series": [{"period": p, "weeks_of_cover": None} for p in periods],
        "kpis": {
            "sales": _to_float(sales),
            "sales_blocked_reason": sales_blocked_reason,
            "soh_value": _to_float(soh_value),
            "soh_value_blocked_reason": soh_value_blocked_reason,
            "safety_stock_rate": safety_stock_rate,
            "safety_stock_rate_blocked_reason": safety_stock_rate_blocked_reason,
            "weeks_of_cover": {
                "value": weeks_of_cover_value,
                "blocked_reason": weeks_of_cover_reason,
            },
        },
        "sales_vs_stock": sales_vs_stock,
        "abc_mix": abc_mix,
        "tier_stock": tier_stock,
        "portfolio_forecast": portfolio_forecast,
        "reorder_preview": reorder_preview,
    }
