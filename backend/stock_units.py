"""
backend.stock_units — the ONE place that reconciles inventory units with
planning units, and the one place that values stock on hand.

WHY THIS MODULE EXISTS (2026-09-23)
-----------------------------------
Inventory_Fact and the planning tables are on DIFFERENT UNITS, and every
comparison between them was silently wrong until this module:

  Inventory_Fact.quantity_on_hand   CASES  (analytics/etl/transform_ssis_soh.py
                                    loads it from stock_qty_cases — see
                                    backend/routers/dashboard.py's
                                    kpis.soh_value evidence trail)
  Inventory_Fact.quantity_pieces    the LOOSE REMAINDER that doesn't make a
                                    full case, in pieces
  LP_Recommendation.ss_i/rop_i/q_i  PIECES (the demand series' own unit:
                                    quantity_sold is pieces, per
                                    config/column_maps/unilever_sku.yaml)
  Forecast_Result.forecast_value    PIECES (same demand series)

So `current_stock >= ss_i` was comparing CASES against PIECES. Live effect
before the fix (2026-03 snapshot, 2026-02 Tier A run): 109 of 120 measurable
Category A SKUs read as "below safety stock" when only 36 actually are, and
GET /recommendations labelled 215 of 429 pending rows CRITICAL where 185 are.
A 420-case SKU with 288 pieces per case holds ~121,000 pieces; the old code
tested 420 >= 32,231 and called it short.

WHY pack_size IS TRUSTED HERE
-----------------------------
recommendations.py used to say "cases x pack_size agrees with pieces only
~84% of the time, so there is no honest conversion to apply". That note is
superseded by three independent checks against the LIVE database (2026-09-23):

  1. REMAINDER INVARIANT — if pack_size is pieces-per-case then the loose
     remainder must be smaller than one case. True for 689 of 689 rows in
     the 2026-03 snapshot that have both values (100%).
  2. THE SOURCE'S OWN VALUATION — Inventory_Fact.valuation equals
     cases * unit_cost_per_case + pieces * (unit_cost_per_case / pack_size)
     for 689 of 689 of those rows (100%). The SOH file itself prices the
     loose remainder at cost-per-case / pack_size, which is only coherent
     if pack_size is pieces-per-case.
  3. COVERAGE — every product in the current snapshot has a usable numeric
     pack_size (1,807 of 2,098 Unilever products overall).

Re-run those checks before widening this module's use:
  SELECT COUNT(*) FILTER (WHERE quantity_pieces >= pack_size::numeric) ...

HONEST-NULL, NOT A GUESS
------------------------
A product with no usable numeric pack_size gets stock_pieces = NULL, which
drops it out of BOTH sides of any comparison (excluded, not counted as
failing) — the same rule dashboard.py's safety_stock_rate already applies to
a missing stock row. We never fall back to comparing cases against pieces.
"""
from __future__ import annotations

# A positive integer or decimal, as TEXT. Product_Dimension.pack_size is a
# free-text column, so anything else ('12x24', 'ASSORTED', '') is unusable
# and must produce NULL rather than a coerced number.
PACK_SIZE_NUMERIC = r"pd_pack.pack_size ~ '^[0-9]+(\.[0-9]+)?$' AND pd_pack.pack_size::numeric > 0"

# Stock on hand converted to PIECES, the unit every planning figure uses.
# NULL when pack_size is unusable — see HONEST-NULL above.
STOCK_PIECES_EXPR = f"""
    CASE WHEN {PACK_SIZE_NUMERIC}
         THEN SUM(inv.quantity_on_hand) * pd_pack.pack_size::numeric
              + COALESCE(SUM(inv.quantity_pieces), 0)
    END
"""

# Peso value of stock on hand. Inventory_Fact.valuation is the SOURCE's own
# extended total and already includes the loose-piece remainder; the
# multiplication is only a fallback for rows that predate it. Using
# valuation first closes a 3.2% gap (PHP 22,700,826 vs 21,991,481 at
# 2026-03) between what this app reported and what the SOH file itself says.
STOCK_VALUE_EXPR = """
    SUM(COALESCE(inv.valuation, inv.quantity_on_hand * inv.unit_cost_per_case))
"""

# One row per product at :inv_period, carrying both figures above.
# Callers LEFT JOIN this so a product with no snapshot row stays NULL
# (a real gap) instead of reading as zero stock.
STOCK_AT_PERIOD_SQL = f"""
    SELECT inv.product_key,
           {STOCK_PIECES_EXPR} AS stock_pieces,
           {STOCK_VALUE_EXPR}  AS stock_value_pesos,
           SUM(inv.quantity_on_hand) AS stock_cases
    FROM inventory_fact_real inv
    JOIN product_dimension pd_pack ON pd_pack.product_key = inv.product_key
    WHERE inv._period = :inv_period
    GROUP BY inv.product_key, pd_pack.pack_size
"""

# Why a comparison could not be made, for the UI to show instead of a number.
NO_PACK_SIZE_REASON = (
    "stock is recorded in cases and this product has no usable pack size, so it "
    "cannot be compared with a safety stock expressed in pieces"
)
