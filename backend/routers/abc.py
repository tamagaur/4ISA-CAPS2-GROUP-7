"""
backend.routers.abc — GET /abc

Phase 6 (CLAUDE.md Step 23):
  Returns ABC tier assignments for all active SKUs.
  Reads from ABC_Classification table in Supabase. Requires auth.

Implemented 2026-08 (was a stub — see git history). Joins
ABC_Classification to Product_Dimension for sku_id/product_name:
COALESCE(sku_code, category_path) per backend/schemas/abc.py's own
note — Del Monte rows carry a category_path here, not a SKU code
(DEC-03). Reads the LATEST classification_period per (principal, sku)
by default (a re-run of analytics/classification/orchestrate_abc.py
upserts rather than appending, so in practice there is only ever one
row per product_key+period, but "latest period across all products
present" is still an explicit MAX(), not an assumption that every
product shares one global period).

tier_summary (backlog #44) is computed here rather than trusted from
individual rows, so it can never silently drift from what `items`
actually contains.

Fixed 2026-08: stock_status was previously `random.choices(...)` — a
placeholder that re-rolled a fake status on every request instead of
reading real inventory. Replaced with the same real, deterministic rule
GET /inventory already uses (backend/routers/inventory.py), extended to
prefer each SKU's actual reorder point (from the latest pending
LP_Recommendation — same source SKUManagement/ReorderRecommendations
read) over the flat 100-unit fallback when one exists.

Fixed 2026-08 (again): current_stock used to COALESCE a missing
Inventory_Fact_Real row to 0, which _stock_status then read as
CRITICAL — but "no inventory record for this product_key" and
"confirmed zero stock" are different facts. Inventory_Fact_Real is a
partial load as of 2025-12 (~509 of ~1,628 ABC-classified products have
a row at all; more coverage expected, per Yuan), so most products
legitimately have no match here yet. current_stock is now left NULL
when there's no match, and stock_status reports "NO DATA" instead of
silently fabricating CRITICAL.

BOTH PRINCIPALS (2026-09-17): `?principal=` is back (see
backend/principals.py) after the 2026-09 Unilever-only period — Del Monte
is in scope again. Omit it (or pass 'all') for both. The latest-period
lookup is filtered by the SAME principal as the row query on purpose:
ABC_Classification carries both principals, so an unfiltered
MAX(classification_period) can resolve to a period the selected principal
has no rows for at all, rendering an empty page that looks like a bug.

NOTE (updated 2026-09-21): Del Monte HAS abc_classification rows again —
run_id 'dm_category_2026-09-21_v1', 673 'single' rows for 2023-01..2025-12,
category grain (DEC-03). Those products have no sku_code (and 59 of the 85
have no product_name), which is why sku_id must fall back to
category_path: with a '' fallback every Del Monte row shared one empty
sku_id, and the ABC page, which keyed its rows on it, collided on all 85.
product_key is returned as well so the frontend has a key that is unique
by construction. Open question for the data side, NOT resolved here: that
run ranks ~63 sub-categories per month in 2023-24 but only 4-5 top-level
categories in 2025, so view=last_known mixes the two grains for Del Monte.

METHOD FILTER (migration 0017): abc_classification's natural key widened
to (product_key, classification_period, method), and a 't3m' run is now
live alongside 'single' (25,437 + 23,223 rows). Every read here MUST pin
the method or each SKU comes back once per basis and revenue_share sums to
~200%. Since migration 0044 the pin is each principal's Tier A basis
(analytics.params.abc_method_sql: Unilever TIER_A_BASIS, Del Monte 'single').

The method fix here was also made independently upstream in e6a7a13
(same five sites, same verified 0.9986-vs-1.9973 evidence); this version
supersedes it only by ALSO pinning method in the MAX(classification_period)
lookups, which that commit left unfiltered.

LAST-KNOWN VIEW (2026-09-21, ?view=last_known): the default view lists
only the SKUs ranked in ONE period — 710 of Unilever's 2,098 for 2026-02 —
because ABC ranks by that month's revenue and a SKU with no sales that
month is simply absent. GET /sku already switched to each product's most
recent tier (1,531 carry one), so the two pages disagreed about the same
SKUs. last_known uses the same rule as GET /sku: DISTINCT ON product_key,
newest 'single' run at or before the anchor. Each item carries
tier_period so a carried-forward tier is always labelled with its age.
What is NOT merged across periods: revenue_share / cumulative_share /
boundary_flag are per-run facts, so tier_summary.revenue_share_total sums
current-run rows only. The default view is unchanged, so existing callers
and tests see exactly what they did before.

PREVIEW (2026-09-23, X-Data-Mode: preview, backend/data_mode.py): no stored
run covers Unilever's 2021-22 placeholder months, so for those months the
tiers are computed on request with the ABC run's own steps and never
written. A month in the window resolves to that month's computed run;
last_known also sees each product's newest placeholder tier, so a product
whose only tiers are placeholder ones is listed, labelled by its
tier_period. A month a stored run covers reads the stored run, unchanged.
Stock and target stock stay real — there is no placeholder stock.

TARGET STOCK (2026-09-30): rop_i is the LP's order-up-to "target stock"
since the 2026-09-30 run, so this module's text says target stock where it
said reorder point. Field names (reorder_point in SQL, 'NO ROP') are kept
because other pages read them.

WHY NO TARGET (2026-10-01): 50 of February's 132 Class A SKUs read "No
target stock" with nothing saying why, and the page told readers the LP
plans Class A — so those looked like a fault. The LP's pool is narrower:
Class A of the latest ABC run whose latest forecast is status 'ok' with
MASE < 1 (scripts/run_lp.py CANDIDATE_QUERY). Of the 132, 46 failed MASE < 1
and 13 had too little history ('insufficient_data'). Every row with no
target now carries the reason, read from the same tables the LP pool is.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.data_mode import (
    PREVIEW,
    REAL,
    abc_relation,
    abc_single,
    forecast_source,
    get_data_mode,
    latest_per_product,
    placeholder_months,
    lp_source,
    placeholder_window,
    preview_block,
)
from backend.deps import TokenPayload, get_db
from backend.permissions import can_see_lp, require_permission
from backend.lp_cycle import PLAN_STATUS_SQL_BARE, current_cycle
from backend.principals import (
    PrincipalQuery,
    abc_period_params,
    abc_period_pred,
    latest_abc_periods,
    normalize_principal,
    principal_clause,
    tier_a_periods,
)
from backend.stock_status import CRITICAL, NO_DATA, stock_status
from backend.stock_units import STOCK_AT_LATEST_SQL
# The stock count's own date (routers/sku.py, 2026-10-03): GET /sku and GET
# /abc state the same count, so they share the one query rather than each
# keeping a copy that could name a different day.
from backend.routers.sku import STOCK_COUNT_DATE_SQL, stock_count_dates
from analytics.classification.abc import abc_rules, pareto_check
from analytics.params import abc_method_sql
from backend.abc_basis import abc_page_basis
from backend.schemas.abc import ABCItem, ABCResponse, ABCRules, ParetoCheck, TierSummary
from backend.response_cache import cached

router = APIRouter(prefix="/abc", tags=["abc"])

# The fewest ranked items an 80/20 check is run on. The check compares the
# top fifth of items with the rest, and the top fifth rounds UP to whole
# items: below 10 it is one or two items (one for 1-5, two for 6-9), so pass
# or fail would describe the biggest one or two items' share, not how revenue
# spreads across many. Del Monte's runs since its Jan 2025 regrouping rank
# 4-5 top-level categories (DEC-03), and the page called 4 categories a
# failed 80/20 split ("1 of 4 earns 71.1%"). At 10 the top fifth is exactly
# 20% of the items. Unilever ranks hundreds of SKUs a month, far above it.
PARETO_MIN_ITEMS = 10

# The LP's forecast-accuracy gate (scripts/run_lp.py MASE_GATE, the same
# 1.0 as analytics/forecasting/baseline.py's MASE_GATE and the dashboard's
# MASE_UNRELIABLE_GATE): a forecast enters the plan only if it beat a naive
# repeat-last-month forecast, MASE < 1. Restated rather than imported because
# run_lp.py pulls in the pulp solver and baseline.py statsmodels, batch-job
# dependencies the API doesn't need (and importing a sibling router for one
# number would couple the two); tests/backend/test_abc.py pins it to
# baseline.MASE_GATE.
LP_MASE_GATE = 1.0

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _month_label(period: str) -> str:
    """'2026-02' -> 'Feb 2026', as the page writes months."""
    year, month = period.split("-")[:2]
    return f"{_MONTHS[int(month) - 1]} {year}"


def _no_target_reason(r, tier: str, tier_period: str | None, *, has_cycle: bool) -> tuple[str | None, str | None]:
    """(reason, code) for a row the LP's current cycle gives no target stock.

    Follows the LP's own pool rule (scripts/run_lp.py CANDIDATE_QUERY): Class
    A of the principal's LATEST ABC run (pool_tier / pool_period), then a
    forecast with status 'ok' and MASE < LP_MASE_GATE (fc_status / fc_mase,
    the product's latest Forecast_Result row). The pool tier is used rather
    than the row's own: a row carried forward, or shown for an earlier month,
    can be Class A on the page and still be outside the plan.

    The row's columns are read with .get(): with no pool columns at all the
    row's own tier stands in, which is what it is whenever the page shows the
    latest run."""
    noun = "category" if r.get("principal") == "delmonte" else "SKU"
    pool_period = r.get("pool_period")
    pool_tier = r.get("pool_tier") if pool_period else tier
    if pool_tier != "A":
        if pool_period is None or (pool_tier == tier and tier_period == pool_period):
            return "Not planned: the reorder plan covers Class A only", "not_class_a"
        if pool_tier is None:
            return (
                f"Not planned: the reorder plan covers Class A of the {_month_label(pool_period)} ranking, "
                f"and this {noun} had no sales that month",
                "not_ranked",
            )
        return (
            f"Not planned: the reorder plan covers Class A only, and this {noun} is Class {pool_tier} "
            f"in the {_month_label(pool_period)} ranking",
            "not_class_a",
        )
    if not has_cycle:
        return "Not planned: there is no current reorder plan for it", "no_plan"
    status, mase = r.get("fc_status"), r.get("fc_mase")
    mase = float(mase) if mase is not None else None
    if status is None:
        return "Not planned: no forecast exists for it", "no_forecast"
    if status == "insufficient_data":
        return "Not planned: too little sales history to forecast", "short_history"
    if status == "dead_sku":
        return "Not planned: no recent sales to forecast from", "no_recent_sales"
    if status == "fit_failed":
        return "Not planned: the forecast could not be produced", "forecast_failed"
    if status == "unreliable" or (mase is not None and mase >= LP_MASE_GATE):
        # Three decimals right at the gate, as SKUForecast.jsx shows it, so
        # 1.004 doesn't read "1.00" next to a "below 1" rule.
        figure = f" (MASE {mase:.{3 if abs(mase - 1) < 0.01 else 2}f})" if mase is not None else ""
        return f"Not planned: forecast accuracy check not passed{figure}", "accuracy"
    if mase is None:
        return "Not planned: forecast accuracy could not be measured", "not_measured"
    # Passes both checks yet has no row in the cycle: the plan was built
    # before this forecast or ranking. Said as such, never guessed past.
    return "Not in the current reorder plan, although its forecast passes the accuracy check", "not_in_plan"


def _tier_shares(current: list[ABCItem]) -> dict[str, float] | None:
    """Each tier's share of the run's revenue, from the stored running total
    at each tier's boundary: A = A's last cumulative share, B = B's last
    minus A's, C = C's last minus B's.

    Summing per-row shares, as this did until 2026-10-01, adds up values
    each rounded to 4 dp: Unilever's 2026-02 Class B summed to 0.1493 and
    read 14.9%, where its revenue is 14.99% of the month (0.9498 - 0.7999 =
    0.1499 from the running total, rounded once). None — fall back to the
    sum — when a row has no cumulative share, the boundaries are out of
    tier order, or a tier is not one unbroken block of the ranking, so a run
    without a consistent running total is never differenced into nonsense.

    The unbroken-block case is Unilever's 12-month Tier A basis (migration
    0044): the tier is set on 12 months but the running total ranks one
    month, so Class A rows sit as deep as 0.9465 with Class B rows above
    them. Differencing read A 94.7% / B 0.3% / C 5.0% for 2026-02, where the
    rows' own shares add up to 81.0% / 14.0% / 4.6% (found 2026-10-12)."""
    if not current or any(i.cumulative_share is None for i in current):
        return None
    bounds: dict[str, float] = {}
    lowest: dict[str, float] = {}
    for item in current:
        share = float(item.cumulative_share)
        bounds[item.tier] = max(bounds.get(item.tier, 0.0), share)
        lowest[item.tier] = min(lowest.get(item.tier, share), share)
    ordered = sorted(bounds)  # 'A' < 'B' < 'C'
    if any(bounds[a] > bounds[b] or lowest[b] < bounds[a] for a, b in zip(ordered, ordered[1:])):
        return None
    shares, previous = {}, 0.0
    for tier in ordered:
        shares[tier] = round(bounds[tier] - previous, 6)
        previous = bounds[tier]
    return shares


