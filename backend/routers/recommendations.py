"""
backend.routers.recommendations — GET /recommendations, PATCH /recommendations/{id}

Returns LP-derived replenishment quantities Q_i per SKU, joined to
Product_Dimension for identity and to the latest Inventory_Fact_Real period
for current_stock. urgency is backend/stock_status.py's one rule under the
reorder page's names (CRITICAL below ss_i, URGENT below the target stock
rop_i, PLANNED at or above it, NO DATA), not stored anywhere. Until
2026-09-30 it was CRITICAL below 0.5 x rop_i, URGENT below rop_i and PLANNED
otherwise — the 0.5 had no source.

?from=/?to= (shared date-range picker, 2026-09) — OPTIONAL, both must be
given together or neither is used (matching backend/routers/dashboard.py's
own ?period=/?start_period= convention for the same shared picker, just
under from/to naming since this is a plain date-bounded table read, not a
period-anchored trend). Filters on lr.planning_cycle_date
falling within [from, to] inclusive — real, meaningful spread on this
column (34 distinct pending planning_cycle_dates from 2023-05 through
2026-03, confirmed live), unlike GET /forecast's forecast_date which is a
single fixed value for every SKU and can't be meaningfully range-filtered
the same way.

PATCH implements the Accept/Dismiss write-back onto LP_Recommendation.status.
There is no cost/lead-time/reason column on LP_Recommendation — accept/dismiss
reasons stay logged client-side to the audit log, not persisted here.

IMPACT RANKING + COVER (2026-09-18). Live, the latest cycle (2026-03) had
248 of 250 rows CRITICAL and 0 URGENT — a severity that never varies says
nothing, so the page now ranks by business impact instead. Three additions,
each derived only from real columns:

  revenue_share   ABC_Classification.revenue_share at the product's latest
                  single-period run (DISTINCT ON product_key). None when the
                  product was never classified (19 of the 250 live rows).
  stockout_gap    max(0, rop_i - current_stock) when the stock row exists.
  priority_score  revenue_share x stockout_gap — the sort key.

UNITS RECONCILED (2026-09-23). This file used to compare quantity_on_hand
(CASES) against rop_i (PIECES) and said so in a caveat, on the grounds that
pack_size agreed with the pieces column "only ~84% of the time". That was
wrong in a way that mattered: it made 215 of 429 pending rows CRITICAL and
0 URGENT. current_stock now comes from backend/stock_units.py, which
converts the snapshot to pieces (cases x pack_size + the loose remainder)
and returns NULL — urgency 'NO DATA' with a reason — when a product has no
usable pack size, rather than comparing two different units. That module
documents the three live checks that justify trusting pack_size. On the
same data the split becomes 185 CRITICAL / 13 URGENT / 20 PLANNED.
  days_of_cover   The one cover figure that IS unit-consistent: stock at
                  cost (the SOH file's own valuation, backend/stock_units.py;
                  pesos, latest snapshot) / average daily sales value
                  (pesos/day) — where the daily rate is the product's
                  net_amount over the SKU_COVER_HISTORY_MONTHS (3, analytics.
                  params) most recent calendar months present in
                  Unilever_SKU_Demand_Fact_Real AT OR BEFORE the stock
                  snapshot month (since 2026-09-30; it took the table's
                  latest months whatever the snapshot), divided by the
                  number of those months and by AVG_DAYS_PER_MONTH. A month
                  the table HAS but this product has no row in counts as 0:
                  the table stores no zero-sale rows, so that month is a
                  month with no sales. (A month missing from the whole table
                  is a gap instead — DEC-29 — which is why the window only
                  takes months the table has.) Until 2026-09-29 those months
                  were averaged out, which overstated the daily rate and
                  understated cover for 24 of the 250 current rows. Exactly
                  the peso basis GET /dashboard's Unilever weeks_of_cover
                  already uses, at SKU grain. Caveat: stock is valued at
                  last purchase cost while sales are at selling price, so
                  cover is understated by the margin — a known bias in one
                  direction, disclosed in the UI tooltip. None (with
                  cover_blocked_reason) when the stock row or its valuation
                  is missing, when the product sold nothing in the window,
                  or when the daily rate is 0 or below. The sales source is
                  Unilever-only, so a Del Monte LP row (none exist live) is
                  honestly blocked.

  current_stock   was COALESCE(..., 0). A product with no Inventory_Fact_Real
                  row at the latest snapshot (39 of the 250 live rows) was
                  read as "0 on hand" and therefore CRITICAL — a fabricated
                  alert. It is now None, and urgency is 'NO DATA'.

NOT IN THE STOCK COUNT = 0 ON HAND, AS THE LP READS IT (2026-10-01). The
2026-09-30 LP (scripts/run_lp.py product_input) plans a product with no row
in its principal's latest stock count as 0 on hand, because the stock file
lists no zero-stock rows (0 of 785 Unilever rows at 2026-03, re-checked
2026-10-01): no row means nothing on hand. Reading such a row as 'NO DATA'
here made the page disagree with the plan it explains. Live, 3 of the 73
rows in the 2026-03 cycle (64971078, 65071335, 69731884) are absent from
the count; the LP cut all three to fit the allocation (1,272 / 542 / 653
pieces short), yet the page counted 37 cut SKUs instead of 40 and left the
three unranked at the bottom. Such a row now gets current_stock 0 and is
ranked, bucketed and cut-checked like any other, with stock_not_in_count
set so the page says the 0 is inferred, not counted. Three cases keep the
old 'NO DATA': a stock row that can't be put in pieces (no usable pack
size; the LP skips those products too), a principal with no stock count
at that snapshot at all, where a missing row says nothing about stock
(in_stock_count is NULL then, see _SELECT_ONE), and — since 2026-10-02 — a
principal whose count DOES list zero-stock items: Del Monte's inventory
files hold 24 explicit Quantity-0 rows, so a Del Monte product missing from
one is unknown, not empty. Only Unilever's count omits zeros (0 of 27,321
raw SOH rows across all 39 sheets read 0/0; backend/stock_status.py's
COUNT_OMITS_ZERO_STOCK has the evidence).

STOCK TIMING (2026-10-03). The stock on this page is the count that OPENS
the cycle month, the month before it (backend/stock_units.opening_period),
because that is the count scripts/run_lp.py now plans from. Until this date
both used each principal's LATEST count: for cycle 2026-03 that was the count
of 2026-04-06, the stock left after March's sales, so need = forecast +
target - stock counted March twice (reports/diagnostics/lp_logic_check_
2026-10-03). Wherever this docstring says "latest snapshot" for a row's stock
or cover, read "the cycle's opening count". The response's stock_counts says
which count that is and when it was counted, or, when the principal has
none, the reason the plan can't be made from it ("no opening stock count for
<month>"). cycle=all reads each cycle's own opening count. "Stock now"
screens keep the latest count (GET /dashboard's kpis.stock_counts).

REVIEW FLAG (2026-10-04, DEC-33) — the contract the Reorder page's review
badge reads:
  needs_review    true  = review before ordering: the product's forecast for
                          this cycle is likely to miss by a lot
                  false = assessed, not flagged
                  null  = not assessed for this cycle (no review_flag row,
                          or the table isn't there yet)
  review_reasons  [] or any of 'collapse' (last-3-month mean below half the
                  last-12-month mean) and 'over_forecast_run' (the served
                  model over-forecast it 3+ months running before the cycle)
  review_over_run_months, review_collapse_ratio  the figures behind them
                  (over-run counted back at most 6, so 6 = "6 or more")
Source: review_flag (migration 0042), written by
scripts/compute_review_flags.py (option D, kelvin/surplus-bias-experiment
3226cc4). It says "check before ordering", not which way to adjust.
THE 409 RULE: PATCH /recommendations/{id} with status 'accepted' on a row
whose needs_review is true returns 409 unless the body carries
"reviewed": true. Dismiss needs no confirmation, and unflagged rows accept
as before. The page sends reviewed=true only from a single row's confirm
dialog; "Accept all in view" leaves flagged rows out, so a flagged product
is never accepted in bulk or without a person. The audit-log entry for such
an accept ends "[flagged for review: <reasons>; reviewed]".

ON ORDER (2026-10-04) — INFORMATION ONLY, MEANING UNVERIFIED. on_order is
the "PO Qty" of the same opening count the row's stock comes from, in pieces
(backend/stock_units.ON_ORDER_AT_PERIOD_SQL). It is NOT treated as stock in
transit and is never subtracted from q_i or any other order quantity
(decision 2026-10-04, Yuan, DEC-34): on the count of 2 March 2026 it totals
1,644,300 pieces against an order plan of 325,468 and about 1.69M on hand,
and it runs 1-3M pieces every month, which doesn't fit in-transit stock.
on_order_note says so on every row until SSM explains the column. None with
on_order_blocked_reason when the count's PO Qty isn't loaded (live rows stay
unloaded until SSM answers), the principal's file has no PO column (Del
Monte), the product is absent from the count, or it has no usable pack size.

PLANNING MART (2026-10-05, migration 0046). In real mode GET reads
mart.planning_mart: one row per product x cycle that already carries every
column _SELECT_ONE joins per request, built by the same rules
(mart.refresh_planning). One statement instead of 12 (_from_mart,
backend/planning_mart.py); the rows go through the same _to_item, so the
response is field for field the one the joins give
(scripts/rehearse_planning_mart.py compares the two for every row before the
migration is applied). The joins below stay: preview mode reads them, and so
does real mode whenever the mart is missing or out of step with its sources
(backend/planning_mart.usable / read), so a missed refresh costs speed, never
a wrong figure. A decision (PATCH) updates the mart's row in its own
transaction.

PACK SIZE (2026-10-01). Every quantity here is in PIECES, while SSM buys
in cases: an order of 104,575 pieces is about 363 cases of 288. pack_size
(Product_Dimension's pieces per case, None when unusable — the same rule
backend/stock_units.py converts stock with) lets the page show the case
count beside each quantity. Only 6 of the 73 live orders are whole cases;
the LP doesn't round to cases, and nothing here does either.
"""
from __future__ import annotations

