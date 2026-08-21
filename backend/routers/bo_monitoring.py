from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from backend.deps import TokenPayload, get_current_user, get_db

router = APIRouter(prefix="/bo-monitoring", tags=["bo-monitoring"])

@router.get("")
def get_bo_monitoring(
    principal: str = Query("all"),
    from_date: str = Query(None, alias="from"),
    to_date: str = Query(None, alias="to"),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
):
    principal_filter = ""
    params = {}
    if principal in ("unilever", "delmonte"):
        principal_filter = "AND principal = :principal"
        params["principal"] = principal

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
        FROM SalesReturn_Fact_Real
        WHERE return_type = 'BO' {principal_filter} {period_filter}
        ORDER BY return_date DESC
    """)
    rows = db.execute(incidents_query, params).mappings().all()

    incidents = []
    for r in rows:
        incidents.append({
            "id": r["id"] or "Unknown",
            "sku": "N/A",
            "brand": "Unilever" if r["principal"] == "unilever" else "Del Monte",
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
        FROM SalesReturn_Fact_Real
        WHERE return_type = 'BO' {principal_filter} {period_filter}
    """)
    kpi_row = db.execute(kpi_query, params).mappings().first()

    return {
        "incidents": incidents,
        "kpis": {
            "incidents": int(kpi_row["incidents_count"]),
            "unitsLost": 0,
            "valueLost": float(kpi_row["value_lost"]),
            "rate": "0.0%"
        }
    }