def _pareto(current: list[ABCItem]) -> ParetoCheck | None:
    """pareto_check for one principal's run, or 'not_applicable' below
    PARETO_MIN_ITEMS. The cumulative shares go along so the check reads the
    top items' share off one stored running total instead of summing ~140
    separately rounded shares (see pareto_check)."""
    check = pareto_check([i.revenue_share for i in current], [i.cumulative_share for i in current])
    if check is None:
        return None
    ranked = check["ranked_count"]
    if ranked < PARETO_MIN_ITEMS:
        many = "categories" if current[0].principal == "delmonte" else "SKUs"
        return ParetoCheck(
            **{**check, "passes": None},
            status="not_applicable",
            min_items=PARETO_MIN_ITEMS,
            reason=(
                f"Too few {many} for an 80/20 check ({ranked} ranked; it needs at least {PARETO_MIN_ITEMS}). "
                f"With so few, the top fifth is only one or two {many}, which says nothing about how "
                f"revenue is spread."
            ),
        )
    return ParetoCheck(**check, status="pass" if check["passes"] else "fail", min_items=PARETO_MIN_ITEMS)


def _summarize(items: list[ABCItem], periods: dict[str, str]) -> tuple[list[TierSummary], ParetoCheck | None]:
    """tier_summary plus the run's Pareto check (manuscript §3.4.4.2.2).
    Only CURRENT-run rows feed shares: a carried-forward row's revenue_share
    is a fraction of another month's revenue. The shares and the check need
    one principal — two principals' shares are fractions of two different
    totals, and their running totals interleave."""
    summary: dict[str, TierSummary] = {}
    one_principal = len({i.principal for i in items if i.tier_period == periods.get(i.principal)}) == 1
    # "Current" is each row's OWN principal's run: under 'all' the two
    # principals' latest runs differ (Unilever 2026-02, Del Monte 2025-12).
    def is_current(i: ABCItem) -> bool:
        return i.tier_period == periods.get(i.principal)

    current = [i for i in items if is_current(i)]
    for item in items:
        entry = summary.setdefault(item.tier, TierSummary(tier=item.tier, sku_count=0, revenue_share_total=0.0))
        entry.sku_count += 1
        if is_current(item) and one_principal:
            entry.revenue_share_total += item.revenue_share or 0.0
        else:
            entry.carried_forward_count += 1
    shares = _tier_shares(current) if one_principal else None
    for entry in summary.values():
        ranked_here = entry.sku_count - entry.carried_forward_count
        entry.sku_share = round(ranked_here / len(current), 6) if current and one_principal else None
        if shares is not None:
            entry.revenue_share_total = shares.get(entry.tier, 0.0)
        elif not one_principal:  # audit 2026-10-23 finding 5: a sum over two principals is ~200%, not a share
            entry.revenue_share_total = None
    check = _pareto(current) if one_principal else None
    return sorted(summary.values(), key=lambda t: t.tier), check


