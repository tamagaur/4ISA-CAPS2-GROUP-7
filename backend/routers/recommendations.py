"""
backend.routers.recommendations — GET /recommendations, PATCH /recommendations/{id}

Returns LP-derived replenishment quantities Q_i per SKU, joined to
Product_Dimension for identity and to the latest Inventory_Fact_Real period
for current_stock. urgency is derived from current_stock vs rop_i (same
CRITICAL/URGENT/PLANNED thresholds a reviewer would apply reading the ROP
column), not stored anywhere.

?from=/?to= (shared date-range picker, 2026-09) — OPTIONAL, both must be
given together or neither is used (matching backend/routers/dashboard.py's
own ?period=/?start_period= convention for the same shared picker, just
under from/to naming since this is a plain date-bounded table read, not a
period-anchored trend). Filters on lr.planning_cycle_date
falling within [from, to] inclusive — real, meaningful spread on this
column (34 distinct pending planning_cycle_dates from 2023-05 through
2026-03, confirmed live), unlike GET /forecast's forecast_date which is a
single fixed value for every SKU and can't be meaningfully range-filtered
the same way.

PATCH implements the Accept/Dismiss write-back onto LP_Recommendation.status.
There is no cost/lead-time/reason column on LP_Recommendation — accept/dismiss
reasons stay logged client-side to the audit log, not persisted here.

IMPACT RANKING + COVER (2026-09-18). Live, the latest cycle (2026-03) had
248 of 250 rows CRITICAL and 0 URGENT — a severity that never varies says
nothing, so the page now ranks by business impact instead. Three additions,
each derived only from real columns:

  revenue_share   ABC_Classification.revenue_share at the product's latest
                  single-period run (DISTINCT ON product_key). None when the
                  product was never classified (19 of the 250 live rows).
  stockout_gap    max(0, rop_i - current_stock) when the stock row exists.
  priority_score  revenue_share x stockout_gap — the sort key.

UNITS RECONCILED (2026-09-23). This file used to compare quantity_on_hand
(CASES) against rop_i (PIECES) and said so in a caveat, on the grounds that
pack_size agreed with the pieces column "only ~84% of the time". That was
wrong in a way that mattered: it made 215 of 429 pending rows CRITICAL and
0 URGENT. current_stock now comes from backend/stock_units.py, which
converts the snapshot to pieces (cases x pack_size + the loose remainder)
and returns NULL — urgency 'NO DATA' with a reason — when a product has no
usable pack size, rather than comparing two different units. That module
documents the three live checks that justify trusting pack_size. On the
same data the split becomes 185 CRITICAL / 13 URGENT / 20 PLANNED.
  days_of_cover   The one cover figure that IS unit-consistent: stock at
                  cost (the SOH file's own valuation, backend/stock_units.py;
                  pesos, latest snapshot) / average daily sales value
                  (pesos/day) — where the daily rate is the product's
                  net_amount over the three most recent calendar months
                  present in Unilever_SKU_Demand_Fact_Real, divided by the
                  number of those months and by AVG_DAYS_PER_MONTH. A month
                  the table HAS but this product has no row in counts as 0:
                  the table stores no zero-sale rows, so that month is a
                  month with no sales. (A month missing from the whole table
                  is a gap instead — DEC-29 — which is why the window only
                  takes months the table has.) Until 2026-09-29 those months
                  were averaged out, which overstated the daily rate and
                  understated cover for 24 of the 250 current rows. Exactly
                  the peso basis GET /dashboard's Unilever weeks_of_cover
                  already uses, at SKU grain. Caveat: stock is valued at
                  last purchase cost while sales are at selling price, so
                  cover is understated by the margin — a known bias in one
                  direction, disclosed in the UI tooltip. None (with
                  cover_blocked_reason) when the stock row or its valuation
                  is missing, when the product sold nothing in the window,
                  or when the daily rate is 0 or below. The sales source is
                  Unilever-only, so a Del Monte LP row (none exist live) is
                  honestly blocked.

  current_stock   was COALESCE(..., 0). A product with no Inventory_Fact_Real
                  row at the latest snapshot (39 of the 250 live rows) was
                  read as "0 on hand" and therefore CRITICAL — a fabricated
                  alert. It is now None, and urgency is 'NO DATA'.
"""
from __future__ import annotations

