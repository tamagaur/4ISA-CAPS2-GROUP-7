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

import datetime

from backend import batch
from backend.data_notes import UNUSUAL_STOCK_SNAPSHOTS, opening_count_ruling

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

# The same three figures, one row per product at ITS OWN principal's latest
# snapshot, for lists that can mix principals (GET /sku and GET /abc under
# 'all'). One :inv_period cannot serve both: Unilever's latest snapshot is
# 2026-03 and Del Monte's 2025-12, so the global latest left every Del Monte
# product without stock under 'all' (260 products with stock -> 0, measured
# 2026-09-29). For a single principal it resolves to exactly the snapshot
# principals.latest_inventory_period() would.
STOCK_AT_LATEST_SQL = f"""
    SELECT inv.product_key,
           {STOCK_PIECES_EXPR} AS stock_pieces,
           {STOCK_VALUE_EXPR}  AS stock_value_pesos,
           SUM(inv.quantity_on_hand) AS stock_cases
    FROM inventory_fact_real inv
    JOIN product_dimension pd_pack ON pd_pack.product_key = inv.product_key
    JOIN (
        SELECT principal, MAX(_period) AS latest_period
        FROM inventory_fact_real
        GROUP BY principal
    ) latest_inv ON latest_inv.principal = inv.principal AND inv._period = latest_inv.latest_period
    GROUP BY inv.product_key, pd_pack.pack_size
"""

# A product's last purchase price per piece: the stock file's unit cost per
# case (Unilever: "Last Purchase Price", GSV per case, no VAT) from its latest
# real count that carries one, divided by pack size. NULL when it has no such
# row or no usable pack size, never a default. The same rule as
# scripts/run_lp.py STOCK_AND_COST_QUERY's cost_per_piece (keep them in step);
# SSM has not confirmed it as their purchase cost, so every peso figure built
# on it is labelled pending SSM confirmation. `alias` is the query's
# Product_Dimension alias.
def last_purchase_price_sql(alias: str) -> tuple[str, str]:
    """(select expression, LATERAL join) for the price per piece of `alias`'s product."""
    pack_ok = PACK_SIZE_NUMERIC.replace("pd_pack.", f"{alias}.")
    expr = f"CASE WHEN {pack_ok} THEN last_price.cost_per_case / {alias}.pack_size::numeric END"
    join = f"""
        LEFT JOIN LATERAL (
            SELECT AVG(inv.unit_cost_per_case) AS cost_per_case
            FROM inventory_fact_real inv
            WHERE inv.product_key = {alias}.product_key AND inv.unit_cost_per_case > 0
            GROUP BY inv._period
            ORDER BY inv._period DESC
            LIMIT 1
        ) last_price ON true
    """
    return expr, join


# The count's "PO Qty" at :inv_period, in pieces (migration 0042,
# Inventory_Fact.po_qty_cases/po_qty_pieces), converted with the same pack
# size rule as stock on hand. Its meaning is UNVERIFIED (pending SSM; DEC-34):
# information only, kept out of every figure above and never subtracted from
# an order quantity. on_order_unparsed counts the product's rows in
# that count whose PO Qty was never parsed (loaded before 0042): the figure is
# unknown then, not 0. A separate fragment, so the stock figures every other
# screen reads are untouched. Callers check that the columns exist first
# (backend/routers/recommendations._present).
ON_ORDER_AT_PERIOD_SQL = f"""
    SELECT inv.product_key,
           CASE WHEN {PACK_SIZE_NUMERIC}
                THEN SUM(inv.po_qty_cases) * pd_pack.pack_size::numeric + COALESCE(SUM(inv.po_qty_pieces), 0)
           END AS on_order_pieces,
           SUM(inv.po_qty_cases) AS on_order_cases,
           COUNT(*) - COUNT(inv.po_qty_cases) AS on_order_unparsed
    FROM inventory_fact_real inv
    JOIN product_dimension pd_pack ON pd_pack.product_key = inv.product_key
    WHERE inv._period = :inv_period
    GROUP BY inv.product_key, pd_pack.pack_size
"""
# The same columns from no rows, for a database where 0042 isn't applied yet.
ON_ORDER_ABSENT_SQL = """
    SELECT NULL::bigint AS product_key, NULL::numeric AS on_order_pieces,
           NULL::numeric AS on_order_cases, NULL::bigint AS on_order_unparsed
    WHERE false
"""
# Principals whose stock file carries a PO column. Unilever's SOH file has
# "PO Qty" (config/column_maps/ssis_soh.yaml); Del Monte's inventory sign-off
# has none (config/column_maps/inventory_sign_off.yaml), so its on-order is
# unknown rather than 0.
ON_ORDER_PRINCIPALS = frozenset({"unilever"})