def _stock_status(
    stock_pieces: float | None, safety_stock: float | None, target_stock: float | None, has_stock_row: bool,
) -> str:
    """backend/stock_status.py's one rule, in PIECES (backend/stock_units.py),
    against the LP's current-cycle ss_i and target stock rop_i: CRITICAL
    below ss_i, LOW below rop_i, IN STOCK at or above it. The LP's current
    cycle plans only Class A SKUs whose forecast passed the accuracy check,
    so every B and C product (and every Del Monte one) and part of Class A
    read NO ROP when they have a stock row — with the reason, see
    _no_target_reason — and NO DATA only when they have none. Until
    2026-09-30 this route had its own rule (CRITICAL at <= 0, IN STOCK
    above rop_i, else LOW; NO ROP without one)."""
    return stock_status(stock_pieces, safety_stock, target_stock, has_stock_row)


def _status_for(
    stock_pieces: float | None, safety_stock: float | None, target_stock: float | None, has_stock_row: bool,
    lp_visible: bool,
) -> str:
    """_stock_status for a user with lp.view. Without it, the shared rule's
    statuses would reveal the LP's figures (CRITICAL below ss_i, LOW below
    the target stock, IN STOCK, and NO ROP: whether the LP plans the
    product), so such a user sees only what the stock count itself says:
    NO DATA (no figure in pieces), CRITICAL (nothing on hand — being out of
    stock reveals no LP figure), else ON HAND (Yuan's permissions proposal:
    LP figures follow lp.view everywhere)."""
    if lp_visible:
        return _stock_status(stock_pieces, safety_stock, target_stock, has_stock_row)
    if stock_pieces is None:
        return NO_DATA
    return CRITICAL if stock_pieces <= 0 else "ON HAND"


