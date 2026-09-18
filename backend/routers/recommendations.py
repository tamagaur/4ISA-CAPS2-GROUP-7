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
under bo_monitoring.py's from/to naming since this is a plain date-bounded
table read, not a period-anchored trend). Filters on lr.planning_cycle_date
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
  priority_score  revenue_share x stockout_gap — the sort key. UNIT CAVEAT,
                  stated rather than hidden: rop_i/ss_i/q_i are on the
                  demand series' scale (quantity_sold is PIECES, per
                  config/column_maps/unilever_sku.yaml's sale_quantity_pieces
                  note) while quantity_on_hand is CASES (see
                  backend/routers/dashboard.py's kpis.soh_value evidence).
                  Product_Dimension.pack_size is TEXT and the column map
                  records cases x pack_size agreeing with pieces only ~84% of
                  the time, so there is no honest conversion to apply. The
                  urgency thresholds below inherit the same mismatch (they
                  predate this change). priority_score is therefore a
                  ranking index, not a quantity, and the schema says so.
  days_of_cover   The one cover figure that IS unit-consistent: stock at
                  cost (SUM quantity_on_hand x unit_cost_per_case, pesos,
                  latest snapshot) / average daily sales value (pesos/day) —
                  where the daily rate is the mean of the product's monthly
                  net_amount over the three most recent calendar months
                  present in Unilever_SKU_Demand_Fact_Real (months with no
                  row are excluded, never averaged in as 0 — same rule as
                  dashboard.py's _avg_weekly_demand), divided by
                  AVG_DAYS_PER_MONTH. Exactly the peso basis GET /dashboard's
                  Unilever weeks_of_cover already uses, at SKU grain. Caveat:
                  stock is valued at last purchase cost while sales are at
                  selling price, so cover is understated by the margin — a
                  known bias in one direction, disclosed in the UI tooltip.
                  None (with cover_blocked_reason) when the stock row, the
                  cost, or any recent sales month is missing, or when the
                  daily rate is 0. The sales source is Unilever-only, so a
                  Del Monte LP row (none exist live) is honestly blocked.

  current_stock   was COALESCE(..., 0). A product with no Inventory_Fact_Real
                  row at the latest snapshot (39 of the 250 live rows) was
                  read as "0 on hand" and therefore CRITICAL — a fabricated
                  alert. It is now None, and urgency is 'NO DATA'.
"""
from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.deps import TokenPayload, get_current_user, get_db
from backend.principals import PrincipalQuery, principal_clause
from backend.schemas.recommendations import RecommendationItem, RecommendationDecision, RecommendationsResponse

router = APIRouter(prefix="/recommendations", tags=["recommendations"])

_SELECT_ONE = """
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
        inv.current_stock AS current_stock,
        inv.stock_value_pesos AS stock_value_pesos,
        abc.revenue_share AS revenue_share,
        sales.avg_monthly_sales_pesos AS avg_monthly_sales_pesos
    FROM lp_recommendation lr
    JOIN product_dimension pd ON pd.product_key = lr.product_key
    LEFT JOIN (
        SELECT product_key,
               SUM(quantity_on_hand) AS current_stock,
               SUM(quantity_on_hand * unit_cost_per_case) AS stock_value_pesos
        FROM inventory_fact_real
        WHERE _period = (SELECT MAX(_period) FROM inventory_fact_real)
        GROUP BY product_key
    ) inv ON inv.product_key = lr.product_key
    LEFT JOIN (
        SELECT DISTINCT ON (product_key) product_key, revenue_share
        FROM abc_classification
        WHERE method = 'single'
        ORDER BY product_key, classification_period DESC
    ) abc ON abc.product_key = lr.product_key
    LEFT JOIN (
        SELECT product_key, AVG(month_total) AS avg_monthly_sales_pesos
        FROM (
            SELECT product_key, calendar_month, SUM(net_amount) AS month_total
            FROM unilever_sku_demand_fact_real
            WHERE calendar_month IN (
                SELECT DISTINCT calendar_month FROM unilever_sku_demand_fact_real
                ORDER BY calendar_month DESC LIMIT 3
            )
            GROUP BY product_key, calendar_month
        ) recent
        GROUP BY product_key
    ) sales ON sales.product_key = lr.product_key
"""

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
    stock = None if r["current_stock"] is None else float(r["current_stock"])
    rop = float(r["rop_i"])
    if stock is None:
        urgency = "NO DATA"
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
        urgency=urgency,
        revenue_share=revenue_share,
        stockout_gap=stockout_gap,
        priority_score=priority_score,
        days_of_cover=days_of_cover,
        cover_blocked_reason=cover_reason,
    )


@router.get("", response_model=RecommendationsResponse)
def get_recommendations(
    status: str | None = Query(None, description="Filter to 'pending' | 'accepted' | 'dismissed'. Omit for all."),
    from_date: str | None = Query(None, alias="from", description="'YYYY-MM-DD'. The shared date-range picker's applied start. Must be given with 'to' or not at all — filters on lr.planning_cycle_date."),
    to_date: str | None = Query(None, alias="to", description="'YYYY-MM-DD'. The shared date-range picker's applied end. Must be given with 'from' or not at all."),
    principal: str | None = PrincipalQuery,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> RecommendationsResponse:
    # Both principals again (2026-09-17) — see backend/principals.py.
    # lp_recommendation currently holds 430 Unilever rows and ZERO Del
    # Monte rows (confirmed live 2026-09-17), so ?principal=delmonte
    # honestly returns an empty list until the LP is run for Del Monte.
    scope_sql, scope_params = principal_clause(principal, "pd.principal")
    query = _SELECT_ONE + " WHERE 1=1" + scope_sql
    params: dict = {**scope_params}
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
    query += " ORDER BY lr.planning_cycle_date DESC, lr.rop_i DESC"

    rows = db.execute(text(query), params).mappings().all()
    items = [_to_item(r) for r in rows]
    return RecommendationsResponse(items=items, count=len(items))


@router.patch("/{recommendation_key}", response_model=RecommendationItem)
def update_recommendation(
    recommendation_key: int,
    decision: RecommendationDecision,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> RecommendationItem:
    if decision.status not in ("accepted", "dismissed"):
        raise HTTPException(status_code=400, detail="status must be 'accepted' or 'dismissed'")

    result = db.execute(
        text("""
            UPDATE lp_recommendation
            SET status = :status, decided_at = :decided_at, decided_by = :decided_by
            WHERE recommendation_key = :key
        """),
        {
            "status": decision.status,
            "decided_at": datetime.datetime.utcnow(),
            "decided_by": current_user.email,
            "key": recommendation_key,
        },
    )
    if result.rowcount == 0:
        db.rollback()
        raise HTTPException(status_code=404, detail="Recommendation not found")
    db.commit()

    row = db.execute(
        text(_SELECT_ONE + " WHERE lr.recommendation_key = :key"), {"key": recommendation_key}
    ).mappings().first()
    return _to_item(row)