import datetime
import math

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import text
from analytics.params import abc_method_sql
from sqlalchemy.orm import Session

from backend import audit
from backend.deps import TokenPayload, get_db
from backend.permissions import require_permission
from backend.principals import (
    PrincipalQuery,
    latest_abc_period,
    principal_clause,
)
from backend.schemas.recommendations import RecommendationItem, RecommendationDecision, RecommendationsResponse
from backend.data_mode import PREVIEW, REAL, forecast_source, get_data_mode, lp_source, predictive_preview, preview_block
from backend.lp_cycle import CURRENT_CYCLE_CLAUSE, current_cycle, freshness_from, lp_model_info, stored_run
from backend.lp_cycle import freshness as lp_freshness
from analytics.params import DAYS_PER_MONTH, SKU_COVER_HISTORY_MONTHS
from backend.stock_status import COUNT_OMITS_ZERO_STOCK, NO_DATA, URGENCY, stock_status
from backend.stock_units import (
    NO_PACK_SIZE_REASON,
    ON_ORDER_ABSENT_SQL,
    ON_ORDER_AT_PERIOD_SQL,
    ON_ORDER_PRINCIPALS,
    PACK_SIZE_NUMERIC,
    STOCK_AT_PERIOD_SQL,
    missing_opening_count_reason,
    opening_period,
    stock_count_info,
    stock_counts,
)
from backend import planning_mart, response_cache
from backend.response_cache import cached