def _plan_pool_joins(fc_src: str) -> str:
    """The columns _no_target_reason reads, joined onto `ac`: the product's
    tier in its principal's LATEST stored ABC run (pool_tier, pool_period)
    and its latest forecast (fc_status, fc_mase) — the two tests the LP's
    candidate pool applies (scripts/run_lp.py CANDIDATE_QUERY). Stored ABC
    on purpose: the plan is built from stored runs, never from a preview
    month's computed one. Columns are qualified (MAX(m.classification_period))
    so this subquery reads as what it is, not as latest_abc_period's lookup."""
    return f"""
        LEFT JOIN (
            SELECT m.principal, MAX(m.classification_period) AS p
            FROM abc_classification m
            WHERE {abc_method_sql("m")}
            GROUP BY m.principal
        ) pool_run ON pool_run.principal = ac.principal
        LEFT JOIN abc_classification pool
               ON pool.product_key = ac.product_key
              AND pool.classification_period = pool_run.p
              AND {abc_method_sql("pool")}
        LEFT JOIN (
            SELECT DISTINCT ON (f.product_key) f.product_key, f.status, f.mase
            FROM {fc_src} f
            ORDER BY f.product_key, f.forecast_date DESC, f.generated_at DESC
        ) fc ON fc.product_key = ac.product_key
    """