import datetime
import math

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend import audit
from backend.deps import TokenPayload, get_current_user, get_db, require_admin
from backend.principals import (
    PrincipalQuery,
    latest_abc_period,
    latest_inventory_period,
    principal_clause,
)
from backend.schemas.recommendations import RecommendationItem, RecommendationDecision, RecommendationsResponse
from backend.data_mode import PREVIEW, REAL, get_data_mode, lp_source, predictive_preview, preview_block
from backend.lp_cycle import CURRENT_CYCLE_CLAUSE, current_cycle, lp_model_info
from backend.lp_cycle import freshness as lp_freshness
from backend.stock_units import NO_PACK_SIZE_REASON, STOCK_AT_PERIOD_SQL

# Order quantities are counted in whole units rounded UP, the rule the Reorder
# page applies to every row (frontend/src/utils/formatNumber.js wholeUnits),
# so any total computed here equals the sum of the rows a planner sees. The
# epsilon keeps float noise (1782.0000000002) from rounding up a whole unit.
_WHOLE_UNIT_EPSILON = 1e-6


def whole_units(value: float) -> int:
    return math.ceil(value - _WHOLE_UNIT_EPSILON)

router = APIRouter(prefix="/recommendations", tags=["recommendations"])

_SELECT_ONE = f"""
    SELECT
        lr.recommendation_key,
        COALESCE(pd.sku_code, pd.category_path) AS sku_id,
        pd.product_name,
        pd.principal,
        lr.planning_cycle_date,
        lr.q_i,
        lr.rop_i,
        lr.ss_i,
        lr.status,
        inv.stock_pieces AS current_stock,
        inv.stock_cases AS current_stock_cases,
        inv.stock_value_pesos AS stock_value_pesos,
        abc.revenue_share AS revenue_share,
        abc.tier AS tier,
        sales.avg_monthly_sales_pesos AS avg_monthly_sales_pesos
    FROM lp_recommendation lr
    JOIN product_dimension pd ON pd.product_key = lr.product_key
    LEFT JOIN (
        {STOCK_AT_PERIOD_SQL}
    ) inv ON inv.product_key = lr.product_key
    LEFT JOIN (
        SELECT DISTINCT ON (product_key) product_key, revenue_share, tier
        FROM abc_classification
        WHERE method = 'single' AND classification_period = :abc_period
        ORDER BY product_key, classification_period DESC
    ) abc ON abc.product_key = lr.product_key
    LEFT JOIN (
        SELECT recent.product_key, SUM(recent.month_total) / MAX(sales_window.months) AS avg_monthly_sales_pesos
        FROM (
            SELECT product_key, calendar_month, SUM(net_amount) AS month_total
            FROM unilever_sku_demand_fact_real
            WHERE calendar_month IN (
                SELECT DISTINCT calendar_month FROM unilever_sku_demand_fact_real
                ORDER BY calendar_month DESC LIMIT 3
            )
            GROUP BY product_key, calendar_month
        ) recent
        CROSS JOIN (
            SELECT COUNT(*) AS months FROM (
                SELECT DISTINCT calendar_month FROM unilever_sku_demand_fact_real
                ORDER BY calendar_month DESC LIMIT 3
            ) window_months
        ) sales_window
        GROUP BY recent.product_key
    ) sales ON sales.product_key = lr.product_key
"""

_LP_FROM = "FROM lp_recommendation lr"
assert _SELECT_ONE.count(_LP_FROM) == 1


def select_one(mode: str = REAL) -> tuple[str, dict]:
    """_SELECT_ONE and its extra params for `mode`: in preview with built
    outputs its one LP read comes from backend/data_mode.lp_source(); every
    other join (stock, ABC, recent sales) is the real one either way."""
    lp, params = lp_source(mode, "lp_recommendation")
    return (_SELECT_ONE if lp == "lp_recommendation" else _SELECT_ONE.replace(_LP_FROM, f"FROM {lp} lr")), params


# Average days per calendar month (365.25 / 12) — the same "documented
# convention, not a fabricated number" that dashboard.py's
# AVG_WEEKS_PER_MONTH is built from.
AVG_DAYS_PER_MONTH = 365.25 / 12


def _opt_float(row, key) -> float | None:
    """Reads an optional column that older callers/fixtures may not
    project at all (RowMapping and dict both support .get)."""
    val = row.get(key) if hasattr(row, "get") else None
    return None if val is None else float(val)


