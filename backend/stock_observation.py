"""
backend.stock_observation - stock someone reports counting, kept apart from the stock on hand (migration 0070).

AN OBSERVATION, NOT STOCK ON HAND
---------------------------------
Inventory_Fact (SSM's stock-on-hand file) is the stock the order plan reads: target stock, the order quantity and
the urgency are all worked from it. A count a staff member types on the Reorder page is a CLAIM about the shelf, so
it goes to lp_stock_observation with who, when, where and the unit typed, and nothing in forecasting, safety stock,
target stock, the LP or the dashboards reads it. An admin can mark it verified or rejected; that records the check
and changes no stock. Making a verified count the stock on hand would be a new Inventory_Fact load, a pipeline
decision for Yuan, and is deliberately not done here.

UNITS
-----
Pieces (the plan's unit) or cases. A case is Product_Dimension.pack_size pieces (backend/stock_units.py says why
that column is trusted). Cases need a numeric pack size and a whole number: a part case is counted in pieces. There
is no packs-per-case or inner-pack figure anywhere in the product master, so "packs" is not offered.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend import audit
from backend.api_errors import ApiError
from backend.case_pack import PACK_TOLERANCE
from backend.deps import TokenPayload
from backend.schemas.recommendations import StockObservation, StockObservationIn

_INSERT_SQL = """
    INSERT INTO lp_stock_observation (product_key, recommendation_key, quantity_entered, unit_entered,
                                      pieces_per_case, quantity_pieces, counted_at, location, notes, context,
                                      quantity_change_key, dismissal_request_key, reported_by, reporter_role)
    VALUES (:product_key, :recommendation_key, :quantity_entered, :unit_entered, :pieces_per_case,
            :quantity_pieces, :counted_at, :location, :notes, :context, :quantity_change_key,
            :dismissal_request_key, :reported_by, :reporter_role)
    RETURNING observation_key
"""

COLUMNS_SQL = """
    SELECT o.observation_key, o.recommendation_key, COALESCE(pd.sku_code, pd.category_path) AS sku_code,
           pd.product_name, o.quantity_entered, o.unit_entered, o.pieces_per_case, o.quantity_pieces, o.counted_at,
           o.location, o.notes, o.context, o.quantity_change_key, o.dismissal_request_key, o.reported_by,
           o.reporter_role, o.reported_at, o.verification_state, o.verified_by, o.verified_at, o.verification_note
    FROM lp_stock_observation o
    JOIN product_dimension pd ON pd.product_key = o.product_key
"""


def _clean(value: str | None) -> str | None:
    return (value or "").strip() or None


def to_pieces(quantity: float, unit: str, pack) -> tuple[float, float | None]:
    """(quantity in pieces, pieces per case used or None). Refuses (422) a cases entry for a product with no
    pieces-per-case on record, and a part case."""
    quantity = round(float(quantity), 2)
    if unit == "pieces":
        return quantity, None
    if pack is None or float(pack) <= 0:
        raise ApiError(422, "This product has no pieces-per-case on record, so its stock can only be counted in "
                            "pieces.", code="no_case_size")
    if abs(quantity - round(quantity)) > PACK_TOLERANCE:
        raise ApiError(422, f"{quantity:g} is not a whole number of cases. Count a part case in pieces instead.",
                       code="not_whole_cases", unit="cases")
    pack = float(pack)
    return round(round(quantity) * pack, 2), pack


def record(db: Session, observation: StockObservationIn, *, product_key: int, recommendation_key: int | None,
           pack, context: str, actor: TokenPayload, sku: str, change_key: int | None = None,
           request_key: int | None = None) -> int:
    """Insert one observation and its audit entry in the caller's transaction (the caller commits)."""
    pieces, per_case = to_pieces(observation.quantity, observation.unit, pack)
    entered = round(float(observation.quantity), 2)
    row = db.execute(text(_INSERT_SQL), {
        "product_key": product_key, "recommendation_key": recommendation_key, "quantity_entered": entered,
        "unit_entered": observation.unit, "pieces_per_case": per_case, "quantity_pieces": pieces,
        "counted_at": observation.counted_at, "location": _clean(observation.location),
        "notes": _clean(observation.notes), "context": context, "quantity_change_key": change_key,
        "dismissal_request_key": request_key, "reported_by": actor.email, "reporter_role": actor.role,
    }).mappings().first()
    key = row["observation_key"]
    typed = f"{entered:g} {observation.unit}" + (f" = {pieces:g} pieces at {per_case:g} per case" if per_case else "")
    where = f", at {_clean(observation.location)}" if _clean(observation.location) else ""
    when = f", counted {observation.counted_at:%Y-%m-%d %H:%M}" if observation.counted_at else ""
    audit.record(db, "Stock Count Reported",
                 f"SKU {sku}: {typed}{where}{when} (observation {key}, unverified; with {context.replace('_', ' ')}). "
                 "Recorded only: stock on hand and the order plan are unchanged.", actor=actor)
    return key


def latest_for(db: Session, column: str, keys: list[int]) -> dict[int, StockObservation]:
    """{change_key or request_key: its latest observation} for `keys`. `column` is quantity_change_key or
    dismissal_request_key."""
    if column not in ("quantity_change_key", "dismissal_request_key") or not keys:
        return {}
    rows = db.execute(text(COLUMNS_SQL + f" WHERE o.{column} = ANY(:keys) ORDER BY o.reported_at, o.observation_key"),
                      {"keys": list(keys)}).mappings().all()
    return {r[column]: StockObservation(**dict(r)) for r in rows}