# Order quantities are counted in whole units rounded UP, the rule the Reorder
# page applies to every row (frontend/src/utils/formatNumber.js wholeUnits),
# so any total computed here equals the sum of the rows a planner sees. The
# epsilon keeps float noise (1782.0000000002) from rounding up a whole unit.
_WHOLE_UNIT_EPSILON = 1e-6


def whole_units(value: float) -> int:
    return math.ceil(value - _WHOLE_UNIT_EPSILON)

router = APIRouter(prefix="/recommendations", tags=["recommendations"])

# stock_units.PACK_SIZE_NUMERIC is written against its own pd_pack alias;
# the row query reads Product_Dimension as pd.
_PACK_SIZE_USABLE = PACK_SIZE_NUMERIC.replace("pd_pack.", "pd.")
assert "pd_pack" not in _PACK_SIZE_USABLE

# :inv_period is the cycle's opening count (opening_period), never the latest.
# in_stock_count — TRUE: the product has a row in the stock count. FALSE:
# its principal was counted at this snapshot but the product wasn't, which
# the LP reads as 0 on hand, and so does _to_item where the principal's file
# lists no zero-stock rows (Unilever; Del Monte's does, so NO DATA). NULL: the
# principal has no count at this snapshot (no opening count for the cycle),
# so a missing row says nothing about stock and stays 'NO DATA'.
_SELECT_ONE = f"""
    SELECT
        lr.recommendation_key,
        COALESCE(pd.sku_code, pd.category_path) AS sku_id,
        pd.product_name,
        pd.principal,
        CASE WHEN {_PACK_SIZE_USABLE} THEN pd.pack_size::numeric END AS pack_size,
        lr.planning_cycle_date,
        lr.q_i,
        lr.rop_i,
        lr.ss_i,
        lr.status,
        inv.stock_pieces AS current_stock,
        inv.stock_cases AS current_stock_cases,
        inv.stock_value_pesos AS stock_value_pesos,
        CASE WHEN inv.product_key IS NOT NULL THEN TRUE
             WHEN counted.principal IS NOT NULL THEN FALSE
        END AS in_stock_count,
        abc.revenue_share AS revenue_share,
        abc.tier AS tier,
        sales.avg_monthly_sales_pesos AS avg_monthly_sales_pesos,
        fr.forecast_value AS forecast_units,
        oo.on_order_pieces AS on_order_pieces,
        oo.on_order_cases AS on_order_cases,
        oo.on_order_unparsed AS on_order_unparsed,
        rf.needs_review AS needs_review,
        rf.reasons AS review_reasons,
        rf.over_run_months AS review_over_run_months,
        rf.collapse_ratio AS review_collapse_ratio
    FROM lp_recommendation lr
    JOIN product_dimension pd ON pd.product_key = lr.product_key
    LEFT JOIN Forecast_Result fr
      ON fr.product_key = lr.product_key AND fr.forecast_date = lr.planning_cycle_date
    LEFT JOIN (
        {STOCK_AT_PERIOD_SQL}
    ) inv ON inv.product_key = lr.product_key
    LEFT JOIN (
        SELECT DISTINCT principal FROM inventory_fact_real WHERE _period = :inv_period
    ) counted ON counted.principal = pd.principal
    LEFT JOIN (
        SELECT DISTINCT ON (product_key) product_key, revenue_share, tier
        FROM abc_classification
        WHERE {abc_method_sql()} AND classification_period = :abc_period
        ORDER BY product_key, classification_period DESC
    ) abc ON abc.product_key = lr.product_key
    LEFT JOIN (
        SELECT recent.product_key, SUM(recent.month_total) / MAX(sales_window.months) AS avg_monthly_sales_pesos
        FROM (
            SELECT product_key, calendar_month, SUM(net_amount) AS month_total
            FROM unilever_sku_demand_fact_real
            WHERE calendar_month IN (
                SELECT DISTINCT calendar_month FROM unilever_sku_demand_fact_real
                WHERE calendar_month <= :inv_period
                ORDER BY calendar_month DESC LIMIT {SKU_COVER_HISTORY_MONTHS}
            )
            GROUP BY product_key, calendar_month
        ) recent
        CROSS JOIN (
            SELECT COUNT(*) AS months FROM (
                SELECT DISTINCT calendar_month FROM unilever_sku_demand_fact_real
                WHERE calendar_month <= :inv_period
                ORDER BY calendar_month DESC LIMIT {SKU_COVER_HISTORY_MONTHS}
            ) window_months
        ) sales_window
        GROUP BY recent.product_key
    ) sales ON sales.product_key = lr.product_key
    LEFT JOIN (
        {{_ON_ORDER}}
    ) oo ON oo.product_key = lr.product_key
    LEFT JOIN (
        {{_REVIEW}}
    ) rf ON rf.product_key = lr.product_key AND rf.planning_cycle_date = lr.planning_cycle_date
"""

