"""
backend.routers.sku — GET/POST/PATCH /sku

SKU master data management, backing SKUManagement.jsx. Requires
analytics/db/migrations/0002_add_sku_management_fields.sql to have been
applied (unit_price/lead_time_days/status/notes on Product_Dimension).

current_stock, reorder_point, and tier are read-only derived fields (stock
in pieces at each principal's own latest Inventory_Fact_Real snapshot, the
LP's current cycle, and the latest ABC_Classification period respectively) —
never written here.

Fixed 2026-09-17: the tier subquery had no ABC_Classification.method
filter, so once migration 0017's t3m rows landed in public every product
joined to two tier rows (one per method), duplicating list rows. Filtered
to one method: since migration 0044 each principal's Tier A basis
(analytics.params.abc_method_sql).
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from analytics.params import abc_method_sql
from backend import audit
from backend.deps import TokenPayload, get_current_user, get_db
from backend.permissions import can_see_lp, require_permission
from backend.lp_cycle import current_cycle
from backend.principals import (
    PrincipalQuery,
    abc_period_params,
    abc_period_pred,
    latest_abc_periods,
    tier_a_periods,
    principal_clause,
)
from backend.schemas.sku import SKUCreate, SKUItem, SKUListResponse, SKUUpdate
from backend.stock_units import STOCK_AT_LATEST_SQL
from backend import planning_mart, response_cache
from backend.response_cache import cached

router = APIRouter(prefix="/sku", tags=["sku"])

# The day each principal's latest stock count was taken (2026-10-03). The
# warehouse file is filed under a month (_period) but counted on a day of its
# own: the Unilever stock the pages called "Mar 2026" was counted on 6 Apr
# 2026, Del Monte's "Dec 2025" on 1 Dec 2025. The Technical Adviser asked for
# every stock figure to say when it was counted, so this reads
# MAX(snapshot_date) from the SAME latest-snapshot-per-principal rows
# STOCK_AT_LATEST_SQL takes the stock from — one row per principal, joined
# on principal, so it can't name a different count than the figure beside
# it. Read-only; GET /abc joins it too.
#
# Del Monte is left out (audit FE-5, 2026-10-20): its stored snapshot_date is a 1st-of-month placeholder
# (DEC-12; mart.inventory_count already refuses it as `count date not loaded`), so MAX(snapshot_date) printed
# "counted Dec 1, 2025" beside a figure nobody counted on that day — and, on the demonstration path, beside
# stock that is generated. The page names the month instead.
STOCK_COUNT_DATE_SQL = """
    SELECT inv.principal, MAX(inv.snapshot_date) AS count_date
    FROM inventory_fact_real inv
    JOIN (
        SELECT principal, MAX(_period) AS latest_period
        FROM inventory_fact_real
        GROUP BY principal
    ) latest_inv ON latest_inv.principal = inv.principal AND inv._period = latest_inv.latest_period
    WHERE inv.principal <> 'delmonte'
    GROUP BY inv.principal
"""


def stock_count_dates(rows) -> dict:
    """{principal: count date} from rows carrying stock_count_date — one
    entry per principal present, so an 'all' list states both counts."""
    return {r["principal"]: r.get("stock_count_date") for r in rows if r.get("stock_count_date") is not None}

# Product_Dimension's own CHECK (migration 0030): a Unilever sku_code is
# exactly 8 digits. Checked here too so a bad code gets a 400 that says why,
# not a 500 from the constraint.
UNILEVER_SKU_CODE = re.compile(r"[0-9]{8}")

# Stock is in PIECES (backend/stock_units.py), the unit reorder_point is in;
# stock_cases rides along because it is what the warehouse counts.
# reorder_point comes from the LP's current cycle only (backend/lp_cycle.py):
# the newest pending row from ANY cycle showed 179 superseded rows from runs
# as old as 2023-05 (2026-09-29).
_SELECT_ONE = f"""
    SELECT
        pd.product_key,
        COALESCE(pd.sku_code, pd.category_path) AS sku_id,
        pd.product_name,
        pd.principal,
        pd.grain,
        pd.pack_size,
        pd.brand,
        pd.unit_price AS unit_price,
        pd.unit_cost AS unit_cost,
        pd.lead_time_days AS lead_time_days,
        pd.status AS status,
        pd.notes AS notes,
        inv.stock_pieces AS current_stock,
        inv.stock_cases AS current_stock_cases,
        rop.rop_i AS reorder_point,
        abc.tier AS tier,
        abc.classification_period AS tier_period,
        stock_count.count_date AS stock_count_date
    FROM product_dimension pd
    LEFT JOIN ({STOCK_AT_LATEST_SQL}) inv ON inv.product_key = pd.product_key
    LEFT JOIN ({STOCK_COUNT_DATE_SQL}) stock_count ON stock_count.principal = pd.principal
    LEFT JOIN (
        SELECT product_key, rop_i
        FROM lp_recommendation
        WHERE status = 'pending' AND planning_cycle_date = :current_cycle
    ) rop ON rop.product_key = pd.product_key
    LEFT JOIN (
        SELECT DISTINCT ON (product_key)
               product_key, tier, classification_period
        FROM abc_classification
        WHERE {abc_method_sql()}
          AND (CAST(:abc_p_unilever AS TEXT) IS NULL AND CAST(:abc_p_delmonte AS TEXT) IS NULL
               OR {abc_period_pred("<=")})
        ORDER BY product_key, classification_period DESC
    ) abc ON abc.product_key = pd.product_key
