"""
backend.stock_status — the ONE stock-status rule every screen uses
(GET /recommendations' urgency, GET /dashboard's reorder_preview counts,
GET /abc's stock_status, GET /inventory/current's status).

Stock on hand in PIECES (backend/stock_units.py) against the LP's own two
quantities for the product's current cycle, also pieces:

  NO DATA      no stock row for the product at the latest snapshot
  NOT PLANNED  a stock row, but the LP has no SS_i / T_i for the product in
               the current cycle (every Del Monte product, and any Unilever
               product outside the plan) — whether or not its stock can be
               put in pieces
  CRITICAL     stock < SS_i              safety stock breached
  LOW          SS_i <= stock < T_i       below the target stock: reorder
  OK           stock >= T_i              at or above the target stock

A planned product whose stock row has no usable pack size (no pieces) is
NO DATA too, with the caller stating why (backend/stock_units.
NO_PACK_SIZE_REASON); none exists in the 2026-03 snapshot.

T_i is LP_Recommendation.rop_i. Despite the column's name it is the
order-up-to TARGET stock (scripts/run_lp.py: weekly forecast x (review +
lead days) / 5 + SS_i), not a reorder point.

It adds no threshold of its own. The three rules it replaces each had one
with no source: stock < 0.5 x rop_i (recommendations), stock <= 0 / stock >
rop_i (abc), and > 100 cases summed over every period in range (inventory).
"""
from __future__ import annotations

CRITICAL, LOW, OK, NO_DATA, NOT_PLANNED = "CRITICAL", "LOW", "OK", "NO DATA", "NOT PLANNED"
STATUSES = (CRITICAL, LOW, OK, NO_DATA, NOT_PLANNED)
# Most urgent first: the order screens sort by.
URGENCY_RANK = {CRITICAL: 0, LOW: 1, OK: 2}


def stock_status(
    stock_pieces: float | None, safety_stock: float | None, target_stock: float | None,
    has_stock_row: bool | None = None,
) -> str:
    """has_stock_row: the latest snapshot has a row for the product. None =
    infer it from stock_pieces (for a caller whose rows always carry pieces)."""
    if has_stock_row is None:
        has_stock_row = stock_pieces is not None
    if not has_stock_row:
        return NO_DATA
    if safety_stock is None or target_stock is None:
        return NOT_PLANNED
    if stock_pieces is None:
        return NO_DATA
    if stock_pieces < safety_stock:
        return CRITICAL
    if stock_pieces < target_stock:
        return LOW
    return OK