_PLAN_POOL_COLUMNS = """,
            pool_run.p AS pool_period,
            pool.tier AS pool_tier,
            fc.status AS fc_status,
            fc.mase AS fc_mase"""


def _item(r, tier_period: str | None, *, lp_visible: bool, has_cycle: bool) -> ABCItem:
    """One ABCItem from a row of either view's query."""
    stock = float(r["current_stock"]) if r["current_stock"] is not None else None
    target = float(r["reorder_point"]) if r["reorder_point"] is not None else None
    safety = float(r["safety_stock"]) if r["safety_stock"] is not None else None
    reason, code = (
        _no_target_reason(r, r["tier"], tier_period, has_cycle=has_cycle)
        if lp_visible and target is None else (None, None)
    )
    return ABCItem(
        product_key=r["product_key"],
        sku_id=r["sku_id"] or "",
        product_name=r["product_name"],
        principal=r["principal"],
        tier=r["tier"],
        tier_period=tier_period,
        revenue_share=r["revenue_share"],
        cumulative_share=r["cumulative_share"],
        boundary_flag=bool(r["boundary_flag"]),
        current_stock=stock,
        stock_status=_status_for(stock, safety, target, bool(r["has_stock_row"]), lp_visible),
        no_target_reason=reason,
        no_target_code=code,
    )


@router.get("", response_model=ABCResponse)
@cached("GET /abc")
def get_abc(
    classification_period: str | None = Query(
        None,
        description="'YYYY-MM'. Resolves to the latest classified period at or before it, per principal; "
        "omit for the latest period present.",
    ),
    principal: str | None = PrincipalQuery,
    view: Literal["period", "last_known"] = Query(
        "period",
        description="'period' (default): only SKUs ranked in that run. "
        "'last_known': every product's most recent tier at or before it, with tier_period.",
    ),
    mode: str = Depends(get_data_mode),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_permission("abc.view", "forecast.view")),
) -> ABCResponse:
    # The placeholder is Unilever's, so a Del Monte-only request has nothing
    # to add and reads exactly as in real mode.
    window = (
        placeholder_window(db)
        if mode == PREVIEW and normalize_principal(principal) in (None, "unilever")
        else None
    )
    # Without lp.view the stock status can't be judged against the LP's
    # target stock in the user's sight (see _status_for).
    lp_visible = can_see_lp(db, current_user)
    if view == "last_known":
        return _with_data_mode(
            _get_abc_last_known(db, classification_period, principal, window, mode, lp_visible=lp_visible), db, mode,
        )
    return _with_data_mode(
        _get_abc_period(db, classification_period, principal, window, mode, lp_visible=lp_visible), db, mode,
    )