"""
# The method pin is load-bearing in BOTH places above (migration 0017):
# several bases are live side by side, so without it this subquery
# returns one tier row per basis per product_key and the LEFT JOIN fans out —
# silently DUPLICATING every row in the SKU list. Pinned in the inner
# MAX() too, so the period resolved is one the basis actually has
# (analytics.params.abc_method_sql, migration 0044).
#
# LAST-KNOWN tier, not latest-period-only (2026-09-21). This used to
# require classification_period = the single resolved anchor, so a SKU that
# simply had no sales in that one month reported no category at all.
# Measured against live data: 710 of Unilever's 2,098 SKUs (33.8%) matched
# the 2026-02 anchor, while 1,531 (73.0%) carry a real classification in
# SOME period — the other 821 were shown as uncategorised despite having
# been ranked. DISTINCT ON ... ORDER BY classification_period DESC takes
# each product's most recent run instead, and still yields exactly one row
# per product_key, so the fan-out fix above is preserved. (The rop join needs
# no DISTINCT ON: (product_key, planning_cycle_date) is LP_Recommendation's
# upsert key, so one cycle holds at most one row per product.)
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
        grain=r.get("grain"),
        pack_size=r.get("pack_size"),
        brand=r.get("brand"),
        unit_price=float(r["unit_price"]) if r.get("unit_price") is not None else None,
        unit_cost=float(r["unit_cost"]) if r.get("unit_cost") is not None else None,
        lead_time_days=r.get("lead_time_days"),
        status=r.get("status") or "ACTIVE",
        notes=r.get("notes"),
        current_stock=float(r["current_stock"]) if r.get("current_stock") is not None else None,
        current_stock_cases=(
            float(r["current_stock_cases"]) if r.get("current_stock_cases") is not None else None
        ),
        reorder_point=float(r["reorder_point"]) if r.get("reorder_point") is not None else None,
        tier=r.get("tier"),
        tier_period=r.get("tier_period"),
        stock_count_date=r.get("stock_count_date"),
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
        "current_cycle": current_cycle(db),
        **abc_period_params(latest_abc_periods(db, None)),
    }


@router.get("", response_model=SKUListResponse)
@cached("GET /sku")
def get_skus(
    status: str | None = Query(None, description="Filter to 'ACTIVE' or 'DISABLED'. Omit for both."),
    principal: str | None = PrincipalQuery,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(
        require_permission("sku.view", "abc.view", "lp.view", "forecast.view")
    ),
) -> SKUListResponse:
    # Any one of the four pages that read it (was sign-in only, from Yuan's
    # permissions proposal): the ABC, Reorder and SKU Forecast pages read
    # product and brand names from here too, so each of their permissions
    # opens it, but someone with none of them no longer gets the whole
    # catalog with its stock and classes (2026-10-02). Its one LP figure,
    # reorder_point, still follows lp.view (below).
    # Both principals again (2026-09-17) — see backend/principals.py.
    # Unlike the ABC/forecast endpoints, Del Monte DOES have real rows
    # here (15,127 sku-grain + 182 category-grain product_dimension rows),
    # so ?principal=delmonte returns genuine data rather than an empty
    # list. Note the two principals differ in grain (DEC-03), so an
    # unfiltered 'all' list legitimately mixes SKU- and category-grain
    # rows — that's the real shape of the product master, not a defect.
    scope_sql, scope_params = principal_clause(principal, "pd.principal")
    query = _SELECT_ONE + " WHERE 1=1" + scope_sql
    # Anchors resolve under the SAME scope as the rows. Measured 2026-09-20:
    # unscoped they resolved to 2026-03 (Unilever's max), so every Del Monte
    # SKU reported current_stock NULL despite Del Monte inventory existing at
    # 2025-12. Stock now resolves per principal inside the query
    # (STOCK_AT_LATEST_SQL), which is what keeps it right under 'all' too.
    cycle = current_cycle(db, principal)
    params: dict = {
        "current_cycle": cycle,
        **abc_period_params(latest_abc_periods(db, principal)),
        **scope_params,
    }
    if status:
        query += " AND pd.status = :status"
        params["status"] = status
    query += " ORDER BY pd.product_name"

    rows = db.execute(text(query), params).mappings().all()
    items = [_to_item(r) for r in rows]
    lp_visible = can_see_lp(db, current_user)
    if not lp_visible:
        for item in items:
            item.reorder_point = None
    return SKUListResponse(
        items=items,
        count=len(items),
        stock_count_dates=stock_count_dates(rows),
        # The cycle the target stock comes from ("Mar 2026 plan"); an LP
        # fact, so it follows lp.view like reorder_point.
        planning_cycle_date=cycle if lp_visible else None,
        # Anchor None = the latest run, per principal.
        tier_a_periods=tier_a_periods(latest_abc_periods(db, principal)),
    )


@router.post("", response_model=SKUItem, status_code=201)
def create_sku(
    payload: SKUCreate,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_permission("sku.edit")),
) -> SKUItem:
    # Unilever-only (2026-09): hard-reject anything else rather than
    # silently coercing — a client believing a non-Unilever SKU was
    # created when it wasn't is worse than a clear 400. See
    # backend/routers/dashboard.py's module docstring for the full
    # reasoning.
    if payload.principal != "unilever":
        raise HTTPException(status_code=400, detail="principal must be 'unilever'")
    if not UNILEVER_SKU_CODE.fullmatch(payload.sku_code):
        raise HTTPException(status_code=400, detail="SKU code must be exactly 8 digits (e.g. 20071069)")

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
    audit.record(db, "Add SKU", f"Added SKU {payload.sku_code} ({payload.product_name})", actor=current_user)
    db.commit()
    response_cache.invalidate()

    result = db.execute(
        text(_SELECT_ONE + " WHERE pd.product_key = :key"),
        {
            "key": row["product_key"],
            "current_cycle": current_cycle(db, "unilever"),
            **abc_period_params(latest_abc_periods(db, "unilever")),
        },
    ).mappings().first()
    return _to_item(result)


@router.patch("/{product_key}", response_model=SKUItem)
def update_sku(
    product_key: int,
    payload: SKUUpdate,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_permission("sku.edit")),
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

    before = db.execute(
        text("SELECT product_name, pack_size, brand FROM product_dimension WHERE product_key = :key"),
        {"key": product_key},
    ).mappings().first()
    if before is None:
        raise HTTPException(status_code=404, detail="SKU not found")
    # Only what actually changed goes in the audit entry; the edit form sends
    # every field whether or not it was touched.
    changes = ", ".join(
        f"{key}: {before[key]} → {value}" for key, value in fields.items() if before[key] != value
    )
    set_clause = ", ".join(f"{key} = :{key}" for key in fields)
    fields["key"] = product_key
    updated = db.execute(
        text(
            f"UPDATE product_dimension SET {set_clause} WHERE product_key = :key "
            "RETURNING COALESCE(sku_code, category_path) AS sku_id"
        ),
        fields,
    ).mappings().first()
    if updated is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="SKU not found")
    if changes:
        audit.record(db, "Edit SKU", f"SKU {updated['sku_id']}: {changes}", actor=current_user)
        # The Reorder page reads the product's name and pack size (and the stock in pieces
        # worked out from it) from the planning mart, migration 0046.
        planning_mart.refresh(db, "Edit SKU")
    db.commit()
    response_cache.invalidate()

    row = db.execute(
        text(_SELECT_ONE + " WHERE pd.product_key = :key"), _one_row_params(db, product_key)
    ).mappings().first()
    return _to_item(row)