# review_flag (migration 0042) and the PO Qty columns may not exist yet on the
# database this runs against: the row query then reads the same columns from
# no rows, so every row says "not assessed" / "not loaded" instead of failing.
_PRESENT_SQL = """
    SELECT to_regclass('review_flag') IS NOT NULL AS review_flag,
           EXISTS (
               SELECT 1 FROM pg_attribute
               WHERE attrelid = to_regclass('inventory_fact') AND attname = 'po_qty_cases' AND NOT attisdropped
           ) AS on_order
"""
_REVIEW_SQL = """
        SELECT product_key, planning_cycle_date, needs_review, reasons, over_run_months, collapse_ratio
        FROM review_flag
"""
_REVIEW_ABSENT_SQL = """
        SELECT NULL::bigint AS product_key, NULL::date AS planning_cycle_date, NULL::boolean AS needs_review,
               NULL::text[] AS reasons, NULL::integer AS over_run_months, NULL::numeric AS collapse_ratio
        WHERE false
"""


def _present(db: Session) -> dict:
    """{review_flag, on_order}: whether migration 0042's table and columns
    exist. A database (or test fake) that can't answer counts as neither."""
    row = db.execute(text(_PRESENT_SQL)).mappings().first()
    return {"review_flag": bool(row and row["review_flag"]), "on_order": bool(row and row["on_order"])}


def _with_present(sql: str, present: dict) -> str:
    return (sql.replace("{_ON_ORDER}", ON_ORDER_AT_PERIOD_SQL if present["on_order"] else ON_ORDER_ABSENT_SQL)
               .replace("{_REVIEW}", _REVIEW_SQL if present["review_flag"] else _REVIEW_ABSENT_SQL))

_LP_FROM = "FROM lp_recommendation lr"
assert _SELECT_ONE.count(_LP_FROM) == 1
_FC_JOIN = "LEFT JOIN Forecast_Result fr"
assert _SELECT_ONE.count(_FC_JOIN) == 1


def select_one(mode: str = REAL, present: dict | None = None) -> tuple[str, dict]:
    """_SELECT_ONE and its extra params for `mode`: in preview with built
    outputs its LP read comes from backend/data_mode.lp_source() and its
    forecast read from forecast_source(), so a what-if row is explained by
    the what-if forecast it was solved against; every other join (stock,
    ABC, recent sales, on order, review flag) is the real one either way.
    `present` is _present(db); None reads 0042's table and columns."""
    lp, params = lp_source(mode, "lp_recommendation")
    fc, fc_params = forecast_source(mode, "Forecast_Result")
    base = _with_present(_SELECT_ONE, present or {"review_flag": True, "on_order": True})
    sql = base if lp == "lp_recommendation" else base.replace(_LP_FROM, f"FROM {lp} lr")
    if fc != "Forecast_Result":
        sql = sql.replace(_FC_JOIN, f"LEFT JOIN {fc} fr")
    return sql, {**params, **fc_params}