def _with_data_mode(response: ABCResponse, db: Session, mode: str):
    """Real mode returns the model untouched. Preview adds the data_mode
    block beside it, so a preview payload says so and a real one is
    unchanged."""
    if mode != PREVIEW:
        return response
    return JSONResponse({**jsonable_encoder(response), "data_mode": preview_block(db)})


def _get_abc_period(
    db: Session, classification_period: str | None, principal: str | None, window: dict | None = None,
    mode: str = REAL, *, lp_visible: bool = True,
) -> ABCResponse:
    """view=period — the SKUs ranked in one run."""
    # The row query reads under the same principal scope the period is
    # resolved under — resolving the latest period under a different scope
    # than the rows are read under is exactly how an empty page gets
    # rendered for a principal that does have data.
    _, scope_params = principal_clause(principal, "principal")

    # The page always sends a month, and each principal has its own latest
    # run (Del Monte's is 2025-12 while Unilever's is 2026-02). An exact
    # match on the requested month therefore returned nothing for Del Monte
    # at 2026-02. Resolve to the latest classified period AT OR BEFORE the
    # request instead — the same helper view=last_known already uses; with
    # no month given it is the plain latest period, as before.
    periods = latest_abc_periods(db, principal, at_or_before=classification_period)
    period = max(periods.values()) if periods else None  # the response field / gate only
    abc_source, source_params = "abc_classification", {}
    # Preview: no stored run at or before a placeholder month, so that
    # month's run is computed now (backend/data_mode.abc_single).
    if period is None and window and classification_period and classification_period >= window["start"]:
        month = min(classification_period, window["end"])
        computed = abc_single(db, [month], PREVIEW)
        if not computed.empty:
            period = month
            periods = {"unilever": month}
            abc_source, source_params = abc_relation(computed, with_stored=False)
    if period is None:
        return ABCResponse(items=[], count=0, classification_period=None, tier_summary=[], basis=abc_page_basis(principal),
                           rules=ABCRules(**abc_rules()))
    # The target stock each row's stock status is judged against: the LP's
    # own, or in preview with built outputs the five-year what-if's.
    lp_src, lp_params = lp_source(mode, "lp_recommendation")
    fc_src, fc_params = forecast_source(mode, "forecast_result")
    # The LP's current cycle only, like every other LP read
    # (backend/lp_cycle.py): the newest pending row from ANY cycle let a
    # three-year-old superseded run supply the target stock.
    cycle = current_cycle(db, principal, mode)

    query = f"""
        SELECT
            ac.product_key,
            COALESCE(pd.sku_code, pd.category_path, '') AS sku_id,
            pd.product_name,
            ac.principal,
            ac.tier,
            ac.revenue_share,
            ac.cumulative_share,
            ac.boundary_flag,
            inv.stock_pieces AS current_stock,
            inv.product_key IS NOT NULL AS has_stock_row,
            rop.rop_i AS reorder_point,
            rop.ss_i AS safety_stock,
            stock_count.count_date AS stock_count_date{_PLAN_POOL_COLUMNS}
        FROM {abc_source} ac
        JOIN product_dimension pd ON pd.product_key = ac.product_key
        LEFT JOIN ({STOCK_AT_LATEST_SQL}) inv ON inv.product_key = ac.product_key
        LEFT JOIN ({STOCK_COUNT_DATE_SQL}) stock_count ON stock_count.principal = ac.principal
        LEFT JOIN (
            SELECT product_key, rop_i, ss_i
            FROM {lp_src}
            WHERE {PLAN_STATUS_SQL_BARE} AND planning_cycle_date = :current_cycle
        ) rop ON rop.product_key = ac.product_key
        {_plan_pool_joins(fc_src)}
        WHERE {abc_period_pred("=", "ac")} AND {abc_method_sql("ac")}
    """
    query += principal_clause(principal, "ac.principal")[0]
    # product_key last: equal shares otherwise come back in whatever order the
    # joins leave them, so the list reshuffled between loads (2026-10-02).
    query += " ORDER BY ac.tier, ac.revenue_share DESC NULLS LAST, ac.product_key"

    params: dict = {
        **abc_period_params(periods),
        "current_cycle": cycle,
        **scope_params,
        **source_params,
        **lp_params,
        **fc_params,
    }

    rows = db.execute(text(query), params).mappings().all()
    items = [_item(r, periods.get(r["principal"]), lp_visible=lp_visible, has_cycle=cycle is not None) for r in rows]

    tier_summary, check = _summarize(items, periods)
    return ABCResponse(
        items=items,
        count=len(items),
        classification_period=period,
        tier_a_periods=tier_a_periods(periods),
        tier_summary=tier_summary,
        basis=abc_page_basis(principal),
        rules=ABCRules(**abc_rules()),
        pareto_check=check,
        stock_count_dates=stock_count_dates(rows),
        planning_cycle_date=cycle if lp_visible else None,
    )


