"""
backend.routers.dashboard_range — the detail behind GET /dashboard's range cards, read from
the `mart` schema (migration 0041, backend/marts.py).

    GET /dashboard/pareto         every product ranked on the range: rank, class, revenue,
                                  share, cumulative share; the product list per class
    GET /dashboard/yoy            per product, the range's real sales against the same months
                                  a year earlier
    GET /dashboard/accuracy       forecast vs actual per product or category, with the signed
                                  miss in pieces and pesos; two labelled headline figures,
                                  company_total and typical_product_weighted
    GET /dashboard/error-decomposition[/product/{sku}|/aggregate|/concentration]  the forecast miss split into
                                  over, absorbed by safety stock and beyond it
    GET /dashboard/class-changes  products that entered or left Class A between two ranges,
                                  with their revenue change
    GET /dashboard/idle-stock     products in the count at the range's end with no sale in the
                                  6 sales months up to it
    GET /dashboard/stock-detail   every product in the count at the range's end: stock value,
                                  weekly sales, weeks of cover, pesos above SSM's 3-week rule
    GET /dashboard/product-sales  product x month sales, real and filled, each labelled (Del
                                  Monte's product split, DEC-31, is served here: hole H4)
    GET /dashboard/forecast-runs  the forecast history the accuracy figures come from

Every endpoint takes the same range as GET /dashboard: `period` (the picker's end month) and
`start_period` (its start); without a start, the 12 months ending at `period`; without
`period`, ending at the scope's latest month of real sales. Real rows only, except where a
row says data_kind / estimated. Nothing here is derived from LP_Recommendation, so none of
it needs lp.view.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from analytics.classification.abc import TIER_A_CUTOFF, TIER_B_CUTOFF, pareto_check
from analytics.params import DEAD_SKU_MONTHS, REVIEW_OVER_RUN_MONTHS
from backend import batch, marts
from backend.data_mode import PREVIEW, get_data_mode, preview_block
from backend.deps import TokenPayload, get_db
from backend.permissions import require_permission
from backend.principals import PrincipalQuery, normalize_principal
from analytics.params import COVER_KPI_HISTORY_MONTHS, POLICY_COVER_WEEKS, WEEKS_PER_MONTH
from backend.routers.dashboard import _last_12_periods, _latest_sales_period, _month_range, _resolve_sales_anchor
from backend.series_gaps import gap_note

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

PERIOD = r"^\d{4}-(0[1-9]|1[0-2])$"
PeriodQuery = Query(None, pattern=PERIOD, description="'YYYY-MM': the range's end month.")
StartQuery = Query(None, pattern=PERIOD, description="'YYYY-MM': the range's first month.")


def resolve_range(db: Session, period: str | None, start_period: str | None, scope: str) -> tuple[str, str]:
    """(start, end) exactly as GET /dashboard resolves its window."""
    periods = (
        _month_range(start_period, _resolve_sales_anchor(db, period, scope))
        if start_period is not None
        else _last_12_periods(db, period, scope)
    )
    return periods[0], periods[-1]


def _principals(scope: str) -> list[str]:
    return ["unilever", "delmonte"] if scope == "all" else [scope]


@router.get("/pareto")
def get_range_pareto(
    period: str | None = PeriodQuery,
    start_period: str | None = StartQuery,
    principal: str | None = PrincipalQuery,
    mode: str = Depends(get_data_mode),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_permission("dashboard.view")),
) -> dict:
    """Each principal ranked against its own revenue: Unilever by SKU, Del Monte by product
    category (DEC-03), with the ABC run's rules applied to the range: a month where returns
    exceeded sales counts as 0, so ranked_revenue can sit above net_sales."""
    scope = normalize_principal(principal) or "all"
    start, end = resolve_range(db, period, start_period, scope)
    out = []
    for who in _principals(scope):
        rows = marts.pareto(db, start, end, who, mode)
        total = sum(r["revenue"] for r in rows)
        classes = []
        for tier in ("A", "B", "C"):
            members = [r for r in rows if r["class"] == tier]
            revenue = sum(r["revenue"] for r in members)
            classes.append({
                "tier": tier, "count": len(members), "revenue": round(revenue, 2),
                "share": round(revenue / total, 6) if total > 0 else None,
                "products": [{k: r[k] for k in ("rank", "product_key", "sku_id", "product_name", "category_path",
                                                 "revenue", "pieces", "share", "cumulative_share",
                                                 "months_with_sales")} for r in members],
            })
        out.append({
            "principal": who,
            "grain": "category" if who == "delmonte" else "sku",
            "ranked_count": len(rows),
            "ranked_revenue": round(total, 2),
            "net_sales": marts.net_sales_total(db, start, end, who, mode),
            "pesos_basis": marts.PESOS_BASIS_LABEL["ex_vat" if who == "delmonte" else "vat_inclusive"],
            "pareto_check": pareto_check([r["share"] for r in rows], [r["cumulative_share"] for r in rows]),
            "classes": classes,
            "blocked_reason": None if rows else marts.pareto_blocked_reason(db, start, end, who, mode),
        })
    payload = {"start_period": start, "end_period": end, "label": marts.range_label(start, end),
               "cutoffs": {"A": TIER_A_CUTOFF, "B": TIER_B_CUTOFF}, "principals": out}
    if mode == PREVIEW:
        payload["data_mode"] = preview_block(db)
    return payload


@router.get("/yoy")
def get_range_yoy(
    period: str | None = PeriodQuery,
    start_period: str | None = StartQuery,
    principal: str | None = PrincipalQuery,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_permission("dashboard.view")),
) -> dict:
    """Per product (Del Monte: category), real sales over the range against the same months
    a year earlier. A side with no real month is null, never 0; months / prior_months say
    how many months each side has."""
    scope = normalize_principal(principal) or "all"
    start, end = resolve_range(db, period, start_period, scope)
    prior_start, prior_end = marts.month_add(start, -12), marts.month_add(end, -12)
    out = []
    for who in _principals(scope):
        rows = marts.product_yoy(db, start, end, who)
        cur = [r["pesos"] for r in rows if r["pesos"] is not None]
        prev = [r["prior_pesos"] for r in rows if r["prior_pesos"] is not None]
        out.append({
            "principal": who,
            "grain": "category" if who == "delmonte" else "sku",
            "pesos": round(sum(cur), 2) if cur else None,
            "prior_pesos": round(sum(prev), 2) if prev else None,
            "pesos_basis": marts.PESOS_BASIS_LABEL["ex_vat" if who == "delmonte" else "vat_inclusive"],
            "rows": rows,
        })
    payload = {"start_period": start, "end_period": end, "label": marts.range_label(start, end),
               "prior_start_period": prior_start, "prior_end_period": prior_end,
               "prior_label": marts.range_label(prior_start, prior_end), "principals": out}
    note = gap_note(v for block in out for r in block["rows"] for k, v in r.items() if k.endswith("_reason"))
    if note:
        payload["gap_note"] = note
    return payload


@router.get("/class-changes")
def get_class_changes(
    period: str | None = PeriodQuery,
    start_period: str | None = StartQuery,
    compare_period: str | None = Query(None, pattern=PERIOD, description="'YYYY-MM': the earlier range's end month. "
                                       "Default: the same months a year before the range."),
    compare_start_period: str | None = Query(None, pattern=PERIOD, description="'YYYY-MM': the earlier range's first "
                                             "month. Default: as many months as the range, ending at compare_period."),
    principal: str | None = PrincipalQuery,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_permission("dashboard.view")),
) -> dict:
    """Products that entered or left Class A between two ranges (Del Monte: product
    categories), each range ranked on its own real sales exactly as GET /dashboard/pareto
    ranks it: a month where returns exceeded sales counts as 0 (revenue_rule).
    'entered' = Class A in the range, not in the compare range;
    'left' = the reverse. Each row has both ranges' revenue, class and rank; a side where the
    product was not ranked has class null and says why in class_note / compare_class_note."""
    scope = normalize_principal(principal) or "all"
    start, end = resolve_range(db, period, start_period, scope)
    if compare_period is None:
        if compare_start_period is not None:
            raise HTTPException(status_code=422, detail="compare_start_period needs compare_period (the earlier range's end month).")
        compare_start, compare_end = marts.month_add(start, -12), marts.month_add(end, -12)
    else:
        compare_end = compare_period
        compare_start = compare_start_period or marts.month_add(compare_end, 1 - len(_month_range(start, end)))
        if compare_start > compare_end:
            raise HTTPException(status_code=422, detail="compare_start_period is after compare_period.")
    out = []
    for who in _principals(scope):
        block = marts.class_changes(db, start, end, compare_start, compare_end, who)
        block["pesos_basis"] = marts.PESOS_BASIS_LABEL["ex_vat" if who == "delmonte" else "vat_inclusive"]
        block["blocked_reason"] = None if block["class_a_count"] or block["compare_class_a_count"] else (
            f"No {who} product is ranked in {marts.range_label(start, end)} or "
            f"{marts.range_label(compare_start, compare_end)}.")
        out.append(block)
    return {"start_period": start, "end_period": end, "label": marts.range_label(start, end),
            "compare_start_period": compare_start, "compare_end_period": compare_end,
            "compare_label": marts.range_label(compare_start, compare_end),
            "cutoffs": {"A": TIER_A_CUTOFF, "B": TIER_B_CUTOFF}, "principals": out}


COUNTERFACTUAL_WARNING = ("These forecasts are COUNTERFACTUAL: a backtest of a tier the live runner does not forecast "
                          "(Tier A only). They are not served or deployed accuracy.")


def _flag_counterfactual(body: dict) -> dict:
    """A chosen run whose label says COUNTERFACTUAL (mart.forecast_run, migration 0064) is never read as served accuracy."""
    flagged = any(str(l).startswith("COUNTERFACTUAL") for l in body.get("run_labels") or [])
    return {**body, "counterfactual": flagged, "counterfactual_warning": COUNTERFACTUAL_WARNING if flagged else None}


@router.get("/accuracy")
def get_range_accuracy(
    period: str | None = PeriodQuery,
    start_period: str | None = StartQuery,
    principal: str | None = PrincipalQuery,
    run_id: int | None = Query(None, ge=1, description="A forecast run (GET /dashboard/forecast-runs); "
                                                       "default: the at-the-time backtest, then stored runs."),
    level: str = Query("summary", pattern="^(product|category|summary|total)$",
                       description="Detail rows: per product, per category, or none ('summary'; "
                                   "'total' is its old name and still accepted)."),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_permission("dashboard.view")),
) -> dict:
    """forecast_source says where each forecast came from: 'backtest_recreated' (the 29-month
    backtest regenerated from the production router, scripts/backtest_forecast_run.py) or
    'stored_run' (a forecast_result run kept in the history).

    Two headline figures, always both, each with its plain label (marts.ACCURACY_LABELS):
    company_total (all products summed first) and typical_product_weighted (sales-weighted
    per-product miss). Show the label with the number; neither is 'the total'."""
    level = "summary" if level == "total" else level
    scope = normalize_principal(principal) or "all"
    start, end = resolve_range(db, period, start_period, scope if scope != "delmonte" else "unilever")
    if scope == "delmonte":
        summary = marts.accuracy_summary([], start, end, REVIEW_OVER_RUN_MONTHS)
        summary["blocked_reason"] = ("No product-level forecasts exist for Del Monte: its sales data is "
                                     "category grain, so no per-product forecast is made to check.")
        return {**summary, "level": level, "rows": []}
    if level == "summary":  # nothing per product or category is asked for: the database sums
        agg = marts.accuracy_aggregates_from_query(batch.rows(db, *marts.accuracy_summary_query(start, end, run_id)))
        summary = marts.accuracy_summary_from(agg, start, end, REVIEW_OVER_RUN_MONTHS, review_limit=1000)
        summary["compare_run"] = marts.accuracy_comparison(db, summary)
        return _flag_counterfactual({**summary, "level": level, "rows": [], "coverage": ["unilever"]})
    rows = marts.accuracy_rows(db, start, end, run_id)
    summary = marts.accuracy_summary(rows, start, end, REVIEW_OVER_RUN_MONTHS, review_limit=1000)
    # The unadjusted twin of a calendar-adjusted run (GET /dashboard's forecast_accuracy
    # carries the same), so a caller can fetch the same months before the adjustment.
    summary["compare_run"] = marts.accuracy_comparison(db, summary)
    detail: list[dict] = []
    if level == "category":
        detail = marts.accuracy_by_category(rows)
    elif level == "product":
        keep = ("product_key", "sku_code", "product_name", "category_path", "month", "forecast_source", "run_label",
                "forecast_pieces", "actual_pieces", "ma3_pieces", "miss_pieces", "abs_miss_pieces", "direction",
                "run_length", "price_per_piece", "miss_pesos", "abs_miss_pesos", "surplus_pesos",
                "shortage_pesos", "opening_pieces", "closing_pieces", "possibly_stock_limited", "method", "bin")
        detail = [{k: (float(r[k]) if hasattr(r.get(k), "is_finite") else r.get(k)) for k in keep} for r in rows]
    return _flag_counterfactual({**summary, "level": level, "rows": detail, "coverage": ["unilever"]})


@router.get("/error-decomposition")
def get_error_decomposition(
    period: str | None = PeriodQuery,
    start_period: str | None = StartQuery,
    principal: str | None = PrincipalQuery,
    top: int = Query(10, ge=1, le=100, description="How many products to list by stockout exposure."),
    tier: str = Query("all", pattern="^(all|A|B|C)$", description="Whose products the exposure list and its concentration "
                                                                   "cover; totals and by_tier always show every tier."),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_permission("dashboard.view")),
) -> dict:
    """The forecast miss for the range, split into over-buying, under-forecast that safety stock absorbed, and
    under-forecast beyond safety stock (potential stockout exposure), in pieces and pesos, each as a share of the
    total error and of the total actual; the share of product-months where demand beat the forecast by more than
    safety stock; the same per ABC tier; and the `top` products by exposure (exposure is concentrated, so that list
    is the useful part: see stockout_exposure_concentration).

    Same permission and the same range as GET /dashboard/accuracy, and the same scoring rule (as served, see
    scoring_rule). Kept in mart.error_decomposition, rebuilt with every mart refresh. Safety stock is the stored LP
    figure where one exists and is rebuilt from history otherwise; ss_method says which, per figure. A view of
    existing data: it changes no forecast, safety stock, target or order."""
    scope = normalize_principal(principal) or "all"
    if scope == "delmonte":
        return {"available": False, "coverage": [], "totals": None, "by_tier": [], "monthly": [],
                "top_products_by_stockout_exposure": [],
                "blocked_reason": ("No product-level forecasts exist for Del Monte: its sales data is category grain, "
                                   "so there is no per-product miss to split.")}
    start, end = resolve_range(db, period, start_period, "unilever")
    if not marts.decomposition_available(db):
        return {"available": False, "coverage": ["unilever"], "totals": None, "by_tier": [], "monthly": [],
                "top_products_by_stockout_exposure": [], "period_start": start, "period_end": end,
                "blocked_reason": "The error decomposition mart is not built on this database (migration 0063)."}
    out = marts.error_decomposition(db, start, end, top, tier)
    return {"available": out["totals"] is not None, "coverage": ["unilever"], **out,
            "blocked_reason": None if out["totals"] is not None else "No scored product-months in this range."}


_DM_DECOMP_BLOCKED = {"available": False, "coverage": [],
                      "blocked_reason": ("No product-level forecasts exist for Del Monte: its sales data is category "
                                         "grain, so there is no per-product miss to split.")}


def _decomposition_range(db: Session, period: str | None, start_period: str | None):
    """(start, end), or an unavailable body when the mart is not built."""
    start, end = resolve_range(db, period, start_period, "unilever")
    if not marts.decomposition_available(db):
        return start, end, {"available": False, "coverage": ["unilever"], "period_start": start, "period_end": end,
                            "blocked_reason": "The error decomposition mart is not built on this database (migration 0063)."}
    return start, end, None


@router.get("/error-decomposition/product/{sku_code}")
def get_error_decomposition_product(
    sku_code: str,
    period: str | None = PeriodQuery,
    start_period: str | None = StartQuery,
    principal: str | None = PrincipalQuery,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_permission("dashboard.view")),
) -> dict:
    """One product's forecast miss month by month over the range, split into over, absorbed and beyond safety
    stock, in pieces and pesos, with the range totals. 404 for a SKU not in the product master; a known SKU with no
    scored month returns an empty `months`. Same permission, range and scoring rule as GET /dashboard/error-decomposition."""
    if (normalize_principal(principal) or "all") == "delmonte":
        return _DM_DECOMP_BLOCKED
    start, end, blocked = _decomposition_range(db, period, start_period)
    if blocked:
        return blocked
    out = marts.decomposition_by_product(db, sku_code, start, end)
    if out is None:
        raise HTTPException(status_code=404, detail=f"SKU {sku_code} is not in the product master")
    return {"available": bool(out["months"]), "coverage": ["unilever"], **out,
            "blocked_reason": None if out["months"] else "No scored months for this product in this range."}


@router.get("/error-decomposition/aggregate")
def get_error_decomposition_aggregate(
    period: str | None = PeriodQuery,
    start_period: str | None = StartQuery,
    principal: str | None = PrincipalQuery,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_permission("dashboard.view")),
) -> dict:
    """The range's split per principal and per ABC tier (each tier's row plus an 'all' row), summed from
    mart.error_decomposition. Only Unilever has scored product-months, so Del Monte is unavailable. Tier B and C
    carry counterfactual: true."""
    if (normalize_principal(principal) or "all") == "delmonte":
        return _DM_DECOMP_BLOCKED
    start, end, blocked = _decomposition_range(db, period, start_period)
    if blocked:
        return blocked
    out = marts.decomposition_aggregate(db, start, end)
    return {"available": bool(out["principals"]), "coverage": ["unilever"], **out,
            "blocked_reason": None if out["principals"] else "No scored product-months in this range."}


@router.get("/error-decomposition/concentration")
def get_error_decomposition_concentration(
    period: str | None = PeriodQuery,
    start_period: str | None = StartQuery,
    principal: str | None = PrincipalQuery,
    limit: int = Query(25, ge=1, le=500, description="How many products to list."),
    tier: str = Query("all", pattern="^(all|A|B|C)$", description="Whose products are ranked."),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_permission("dashboard.view")),
) -> dict:
    """Products ranked by pesos beyond safety stock (potential stockout exposure) over the range, with each
    one's share and the running cumulative share of the total, plus how many products make up 50% and 80%. Shares are
    of every product with exposure, not only the `limit` listed."""
    if (normalize_principal(principal) or "all") == "delmonte":
        return _DM_DECOMP_BLOCKED
    start, end, blocked = _decomposition_range(db, period, start_period)
    if blocked:
        return blocked
    out = marts.decomposition_concentration(db, start, end, limit, tier)
    return {"available": out["products_with_exposure"] > 0, "coverage": ["unilever"], **out,
            "blocked_reason": None if out["products_with_exposure"] else "No product has exposure beyond safety stock in this range."}


@router.get("/idle-stock")
def get_idle_stock(
    period: str | None = PeriodQuery,
    principal: str | None = PrincipalQuery,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_permission("dashboard.view")),
) -> dict:
    """Unilever products in its last real count on or before `period` with no piece sold in
    the 6 (DEAD_SKU_MONTHS) sales months up to it, each at last purchase price."""
    scope = normalize_principal(principal) or "all"
    if scope == "delmonte":
        out = marts.idle_stock(db, None)
        out["blocked_reason"] = "Del Monte's sales are by product category, so no product can be shown to have gone unsold."
        return {**out, "window_rule_months": DEAD_SKU_MONTHS}
    end = _resolve_sales_anchor(db, period, "unilever")
    return {**marts.idle_stock(db, marts.stock_period_at_or_before(db, end, "unilever")),
            "window_rule_months": DEAD_SKU_MONTHS}


def stock_detail_for(db: Session, scope: str, range_end: str | None, with_items: bool = True) -> dict:
    """marts.stock_detail at the count GET /dashboard's stock cards read: the latest real
    count on or before the range's end, over the 12 months of sales ending at that count
    (or at the last month with sales before it) — kpis.weeks_of_cover's own window."""
    count_period = marts.stock_period_at_or_before(db, range_end, scope)
    coverage = marts.stock_coverage(db, count_period, scope)
    if len(coverage) != 1:
        return {"principal": scope, "count_period": count_period, "totals": None, "items": [],
                "blocked_reason": "Pick one principal to list its products: their stock counts are separate."}
    who = coverage[0]
    latest = _latest_sales_period(db, who)
    cover_end = min(latest, count_period) if latest and count_period else latest
    window = _month_range(marts.month_add(cover_end, -(COVER_KPI_HISTORY_MONTHS - 1)), cover_end) if cover_end else []
    return marts.stock_detail(db, who, count_period, window, POLICY_COVER_WEEKS, WEEKS_PER_MONTH, with_items)