# Average days per calendar month (analytics.params.DAYS_PER_MONTH, 365.25 /
# 12) — the convention dashboard.py's AVG_WEEKS_PER_MONTH is built from.
AVG_DAYS_PER_MONTH = DAYS_PER_MONTH


def _opt_float(row, key) -> float | None:
    """Reads an optional column that older callers/fixtures may not
    project at all (RowMapping and dict both support .get)."""
    val = row.get(key) if hasattr(row, "get") else None
    return None if val is None else float(val)


def _cover(stock_value: float | None, avg_monthly_sales: float | None) -> tuple[float | None, str | None]:
    if stock_value is None:
        return None, "no stock valuation in the cycle's opening stock count (no row, or no unit cost)"
    if avg_monthly_sales is None:
        return None, (f"no sales rows for this SKU in the {SKU_COVER_HISTORY_MONTHS} sales months "
                      "up to the stock snapshot")
    if avg_monthly_sales <= 0:
        return None, "average recent sales value is zero or negative — cannot divide"
    daily = avg_monthly_sales / AVG_DAYS_PER_MONTH
    return round(stock_value / daily, 1), None


def _to_item(r, present: dict | None = None) -> RecommendationItem:
    # current_stock is PIECES (backend/stock_units.py), the same unit as
    # rop_i. Until 2026-09-23 this read quantity_on_hand — CASES — straight
    # off the snapshot and compared it with a piece-scale ROP, which made
    # almost every row CRITICAL. Two different reasons produce no figure,
    # and they are reported apart rather than both as a bare "NO DATA".
    stock = None if r["current_stock"] is None else float(r["current_stock"])
    stock_cases = _opt_float(r, "current_stock_cases")
    stock_value = _opt_float(r, "stock_value_pesos")
    # Absent from a stock count that did happen. Where the principal's count
    # never lists a zero-stock item (Unilever: backend/stock_status.py's
    # COUNT_OMITS_ZERO_STOCK) that is 0 on hand, the LP's own reading (see
    # the module docstring), so this row is ranked and checked for a cut like
    # any other. Where the count does list zeros (Del Monte), missing says
    # nothing, and the row stays 'NO DATA'. Only an explicit FALSE counts —
    # NULL (no count to be absent from) and callers that don't project the
    # column keep the 'NO DATA' path below.
    in_count = r.get("in_stock_count") if hasattr(r, "get") else None
    stock_not_in_count = in_count is False and r["principal"] in COUNT_OMITS_ZERO_STOCK
    if stock_not_in_count:
        stock, stock_value = 0.0, 0.0
    rop = float(r["rop_i"])
    stock_blocked_reason = None
    if stock is None:
        urgency = NO_DATA
        if in_count or stock_cases is not None:
            # In the count, but its cases can't be put in pieces.
            stock_blocked_reason = NO_PACK_SIZE_REASON
        elif in_count is False:
            stock_blocked_reason = (
                "not in its principal's opening stock count for this cycle, which lists zero-stock items, "
                "so its stock is unknown rather than 0"
            )
        elif "in_stock_count" in r:
            stock_blocked_reason = missing_opening_count_reason(r["principal"], r["planning_cycle_date"])
        else:
            stock_blocked_reason = "no Inventory_Fact_Real row for this product in the cycle's opening stock count"
    else:
        urgency = URGENCY[stock_status(stock, float(r["ss_i"]), rop)]

    revenue_share = _opt_float(r, "revenue_share")
    stockout_gap = None if stock is None else max(0.0, rop - stock)
    priority_score = (
        round(revenue_share * stockout_gap, 4)
        if revenue_share is not None and stockout_gap is not None
        else None
    )
    days_of_cover, cover_reason = _cover(stock_value, _opt_float(r, "avg_monthly_sales_pesos"))

    # The LP's own arithmetic since the 2026-09-30 run (scripts/run_lp.py):
    # need = the cycle month's forecast + target stock (rop_i) - stock on
    # hand, floored at 0, and q_i is that need less any cut made to fit the
    # supplier allocation. Without the forecast on the page, q_i can't be
    # read off the row (target 14,418 - stock 22 = 14,396 against an order
    # of 35,365), and a row cut to fit the allocation looks identical to a
    # filled one. short_units is that cut: the row ends the month short of
    # its target by this much. Under 1 piece is rounding, not a cut.
    forecast = _opt_float(r, "forecast_units")
    short_units = None
    if forecast is not None and stock is not None:
        short = max(0.0, forecast + rop - stock) - float(r["q_i"])
        short_units = round(short, 2) if short >= 1.0 else 0.0

    on_order, on_order_cases, on_order_reason = _on_order(r, in_count, stock_not_in_count, present)
    reasons = r.get("review_reasons") if hasattr(r, "get") else None

    return RecommendationItem(
        recommendation_key=r["recommendation_key"],
        sku_id=r["sku_id"] or "",
        product_name=r["product_name"],
        principal=r["principal"],
        planning_cycle_date=r["planning_cycle_date"],
        q_i=float(r["q_i"]),
        rop_i=rop,
        ss_i=float(r["ss_i"]),
        status=r["status"],
        current_stock=stock,
        current_stock_cases=stock_cases,
        stock_not_in_count=stock_not_in_count,
        pack_size=_opt_float(r, "pack_size"),
        stock_blocked_reason=stock_blocked_reason,
        urgency=urgency,
        revenue_share=revenue_share,
        tier=r.get("tier"),
        stockout_gap=stockout_gap,
        priority_score=priority_score,
        days_of_cover=days_of_cover,
        forecast_units=forecast,
        short_units=short_units,
        cover_blocked_reason=cover_reason,
        on_order=on_order,
        on_order_cases=on_order_cases,
        on_order_blocked_reason=on_order_reason,
        on_order_note=ON_ORDER_NOTE,
        needs_review=r.get("needs_review") if hasattr(r, "get") else None,
        review_reasons=list(reasons or []),
        review_over_run_months=r.get("review_over_run_months") if hasattr(r, "get") else None,
        review_collapse_ratio=_opt_float(r, "review_collapse_ratio"),
    )


