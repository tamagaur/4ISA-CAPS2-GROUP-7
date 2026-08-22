from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from backend.deps import TokenPayload, get_current_user, get_db

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

@router.get("")
def get_dashboard(
    principal: str = Query("all", description="Filter to 'unilever' or 'delmonte'. Use 'all' for both."),
    from_date: str = Query(None, alias="from", description="Start date YYYY-MM-DD"),
    to_date: str = Query(None, alias="to", description="End date YYYY-MM-DD"),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
):
    # Principal filter
    principal_filter = ""
    params = {}
    if principal in ("unilever", "delmonte"):
        principal_filter = "AND principal = :principal"
        params["principal"] = principal

    # Period filter (convert YYYY-MM-DD to YYYY-MM for monthly facts)
    period_filter = ""
    if from_date and to_date:
        from_period = from_date[:7]
        to_period = to_date[:7]
        period_filter = "AND _period >= :from_period AND _period <= :to_period"
        params["from_period"] = from_period
        params["to_period"] = to_period

    # 1. Bad Order Value & Incidents
    bo_query = text(f"""
        SELECT 
            COALESCE(SUM(net_amount), 0) as total_value,
            COUNT(*) as incident_count
        FROM salesreturn_fact_real
        WHERE return_type = 'BO' {principal_filter} {period_filter}
    """)
    bo_row = db.execute(bo_query, params).mappings().first()
    bo_value = float(bo_row["total_value"])
    bo_incidents = int(bo_row["incident_count"])

    # 2. Reorder Items
    # LP_Recommendation has no principal column directly, need to join Product_Dimension
    reorder_query = text(f"""
        SELECT 
            COUNT(*) as total_items,
            SUM(q_i) as total_qty,
            COUNT(CASE WHEN (q_i - rop_i) > 0 THEN 1 END) as critical_items
        FROM lp_recommendation lr
        JOIN product_dimension pd ON lr.product_key = pd.product_key
        WHERE status = 'pending'
        {principal_filter.replace("principal", "pd.principal")}
    """)
    reorder_row = db.execute(reorder_query, params).mappings().first()
    reorder_items = int(reorder_row["total_items"])
    reorder_critical = int(reorder_row["critical_items"])
    reorder_qty = float(reorder_row["total_qty"] or 0)

    # 3. Bad Order Trend
    # Group by _period and return_type='BO'
    bo_trend_query = text(f"""
        SELECT _period as period, COALESCE(SUM(net_amount), 0) as val
        FROM salesreturn_fact_real
        WHERE return_type = 'BO' {principal_filter} {period_filter}
        GROUP BY _period
        ORDER BY _period
    """)
    trend_rows = db.execute(bo_trend_query, params).mappings().all()
    # The frontend expects expiry/transport_damage/storage_issue, but DB doesn't have it.
    # We will map the total val to 'storage_issue' for the chart to display it.
    bad_order_series = [
        {"period": r["period"], "expiry": 0, "transport_damage": 0, "storage_issue": float(r["val"])}
        for r in trend_rows
    ]

    # 4. ABC Classification
    abc_query = text(f"""
        SELECT tier, COUNT(*) as sku_count, SUM(revenue_share) as revenue_share
        FROM abc_classification ac
        WHERE 1=1 {principal_filter}
        GROUP BY tier
        ORDER BY tier
    """)
    abc_rows = db.execute(abc_query, params).mappings().all()
    abc_tiers = [
        {"tier": r["tier"], "sku_count": r["sku_count"], "revenue_share": float(r["revenue_share"] or 0)}
        for r in abc_rows
    ]

    # 5. Reorder Alerts
    alerts_query = text(f"""
        SELECT 
            pd.sku_code, pd.category_path, pd.product_name, 
            lr.q_i, lr.rop_i
        FROM lp_recommendation lr
        JOIN product_dimension pd ON lr.product_key = pd.product_key
        WHERE status = 'pending'
        {principal_filter.replace("principal", "pd.principal")}
        LIMIT 5
    """)
    alerts_rows = db.execute(alerts_query, params).mappings().all()
    reorder_alerts = [
        {
            "sku_id": r["sku_code"] or r["category_path"] or "Unknown",
            "product_name": r["product_name"] or "Unknown",
            "current_stock": 0, # Inventory_Fact not joined for simplicity
            "rop": float(r["rop_i"]),
            "urgency": "URGENT"
        }
        for r in alerts_rows
    ]

    # 6. Bad Orders List
    bo_list_query = text(f"""
        SELECT return_slip_num as incident_id, 'Unknown Product' as product_name, net_amount
        FROM salesreturn_fact_real
        WHERE return_type = 'BO' {principal_filter} {period_filter}
        LIMIT 5
    """)
    bo_list_rows = db.execute(bo_list_query, params).mappings().all()
    bad_orders = [
        {
            "incident_id": r["incident_id"],
            "product_name": r["product_name"],
            "reason": "Unknown",
            "status": "OPEN"
        }
        for r in bo_list_rows
    ]

    return {
        "principal": principal,
        "period": {"from": from_date, "to": to_date},
        "kpis": {
            "bad_order_value": {
                "metric_type": "loss",
                "value": round(bo_value / 1000, 1), # In k
                "delta_vs_prev": 0,
                "direction": "stable",
                "incident_count": bo_incidents,
                "by_reason": {"expiry": 0, "transport_damage": 0, "storage_issue": round(bo_value / 1000, 1)}
            },
            "bad_order_incidents": {
                "metric_type": "loss",
                "value": bo_incidents,
                "open_count": bo_incidents,
                "under_investigation": 0,
                "resolved_count": 0,
                "total_count": bo_incidents,
                "delta_vs_prev": 0,
                "direction": "stable"
            },
            "reorder_items": {
                "metric_type": "recommendation",
                "value": reorder_items,
                "critical_count": reorder_critical,
                "total_value": round(reorder_qty, 1), # Using qty as proxy since cost is unknown
                "unit_noun": "items" if principal == 'all' else ('categories' if principal == 'delmonte' else 'products')
            },
            "reorder_value": {
                "metric_type": "recommendation",
                "value": round(reorder_qty, 1),
                "item_count": reorder_items,
                "critical_count": reorder_critical,
                "unit_noun": "items" if principal == 'all' else ('categories' if principal == 'delmonte' else 'products')
            }
        },
        "bad_order_series": bad_order_series,
        "abc": {
            "grain": "mixed" if principal == 'all' else ('category' if principal == 'delmonte' else 'sku'),
            "tiers": abc_tiers
        },
        "reorder_alerts": reorder_alerts,
        "bad_orders": bad_orders
    }