# Del Monte categories that stopped existing (audit BE-3, 2026-10-20). The January 2025 regrouping replaced
# ~80 sub-category paths with five categories and there is no mapping between them (DEC-03), so an old path's
# last real sell-out month is also its last month as a series. view=last_known used to carry its tier forward
# to the anchor, and the page (finding no sales for it in the FSN window) labelled 79-80 of them "Non-moving":
# they are not non-moving, they no longer exist. A series gets no row after its own last real observation,
# as it gets none before its first.
#
# "Retired" = carried (its last real month is before the anchor) AND of the old vocabulary, meaning it first
# sold before the earliest first month of the categories still selling at the principal's latest real month
# (2025-03 today, read from the data, not typed). DAIRY's real data also stops early (2025-06) but it IS the
# new vocabulary, so it is a collection gap, not a retirement, and stays. Unilever is never touched: a SKU that
# stops selling while stock is on hand is genuinely non-moving.
_DM_SERIES_CTES = """dm_span AS (
            SELECT product_key, MIN(_period) AS first_real, MAX(_period) AS last_real
            FROM sellout_fact_real GROUP BY product_key
        ), dm_vocab AS (
            SELECT MIN(first_real) AS starts FROM dm_span
            WHERE last_real = (SELECT MAX(last_real) FROM dm_span)
        )"""
_DM_RETIRED_PRED = """COALESCE(ac.principal = 'delmonte'
                AND dm_span.last_real < :dm_anchor
                AND dm_span.first_real < (SELECT starts FROM dm_vocab), FALSE)"""