# On every row: what on_order is and isn't (decision 2026-10-04, DEC-34).
ON_ORDER_NOTE = ("PO Qty meaning unverified, pending SSM: shown for information only, "
                 "never subtracted from any order quantity")


def _on_order(r, in_count, stock_not_in_count, present) -> tuple[float | None, float | None, str | None]:
    """(pieces on order, cases on order, why unknown) for one row, from the
    opening count's PO Qty. Unknown is None with a reason, never 0. `present`
    is _present(db); None (a caller that didn't check) reads the row alone."""
    principal = r["principal"]
    if principal not in ON_ORDER_PRINCIPALS:
        return None, None, "this principal's stock file has no purchase-order column"
    if (present is not None and not present["on_order"]) or not (hasattr(r, "get") and "on_order_unparsed" in r):
        return None, None, "stock on order is not loaded yet (migration 0042)"
    if stock_not_in_count or in_count is False:
        return None, None, "not in the cycle's opening stock count, which records stock on order only for listed products"
    if r.get("on_order_unparsed") is None:
        return None, None, "no row in the cycle's opening stock count to read stock on order from"
    if r["on_order_unparsed"]:
        return None, None, ("PO Qty is not loaded for the cycle's opening stock count: counts loaded before "
                            "migration 0042 are not reloaded while its meaning is unverified (DEC-34)")
    cases = _opt_float(r, "on_order_cases")
    pieces = _opt_float(r, "on_order_pieces")
    if pieces is None:
        return None, cases, "stock on order is recorded in cases and this product has no usable pack size"
    return pieces, cases, None


