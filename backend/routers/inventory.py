from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from backend.deps import TokenPayload, get_current_user, get_db
from backend.lp_cycle import current_cycle
from backend.principals import PrincipalQuery, principal_clause
from backend.stock_status import stock_status
from backend.stock_units import STOCK_AT_LATEST_SQL

router = APIRouter(prefix="/inventory", tags=["inventory"])

@router.get("/current")
def get_inventory_current(
    principal: str | None = PrincipalQuery,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
):
    # Both principals again (2026-09-17) — see backend/principals.py.
    # Del Monte has 5,164 real inventory rows, so this endpoint returns
    # genuine data for either principal. Caveat for callers: Del Monte's
    # unit_cost_per_case and stock_status are 0% populated live, so any
    # column derived from those is null for Del Monte while Unilever is
    # 100% populated — a real source gap, not a filter artefact.
    #
    # Stock is the latest snapshot per principal, in PIECES
    # (backend/stock_units.py), and status is backend/stock_status.py's one
    # rule against the LP's current cycle: every row here has a stock row, so
    # a product the LP does not plan (all of Del Monte) reads NOT PLANNED. A
    # product whose stock can't be put in pieces (no usable pack size — all
    # of Del Monte) is shown in CASES, with unit saying so. Until 2026-09-30
    # this summed
    # quantity_on_hand (CASES) over every period in the from/to range and
    # called anything above a flat 100 IN STOCK; the range params are gone
    # because a status is a fact about one snapshot, not a sum of them.
    principal_filter, params = principal_clause(principal, "pd.principal")
    params = dict(params)
    params["current_cycle"] = current_cycle(db, principal)

    query = text(f"""
        SELECT
            pd.sku_code,
            pd.principal,
            pd.product_name,
            inv.stock_pieces AS current_stock,
            inv.stock_cases AS current_stock_cases,
            lp.ss_i,
            lp.rop_i
        FROM ({STOCK_AT_LATEST_SQL}) inv
        JOIN product_dimension pd ON inv.product_key = pd.product_key
        LEFT JOIN (
            SELECT product_key, ss_i, rop_i
            FROM lp_recommendation
            WHERE status = 'pending' AND planning_cycle_date = :current_cycle
        ) lp ON lp.product_key = inv.product_key
        WHERE 1=1 {principal_filter}
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
            "currentStock": (
                float(r["current_stock"]) if r["current_stock"] is not None
                else float(r["current_stock_cases"]) if r["current_stock_cases"] is not None else None
            ),
            "unit": (
                "pieces" if r["current_stock"] is not None
                else "cases" if r["current_stock_cases"] is not None else None
            ),
            "receivedMts": 0,
            "dispatchedMts": 0,
            "status": stock_status(
                None if r["current_stock"] is None else float(r["current_stock"]),
                None if r["ss_i"] is None else float(r["ss_i"]),
                None if r["rop_i"] is None else float(r["rop_i"]),
                has_stock_row=True,
            ),
        })

    return inventory


@router.get("/movement")
def get_inventory_movement(
    from_date: str = Query(None, alias="from"),
    to_date: str = Query(None, alias="to"),
    principal: str | None = PrincipalQuery,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
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
