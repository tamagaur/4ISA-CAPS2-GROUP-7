from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from backend.deps import TokenPayload, get_db
from backend.lp_cycle import PLAN_STATUS_SQL_BARE, current_cycle
from backend.permissions import require_permission
from backend.principals import PrincipalQuery, principal_clause
from backend.stock_status import stock_status
from backend.routers.sku import STOCK_COUNT_DATE_SQL
from backend.stock_units import COUNT_DATE_NOT_LOADED, STOCK_AT_LATEST_SQL

router = APIRouter(prefix="/inventory", tags=["inventory"])

@router.get("/current")
def get_inventory_current(
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
    #
    # Stock is the latest snapshot per principal, in PIECES
    # (backend/stock_units.py), and status is backend/stock_status.py's one
    # rule against the LP's current cycle: every row here has a stock row, so
    # a product the LP does not plan (all of Del Monte) reads NO ROP. A
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
            lp.rop_i,
            count_period.latest_period AS count_period,
            stock_count.count_date AS count_date
        FROM ({STOCK_AT_LATEST_SQL}) inv
        JOIN product_dimension pd ON inv.product_key = pd.product_key
        -- The count every stock figure above comes from, per principal (the same latest snapshot
        -- STOCK_AT_LATEST_SQL reads): its file month and the day it was counted (2026-10-23).
        LEFT JOIN (SELECT principal, MAX(_period) AS latest_period FROM inventory_fact_real GROUP BY principal)
               count_period ON count_period.principal = pd.principal
        LEFT JOIN ({STOCK_COUNT_DATE_SQL}) stock_count ON stock_count.principal = pd.principal
        LEFT JOIN (
            SELECT product_key, ss_i, rop_i
            FROM lp_recommendation
            WHERE {PLAN_STATUS_SQL_BARE} AND planning_cycle_date = :current_cycle
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
            # receivedMts / dispatchedMts were hardcoded 0 here until 2026-10-20. Purchases and
            # sales have no product on them (see /movement), so a per-SKU received or dispatched
            # figure does not exist; the keys are gone rather than served as a zero.
            # Which count currentStock is: the file month it is filed under and the day it was counted.
            # Del Monte's stored day is a placeholder (DEC-12), so its date is null and says why.
            "count_period": r["count_period"],
            "count_date": r["count_date"].isoformat() if r["count_date"] is not None else None,
            "count_date_note": COUNT_DATE_NOT_LOADED if r["count_date"] is None else None,
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

    # One row per purchase invoice (RECEIVED) and per sales invoice (DISPATCHED). Neither table has
    # a product on it, so there is no SKU or product name to show; the keys say null instead of the
    # "N/A" / "Assorted Items" this route used to invent. The two carry DIFFERENT units, so they are
    # different fields: `quantity` is units received (purchases only; null when the source did not
    # give it, not 0) and `amount_pesos` is the invoice value (both). Newest first, 50 of each.
    purchases = db.execute(text(f"""
        SELECT invoice_date AS date, invoice_num AS ref, principal, units_received, net_amount
        FROM purchase_fact_real
        WHERE 1=1 {principal_filter} {period_filter}
        ORDER BY invoice_date DESC NULLS LAST, invoice_num
        LIMIT 50
    """), params).mappings().all()
    sales = db.execute(text(f"""
        SELECT invoice_date AS date, invoice_num AS ref, principal, net_amount
        FROM sales_fact_real
        WHERE 1=1 {principal_filter} {period_filter}
        ORDER BY invoice_date DESC NULLS LAST, invoice_num
        LIMIT 50
    """), params).mappings().all()

    def _number(value):
        return float(value) if value is not None else None

    movements = []
    for kind, source in (("RECEIVED", purchases), ("DISPATCHED", sales)):
        for r in source:
            movements.append({
                "id": len(movements) + 1,
                "date": str(r["date"]) if r["date"] is not None else None,
                "sku": None,
                "product": None,
                "type": kind,
                "quantity": _number(r["units_received"]) if kind == "RECEIVED" else None,
                "quantity_unit": "units" if kind == "RECEIVED" else None,
                "amount_pesos": _number(r["net_amount"]),
                "ref": r["ref"],
                "supplier": (r["principal"] or "").title() or None,
            })

    movements.sort(key=lambda x: x["date"] or "", reverse=True)

    return movements


_RECEIPT_SIGNALS_SQL = {
    "by_period": """
        SELECT settled_by_period AS period, COUNT(*)::int AS settled,
               COUNT(*) FILTER (WHERE not_visible_in_count)::int AS not_visible,
               COUNT(*) FILTER (WHERE stock_change_pieces IS NULL)::int AS untested,
               COALESCE(SUM(pieces), 0) AS pieces,
               COALESCE(SUM(pieces) FILTER (WHERE not_visible_in_count), 0) AS not_visible_pieces
        FROM expected_receipt WHERE state = 'arrived_in_count'
        GROUP BY settled_by_period ORDER BY settled_by_period DESC""",
    "items": """
        SELECT er.receipt_id, pd.sku_code, pd.product_name, er.pieces, er.settled_by_period, er.settled_by_count_date,
               er.expected_on, er.stock_change_pieces AS implied_receipts_in_count
        FROM expected_receipt er JOIN product_dimension pd ON pd.product_key = er.product_key
        WHERE er.state = 'arrived_in_count' AND er.not_visible_in_count
        ORDER BY er.settled_by_period DESC, er.pieces DESC LIMIT :limit""",
    "open": """
        SELECT COUNT(*)::int AS receipts, COALESCE(SUM(pieces), 0) AS pieces,
               COUNT(*) FILTER (WHERE expected_on < CURRENT_DATE)::int AS overdue
        FROM expected_receipt WHERE state = 'expected'""",
    "derived": """
        SELECT _period AS period, COUNT(*)::int AS products,
               COUNT(*) FILTER (WHERE flag = 'negative_balance')::int AS negative_balance
        FROM derived_receipt_fact WHERE principal = 'unilever'
        GROUP BY _period ORDER BY _period DESC LIMIT :months""",
}


@router.get("/receipt-signals")
def get_receipt_signals(
    limit: int = Query(25, ge=1, le=200, description="How many not-visible receipts to list."),
    months: int = Query(12, ge=1, le=60, description="How many months of the derived-receipts check to show."),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_permission("dashboard.view")),
):
    """Receipts a stock count settled that the count gives no sign of (migration 0069, docs/ROLLOVER_DESIGN.md b).

    An accepted order is an expected receipt. A count dated on or after its expected date settles it as arrived, and
    when the product's stock plus what it sold did not rise in that month (closing - opening + sold <= 0) the receipt
    is marked not_visible_in_count: the same impossible-receipt signal the derived-receipts check computes, kept on
    the receipt so it accumulates here instead of in a flag nobody reads. Nothing is corrected. `derived_receipts`
    is that older check beside it (products whose derived receipt is negative, per count month). Unilever only.
    A receipt settled before its month's sales were loaded is `untested` until they are."""
    if not db.execute(text("SELECT to_regclass('expected_receipt') IS NOT NULL")).scalar():
        return {"available": False, "coverage": ["unilever"], "blocked_reason": "The receipt ledger is not built on this database (migration 0069)."}
    q = _RECEIPT_SIGNALS_SQL
    by_period = [dict(r) for r in db.execute(text(q["by_period"])).mappings().all()]
    for r in by_period:
        r["not_visible_share"] = round(r["not_visible"] / (r["settled"] - r["untested"]), 4) if r["settled"] - r["untested"] else None
        r["pieces"], r["not_visible_pieces"] = float(r["pieces"]), float(r["not_visible_pieces"])
    items = [dict(r) for r in db.execute(text(q["items"]), {"limit": limit}).mappings().all()]
    for i in items:
        i["pieces"] = float(i["pieces"])
        i["implied_receipts_in_count"] = float(i["implied_receipts_in_count"]) if i["implied_receipts_in_count"] is not None else None
        i["settled_by_count_date"] = i["settled_by_count_date"].isoformat() if i["settled_by_count_date"] else None
        i["expected_on"] = i["expected_on"].isoformat() if i["expected_on"] else None
    open_ = dict(db.execute(text(q["open"])).mappings().first())
    open_["pieces"] = float(open_["pieces"])
    derived = [dict(r) for r in db.execute(text(q["derived"]), {"months": months}).mappings().all()]
    for r in derived:
        r["negative_share"] = round(r["negative_balance"] / r["products"], 4) if r["products"] else None
    settled = sum(r["settled"] for r in by_period)
    tested = settled - sum(r["untested"] for r in by_period)
    not_visible = sum(r["not_visible"] for r in by_period)
    return {
        "available": True, "coverage": ["unilever"],
        "definition": ("not_visible_in_count: the receipt was settled by a count, and the product's closing - opening + sold in "
                       "that month is not above zero. A flag only; nothing is corrected."),
        "totals": {"settled": settled, "tested": tested, "not_visible": not_visible,
                   "not_visible_share": round(not_visible / tested, 4) if tested else None},
        "by_period": by_period, "not_visible_receipts": items, "open_receipts": open_,
        "derived_receipts": derived,
    }