@router.get("", response_model=RecommendationsResponse)
@cached("GET /recommendations")
def get_recommendations(
    status: str | None = Query(None, description="Filter to 'pending' | 'accepted' | 'dismissed'. Omit for all."),
    cycle: str = Query(
        "current",
        pattern="^(current|all)$",
        description=(
            "'current' (default) returns only the LP's current planning cycle — the most recent "
            "cycle that still has pending rows. Superseded pending rows from earlier runs are "
            "withheld and counted in `superseded_count`. 'all' returns every cycle, for an audit "
            "view. See backend/lp_cycle.py."
        ),
    ),
    from_date: str | None = Query(None, alias="from", description="'YYYY-MM-DD'. The shared date-range picker's applied start. Must be given with 'to' or not at all — filters on lr.planning_cycle_date."),
    to_date: str | None = Query(None, alias="to", description="'YYYY-MM-DD'. The shared date-range picker's applied end. Must be given with 'from' or not at all."),
    principal: str | None = PrincipalQuery,
    mode: str = Depends(get_data_mode),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_permission("lp.view")),
) -> RecommendationsResponse:
    # Both principals again (2026-09-17) — see backend/principals.py.
    # lp_recommendation currently holds 430 Unilever rows and ZERO Del
    # Monte rows (confirmed live 2026-09-17), so ?principal=delmonte
    # honestly returns an empty list until the LP is run for Del Monte.
    if planning_mart.usable(db, mode):
        served = _from_mart(db, status, cycle, from_date, to_date, principal)
        if served is not None:
            return served
    scope_sql, scope_params = principal_clause(principal, "pd.principal")
    present = _present(db)
    select_sql, lp_params = select_one(mode, present)
    filters = scope_sql
    # The ABC anchor resolves under the SAME scope as the rows. It replaces a
    # per-product "latest classification_period" walk, which quietly mixed
    # classification vintages: a SKU last classified months ago contributed
    # a stale revenue_share alongside current ones. Pinned to one period,
    # such a SKU now yields revenue_share None and therefore priority_score
    # None — already null-guarded below. The stock anchor (:inv_period) is
    # set per cycle below: the count that opens it.
    params: dict = {
        "abc_period": latest_abc_period(db, principal),
        **scope_params,
        **lp_params,
    }
    if status:
        filters += " AND lr.status = :status"
        params["status"] = status
    # Shared date-range picker (2026-09) — planning_cycle_date is a real
    # DATE column (unlike the fact tables' 'YYYY-MM' _period text), so this
    # compares dates directly, no month-truncation needed.
    if from_date and to_date:
        filters += " AND lr.planning_cycle_date >= :from_date AND lr.planning_cycle_date <= :to_date"
        params["from_date"] = from_date
        params["to_date"] = to_date

    # Superseded cycles never reach a screen (2026-09-23) — see
    # backend/lp_cycle.py. A leftover `pending` row from a 2023 run is not a
    # recommendation anyone should act on today, and mixing it into this
    # list was what made the dashboard's pending count read 429 instead of
    # 250. `cycle=all` is the deliberate audit escape hatch.
    freshness = lp_freshness(db, principal, mode)
    if cycle == "current":
        current = current_cycle(db, principal, mode)
        if current is None:
            # Nothing pending at all: 'current' has nothing to scope to, so
            # returning every decided row would contradict the filter's
            # promise. An empty list with the reason is the honest answer.
            return _with_data_mode(RecommendationsResponse(
                items=[], count=0, planning_cycle_date=None,
                superseded_count=0, freshness=freshness, lp_model=lp_model_info(),  # no cycle: defaults
                stock_counts=[],
            ), db, mode)
        cycles, cycle_clause = [current], CURRENT_CYCLE_CLAUSE
    else:
        # Each cycle against its own opening count, so the audit view runs
        # the row query once per cycle, newest first.
        lp, _ = lp_source(mode, "lp_recommendation")
        listed = db.execute(text(
            f"SELECT DISTINCT lr.planning_cycle_date AS d FROM {lp} lr "
            f"JOIN product_dimension pd ON pd.product_key = lr.product_key WHERE 1=1{filters}"
        ), params).mappings().all()
        cycles = sorted((r["d"] for r in listed), reverse=True)
        cycle_clause = " AND lr.planning_cycle_date = :listed_cycle"

    rows: list = []
    counts: list[dict] = []
    for planning_cycle in cycles:
        cycle_params = {**params, "inv_period": opening_period(planning_cycle),
                        "current_cycle": planning_cycle, "listed_cycle": planning_cycle}
        cycle_rows = db.execute(
            text(select_sql + " WHERE 1=1" + filters + cycle_clause + " ORDER BY lr.rop_i DESC"), cycle_params,
        ).mappings().all()
        rows.extend(cycle_rows)
        # Which count each principal on the list was checked against, and
        # when it was counted, or why there is none.
        principals = sorted({r["principal"] for r in cycle_rows})
        counts.extend(stock_counts(db, opening_period(planning_cycle), principals, cycle=planning_cycle))
    items = [_to_item(r, present) for r in rows]
    return _with_data_mode(RecommendationsResponse(
        items=items,
        count=len(items),
        planning_cycle_date=freshness["cycle_date"],
        superseded_count=freshness["superseded_pending_count"] if cycle == "current" else 0,
        freshness=freshness,
        # What the run behind the current cycle used (lp_run), else the defaults, labelled.
        lp_model=lp_model_info(stored_run(db, freshness["cycle_date"], principal, mode)),
        stock_counts=counts,
    ), db, mode)


# The planning mart is built on migration 0042's table and columns.
_MART_PRESENT = {"review_flag": True, "on_order": True}


