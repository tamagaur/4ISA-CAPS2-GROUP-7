from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from backend.deps import TokenPayload, get_current_user, get_db

router = APIRouter(prefix="/inventory", tags=["inventory"])

@router.get("/current")
def get_inventory_current(
    principal: str = Query("all"),
    from_date: str = Query(None, alias="from"),
    to_date: str = Query(None, alias="to"),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
):
    principal_filter = ""
    params = {}
    if principal in ("unilever", "delmonte"):
        principal_filter = "AND i.principal = :principal"
        params["principal"] = principal
        
    period_filter = ""
    if from_date and to_date:
        from_period = from_date[:7]
        to_period = to_date[:7]
        period_filter = "AND i._period >= :from_period AND i._period <= :to_period"
        params["from_period"] = from_period
        params["to_period"] = to_period

    query = text(f"""
        SELECT 
            i.sku_code,
            i.principal,
            pd.product_name,
            SUM(i.quantity_on_hand) as current_stock
        FROM Inventory_Fact_Real i
        JOIN Product_Dimension pd ON i.product_key = pd.product_key
        WHERE 1=1 {principal_filter} {period_filter}
        GROUP BY i.sku_code, i.principal, pd.product_name
    """)
    rows = db.execute(query, params).mappings().all()

    inventory = []
    for r in rows:
        inventory.append({
            "id": r["sku_code"],
            "sku": r["sku_code"],
            "brand": "Unilever" if r["principal"] == "unilever" else "Del Monte",
            "product": r["product_name"] or "Unknown Product",
            "currentStock": float(r["current_stock"] or 0),
            "receivedMts": 0,
            "dispatchedMts": 0,
            "status": "IN STOCK" if float(r["current_stock"] or 0) > 100 else ("LOW" if float(r["current_stock"] or 0) > 0 else "CRITICAL")
        })

    return inventory


@router.get("/movement")
def get_inventory_movement(
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

    # PURCHASE (Received)
    purchases_query = text(f"""
        SELECT 
            invoice_date as date,
            invoice_num as ref,
            principal,
            units_received as qty,
            'RECEIVED' as type
        FROM Purchase_Fact_Real
        WHERE 1=1 {principal_filter} {period_filter}
        LIMIT 50
    """)
    purchases = db.execute(purchases_query, params).mappings().all()

    # SALES (Dispatched)
    sales_query = text(f"""
        SELECT 
            invoice_date as date,
            invoice_num as ref,
            principal,
            net_amount as qty, -- Sales_Fact_Real has no qty, use amount as proxy
            'DISPATCHED' as type
        FROM Sales_Fact_Real
        WHERE 1=1 {principal_filter} {period_filter}
        LIMIT 50
    """)
    sales = db.execute(sales_query, params).mappings().all()

    movements = []
    _id = 1
    for r in list(purchases) + list(sales):
        movements.append({
            "id": _id,
            "date": str(r["date"]),
            "sku": "N/A",
            "product": "Assorted Items",
            "type": r["type"],
            "qty": float(r["qty"] or 0),
            "ref": r["ref"],
            "supplier": "Unilever" if r["principal"] == "unilever" else "Del Monte"
        })
        _id += 1

    # Sort by date desc
    movements.sort(key=lambda x: x["date"], reverse=True)

    return movements
