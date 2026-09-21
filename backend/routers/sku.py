"""
backend.routers.sku — GET/POST/PATCH /sku

SKU master data management, backing SKUManagement.jsx. Requires
analytics/db/migrations/0002_add_sku_management_fields.sql to have been
applied (unit_price/lead_time_days/status/notes on Product_Dimension).

current_stock, reorder_point, and tier are read-only derived fields (latest
Inventory_Fact_Real period, latest pending LP_Recommendation, latest
ABC_Classification period respectively) — never written here.

Fixed 2026-09-17: the tier subquery had no ABC_Classification.method
filter, so once migration 0017's t3m rows landed in public every product
joined to two tier rows (one per method), duplicating list rows. Filtered
to method = 'single', the deployed basis.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.deps import TokenPayload, get_current_user, get_db
from backend.principals import (
    PrincipalQuery,
    latest_abc_period,
    latest_inventory_period,
    principal_clause,
)
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
        abc.tier AS tier,
        abc.classification_period AS tier_period
    FROM product_dimension pd
    LEFT JOIN (
        SELECT product_key, SUM(quantity_on_hand) AS current_stock
        FROM inventory_fact_real
        WHERE _period = :inv_period
        GROUP BY product_key
    ) inv ON inv.product_key = pd.product_key
    LEFT JOIN (
        SELECT DISTINCT ON (product_key) product_key, rop_i
        FROM lp_recommendation
        WHERE status = 'pending'
        ORDER BY product_key, planning_cycle_date DESC
    ) rop ON rop.product_key = pd.product_key
    LEFT JOIN (
        SELECT DISTINCT ON (product_key)
               product_key, tier, classification_period
        FROM abc_classification
        WHERE method = 'single'
          AND (CAST(:abc_period AS TEXT) IS NULL
               OR classification_period <= CAST(:abc_period AS TEXT))
        ORDER BY product_key, classification_period DESC
    ) abc ON abc.product_key = pd.product_key
"""
# method='single' is load-bearing in BOTH places above (migration 0017):
# a 't3m' run is live alongside 'single', so without it this subquery
# returns two tier rows per product_key and the LEFT JOIN fans out —
# silently DUPLICATING every row in the SKU list. Pinned in the inner
# MAX() too, so the period resolved is one 'single' actually has.
#
# LAST-KNOWN tier, not latest-period-only (2026-09-21). This used to
# require classification_period = the single resolved anchor, so a SKU that
# simply had no sales in that one month reported no category at all.
# Measured against live data: 710 of Unilever's 2,098 SKUs (33.8%) matched
# the 2026-02 anchor, while 1,531 (73.0%) carry a real classification in
# SOME period — the other 821 were shown as uncategorised despite having
# been ranked. DISTINCT ON ... ORDER BY classification_period DESC takes
# each product's most recent run instead, the same shape the rop join above
# already uses for lp_recommendation, and still yields exactly one row per
# product_key, so the fan-out fix above is preserved.
#
# classification_period comes back with it so callers can show HOW OLD a
# tier is: a last-known tier is only honest if its date travels with it.
# The anchor stays as an upper bound (NULL-safe — Del Monte has no
# abc_classification rows at all, so its anchor resolves to NULL) rather
# than being dropped, so this can never report a classification from a
# period later than the one the caller resolved.


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
        tier_period=r.get("tier_period"),
    )


def _one_row_params(db: Session, product_key: int) -> dict:
    """Bind params for a single-row _SELECT_ONE read by product_key.

    Scope is left unfiltered (None = all), which is exactly today's
    behaviour: the row is already pinned by product_key, so resolving its
    true principal would cost an extra lookup and change nothing. Not an
    oversight - the list endpoint is where scope matters.
    """
    return {
        "key": product_key,
        "inv_period": latest_inventory_period(db, None),
        "abc_period": latest_abc_period(db, None),
    }


@router.get("", response_model=SKUListResponse)
def get_skus(
    status: str | None = Query(None, description="Filter to 'ACTIVE' or 'DISABLED'. Omit for both."),
    principal: str | None = PrincipalQuery,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> SKUListResponse:
    # Both principals again (2026-09-17) — see backend/principals.py.
    # Unlike the ABC/forecast endpoints, Del Monte DOES have real rows
    # here (15,127 sku-grain + 182 category-grain product_dimension rows),
    # so ?principal=delmonte returns genuine data rather than an empty
    # list. Note the two principals differ in grain (DEC-03), so an
    # unfiltered 'all' list legitimately mixes SKU- and category-grain
    # rows — that's the real shape of the product master, not a defect.
    scope_sql, scope_params = principal_clause(principal, "pd.principal")
    query = _SELECT_ONE + " WHERE 1=1" + scope_sql
    # Both anchors resolve under the SAME scope as the rows. Measured
    # 2026-09-20: unscoped they resolved to 2026-03 (Unilever's max), so
    # every one of Del Monte's 15,308 SKUs reported current_stock NULL
    # despite 5,164 Del Monte inventory rows existing at 2025-12.
    params: dict = {
        "inv_period": latest_inventory_period(db, principal),
        "abc_period": latest_abc_period(db, principal),
        **scope_params,
    }
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

    result = db.execute(
        text(_SELECT_ONE + " WHERE pd.product_key = :key"),
        {
            "key": row["product_key"],
            "inv_period": latest_inventory_period(db, "unilever"),
            "abc_period": latest_abc_period(db, "unilever"),
        },
    ).mappings().first()
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
        row = db.execute(
            text(_SELECT_ONE + " WHERE pd.product_key = :key"), _one_row_params(db, product_key)
        ).mappings().first()
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

    row = db.execute(
        text(_SELECT_ONE + " WHERE pd.product_key = :key"), _one_row_params(db, product_key)
    ).mappings().first()
    return _to_item(row)