def _from_mart(db: Session, status: str | None, cycle: str, from_date: str | None, to_date: str | None,
               principal: str | None) -> RecommendationsResponse | None:
    """get_recommendations' answer from mart.planning_mart (real mode), in one statement.
    None when the mart must not be served (backend/planning_mart.read): the caller then
    runs the per-request joins."""
    got = planning_mart.read(db, principal, status, cycle, from_date, to_date)
    if got is None:
        return None
    head = got["head"]
    freshness = freshness_from(head["cycle"], head["fc_at"], head["lp_at"], int(head["row_count"] or 0),
                               int(head["stale_count"] or 0), int(head["superseded"] or 0))
    if cycle == "current" and head["cycle"] is None:
        return RecommendationsResponse(
            items=[], count=0, planning_cycle_date=None,
            superseded_count=0, freshness=freshness, lp_model=lp_model_info(),
            stock_counts=[],
        )
    rows = got["rows"]
    # The opening count each principal's rows were checked against, per cycle (newest
    # first): the count's own figures as the mart keeps them, None when there is no count.
    counts = [
        stock_count_info(c["principal"], c["opening_period"], None if c["row_count"] is None else c,
                         c["planning_cycle_date"])
        for c in got["counts"]
    ]
    items = [_to_item(r, _MART_PRESENT) for r in rows]
    return RecommendationsResponse(
        items=items,
        count=len(items),
        planning_cycle_date=freshness["cycle_date"],
        superseded_count=freshness["superseded_pending_count"] if cycle == "current" else 0,
        freshness=freshness,
        lp_model=lp_model_info(got["run"]),
        stock_counts=counts,
    )


def _with_data_mode(response: RecommendationsResponse, db: Session, mode: str):
    """Real mode: the model untouched. Preview: the data_mode block beside it,
    saying whether these rows are the five-year what-if (never saved, not
    decidable) or, with no preview files built, still the real ones."""
    if mode != PREVIEW:
        return response
    block = preview_block(db, real_only=None if predictive_preview(mode) else ["items"])
    return JSONResponse({**jsonable_encoder(response), "data_mode": block})


@router.patch("/{recommendation_key}", response_model=RecommendationItem)
def update_recommendation(
    recommendation_key: int,
    decision: RecommendationDecision,
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_permission("lp.decide")),
) -> RecommendationItem:
    if decision.status not in ("accepted", "dismissed"):
        raise HTTPException(status_code=400, detail="status must be 'accepted' or 'dismissed'")
    present = _present(db)
    flagged = _review_reasons(db, recommendation_key) if present["review_flag"] else None
    if decision.status == "accepted" and flagged is not None and not decision.reviewed:
        raise HTTPException(status_code=409, detail=(
            "This product is flagged for review before ordering (" + ", ".join(flagged) + "). "
            "Accept it from its own row after checking it; it is never accepted in bulk."
        ))

    decision_params = {
        "status": decision.status,
        "decided_at": datetime.datetime.utcnow(),
        "decided_by": current_user.email,
        "key": recommendation_key,
    }
    decided = db.execute(
        text("""
            UPDATE lp_recommendation
            SET status = :status, decided_at = :decided_at, decided_by = :decided_by
            WHERE recommendation_key = :key
            RETURNING (SELECT COALESCE(pd.sku_code, pd.category_path) FROM product_dimension pd
                        WHERE pd.product_key = lp_recommendation.product_key) AS sku,
                      planning_cycle_date
        """),
        decision_params,
    ).mappings().first()
    if decided is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Recommendation not found")
    # The planning mart's row for this decision, in the same transaction (migration 0046).
    planning_mart.decide(db, decision_params)
    audit.record(
        db,
        f"Reorder Recommendation {'Accepted' if decision.status == 'accepted' else 'Dismissed'}",
        f"SKU {decided['sku']}" + (f": {decision.reason}" if decision.reason else "")
        + (f" [flagged for review: {', '.join(flagged)}; reviewed]" if flagged and decision.status == "accepted" else ""),
        actor=current_user,
    )
    db.commit()
    response_cache.invalidate()

    # Single row pinned by recommendation_key; scope left unfiltered (None
    # = all), identical to today's behaviour — see sku.py's _one_row_params.
    # Stock at the row's own cycle's opening count, as GET shows it.
    row = db.execute(
        text(_with_present(_SELECT_ONE, present) + " WHERE lr.recommendation_key = :key"),
        {
            "key": recommendation_key,
            "inv_period": opening_period(decided["planning_cycle_date"]),
            "abc_period": latest_abc_period(db, None),
        },
    ).mappings().first()
    return _to_item(row, present)


def _review_reasons(db: Session, recommendation_key: int) -> list[str] | None:
    """The review_flag reasons when this row's product is flagged for its
    cycle, else None (not flagged, or not assessed)."""
    row = db.execute(text("""
        SELECT rf.reasons FROM lp_recommendation lr
        JOIN review_flag rf ON rf.product_key = lr.product_key AND rf.planning_cycle_date = lr.planning_cycle_date
        WHERE lr.recommendation_key = :key AND rf.needs_review
    """), {"key": recommendation_key}).mappings().first()
    return list(row["reasons"]) if row else None
