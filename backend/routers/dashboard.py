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

Honest-null policy (matches the frontend's null-handling contract — a null
value means "cannot honestly compute this", never a guess or a fabricated
zero):

  ORIGINAL FIELDS (unchanged from before this pass):
  inventory.value / inventory.weeks_of_cover / cover_series[].weeks_of_cover
    — always null. inventory_fact has no valuation/price column anywhere
    (confirmed against the live schema) and unit-quantity math was tried
    and confirmed implausible (Del Monte inventory is per-SKU, demand is
    per-category, they don't join per product). There is nothing honest
    to compute here yet — do not fabricate a value once this file is
    touched again for a different reason.
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
    — real: SUM(net_amount) from Unilever_SKU_Demand_Fact_Real +
    SellOut_Fact_Real for the CURRENT calendar month (the last entry of
    the same 12-month list sales_vs_stock uses) — "this period's total
    sales", matching the KPI card's own label. Null (with
    sales_blocked_reason) when neither source has a row for that month
    and principal scope — a real gap (data usually lags the current
    calendar month), not a bug.
  kpis.soh_value
    — real for BOTH principals, computed differently per principal
    because the source columns mean different things (see the
    Unilever-unit note below), then added together for principal=all:
      Del Monte: SUM(Inventory_Fact_Real.cost) — already an extended
        peso total per SKU/snapshot (R10 in schema.sql: confirmed equal
        to `valuation` on real data), no unit conversion needed.
      Unilever: SUM(quantity_on_hand * unit_cost_per_case). This
        REQUIRED confirming quantity_on_hand is in CASES for Unilever SOH
        rows before multiplying by a per-case price — verified, not
        assumed:
          - config/column_maps/ssis_soh.yaml's "Stock Quantity (CS/PC)"
            parse splits the raw cell into stock_qty_cases /
            stock_qty_pieces.
          - analytics/etl/transform_ssis_soh.py's own column-mapping
            docstring and code (`"quantity_on_hand": df["stock_qty_cases"]`)
            confirm quantity_on_hand is loaded from stock_qty_cases
            specifically — the CASES component, not the pieces remainder
            and not the combined total-units-in-pieces figure.
          - unit_cost_per_case is loaded from "Last Purchase Price(GSV/CS)"
            — schema.sql's own comment on that column confirms the source
            header states it is a per-CASE price.
        quantity_on_hand (cases) x unit_cost_per_case (pesos/case) is
        therefore unit-consistent. KNOWN LIMITATION (documented, not a
        blocked/null condition): this deliberately excludes
        quantity_pieces (the loose-piece remainder that doesn't make a
        full case) — quantity_on_hand's own defined scope is cases only,
        so this is under-counting a small remainder, not a wrong unit.
        Null (with soh_value_blocked_reason) only when Inventory_Fact_Real
        has no rows at all for the resolved period/principal scope — NOT
        when the unit is unconfirmed (it is confirmed, see above). If a
        future change to ssis_soh's Extract/Transform ever changes what
        quantity_on_hand holds, UNILEVER_SOH_UNIT_CONFIRMED below is the
        single switch that re-blocks this whole computation (soh_value
        AND every sales_vs_stock.stock_on_hand point) rather than
        silently multiplying the wrong unit.
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
    — an object, not a bare number: {combined, combined_blocked_reason,
    unilever, unilever_blocked_reason, delmonte, delmonte_blocked_reason}.
    Computed for BOTH principals AND combined on every request, regardless
    of ?principal= — Del Monte and Unilever differ materially here and a
    blended-only figure would hide that, same reasoning abc_mix's
    revenue_share_pct caveat documents for a different field. Formula:
    current stock on hand / average weekly demand.
      Stock on hand reuses kpis.soh_value's own per-principal figures
        verbatim (soh_uni/soh_del, the same _soh_value_by_period() call —
        UNILEVER_SOH_UNIT_CONFIRMED is inherited automatically, not
        re-checked here).
      Average weekly demand reuses kpis.sales' own per-principal figures
        (sales_uni/sales_del): the mean of whatever non-null months exist
        in the trailing 12-month window (a real gap stays excluded, never
        averaged in as 0 demand), converted from a monthly to a weekly
        rate via AVG_WEEKS_PER_MONTH (average days/month / 7 — a
        documented convention, not a fabricated number, same spirit as
        analytics/etl/granularity.py's business_days_in_month()).
    unilever / delmonte: null (with their own *_blocked_reason) whenever
    either that principal's stock or its average weekly demand is
    unavailable, or weekly demand is exactly 0 (division by zero, not "0
    weeks").
    combined: the SAME partial-data rule kpis.soh_value/kpis.sales already
    apply for principal=all — computed by summing BOTH principals' stock
    and BOTH principals' weekly demand first, then dividing (not averaging
    the two principals' own ratios, which would weight a small principal
    equally with a large one) — and only when all four inputs (both
    stocks, both weekly demands) are real. Null otherwise, never a
    one-sided total presented as complete.
    Replaces the removed kpis.fixed_point_ratio, which was always null —
    no supplier allocation table exists anywhere in analytics/db/schema.sql,
    and the frontend's old mock hardcoded 0.94 for it. weeks_of_cover has
    a real formula and real inputs; fixed_point_ratio never did.

  sales_vs_stock[].sales
    — same SUM(net_amount) computation as kpis.sales, one point per
    period in the same last-12-calendar-months list as cover_series.
    Null for any period neither real source has a row for (most of the
    12-month window, in practice, until Load has run further back).
  sales_vs_stock[].stock_on_hand
    — same computation as kpis.soh_value, PESOS (not units — plotted on
    the same axis as sales), one point per Inventory_Fact_Real period
    matching each of the 12 calendar months. If
    UNILEVER_SOH_UNIT_CONFIRMED is ever flipped to False, every point in
    this series is null, per the note on kpis.soh_value above.
  sales_vs_stock[].received
    — SUPPLIER-ALLOCATION PROXY, not a fabricated fixed_allocation
    constant: no supplier allocation schedule exists anywhere in the
    schema or the source files (see kpis.weeks_of_cover's docstring
    section, which documents the same gap for a different field) — SSM
    has never provided one. SUM(Purchase_Fact_Real.net_amount) per
    period, in pesos (same axis as sales/stock_on_hand), via
    _received_by_period() — same "both principals real before combining
    for principal=all" rule as sales/soh_value. Null (a real gap, never
    0) for any period Purchase_Fact_Real has no matching rows for.
    Deliberately isolated in its own function (_received_by_period, one
    call site) so a future swap to a real Supplier_Allocation table is a
    source change inside that one function, not a rewrite of this
    endpoint — see that function's own docstring.

  abc_mix[].revenue_share_pct
    — real: SUM(revenue_share) * 100 per tier at the latest
    classification_period, filtered by ?principal= like every other ABC
    read. CAVEAT (documented, not fixed): revenue_share is only
    normalized to 100% *within* its own principal (ABCClassification.jsx
    already flags this same fact client-side) — Unilever revenue and Del
    Monte revenue are separate 100%-normalized universes, so this figure
    under principal=all is a sum of two independent shares, not a single
    coherent "percent of one pooled revenue total". Kept as specified
    (the task's literal formula), not silently changed to something else.

  tier_stock[]
    — real: per-tier counts of PRODUCTS by stock status, reusing
    backend.routers.abc._stock_status verbatim (imported, not
    reimplemented) including its NO DATA handling — a product with no
    Inventory_Fact_Real row counts toward `no_data`, never toward
    `critical`. No allocation bar — no supplier allocation table exists
    anywhere in the schema (see kpis.weeks_of_cover's docstring section).

  portfolio_forecast
    — real, but structurally different from the old mock's clean 4-period
    horizon: scripts/run_sarima.py forecasts ONE step ahead per product
    (steps=1), and forecast_date is that product's OWN latest actual
    period + 1 month — there is no shared, synchronized multi-period
    horizon anywhere in Forecast_Result to report. Reporting one only
    would be honest but term "gated products' forecast_date(s), whatever
    they real are" is what series actually contains: the last 8 REAL
    actual periods (summed quantity across the gated product set, i.e.
    products with a forecast_date row where status='ok' AND mape < 20 at
    the most recent forecast_date in the table), followed by however many
    distinct real forecast_date buckets exist among those gated rows
    (usually one, sometimes a few if products' own latest periods
    differ) — never fabricated into a clean synchronized run. actual and
    forecast use the same "quantity" concept run_sarima.py itself trains
    on (Unilever quantity_sold + Del Monte SellOut quantity, summed
    without unit conversion — the same simplification already accepted
    in production model training, not a new one introduced here).
    gated_sku_count / avg_mape are computed from the same gated-row set
    (field name "sku" kept as specified even though Del Monte's gated
    rows are category rows, not literal SKUs — DEC-03). scope_label is
    built FROM the principals actually present among the gated rows, not
    assumed — Forecast_Result is confirmed (scripts/run_sarima.py) to run
    for both principals, contrary to an older schema.sql comment claiming
    Unilever-only. Null/empty across the board (gated_sku_count=0,
    avg_mape=None, series=[]) when nothing passes the gate for the
    requested principal scope.

  reorder_preview
    — real: top 5 pending LP_Recommendation rows by urgency, reusing
    backend.routers.recommendations._to_item / _SELECT_ONE verbatim
    (imported, not reimplemented) for the exact same urgency derivation
    GET /recommendations uses. critical_count / urgent_count /
    total_order_qty are computed over the FULL pending, principal-filtered
    set (not just the 5 previewed rows) — a portfolio-wide summary next
    to a 5-row preview, same relationship ABC's tier_summary has to its
    own items list.
"""
from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.deps import TokenPayload, get_current_user, get_db
from backend.routers.abc import _stock_status
from backend.routers.recommendations import _SELECT_ONE as _RECOMMENDATION_SELECT_ONE
from backend.routers.recommendations import _to_item as _to_recommendation_item

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

POLICY_WEEKS = 3
MAPE_UNRELIABLE_GATE = 20.0  # percent — see schema.sql's Forecast_Result.mape comment

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


def _latest_sales_period(db: Session) -> str | None:
    """The most recent real 'YYYY-MM' across the two sources kpis.sales /
    sales_vs_stock read (Unilever_SKU_Demand_Fact_Real.calendar_month,
    SellOut_Fact_Real._period) — the anchor _last_12_periods() uses.
    GREATEST on TEXT works lexically for zero-padded 'YYYY-MM', same
    convention MAX(classification_period) already relies on elsewhere
    (backend/routers/abc.py). None only if both tables are completely
    empty."""
    row = db.execute(text("""
        SELECT GREATEST(
            COALESCE((SELECT MAX(calendar_month) FROM Unilever_SKU_Demand_Fact_Real), ''),
            COALESCE((SELECT MAX(_period) FROM SellOut_Fact_Real), '')
        ) AS p
    """)).mappings().first()
    p = row["p"] if row else None
    return p or None


def _last_12_periods(db: Session) -> list[str]:
    """Last 12 calendar months as 'YYYY-MM', oldest first, ENDING AT THE
    MOST RECENT REAL SALES PERIOD (_latest_sales_period), not today's
    wall-clock date.

    Bug this anchor fixes: with today's real date as the anchor, this
    window can (and, 2026-08 on the live database, does — real sales
    coverage ends 2026-02, six months behind) run almost entirely past
    real coverage. The few real points still inside a wall-clock-anchored
    window were far enough apart (non-adjacent months) that
    SalesVsStockWidget's Line elements — dot={false}, connectNulls={false},
    a deliberate choice matching every other line chart in this file, so
    a real gap always renders as a gap, never a fabricated interpolation
    — drew literally nothing: no dots (dot=false) and no segments (no two
    adjacent non-null points to connect). Anchoring to real data instead
    means principal=unilever (contiguous real coverage every month
    2023-01 through 2026-02 on the live database) renders a complete
    line; principal=delmonte / combined 'all' still show real gaps where
    Del Monte's SellOut_Fact_Real coverage is genuinely sparse — honest,
    not a bug.

    Falls back to today's date only if _latest_sales_period finds no
    sales data anywhere yet — never silently defaults to "today" over a
    real anchor that exists."""
    anchor = _latest_sales_period(db)
    if anchor:
        today = datetime.date(int(anchor[:4]), int(anchor[5:7]), 1)
    else:
        today = datetime.date.today()
    periods = []
    for i in range(11, -1, -1):
        month_index = today.month - 1 - i
        year = today.year + month_index // 12
        month = month_index % 12 + 1
        periods.append(f"{year:04d}-{month:02d}")
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


def _combine_principal_sums(
    periods: list[str],
    unilever: dict[str, float | None],
    delmonte: dict[str, float | None],
    principal: str,
) -> dict[str, float | None]:
    """Combines two independently-sourced per-principal period dicts.

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
    for p in periods:
        u, d = unilever.get(p), delmonte.get(p)
        combined[p] = (u + d) if (u is not None and d is not None) else None
    return combined


def _sales_by_period(
    db: Session, principal: str, periods: list[str]
) -> tuple[dict[str, float | None], dict[str, float | None], dict[str, float | None]]:
    """SUM(net_amount) per period from Unilever_SKU_Demand_Fact_Real +
    SellOut_Fact_Real (product-mart demand facts — deliberately NOT
    Sales_Fact, which is Del Monte-only invoice grain with no per-period
    demand-comparable shape). Returns (combined, unilever, delmonte) so
    callers needing the KPI's per-source blocked_reason don't have to
    re-query."""
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
    return _combine_principal_sums(periods, unilever, delmonte, principal), unilever, delmonte


# SUPPLIER-ALLOCATION PROXY — see sales_vs_stock[].received's docstring
# section for the full reasoning. This is the ONE function to change (SQL
# body only — signature and call site stay the same) the day a real
# Supplier_Allocation table exists: swap Purchase_Fact_Real for that table,
# drop the "(proxy for allocation)" wording at the two frontend call sites
# that reference it (frontend/src/components/Charts.jsx's
# SalesVsStockWidget), and nothing else in this file needs to change.
def _received_by_period(
    db: Session, principal: str, periods: list[str]
) -> tuple[dict[str, float | None], dict[str, float | None], dict[str, float | None]]:
    """SUM(Purchase_Fact_Real.net_amount) per period — unlike sales/soh,
    both principals live in ONE table here (Purchase_Fact.principal), but
    the combine rule is identical: principal='all' still requires BOTH
    sides real for a period before reporting a combined figure, same
    reasoning _sales_by_period/_soh_value_by_period already apply."""
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
    return _combine_principal_sums(periods, unilever, delmonte, principal), unilever, delmonte


def _latest_inventory_period(db: Session) -> str | None:
    row = db.execute(text("SELECT MAX(_period) AS p FROM Inventory_Fact_Real")).mappings().first()
    return row["p"] if row else None


def _soh_value_by_period(
    db: Session, principal: str, periods: list[str]
) -> tuple[dict[str, float | None], dict[str, float | None], dict[str, float | None]]:
    """Peso stock-on-hand valuation per Inventory_Fact_Real period — see
    kpis.soh_value's docstring section for the unit-confirmation evidence
    behind the Unilever branch. Returns (combined, unilever, delmonte),
    same reasoning as _sales_by_period: principal='all' never silently
    reports one side's total as if it were the whole portfolio's."""
    none_periods = {p: None for p in periods}
    if not UNILEVER_SOH_UNIT_CONFIRMED and principal in ("all", "unilever"):
        # Structurally blocked — every period stays None on the Unilever
        # side (and therefore on 'all' too, via _combine_principal_sums).
        unilever = dict(none_periods)
    elif principal in ("all", "unilever"):
        unilever = _query_period_sums(db, """
            SELECT _period AS period, SUM(quantity_on_hand * unit_cost_per_case) AS total
            FROM Inventory_Fact_Real
            WHERE principal = 'unilever' AND _period = ANY(:periods)
            GROUP BY _period
        """, periods)
    else:
        unilever = dict(none_periods)

    delmonte = (
        _query_period_sums(db, """
            SELECT _period AS period, SUM(cost) AS total
            FROM Inventory_Fact_Real
            WHERE principal = 'delmonte' AND _period = ANY(:periods)
            GROUP BY _period
        """, periods)
        if principal in ("all", "delmonte") else dict(none_periods)
    )

    return _combine_principal_sums(periods, unilever, delmonte, principal), unilever, delmonte


def _latest_abc_period(db: Session) -> str | None:
    row = db.execute(text("SELECT MAX(classification_period) AS p FROM ABC_Classification")).mappings().first()
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
    principal: str = Query("all", description="Filter to 'unilever' or 'delmonte'. Use 'all' for both."),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
):
    principal_filter = ""
    params: dict = {}
    if principal in ("unilever", "delmonte"):
        principal_filter = "AND pd.principal = :principal"
        params["principal"] = principal

    # ---- ORIGINAL FIELDS (unchanged) ----------------------------------

    reco_row = db.execute(
        text(f"""
            SELECT COUNT(*) AS product_count
            FROM LP_Recommendation lr
            JOIN Product_Dimension pd ON pd.product_key = lr.product_key
            WHERE lr.status = 'pending' {principal_filter}
        """),
        params,
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
        {**params, "mape_gate": MAPE_UNRELIABLE_GATE},
    ).mappings().first()
    total_count = int(forecast_row["total_count"])
    unreliable_count = int(forecast_row["unreliable_count"]) if total_count > 0 else None

    # ---- kpis.sales / sales_vs_stock.sales ----------------------------

    periods = _last_12_periods(db)
    # Always fetched for BOTH principals (principal="all" here, regardless
    # of this request's own ?principal=) — kpis.weeks_of_cover below needs
    # both sides unconditionally. sales_by_period (the request-scoped view
    # kpis.sales / sales_vs_stock actually use) is then derived from the
    # same two dicts via _combine_principal_sums, so this is a strict
    # superset of the old single-principal fetch, not a behavior change.
    _, sales_uni, sales_del = _sales_by_period(db, "all", periods)
    sales_by_period = _combine_principal_sums(periods, sales_uni, sales_del, principal)
    current_period = periods[-1]
    sales = sales_by_period[current_period]
    if sales is not None:
        sales_blocked_reason = None
    elif principal == "all":
        missing = [
            name for name, d in (("Unilever", sales_uni), ("Del Monte", sales_del))
            if d.get(current_period) is None
        ]
        sales_blocked_reason = (
            f"No {' or '.join(missing)} sales rows for {current_period} yet — cannot report a "
            "combined 'all principals' total from only one side."
        )
    else:
        source = "Unilever_SKU_Demand_Fact_Real" if principal == "unilever" else "SellOut_Fact_Real"
        sales_blocked_reason = f"No {source} rows for {current_period} yet."

    # ---- kpis.soh_value / sales_vs_stock.stock_on_hand ----------------

    inventory_period = _latest_inventory_period(db)
    soh_periods = periods if inventory_period is None else sorted(set(periods) | {inventory_period})
    # Same "always both principals" reasoning as sales_uni/sales_del above.
    _, soh_uni, soh_del = _soh_value_by_period(db, "all", soh_periods)
    soh_by_period = _combine_principal_sums(soh_periods, soh_uni, soh_del, principal)
    soh_value = soh_by_period.get(inventory_period) if inventory_period is not None else None
    if inventory_period is None:
        soh_value_blocked_reason = "Inventory_Fact_Real has no rows at all."
    elif not UNILEVER_SOH_UNIT_CONFIRMED and principal in ("all", "unilever"):
        soh_value_blocked_reason = _UNILEVER_SOH_UNIT_UNCONFIRMED_REASON
    elif soh_value is None:
        if principal == "all":
            missing = [
                name for name, d in (("Unilever", soh_uni), ("Del Monte", soh_del))
                if d.get(inventory_period) is None
            ]
            soh_value_blocked_reason = (
                f"No computable {' or '.join(missing)} valuation for {inventory_period} — cannot "
                "report a combined 'all principals' total from only one side."
            )
        else:
            source = "quantity_on_hand x unit_cost_per_case" if principal == "unilever" else "cost"
            soh_value_blocked_reason = f"No Inventory_Fact_Real rows with {source} populated for {principal} in {inventory_period}."
    else:
        soh_value_blocked_reason = None

    # ---- kpis.safety_stock_rate ----------------------------------------

    abc_period = _latest_abc_period(db)
    safety_stock_rate = None
    safety_stock_rate_blocked_reason = "ABC_Classification has no rows yet."
    if abc_period is not None:
        ss_principal_filter = "AND ac.principal = :principal" if principal in ("unilever", "delmonte") else ""
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
                WHERE ac.classification_period = :period AND ac.tier = 'A' {ss_principal_filter}
            """),
            {"period": abc_period, "principal": principal} if principal in ("unilever", "delmonte") else {"period": abc_period},
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
    # current stock on hand / average weekly demand, per principal AND
    # combined — see the docstring section above for the full reasoning.
    # Reuses soh_uni/soh_del (already both-principals, already carrying
    # UNILEVER_SOH_UNIT_CONFIRMED) and sales_uni/sales_del (same) — no new
    # queries.
    uni_stock = soh_uni.get(inventory_period) if inventory_period is not None else None
    del_stock = soh_del.get(inventory_period) if inventory_period is not None else None
    if inventory_period is None:
        uni_stock_reason = del_stock_reason = "Inventory_Fact_Real has no rows at all."
    else:
        uni_stock_reason = (
            _UNILEVER_SOH_UNIT_UNCONFIRMED_REASON if not UNILEVER_SOH_UNIT_CONFIRMED
            else f"No Inventory_Fact_Real rows with quantity_on_hand x unit_cost_per_case populated for unilever in {inventory_period}."
        )
        del_stock_reason = f"No Inventory_Fact_Real rows with cost populated for delmonte in {inventory_period}."

    uni_weekly_demand, uni_demand_reason = _avg_weekly_demand(sales_uni)
    del_weekly_demand, del_demand_reason = _avg_weekly_demand(sales_del)

    weeks_of_cover_unilever, weeks_of_cover_unilever_reason = _weeks_of_cover(
        uni_stock, uni_stock_reason, uni_weekly_demand, uni_demand_reason
    )
    weeks_of_cover_delmonte, weeks_of_cover_delmonte_reason = _weeks_of_cover(
        del_stock, del_stock_reason, del_weekly_demand, del_demand_reason
    )

    if uni_stock is not None and del_stock is not None and uni_weekly_demand is not None and del_weekly_demand is not None:
        weeks_of_cover_combined, weeks_of_cover_combined_reason = _weeks_of_cover(
            uni_stock + del_stock, None, uni_weekly_demand + del_weekly_demand, None
        )
    else:
        missing = []
        if uni_stock is None or del_stock is None:
            missing.append("a stock-on-hand valuation")
        if uni_weekly_demand is None or del_weekly_demand is None:
            missing.append("an average weekly demand figure")
        weeks_of_cover_combined = None
        weeks_of_cover_combined_reason = (
            f"Unilever or Del Monte is missing {' and '.join(missing)} — cannot report a combined "
            "'all principals' figure from only one side."
        )

    # ---- sales_vs_stock series -------------------------------------------

    received_by_period, _, _ = _received_by_period(db, principal, periods)

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
        mix_principal_filter = "AND principal = :principal" if principal in ("unilever", "delmonte") else ""
        mix_rows = db.execute(
            text(f"""
                SELECT tier, COUNT(*) AS cnt, SUM(revenue_share) AS rev_share_sum
                FROM ABC_Classification
                WHERE classification_period = :period {mix_principal_filter}
                GROUP BY tier
            """),
            {"period": abc_period, "principal": principal} if principal in ("unilever", "delmonte") else {"period": abc_period},
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
        ts_principal_filter = "AND ac.principal = :principal" if principal in ("unilever", "delmonte") else ""
        ts_rows = db.execute(
            text(f"""
                SELECT
                    ac.tier,
                    inv.current_stock AS current_stock,
                    rop.rop_i AS rop_i
                FROM ABC_Classification ac
                LEFT JOIN (
                    SELECT product_key, SUM(quantity_on_hand) AS current_stock
                    FROM Inventory_Fact_Real
                    WHERE _period = (SELECT MAX(_period) FROM Inventory_Fact_Real)
                    GROUP BY product_key
                ) inv ON inv.product_key = ac.product_key
                LEFT JOIN (
                    SELECT DISTINCT ON (product_key) product_key, rop_i
                    FROM LP_Recommendation
                    WHERE status = 'pending'
                    ORDER BY product_key, planning_cycle_date DESC
                ) rop ON rop.product_key = ac.product_key
                WHERE ac.classification_period = :period {ts_principal_filter}
            """),
            {"period": abc_period, "principal": principal} if principal in ("unilever", "delmonte") else {"period": abc_period},
        ).mappings().all()
        buckets: dict[str, dict[str, int]] = {}
        for r in ts_rows:
            tier = r["tier"]
            status = _stock_status(
                float(r["current_stock"]) if r["current_stock"] is not None else None,
                float(r["rop_i"]) if r["rop_i"] is not None else None,
            )
            b = buckets.setdefault(tier, {"in_stock": 0, "low": 0, "critical": 0, "no_data": 0})
            if status == "IN STOCK":
                b["in_stock"] += 1
            elif status == "LOW":
                b["low"] += 1
            elif status == "CRITICAL":
                b["critical"] += 1
            else:  # "NO DATA"
                b["no_data"] += 1
        tier_stock = [
            {"tier": tier, **counts} for tier, counts in sorted(buckets.items())
        ]

    # ---- portfolio_forecast --------------------------------------------

    latest_forecast_date_row = db.execute(text("SELECT MAX(forecast_date) AS d FROM Forecast_Result")).mappings().first()
    latest_forecast_date = latest_forecast_date_row["d"] if latest_forecast_date_row else None

    gated_rows: list = []
    if latest_forecast_date is not None:
        pf_principal_filter = "AND pd.principal = :principal" if principal in ("unilever", "delmonte") else ""
        gated_rows = db.execute(
            text(f"""
                SELECT fr.product_key, fr.forecast_date, fr.forecast_value,
                       fr.confidence_lower, fr.confidence_upper, fr.mape, pd.principal
                FROM Forecast_Result fr
                JOIN Product_Dimension pd ON pd.product_key = fr.product_key
                WHERE fr.forecast_date = :forecast_date
                  AND fr.status = 'ok'
                  AND fr.mape < :mape_gate
                  {pf_principal_filter}
            """),
            {"forecast_date": latest_forecast_date, "mape_gate": MAPE_UNRELIABLE_GATE, "principal": principal}
            if principal in ("unilever", "delmonte")
            else {"forecast_date": latest_forecast_date, "mape_gate": MAPE_UNRELIABLE_GATE},
        ).mappings().all()

    gated_sku_count = len({r["product_key"] for r in gated_rows})
    avg_mape = (
        round(sum(float(r["mape"]) for r in gated_rows) / len(gated_rows), 2)
        if gated_rows else None
    )

    principals_present = sorted({r["principal"] for r in gated_rows})
    if not principals_present:
        scope_label = f"No products currently meet the MAPE < {MAPE_UNRELIABLE_GATE:.0f}% gate for principal={principal}."
    elif principals_present == ["delmonte"]:
        scope_label = "Del Monte only (category-level SARIMA forecasts meeting the MAPE gate)."
    elif principals_present == ["unilever"]:
        scope_label = "Unilever only (SKU-level SARIMA forecasts meeting the MAPE gate)."
    else:
        scope_label = "Unilever (SKU-level) and Del Monte (category-level) SARIMA forecasts meeting the MAPE gate."

    series_by_period: dict[str, dict] = {}
    if gated_rows:
        gated_product_keys = sorted({r["product_key"] for r in gated_rows})

        actual_totals: dict[str, float] = {}
        if principal in ("all", "unilever"):
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
        if principal in ("all", "delmonte"):
            rows = db.execute(
                text("""
                    SELECT _period AS period, SUM(quantity) AS qty
                    FROM SellOut_Fact_Real
                    WHERE product_key = ANY(:keys)
                    GROUP BY _period
                """),
                {"keys": gated_product_keys},
            ).mappings().all()
            for r in rows:
                actual_totals[r["period"]] = actual_totals.get(r["period"], 0.0) + float(r["qty"] or 0)

        last_8_actual_periods = sorted(actual_totals.keys())[-8:]
        for p in last_8_actual_periods:
            series_by_period[p] = {"period": p, "actual": actual_totals[p], "forecast": None,
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

    rp_query = _RECOMMENDATION_SELECT_ONE + " WHERE lr.status = 'pending'"
    rp_params: dict = {}
    if principal in ("unilever", "delmonte"):
        rp_query += " AND pd.principal = :principal"
        rp_params["principal"] = principal
    rp_rows = db.execute(text(rp_query), rp_params).mappings().all()
    rp_items = [_to_recommendation_item(r) for r in rp_rows]
    rp_items_sorted = sorted(rp_items, key=lambda it: _URGENCY_RANK.get(it.urgency, 99))

    reorder_preview = {
        "rows": [item.model_dump() for item in rp_items_sorted[:5]],
        "critical_count": sum(1 for it in rp_items if it.urgency == "CRITICAL"),
        "urgent_count": sum(1 for it in rp_items if it.urgency == "URGENT"),
        "total_order_qty": round(sum(it.q_i for it in rp_items), 2) if rp_items else 0,
    }

    return {
        "principal": principal,
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
                "combined": weeks_of_cover_combined,
                "combined_blocked_reason": weeks_of_cover_combined_reason,
                "unilever": weeks_of_cover_unilever,
                "unilever_blocked_reason": weeks_of_cover_unilever_reason,
                "delmonte": weeks_of_cover_delmonte,
                "delmonte_blocked_reason": weeks_of_cover_delmonte_reason,
            },
        },
        "sales_vs_stock": sales_vs_stock,
        "abc_mix": abc_mix,
        "tier_stock": tier_stock,
        "portfolio_forecast": portfolio_forecast,
        "reorder_preview": reorder_preview,
    }
