"""
backend.routers.sku — GET/POST/PATCH /sku

SKU master data management, backing SKUManagement.jsx. Requires
analytics/db/migrations/0002_add_sku_management_fields.sql to have been
applied (unit_price/lead_time_days/status/notes on Product_Dimension).

current_stock, reorder_point, and tier are read-only derived fields (latest
Inventory_Fact_Real period, latest pending LP_Recommendation, latest
ABC_Classification period respectively) — never written here.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.deps import TokenPayload, get_current_user, get_db
from backend.schemas.sku import SKUCreate, SKUItem, SKUListResponse, SKUUpdate

router = APIRouter(prefix="/sku", tags=["sku"])

_SELECT_ONE = """
    SELECT
        pd.product_key,
        COALESCE(pd.sku_code, pd.category_path) AS sku_id,
        pd.product_name,
        pd.principal,
        pd.pack_size,
        pd.brand,
        pd.unit_price AS unit_price,
        pd.lead_time_days AS lead_time_days,
        pd.status AS status,
        pd.notes AS notes,
        COALESCE(inv.current_stock, NULL) AS current_stock,
        rop.rop_i AS reorder_point,
        abc.tier AS tier
    FROM product_dimension pd
    LEFT JOIN (
        SELECT product_key, SUM(quantity_on_hand) AS current_stock
        FROM inventory_fact_real
        WHERE _period = (SELECT MAX(_period) FROM inventory_fact_real)
        GROUP BY product_key
    ) inv ON inv.product_key = pd.product_key
    LEFT JOIN (
        SELECT DISTINCT ON (product_key) product_key, rop_i
        FROM lp_recommendation
        WHERE status = 'pending'
        ORDER BY product_key, planning_cycle_date DESC
    ) rop ON rop.product_key = pd.product_key
    LEFT JOIN (
        SELECT product_key, tier
        FROM abc_classification
        WHERE classification_period = (SELECT MAX(classification_period) FROM abc_classification)
    ) abc ON abc.product_key = pd.product_key
"""


def _to_item(r) -> SKUItem:
    return SKUItem(
        product_key=r["product_key"],
        sku_id=r["sku_id"] or "",
        product_name=r["product_name"],
        principal=r["principal"],
        pack_size=r.get("pack_size"),
        brand=r.get("brand"),
        unit_price=float(r["unit_price"]) if r.get("unit_price") is not None else None,
        lead_time_days=r.get("lead_time_days"),
        status=r.get("status") or "ACTIVE",
        notes=r.get("notes"),
        current_stock=float(r["current_stock"]) if r.get("current_stock") is not None else None,
        reorder_point=float(r["reorder_point"]) if r.get("reorder_point") is not None else None,
        tier=r.get("tier"),
    )


@router.get("", response_model=SKUListResponse)
def get_skus(
    status: str | None = Query(None, description="Filter to 'ACTIVE' or 'DISABLED'. Omit for both."),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> SKUListResponse:
    # Unilever-only (2026-09) — see backend/routers/dashboard.py's module
    # docstring for the full reasoning.
    query = _SELECT_ONE + " WHERE pd.principal = 'unilever'"
    params: dict = {}
    if status:
        query += " AND pd.status = :status"
        params["status"] = status
    query += " ORDER BY pd.product_name"

    rows = db.execute(text(query), params).mappings().all()
    items = [_to_item(r) for r in rows]
    return SKUListResponse(items=items, count=len(items))


@router.post("", response_model=SKUItem, status_code=201)
def create_sku(
    payload: SKUCreate,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> SKUItem:
    # Unilever-only (2026-09): hard-reject anything else rather than
    # silently coercing — a client believing a non-Unilever SKU was
    # created when it wasn't is worse than a clear 400. See
    # backend/routers/dashboard.py's module docstring for the full
    # reasoning.
    if payload.principal != "unilever":
        raise HTTPException(status_code=400, detail="principal must be 'unilever'")

    existing = db.execute(
        text("SELECT 1 FROM product_dimension WHERE principal = 'unilever' AND sku_code = :sku_code"),
        {"sku_code": payload.sku_code},
    ).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"SKU {payload.sku_code} already exists for unilever")

    row = db.execute(
        text("""
            INSERT INTO product_dimension
                (principal, grain, sku_code, product_name, pack_size, brand)
            VALUES
                ('unilever', 'sku', :sku_code, :product_name, :pack_size, :brand)
            RETURNING product_key
        """),
        {
            "sku_code": payload.sku_code,
            "product_name": payload.product_name,
            "pack_size": payload.pack_size,
            "brand": payload.brand,
        },
    ).mappings().first()
    db.commit()

    result = db.execute(text(_SELECT_ONE + " WHERE pd.product_key = :key"), {"key": row["product_key"]}).mappings().first()
    return _to_item(result)


@router.patch("/{product_key}", response_model=SKUItem)
def update_sku(
    product_key: int,
    payload: SKUUpdate,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> SKUItem:
    if payload.status is not None and payload.status not in ("ACTIVE", "DISABLED"):
        raise HTTPException(status_code=400, detail="status must be 'ACTIVE' or 'DISABLED'")

    # Only update columns that actually exist in the current schema.
    # status/unit_price/lead_time_days/notes are not yet in product_dimension.
    _UPDATABLE_COLUMNS = {"product_name", "pack_size", "brand"}
    fields = {
        k: v for k, v in payload.model_dump(exclude_unset=True).items()
        if k in _UPDATABLE_COLUMNS and v is not None
    }
    if not fields:
        # Nothing to update in DB — just return current state
        row = db.execute(text(_SELECT_ONE + " WHERE pd.product_key = :key"), {"key": product_key}).mappings().first()
        if row is None:
            raise HTTPException(status_code=404, detail="SKU not found")
        return _to_item(row)

    set_clause = ", ".join(f"{key} = :{key}" for key in fields)
    fields["key"] = product_key
    result = db.execute(
        text(f"UPDATE product_dimension SET {set_clause} WHERE product_key = :key"), fields
    )
    if result.rowcount == 0:
        db.rollback()
        raise HTTPException(status_code=404, detail="SKU not found")
    db.commit()

    row = db.execute(text(_SELECT_ONE + " WHERE pd.product_key = :key"), {"key": product_key}).mappings().first()
    return _to_item(row)
