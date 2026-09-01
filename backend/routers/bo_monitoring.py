from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from backend.deps import TokenPayload, get_current_user, get_db

router = APIRouter(prefix="/bo-monitoring", tags=["bo-monitoring"])

_WEEKDAY_NAMES = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}

# Unilever-only (2026-09) — see backend/routers/dashboard.py's module
# docstring for the full reasoning. No more ?principal= param.
_PRINCIPAL_FILTER = "AND principal = 'unilever'"


@router.get("")
def get_bo_monitoring(
    from_date: str = Query(None, alias="from"),
    to_date: str = Query(None, alias="to"),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
):
    principal_filter = _PRINCIPAL_FILTER
    params = {}

    period_filter = ""
    if from_date and to_date:
        from_period = from_date[:7]
        to_period = to_date[:7]
        period_filter = "AND _period >= :from_period AND _period <= :to_period"
        params["from_period"] = from_period
        params["to_period"] = to_period

    incidents_query = text(f"""
        SELECT
            return_slip_num as id,
            principal,
            return_date as date,
            net_amount as value
        FROM salesreturn_fact_real
        WHERE return_type = 'BO' {principal_filter} {period_filter}
        ORDER BY return_date DESC
    """)
    rows = db.execute(incidents_query, params).mappings().all()

    incidents = []
    for r in rows:
        incidents.append({
            "id": r["id"] or "Unknown",
            "sku": "N/A",
            "brand": "Unilever",
            "product": "Assorted Returns",
            "qty": 0,
            "reason": "Unknown",
            "value": float(r["value"] or 0),
            "date": str(r["date"])
        })

    kpi_query = text(f"""
        SELECT
            COUNT(*) as incidents_count,
            COALESCE(SUM(net_amount), 0) as value_lost
        FROM salesreturn_fact_real
        WHERE return_type = 'BO' {principal_filter} {period_filter}
    """)
    kpi_row = db.execute(kpi_query, params).mappings().first()

    purchase_total_query = text(f"""
        SELECT COALESCE(SUM(net_amount), 0) as purchase_total
        FROM purchase_fact_real
        WHERE 1=1 {principal_filter} {period_filter}
    """)
    purchase_total_row = db.execute(purchase_total_query, params).mappings().first()
    purchase_total = float(purchase_total_row["purchase_total"] or 0)
    value_lost = float(kpi_row["value_lost"])
    bo_rate_pct = round(value_lost / purchase_total * 100, 2) if purchase_total > 0 else None

    # BO value/count trend per period, plus a real peso-based BO rate
    # (BO net_amount / Purchase net_amount) — same ratio BO_Monitoring_View
    # computes, but against the *_Real tables this API actually reads from.
    # SalesReturn_Fact_Real has no sku/reason/qty column (confirmed against
    # real staged headers, see analytics/db/schema.sql SalesReturn_Fact
    # comment), so this is aggregate-only — no per-SKU or per-reason series
    # exists to compute here.
    trend_query = text(f"""
        WITH bo AS (
            SELECT _period, COUNT(*) AS incident_count, COALESCE(SUM(net_amount), 0) AS bo_value
            FROM salesreturn_fact_real
            WHERE return_type = 'BO' {principal_filter} {period_filter}
            GROUP BY _period
        ),
        purchases AS (
            SELECT _period, COALESCE(SUM(net_amount), 0) AS purchase_value
            FROM purchase_fact_real
            WHERE 1=1 {principal_filter} {period_filter}
            GROUP BY _period
        )
        SELECT
            bo._period AS period,
            bo.incident_count,
            bo.bo_value,
            CASE WHEN purchases.purchase_value > 0
                 THEN ROUND(bo.bo_value / purchases.purchase_value * 100, 2)
                 ELSE NULL END AS bo_rate
        FROM bo
        LEFT JOIN purchases ON purchases._period = bo._period
        ORDER BY bo._period
    """)
    trend_rows = db.execute(trend_query, params).mappings().all()
    trend = [
        {
            "period": r["period"],
            "incident_count": int(r["incident_count"]),
            "value_lost": float(r["bo_value"]),
            "bo_rate": float(r["bo_rate"]) if r["bo_rate"] is not None else None,
        }
        for r in trend_rows
    ]

    weekday_query = text(f"""
        SELECT EXTRACT(ISODOW FROM return_date)::int AS dow, COUNT(*) AS count
        FROM salesreturn_fact_real
        WHERE return_type = 'BO' {principal_filter} {period_filter}
        GROUP BY dow
        ORDER BY dow
    """)
    weekday_rows = db.execute(weekday_query, params).mappings().all()
    weekday_counts = {_WEEKDAY_NAMES[r["dow"]]: int(r["count"]) for r in weekday_rows if r["dow"] in _WEEKDAY_NAMES}
    weekday_breakdown = [{"day": day, "count": weekday_counts.get(day, 0)} for day in _WEEKDAY_NAMES.values()]

    brand_query = text(f"""
        SELECT COUNT(*) as count
        FROM salesreturn_fact_real
        WHERE return_type = 'BO' {principal_filter} {period_filter}
    """)
    brand_row = db.execute(brand_query, params).mappings().first()
    brand_breakdown = [{"brand": "Unilever", "count": int(brand_row["count"])}]

    return {
        "incidents": incidents,
        "kpis": {
            "incidents": int(kpi_row["incidents_count"]),
            "unitsLost": 0,
            "valueLost": value_lost,
            "rate": f"{bo_rate_pct}%" if bo_rate_pct is not None else "N/A"
        },
        "trend": trend,
        "weekday_breakdown": weekday_breakdown,
        "brand_breakdown": brand_breakdown,
    }
