"""
backend.stock_status — the ONE stock-status rule every screen uses
(GET /recommendations' urgency, GET /dashboard's reorder_preview counts,
GET /abc's stock_status, GET /inventory/current's status).

Stock on hand in PIECES (backend/stock_units.py) against the LP's own two
quantities for the product's current cycle, also pieces:

  CRITICAL   stock < SS_i              safety stock breached
  LOW        SS_i <= stock < T_i       below the target stock: reorder
  OK         stock >= T_i              at or above the target stock
  NO DATA    no stock figure in pieces (no snapshot row, or no usable pack size)
  NO TARGET  no LP row for the product in the current cycle

T_i is LP_Recommendation.rop_i. Despite the column's name it is the
order-up-to TARGET stock (scripts/run_lp.py: weekly forecast x (review +
lead days) / 5 + SS_i), not a reorder point.

It adds no threshold of its own. The three rules it replaces each had one
with no source: stock < 0.5 x rop_i (recommendations), stock <= 0 / stock >
rop_i (abc), and > 100 cases summed over every period in range (inventory).
"""
from __future__ import annotations

CRITICAL, LOW, OK, NO_DATA, NO_TARGET = "CRITICAL", "LOW", "OK", "NO DATA", "NO TARGET"
STATUSES = (CRITICAL, LOW, OK, NO_DATA, NO_TARGET)
# Most urgent first: the order screens sort by.
URGENCY_RANK = {CRITICAL: 0, LOW: 1, OK: 2}


def stock_status(stock_pieces: float | None, safety_stock: float | None, target_stock: float | None) -> str:
    if stock_pieces is None:
        return NO_DATA
    if safety_stock is None or target_stock is None:
        return NO_TARGET
    if stock_pieces < safety_stock:
        return CRITICAL
    if stock_pieces < target_stock:
        return LOW
    return OK