# Why a comparison could not be made, for the UI to show instead of a number.
NO_PACK_SIZE_REASON = (
    "stock is recorded in cases and this product has no usable pack size, so it "
    "cannot be compared with a safety stock expressed in pieces"
)


# ---------------------------------------------------------------------------
# Which stock count a monthly order plan starts from (2026-10-03)
# ---------------------------------------------------------------------------
# A stock count's _period is the month it CLOSES: Unilever's SSIS file for
# 2026-02 was counted 2026-03-02 (DEC-20), and Del Monte's sign-off for
# 2025-09 reads "Actual as of 2025-09-30". So the count that OPENS month M is
# the one with _period = M - 1. The LP used each principal's latest count
# instead, whatever the cycle: cycle 2026-03 subtracted the count of
# 2026-04-06, the stock left AFTER March's sales, from March's forecast, and
# counted March's demand twice (reports/diagnostics/lp_logic_check_2026-10-03).
#
# A plan for month M uses the count of M - 1 or nothing. An older count would
# skip a month of sales and receipts, and Unilever has no receipt records to
# roll it forward; a later one is the look-ahead above. "Stock now" screens
# (the dashboard's stock card, inventory, SKU and ABC lists) keep the latest
# count, and say its date (stock_count_info).

_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December")


def _year_month(value) -> tuple[int, int]:
    """(year, month) of a date, datetime, 'YYYY-MM' or 'YYYY-MM-DD'."""
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.year, value.month
    text_value = str(value)
    return int(text_value[0:4]), int(text_value[5:7])


def opening_period(cycle) -> str:
    """The _period of the stock count that opens planning month `cycle`:
    the month before it ('2026-03-01' -> '2026-02', January -> the previous
    December)."""
    year, month = _year_month(cycle)
    return f"{year - 1}-12" if month == 1 else f"{year}-{month - 1:02d}"


def month_label(value) -> str:
    """'2026-02' -> 'February 2026'."""
    year, month = _year_month(value)
    return f"{_MONTHS[month - 1]} {year}"


# Only Unilever's count date is real. Its SSIS file states when it was
# counted, 1 to 6 days after the month closes (DEC-20). Del Monte's sign-off
# states one too ("Actual as of", month-end) but the loader doesn't keep it:
# its snapshot_date is a 1st-of-_period placeholder (DEC-12), so showing it as
# a count date would put a December count on 1 December.
COUNT_DATE_IS_REPORTED = frozenset({"unilever"})
COUNT_DATE_NOT_LOADED = (
    "the stock file states its count date (\"Actual as of\", the last day of the month) "
    "but the loader does not keep it (DEC-12)"
)

# One row per principal counted at :count_period. Reads the _Real view, like
# every stock figure.
STOCK_COUNTS_SQL = """
    SELECT inv.principal, inv._period AS period, COUNT(*) AS row_count,
           MIN(inv.snapshot_date) AS first_date, MAX(inv.snapshot_date) AS last_date
    FROM inventory_fact_real inv
    WHERE inv._period = :count_period
    GROUP BY inv.principal, inv._period
"""


def missing_opening_count_reason(principal: str, cycle) -> str:
    """Why `principal`'s plan for `cycle` was refused. The wording the app shows."""
    return (f"no opening stock count for {month_label(cycle)}: {principal} has no stock count "
            f"for {month_label(opening_period(cycle))}")