@router.get("/stock-detail")
def get_stock_detail(
    period: str | None = PeriodQuery,
    start_period: str | None = StartQuery,
    principal: str | None = PrincipalQuery,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_permission("dashboard.view")),
) -> dict:
    """The products behind the Inventory value and Stock cover cards (2026-10-19): each
    product in the stock count at the range's end with its stock value, its weekly sales,
    its weeks of cover and the pesos it holds beyond SSM's 3-week rule. The totals are the
    cards' own figures."""
    scope = normalize_principal(principal) or "all"
    _, end = resolve_range(db, period, start_period, scope)
    return stock_detail_for(db, scope, end)


@router.get("/product-sales")
def get_product_sales(
    period: str | None = PeriodQuery,
    start_period: str | None = StartQuery,
    principal: str = Query(..., pattern="^(unilever|delmonte)$"),
    mode: str = Depends(get_data_mode),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_permission("dashboard.view")),
) -> dict:
    """Product x month rows with their data kind. Del Monte's are the DEC-31 product split
    (its real sell-out divided by stock share): filled, estimated, never a KPI."""
    start, end = resolve_range(db, period, start_period, principal)
    rows = marts.product_sales(db, start, end, principal, mode)
    return {"start_period": start, "end_period": end, "label": marts.range_label(start, end),
            "principal": principal, "estimated_rows": sum(1 for r in rows if r["estimated"]), "rows": rows}


@router.get("/forecast-runs")
def get_forecast_runs(
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_permission("dashboard.view")),
) -> dict:
    return {"runs": marts.accuracy_runs(db), "default_backtest": marts.DEFAULT_BACKTEST_LABEL,
            "marts": marts.status(db)}