def _cover(stock_value: float | None, avg_monthly_sales: float | None) -> tuple[float | None, str | None]:
    if stock_value is None:
        return None, "no stock valuation at the latest inventory snapshot (no row, or no unit cost)"
    if avg_monthly_sales is None:
        return None, "no sales rows for this SKU in the three most recent sales months"
    if avg_monthly_sales <= 0:
        return None, "average recent sales value is zero or negative — cannot divide"
    daily = avg_monthly_sales / AVG_DAYS_PER_MONTH
    return round(stock_value / daily, 1), None


def _to_item(r) -> RecommendationItem:
    # current_stock is PIECES (backend/stock_units.py), the same unit as
    # rop_i. Until 2026-09-23 this read quantity_on_hand — CASES — straight
    # off the snapshot and compared it with a piece-scale ROP, which made
    # almost every row CRITICAL. Two different reasons produce no figure,
    # and they are reported apart rather than both as a bare "NO DATA".
    stock = None if r["current_stock"] is None else float(r["current_stock"])
    stock_cases = _opt_float(r, "current_stock_cases")
    rop = float(r["rop_i"])
    stock_blocked_reason = None
    if stock is None:
        urgency = "NO DATA"
        stock_blocked_reason = (
            NO_PACK_SIZE_REASON if stock_cases is not None
            else "no Inventory_Fact_Real row for this product at the latest snapshot"
        )
    else:
        urgency = "CRITICAL" if stock < rop * 0.5 else ("URGENT" if stock < rop else "PLANNED")

    revenue_share = _opt_float(r, "revenue_share")
    stockout_gap = None if stock is None else max(0.0, rop - stock)
    priority_score = (
        round(revenue_share * stockout_gap, 4)
        if revenue_share is not None and stockout_gap is not None
        else None
    )
    days_of_cover, cover_reason = _cover(_opt_float(r, "stock_value_pesos"), _opt_float(r, "avg_monthly_sales_pesos"))

    return RecommendationItem(
        recommendation_key=r["recommendation_key"],
        sku_id=r["sku_id"] or "",
        product_name=r["product_name"],
        principal=r["principal"],
        planning_cycle_date=r["planning_cycle_date"],
        q_i=float(r["q_i"]),
        rop_i=rop,
        ss_i=float(r["ss_i"]),
        status=r["status"],
        current_stock=stock,
        current_stock_cases=stock_cases,
        stock_blocked_reason=stock_blocked_reason,
        urgency=urgency,
        revenue_share=revenue_share,
        tier=r.get("tier"),
        stockout_gap=stockout_gap,
        priority_score=priority_score,
        days_of_cover=days_of_cover,
        cover_blocked_reason=cover_reason,
    )


