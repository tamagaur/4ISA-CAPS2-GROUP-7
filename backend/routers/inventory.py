from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from backend.deps import TokenPayload, get_db
from backend.permissions import require_permission
from backend.principals import PrincipalQuery, principal_clause

router = APIRouter(prefix="/inventory", tags=["inventory"])

@router.get("/current")
def get_inventory_current(
    from_date: str = Query(None, alias="from"),
    to_date: str = Query(None, alias="to"),
    principal: str | None = PrincipalQuery,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_permission("dashboard.view")),
):
    # Both principals again (2026-09-17) — see backend/principals.py.
    # Del Monte has 5,164 real inventory rows, so this endpoint returns
    # genuine data for either principal. Caveat for callers: Del Monte's
    # unit_cost_per_case and stock_status are 0% populated live, so any
    # column derived from those is null for Del Monte while Unilever is
    # 100% populated — a real source gap, not a filter artefact.
    principal_filter, params = principal_clause(principal, "i.principal")
    params = dict(params)

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
        FROM inventory_fact_real i
        JOIN product_dimension pd ON i.product_key = pd.product_key
        WHERE 1=1 {principal_filter} {period_filter}
        GROUP BY i.sku_code, i.principal, pd.product_name
    """)
    rows = db.execute(query, params).mappings().all()

    inventory = []
    for r in rows:
        inventory.append({
            "id": r["sku_code"],
            "sku": r["sku_code"],
            # Real per-row principal, not a hardcoded literal — this list
            # can now contain Del Monte rows.
            "brand": (r["principal"] or "").title() or None,
            "product": r["product_name"] or "Unknown Product",
            "currentStock": float(r["current_stock"] or 0),
            "receivedMts": 0,
            "dispatchedMts": 0,
            "status": "IN STOCK" if float(r["current_stock"] or 0) > 100 else ("LOW" if float(r["current_stock"] or 0) > 0 else "CRITICAL")
        })

    return inventory


@router.get("/movement")
def get_inventory_movement(
    from_date: str = Query(None, alias="from"),
    to_date: str = Query(None, alias="to"),
    principal: str | None = PrincipalQuery,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_permission("dashboard.view")),
):
    # Both principals again (2026-09-17) — see backend/principals.py.
    # NOTE, still true: sales_fact_real is Del Monte-only at the schema
    # level (CHECK (principal = 'delmonte')) and purchase_fact_real turns
    # out to hold Del Monte rows ONLY too (499 rows, 0 Unilever, confirmed
    # live 2026-09-17). So ?principal=unilever legitimately returns an
    # empty movement list while 'delmonte'/'all' return real rows — the
    # exact inverse of what the old hardcoded 'unilever' filter could ever
    # produce, which is why that filter always yielded nothing.
    principal_filter, params = principal_clause(principal, "principal")
    params = dict(params)

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
        FROM purchase_fact_real
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
        FROM sales_fact_real
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
            "supplier": (r["principal"] or "").title() or None
        })
        _id += 1

    # Sort by date desc
    movements.sort(key=lambda x: x["date"], reverse=True)

    return movements