def _get_abc_last_known(
    db: Session, classification_period: str | None, principal: str | None, window: dict | None = None,
    mode: str = REAL, *, lp_visible: bool = True,
) -> ABCResponse:
    """view=last_known — every product's most recent 'single' tier at or
    before the anchor period, the same rule GET /sku uses.

    The anchor is the newest run AT OR BEFORE the requested month (not an
    exact match), so a month past the latest run — the ABC page seeds from
    the dashboard's end month, which routinely runs ahead of it — lands on
    the nearest real run instead of an empty page. It stays an upper bound:
    no tier from a later run can appear.
    """
    periods = latest_abc_periods(db, principal, at_or_before=classification_period)
    period = max(periods.values()) if periods else None  # the response field / gate only
    abc_source, source_params = "abc_classification", {}
    # Preview: every product's newest placeholder tier joins the stored runs.
    # Stored runs are all later than the placeholder, so a product with a
    # stored tier keeps it; the anchor only falls back to a placeholder month
    # when no stored run is at or before the request.
    if window:
        computed = latest_per_product(abc_single(db, placeholder_months(window, classification_period), PREVIEW))
        if not computed.empty:
            abc_source, source_params = abc_relation(computed, with_stored=True)
            if period is None:
                period = computed["classification_period"].max()
                periods = {"unilever": period}

    pd_scope_sql, pd_scope_params = principal_clause(principal, "pd.principal")
    # Never-ranked products: counted, not listed. Listing them would add
    # Del Monte's ~15k tierless rows to a page about tiers; the count is what
    # tells the reader how much of the product master ABC does not cover.
    unclassified_sql = (
        "SELECT COUNT(*) AS n FROM product_dimension pd WHERE NOT EXISTS ("
        f" SELECT 1 FROM {abc_source} a WHERE a.product_key = pd.product_key"
        f" AND {abc_method_sql('a')}"
        f" AND (CAST(:period AS TEXT) IS NULL OR {abc_period_pred('<=', 'a')}))"
        + pd_scope_sql
    )
    unclassified = db.execute(
        text(unclassified_sql), {"period": period, **abc_period_params(periods), **pd_scope_params, **source_params}
    ).mappings().first()
    unclassified_count = int(unclassified["n"]) if unclassified else 0

    if period is None:
        return ABCResponse(
            items=[], count=0, classification_period=None, tier_summary=[], basis=abc_page_basis(principal),
            rules=ABCRules(**abc_rules()), unclassified_count=unclassified_count,
        )

    ac_scope_sql, ac_scope_params = principal_clause(principal, "principal")
    lp_src, lp_params = lp_source(mode, "lp_recommendation")
    fc_src, fc_params = forecast_source(mode, "forecast_result")
    cycle = current_cycle(db, principal, mode)
    # The method pin inside the DISTINCT ON is what keeps this one row per
    # product_key (migration 0017) — see the module docstring. Each
    # principal's own Tier A basis (analytics.params.abc_method_sql).
    query = f"""
        WITH latest AS (
            SELECT DISTINCT ON (product_key)
                   product_key, principal, tier, revenue_share,
                   cumulative_share, boundary_flag, classification_period
            FROM {abc_source}
            WHERE {abc_method_sql()} AND {abc_period_pred("<=")}{ac_scope_sql}
            ORDER BY product_key, classification_period DESC
        ),
        {_DM_SERIES_CTES}
        SELECT
            ac.product_key,
            COALESCE(pd.sku_code, pd.category_path, '') AS sku_id,
            pd.product_name,
            ac.principal,
            ac.tier,
            ac.classification_period AS tier_period,
            ac.revenue_share,
            ac.cumulative_share,
            ac.boundary_flag,
            inv.stock_pieces AS current_stock,
            inv.product_key IS NOT NULL AS has_stock_row,
            rop.rop_i AS reorder_point,
            rop.ss_i AS safety_stock,
            stock_count.count_date AS stock_count_date,
            {_DM_RETIRED_PRED} AS retired_series{_PLAN_POOL_COLUMNS}
        FROM latest ac
        JOIN product_dimension pd ON pd.product_key = ac.product_key
        LEFT JOIN dm_span ON dm_span.product_key = ac.product_key
        LEFT JOIN ({STOCK_AT_LATEST_SQL}) inv ON inv.product_key = ac.product_key
        LEFT JOIN ({STOCK_COUNT_DATE_SQL}) stock_count ON stock_count.principal = ac.principal
        LEFT JOIN (
            SELECT product_key, rop_i, ss_i
            FROM {lp_src}
            WHERE {PLAN_STATUS_SQL_BARE} AND planning_cycle_date = :current_cycle
        ) rop ON rop.product_key = ac.product_key
        {_plan_pool_joins(fc_src)}
        ORDER BY ac.tier,
                 ({abc_period_pred("=", "ac")}) DESC,
                 ac.classification_period DESC,
                 ac.revenue_share DESC NULLS LAST,
                 ac.product_key
    """
    params: dict = {
        **abc_period_params(periods),
        "current_cycle": cycle,
        **ac_scope_params,
        **source_params,
        **lp_params,
        **fc_params,
        "dm_anchor": periods.get("delmonte") or "",
    }
    all_rows = db.execute(text(query), params).mappings().all()
    # A retired Del Monte category (see _DM_RETIRED_PRED) is not carried past its last real month, so it is
    # neither listed nor read as "Non-moving" on the strength of a tier it earned before it stopped existing.
    rows = [r for r in all_rows if not r["retired_series"]]
    retired_count = len(all_rows) - len(rows)

    items = [_item(r, r["tier_period"], lp_visible=lp_visible, has_cycle=cycle is not None) for r in rows]

    tier_summary, check = _summarize(items, periods)
    return ABCResponse(
        items=items,
        count=len(items),
        retired_series_count=retired_count,
        classification_period=period,
        tier_a_periods=tier_a_periods(periods),
        tier_summary=tier_summary,
        basis=abc_page_basis(principal),
        unclassified_count=unclassified_count,
        rules=ABCRules(**abc_rules()),
        pareto_check=check,
        stock_count_dates=stock_count_dates(rows),
        planning_cycle_date=cycle if lp_visible else None,
    )