def stock_count_info(principal: str, period: str | None, row, cycle=None) -> dict:
    """What a screen says about the stock count it used, from a STOCK_COUNTS_SQL
    row (None when the principal has no count at `period`).

    With `cycle`, the count is the one that opens that planning month, and
    backend/data_notes.OPENING_COUNT_RULINGS may set it aside: available is
    then False and reason says why, the same as a count that doesn't exist.
    Keys: cycle (the planning month, ISO, or None), principal, period, role
    ('opening' | 'latest'), available, counted_on (ISO date, or None with
    counted_on_note), row_count, flag (a reviewed note on the count, else
    None) and reason (why it can't be used, else None)."""
    role = "latest" if cycle is None else "opening"
    year, month = _year_month(cycle) if cycle is not None else (None, None)
    info = {"cycle": None if cycle is None else f"{year}-{month:02d}-01",
            "principal": principal, "period": period, "role": role, "available": False,
            "counted_on": None, "counted_on_note": None, "row_count": 0, "flag": None, "reason": None}
    if row is None or period is None:
        info["reason"] = (missing_opening_count_reason(principal, cycle) if cycle is not None
                          else f"{principal} has no stock count")
        return info
    first, last = row["first_date"], row["last_date"]
    if principal not in COUNT_DATE_IS_REPORTED:
        info["counted_on_note"] = COUNT_DATE_NOT_LOADED
    elif first != last:
        info["counted_on_note"] = f"the count's rows carry {first.isoformat()} to {last.isoformat()}"
    else:
        info["counted_on"] = first.isoformat()
    info["row_count"] = int(row["row_count"])
    info["flag"] = UNUSUAL_STOCK_SNAPSHOTS.get((principal, period))
    info["available"] = True
    if cycle is not None:
        ruling = opening_count_ruling(principal, period)
        if ruling is not None:
            treat_as, note = ruling
            if treat_as == "missing":
                info["available"] = False
                info["reason"] = (f"no opening stock count for {month_label(cycle)}: {principal}'s count for "
                                  f"{month_label(period)} is set aside ({note})")
            else:
                info["flag"] = note
    return info


def with_opening_basis(info: dict, recorded: dict | None) -> dict:
    """Says how a cycle's opening stock was obtained (migration 0069). `recorded` is the stock_counts entry the run
    for that cycle kept for this principal (lp_run.inputs.stock_counts.<principal>, scripts/run_lp.py).

    opening_basis 'count': the plan started from the opening month's count.
    opening_basis 'projected': the plan started from a PROJECTION (the earlier count + receipts on the way - the
        month's sales), because the opening count was not loaded when it was made. `period` and `counted_on` are
        then the count it started from, never presented as the opening month's count. `count_now_loaded` says
        the opening count has arrived since, so the plan can be re-run from it.
    None: no plan for this cycle, so nothing to label."""
    info = dict(info)
    if recorded and recorded.get("opening_basis") == "projected":
        info.update({"opening_basis": "projected", "available": True, "reason": None,
                     "count_now_loaded": bool(info["available"]),
                     "projected_from_period": recorded.get("period"), "counted_on": recorded.get("counted_on"),
                     "projection": recorded.get("projection")})
        info["period"] = recorded.get("period")
    else:
        info["opening_basis"] = "count" if info["available"] else None
    return info


def stock_counts(db, period: str | None, principals, cycle=None, run: dict | None = None) -> list[dict]:
    """stock_count_info for each of `principals` at `period`, in that order.
    Pass `cycle` for a plan's opening count (period = opening_period(cycle)), and `run` (backend/lp_cycle.stored_run)
    for the run that made that cycle's plan, so each entry says whether the plan started from a count or from a
    projection (opening_basis, see with_opening_basis)."""
    rows = {}
    if period is not None:
        rows = {r["principal"]: r for r in batch.rows(db, STOCK_COUNTS_SQL, {"count_period": period})}
    recorded = (((run or {}).get("inputs") or {}).get("stock_counts") or {}) if cycle is not None else {}
    return [with_opening_basis(stock_count_info(p, period, rows.get(p), cycle), recorded.get(p)) for p in principals]
