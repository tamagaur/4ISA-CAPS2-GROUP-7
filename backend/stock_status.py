"""
backend.stock_status — the ONE stock-status rule every screen uses
(GET /recommendations' urgency, GET /dashboard's reorder_preview counts,
GET /abc's stock_status, GET /inventory/current's status).

Stock on hand in PIECES (backend/stock_units.py) against the LP's own two
quantities for the product's current cycle, also pieces:

  NO DATA      no stock row for the product at the latest snapshot
  NO ROP       a stock row, but the LP has no SS_i / T_i for the product in
               the current cycle (every Del Monte product, and any Unilever
               product outside the plan) — whether or not its stock can be
               put in pieces
  CRITICAL     stock < SS_i              safety stock breached
  LOW          SS_i <= stock < T_i       below the target stock: reorder
  IN STOCK     stock >= T_i              at or above the target stock

The labels are the ones the frontend reads (Audrey's, 2026-10-01; params
consolidation called NO ROP "NOT PLANNED" and IN STOCK "OK" — merged
2026-10-02 keeping these thresholds under her names). GET /recommendations
names the three planned states its own way (URGENCY below): CRITICAL,
URGENT, PLANNED.

A planned product whose stock row has no usable pack size (no pieces) is
NO DATA too, with the caller stating why (backend/stock_units.
NO_PACK_SIZE_REASON); none exists in the 2026-03 snapshot.

T_i is LP_Recommendation.rop_i. Despite the column's name it is the
order-up-to TARGET stock (scripts/run_lp.py: weekly forecast x (review +
lead days) / 5 + SS_i), not a reorder point.

It adds no threshold of its own. The three rules it replaces each had one
with no source: stock < 0.5 x rop_i (recommendations), stock <= 0 / stock >
rop_i (abc), and > 100 cases summed over every period in range (inventory).

A PRODUCT MISSING FROM A COUNT THAT WAS TAKEN (checked 2026-10-02). Whether
that means 0 on hand depends on whether the principal's stock file ever
lists a zero-stock item:
  unilever  never. Its SOH sheets hold "<cases>/<pieces>" per item and 0 of
            27,321 raw rows across all 39 sheets read 0/0 (the 39 blank
            cells are each sheet's footer row); Inventory_Fact_Real agrees,
            0 of 27,282 rows with 0 cases and 0 loose pieces, and 1,207 times
            a product drops out of one month's count and is back the next.
            The 2,955 rows with quantity_pieces = 0 are whole cases with no
            loose remainder, not empty stock. Missing = 0 on hand, as the LP
            reads it (recommendations' stock_not_in_count).
  delmonte  sometimes: 24 rows with Quantity 0 (all real SKU rows, valuation
            0) in 5 of its 17 inventory files. Missing says nothing: NO DATA.
"""
from __future__ import annotations

CRITICAL, LOW, IN_STOCK, NO_DATA, NO_ROP = "CRITICAL", "LOW", "IN STOCK", "NO DATA", "NO ROP"
STATUSES = (CRITICAL, LOW, IN_STOCK, NO_DATA, NO_ROP)

# GET /recommendations' urgency: the same rule, under the reorder page's names
# for a planned product (frontend ReorderRecommendations.jsx).
URGENT, PLANNED = "URGENT", "PLANNED"
URGENCY = {CRITICAL: CRITICAL, LOW: URGENT, IN_STOCK: PLANNED, NO_DATA: NO_DATA}
# Most urgent first: the order screens sort by.
URGENCY_RANK = {CRITICAL: 0, URGENT: 1, PLANNED: 2}

# Principals whose stock count never lists a zero-stock item (see above).
COUNT_OMITS_ZERO_STOCK = frozenset({"unilever"})


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
        return NO_ROP
    if stock_pieces is None:
        return NO_DATA
    if stock_pieces < safety_stock:
        return CRITICAL
    if stock_pieces < target_stock:
        return LOW
    return IN_STOCK