@router.get("", response_model=RecommendationsResponse)
def get_recommendations(
    status: str | None = Query(None, description="Filter to 'pending' | 'accepted' | 'dismissed'. Omit for all."),
    cycle: str = Query(
        "current",
        pattern="^(current|all)$",
        description=(
            "'current' (default) returns only the LP's current planning cycle — the most recent "
            "cycle that still has pending rows. Superseded pending rows from earlier runs are "
            "withheld and counted in `superseded_count`. 'all' returns every cycle, for an audit "
            "view. See backend/lp_cycle.py."
        ),
    ),
    from_date: str | None = Query(None, alias="from", description="'YYYY-MM-DD'. The shared date-range picker's applied start. Must be given with 'to' or not at all — filters on lr.planning_cycle_date."),
    to_date: str | None = Query(None, alias="to", description="'YYYY-MM-DD'. The shared date-range picker's applied end. Must be given with 'from' or not at all."),
    principal: str | None = PrincipalQuery,
    mode: str = Depends(get_data_mode),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> RecommendationsResponse:
    # Both principals again (2026-09-17) — see backend/principals.py.
    # lp_recommendation currently holds 430 Unilever rows and ZERO Del
    # Monte rows (confirmed live 2026-09-17), so ?principal=delmonte
    # honestly returns an empty list until the LP is run for Del Monte.
    scope_sql, scope_params = principal_clause(principal, "pd.principal")
    select_sql, lp_params = select_one(mode)
    query = select_sql + " WHERE 1=1" + scope_sql
    # Both anchors resolve under the SAME scope as the rows. The ABC anchor
    # replaces a per-product "latest classification_period" walk, which
    # quietly mixed classification vintages: a SKU last classified months
    # ago contributed a stale revenue_share alongside current ones. Pinned
    # to one period, such a SKU now yields revenue_share None and therefore
    # priority_score None — already null-guarded below.
    params: dict = {
        "inv_period": latest_inventory_period(db, principal),
        "abc_period": latest_abc_period(db, principal),
        **scope_params,
        **lp_params,
    }
    if status:
        query += " AND lr.status = :status"
        params["status"] = status
    # Shared date-range picker (2026-09) — planning_cycle_date is a real
    # DATE column (unlike the fact tables' 'YYYY-MM' _period text), so this
    # compares dates directly, no month-truncation needed.
    if from_date and to_date:
        query += " AND lr.planning_cycle_date >= :from_date AND lr.planning_cycle_date <= :to_date"
        params["from_date"] = from_date
        params["to_date"] = to_date

    # Superseded cycles never reach a screen (2026-09-23) — see
    # backend/lp_cycle.py. A leftover `pending` row from a 2023 run is not a
    # recommendation anyone should act on today, and mixing it into this
    # list was what made the dashboard's pending count read 429 instead of
    # 250. `cycle=all` is the deliberate audit escape hatch.
    freshness = lp_freshness(db, principal, mode)
    if cycle == "current":
        current = current_cycle(db, principal, mode)
        if current is None:
            # Nothing pending at all: 'current' has nothing to scope to, so
            # returning every decided row would contradict the filter's
            # promise. An empty list with the reason is the honest answer.
            return _with_data_mode(RecommendationsResponse(
                items=[], count=0, planning_cycle_date=None,
                superseded_count=0, freshness=freshness, lp_model=lp_model_info(),
            ), db, mode)
        query += CURRENT_CYCLE_CLAUSE
        params["current_cycle"] = current
    query += " ORDER BY lr.planning_cycle_date DESC, lr.rop_i DESC"

    rows = db.execute(text(query), params).mappings().all()
    items = [_to_item(r) for r in rows]
    return _with_data_mode(RecommendationsResponse(
        items=items,
        count=len(items),
        planning_cycle_date=freshness["cycle_date"],
        superseded_count=freshness["superseded_pending_count"] if cycle == "current" else 0,
        freshness=freshness,
        lp_model=lp_model_info(),
    ), db, mode)


def _with_data_mode(response: RecommendationsResponse, db: Session, mode: str):
    """Real mode: the model untouched. Preview: the data_mode block beside it,
    saying whether these rows are the five-year what-if (never saved, not
    decidable) or, with no preview files built, still the real ones."""
    if mode != PREVIEW:
        return response
    block = preview_block(db, real_only=None if predictive_preview(mode) else ["items"])
    return JSONResponse({**jsonable_encoder(response), "data_mode": block})


@router.patch("/{recommendation_key}", response_model=RecommendationItem)
def update_recommendation(
    recommendation_key: int,
    decision: RecommendationDecision,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_admin),
) -> RecommendationItem:
    if decision.status not in ("accepted", "dismissed"):
        raise HTTPException(status_code=400, detail="status must be 'accepted' or 'dismissed'")

    decided = db.execute(
        text("""
            UPDATE lp_recommendation
            SET status = :status, decided_at = :decided_at, decided_by = :decided_by
            WHERE recommendation_key = :key
            RETURNING (SELECT COALESCE(pd.sku_code, pd.category_path) FROM product_dimension pd
                        WHERE pd.product_key = lp_recommendation.product_key) AS sku
        """),
        {
            "status": decision.status,
            "decided_at": datetime.datetime.utcnow(),
            "decided_by": current_user.email,
            "key": recommendation_key,
        },
    ).mappings().first()
    if decided is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Recommendation not found")
    audit.record(
        db,
        f"Reorder Recommendation {'Accepted' if decision.status == 'accepted' else 'Dismissed'}",
        f"SKU {decided['sku']}" + (f": {decision.reason}" if decision.reason else ""),
        actor=current_user,
    )
    db.commit()

    # Single row pinned by recommendation_key; scope left unfiltered (None
    # = all), identical to today's behaviour — see sku.py's _one_row_params.
    row = db.execute(
        text(_SELECT_ONE + " WHERE lr.recommendation_key = :key"),
        {
            "key": recommendation_key,
            "inv_period": latest_inventory_period(db, None),
            "abc_period": latest_abc_period(db, None),
        },
    ).mappings().first()
    return _to_item(row)
