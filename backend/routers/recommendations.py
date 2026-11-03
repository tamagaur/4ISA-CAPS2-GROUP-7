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
                  understated cover for 24 of the 250 current rows. Since 2026-10-28 (D3) it is PIECES
                  over PIECES: current_stock / average daily pieces (the same window,
                  quantity_sold), the basis of GET /dashboard's Unilever
                  weeks_of_cover. The earlier stock-at-cost over sales-at-selling-price
                  version understated cover by the margin (portfolio 6.21 weeks
                  against 7.06 in pieces, queried 2026-10-28). None (with
                  cover_blocked_reason) when the stock row (in pieces)
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

NOT PLANNED (2026-11-03). The plan covers Class A products whose forecast
passed the accuracy check, so the rest of Class A had no row and no signal on
this page: 80 of the 189 as of 2026-02 (66 failed the check, 9 too little
history, 5 dead), 33.16% of 12-month revenue, 12 of them with under a week of
cover on the opening count (all queried read-only, 2026-11-03).
?include_not_planned=true adds them as `not_planned`, lowest cover first:
reason, stock and recent sales, read as a plan row's are, and no order quantity.
It is a list beside the plan, not part of it: count, order_count and the plan
total don't include it, and nothing in forecasting, safety stock or the LP
reads it. Opt-in so that the other callers of this route don't pay for the read.
"""
from __future__ import annotations

import datetime
import json
import math

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import text
from analytics.params import abc_method_sql
from sqlalchemy.orm import Session

from backend import audit, demo_data, expected_receipts
from backend.api_errors import ApiError
from backend.deps import TokenPayload, get_db
from backend.permissions import require_permission
from backend.principals import (
    PrincipalQuery,
    normalize_principal,
    abc_period_params,
    abc_period_pred,
    latest_abc_period,
    latest_abc_periods,
    tier_a_periods,
    principal_clause,
)
from backend.schemas.recommendations import (
    NotPlannedItem, RecommendationItem, RecommendationDecision, RecommendationsResponse,
)
from backend.data_mode import (
    PREVIEW, REAL, demo_data_enabled, forecast_source, get_data_mode, lp_source, predictive_preview, preview_block,
)
from backend.lp_cycle import (
    CURRENT_CYCLE_CLAUSE, PLAN_STATUS_SQL_BARE, current_cycle, freshness_from, lp_model_info, stored_run,
)
from backend.lp_cycle import freshness as lp_freshness
from analytics.params import DAYS_PER_MONTH, SKU_COVER_HISTORY_MONTHS
from backend.case_pack import PACK_SQL, check_whole_cases
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
    with_opening_basis,
)
from backend import planning_mart, response_cache, stock_observation
# The one account of why a product isn't planned, so this list and GET /abc can't give two.
from backend.routers.abc import _no_target_reason
from backend.response_cache import cached

# Order quantities are counted in whole units rounded UP, the rule the Reorder
# page applies to every row (frontend/src/utils/formatNumber.js wholeUnits),
# so any total computed here equals the sum of the rows a planner sees. The
# epsilon keeps float noise (1782.0000000002) from rounding up a whole unit.
_WHOLE_UNIT_EPSILON = 1e-6


def whole_units(value: float) -> int:
    return math.ceil(value - _WHOLE_UNIT_EPSILON)


def plan_quantity(q_i, status, decided_q_i) -> float:
    """The quantity a row adds to the displayed plan total: the planner's accepted quantity where there is
    one, else the LP's q_i. This is the only reader of decided_q_i besides the decision endpoints; it feeds
    the total and count shown on /recommendations and /dashboard and nothing upstream of them."""
    if status == "accepted" and decided_q_i is not None:
        return float(decided_q_i)
    return float(q_i)


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
        (lr.status <> 'pending' AND lr.lp_run_key IS NULL) AS outside_plan,
        inv.stock_pieces AS current_stock,
        inv.stock_cases AS current_stock_cases,
        inv.stock_value_pesos AS stock_value_pesos,
        CASE WHEN inv.product_key IS NOT NULL THEN TRUE
             WHEN counted.principal IS NOT NULL THEN FALSE
        END AS in_stock_count,
        abc.revenue_share AS revenue_share,
        abc_last.tier AS tier,
        abc_last.classification_period AS tier_period,
        (abc.product_key IS NOT NULL) AS tier_is_current,
        sales.avg_monthly_sales_pesos AS avg_monthly_sales_pesos,
        sales.avg_monthly_pieces AS avg_monthly_pieces,
        fr.forecast_value AS forecast_units,
        oo.on_order_pieces AS on_order_pieces,
        oo.on_order_cases AS on_order_cases,
        oo.on_order_unparsed AS on_order_unparsed,
        rf.needs_review AS needs_review,
        rf.reasons AS review_reasons,
        rf.over_run_months AS review_over_run_months,
        rf.collapse_ratio AS review_collapse_ratio,
        lr.q_i AS recommended_q_i,
        {{_DECISION}}
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
        WHERE {abc_method_sql()} AND {abc_period_pred()}
        ORDER BY product_key, classification_period DESC
    ) abc ON abc.product_key = lr.product_key
    LEFT JOIN (
        -- DISPLAY ONLY: each SKU's last-known tier at or before the cycle month,
        -- carried forward and labelled with its period. Shares, priority and
        -- every cohort read `abc` above (the exact period), never this.
        SELECT DISTINCT ON (ac.product_key) ac.product_key, ac.tier, ac.classification_period
        FROM abc_classification ac
        WHERE {abc_method_sql()} AND {abc_period_pred("<=", "ac")}
        ORDER BY ac.product_key, ac.classification_period DESC
    ) abc_last ON abc_last.product_key = lr.product_key
    LEFT JOIN (
        SELECT recent.product_key, SUM(recent.month_total) / MAX(sales_window.months) AS avg_monthly_sales_pesos,
               SUM(recent.month_pieces) / MAX(sales_window.months) AS avg_monthly_pieces
        FROM (
            SELECT product_key, calendar_month, SUM(net_amount) AS month_total, SUM(quantity_sold) AS month_pieces
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
           ) AS on_order,
           EXISTS (
               SELECT 1 FROM pg_attribute
               WHERE attrelid = to_regclass('lp_recommendation') AND attname = 'decided_q_i' AND NOT attisdropped
           ) AS decision_cols,
           (to_regclass('lp_quantity_change') IS NOT NULL
            AND to_regclass('lp_direct_apply_grant') IS NOT NULL) AS approval,
           to_regclass('lp_decision_reversal') IS NOT NULL AS reversal,
           to_regclass('expected_receipt') IS NOT NULL AS receipts,
           (to_regclass('lp_dismissal_request') IS NOT NULL
            AND to_regclass('lp_stock_observation') IS NOT NULL) AS requests
"""
# Migration 0062's columns. Where it isn't applied the row query reads the same names as NULLs.
_DECISION_COLS_SQL = ("lr.decided_q_i AS decided_q_i, lr.decision_reason AS decision_reason, "
                      "lr.decided_at AS decided_at, lr.decided_by AS decided_by")
_DECISION_COLS_ABSENT_SQL = ("NULL::numeric AS decided_q_i, NULL::text AS decision_reason, "
                             "NULL::timestamptz AS decided_at, NULL::text AS decided_by")
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
    """{review_flag, on_order, decision_cols, approval, reversal, requests}: whether migration 0042's table and
    columns, migration 0062's columns, migration 0068's two tables (approval), migration 0067's table
    (reversal) and migration 0070's two tables (requests: dismissal requests and stock counts) exist. A database
    (or test fake) that can't answer counts as none of them."""
    row = db.execute(text(_PRESENT_SQL)).mappings().first()
    return {"review_flag": bool(row and row["review_flag"]), "on_order": bool(row and row["on_order"]),
            "decision_cols": bool(row and row.get("decision_cols")),
            "approval": bool(row and row.get("approval")), "reversal": bool(row and row.get("reversal")),
            "receipts": bool(row and row.get("receipts")),
            "requests": bool(row and row.get("requests"))}


def _with_present(sql: str, present: dict) -> str:
    return (sql.replace("{_ON_ORDER}", ON_ORDER_AT_PERIOD_SQL if present["on_order"] else ON_ORDER_ABSENT_SQL)
               .replace("{_REVIEW}", _REVIEW_SQL if present["review_flag"] else _REVIEW_ABSENT_SQL)
               .replace("{_DECISION}", _DECISION_COLS_SQL if present.get("decision_cols") else _DECISION_COLS_ABSENT_SQL))

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
    base = _with_present(_SELECT_ONE, present or {"review_flag": True, "on_order": True, "decision_cols": False})
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


def _cover(stock_pieces: float | None, avg_monthly_pieces: float | None) -> tuple[float | None, str | None]:
    """Days of cover in PIECES over PIECES, the basis of the Dashboard's kpis.weeks_of_cover (D3, 2026-10-28). It was stock
    at purchase cost over sales at selling price, which understated cover by the margin (portfolio: 6.21 weeks against
    7.06 in pieces, both queried 2026-10-28); stock_value_pesos and avg_monthly_sales_pesos are no longer read for it."""
    if stock_pieces is None:
        return None, "no stock in pieces in the cycle's opening stock count (no row, or no usable pack size)"
    if avg_monthly_pieces is None:
        return None, (f"no sales rows for this SKU in the {SKU_COVER_HISTORY_MONTHS} sales months "
                      "up to the stock snapshot")
    if avg_monthly_pieces <= 0:
        return None, "average recent sales quantity is zero or negative — cannot divide"
    daily = avg_monthly_pieces / AVG_DAYS_PER_MONTH
    return round(stock_pieces / daily, 1), None


_AVG_PIECES_SQL = f"""
    SELECT pd.sku_code AS sku_id, SUM(d.quantity_sold) / MAX(w.months) AS avg_monthly_pieces
    FROM unilever_sku_demand_fact_real d
    JOIN product_dimension pd ON pd.product_key = d.product_key
    CROSS JOIN (
        SELECT COUNT(*) AS months FROM (
            SELECT DISTINCT calendar_month FROM unilever_sku_demand_fact_real
            WHERE calendar_month <= :inv_period ORDER BY calendar_month DESC LIMIT {SKU_COVER_HISTORY_MONTHS}
        ) window_months
    ) w
    WHERE pd.sku_code = ANY(:skus) AND d.calendar_month IN (
        SELECT DISTINCT calendar_month FROM unilever_sku_demand_fact_real
        WHERE calendar_month <= :inv_period ORDER BY calendar_month DESC LIMIT {SKU_COVER_HISTORY_MONTHS})
    GROUP BY pd.sku_code
"""


def _attach_avg_pieces(db: Session, rows: list[dict]) -> None:
    """The planning mart stores sales in pesos only, so the pieces side of cover is read here, one statement per
    cycle on the page, over the same SKU_COVER_HISTORY_MONTHS window as the row query's sales join."""
    by_cycle: dict = {}
    for r in rows:
        by_cycle.setdefault(r["planning_cycle_date"], []).append(r)
    for cycle, group in by_cycle.items():
        got = {x["sku_id"]: x["avg_monthly_pieces"] for x in db.execute(text(_AVG_PIECES_SQL), {
            "inv_period": opening_period(cycle), "skus": sorted({r["sku_id"] for r in group})}).mappings()}
        for r in group:
            r["avg_monthly_pieces"] = got.get(r["sku_id"])


def _to_item(r, present: dict | None = None) -> RecommendationItem:
    # current_stock is PIECES (backend/stock_units.py), the same unit as
    # rop_i. Until 2026-09-23 this read quantity_on_hand — CASES — straight
    # off the snapshot and compared it with a piece-scale ROP, which made
    # almost every row CRITICAL. Two different reasons produce no figure,
    # and they are reported apart rather than both as a bare "NO DATA".
    stock = None if r["current_stock"] is None else float(r["current_stock"])
    stock_cases = _opt_float(r, "current_stock_cases")
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
        stock = 0.0
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
    tier_is_current = r.get("tier_is_current") if hasattr(r, "get") else None
    # A carried-forward tier (tier_period before the cycle's own ABC period) is
    # display only: it has no share, so it has no priority score and no cohort.
    assert tier_is_current is not False or revenue_share is None, "aged tier leaked into a calculation"
    stockout_gap = None if stock is None else max(0.0, rop - stock)
    priority_score = (
        round(revenue_share * stockout_gap, 4)
        if revenue_share is not None and stockout_gap is not None
        else None
    )
    days_of_cover, cover_reason = _cover(stock, _opt_float(r, "avg_monthly_pieces"))

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
        tier_period=r.get("tier_period") if hasattr(r, "get") else None,
        tier_is_current=tier_is_current,
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
        # Always the LP's own quantity, however the planner decided (migration 0062).
        recommended_q_i=float(r["q_i"]),
        decided_q_i=_opt_float(r, "decided_q_i"),
        plan_q_i=plan_quantity(r["q_i"], r["status"], _opt_float(r, "decided_q_i")),
        decision_reason=r.get("decision_reason") if hasattr(r, "get") else None,
        decided_at=r.get("decided_at") if hasattr(r, "get") else None,
        decided_by=r.get("decided_by") if hasattr(r, "get") else None,
        outside_plan=bool(r.get("outside_plan")) if hasattr(r, "get") else False,
        plan_note=(f"{str(r['status']).capitalize()} recommendation outside the current plan: no LP run produced it, "
                   "so it is not in the plan count or the plan total.")
        if hasattr(r, "get") and r.get("outside_plan") else None,
    )


# The dates behind the row figures, so the page can label every number with
# its period (the technical adviser's rule, 2026-10-02). Read-only and beside
# the rows, never inside them: nothing here changes what the rows say.
#   count_date  — the day the stock count was taken. The Unilever _period
#                 '2026-03' is the count of 6 Apr 2026 (snapshot_date), so
#                 "Mar 2026 stock" undersold how late it is. MAX because a
#                 period could in principle hold more than one count day.
#   sales_start/end — the sales months cover's daily rate averages over: the
#                 same SKU_COVER_HISTORY_MONTHS window the row query's sales
#                 join reads (latest months at or before the stock period).
_LABEL_CONTEXT_SQL = f"""
    SELECT
        (SELECT MAX(snapshot_date) FROM inventory_fact_real
         WHERE _period = :inv_period AND principal <> 'delmonte'{{scope}}) AS count_date,
        (SELECT MIN(m) FROM (
            SELECT DISTINCT calendar_month AS m FROM unilever_sku_demand_fact_real
            WHERE calendar_month <= :inv_period
            ORDER BY m DESC LIMIT {SKU_COVER_HISTORY_MONTHS}
        ) cover_months) AS sales_start,
        (SELECT MAX(calendar_month) FROM unilever_sku_demand_fact_real
         WHERE calendar_month <= :inv_period) AS sales_end
"""


def label_context(db: Session, inv_period: str | None, abc_period: str | None, principal: str | None) -> dict:
    """{stock_period, stock_count_date, abc_period, cover_sales_start,
    cover_sales_end} for RecommendationsResponse — the periods the rows were
    read at. All None when there is no stock period to anchor on."""
    out = {"stock_period": inv_period, "stock_count_date": None, "abc_period": abc_period,
           "cover_sales_start": None, "cover_sales_end": None}
    if inv_period is None:
        return out
    scope_sql, scope_params = principal_clause(principal, "principal")
    row = db.execute(
        text(_LABEL_CONTEXT_SQL.format(scope=scope_sql)), {"inv_period": inv_period, **scope_params}
    ).mappings().first()
    if row:
        out.update(stock_count_date=row["count_date"], cover_sales_start=row["sales_start"],
                   cover_sales_end=row["sales_end"])
    # Del Monte's stored day is a 1st-of-month placeholder (DEC-12), never offered as a count date (audit FE-5):
    # when it is the stock in view, the page is told why there is no day instead of being left to guess.
    if out["stock_count_date"] is None and normalize_principal(principal) in (None, "delmonte"):
        out["stock_count_note"] = STOCK_COUNT_DATE_NOTE
    return out


STOCK_COUNT_DATE_NOTE = (
    "Del Monte's count day is not recorded (DEC-12): the stored date is a 1st-of-month placeholder, not the day "
    "stock was counted. Any stock shown by the demonstration is generated, not counted."
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
    from_date: datetime.date | None = Query(None, alias="from", description="'YYYY-MM-DD'. The shared date-range picker's applied start. Must be given with 'to' or not at all — filters on lr.planning_cycle_date."),
    to_date: datetime.date | None = Query(None, alias="to", description="'YYYY-MM-DD'. The shared date-range picker's applied end. Must be given with 'from' or not at all."),
    principal: str | None = PrincipalQuery,
    include_not_planned: bool = Query(
        False,
        description=(
            "Also list the Class A products the current plan has no row for (`not_planned`): why, stock and recent "
            "sales, no order quantity. The current plan's whole view only: no status or date filter, real data."
        ),
    ),
    mode: str = Depends(get_data_mode),
    db: Session = Depends(get_db),
    current_user: TokenPayload = Depends(require_permission("lp.view")),
) -> RecommendationsResponse:
    # Declared as dates, so 'abc' or 2026-13-45 is a 422, not Postgres's InvalidDatetimeFormat as a 500 (QA
    # 2026-10-24 finding 4). The reads below take the ISO text.
    if (from_date is None) != (to_date is None):
        raise HTTPException(status_code=422, detail="from and to go together: send both or neither.")
    from_date = from_date.isoformat() if from_date else None
    to_date = to_date.isoformat() if to_date else None
    # Del Monte has no product-level plan to leave a product out of, and a preview's what-if rows aren't the plan.
    list_not_planned = (include_not_planned and mode == REAL and cycle == "current" and not status and not from_date
                        and normalize_principal(principal) != "delmonte")
    # Both principals again (2026-09-17) — see backend/principals.py.
    # lp_recommendation currently holds 430 Unilever rows and ZERO Del
    # Monte rows (confirmed live 2026-09-17), so ?principal=delmonte
    # honestly returns an empty list until the LP is run for Del Monte.
    if demo_data_enabled(mode) and normalize_principal(principal) == "delmonte":
        # Behind DM_DEMO_ENABLED: the labelled demonstration forecasts, stock and order plan (schema demo;
        # backend/demo_data.py; migration 0056). order_plan.available is False until the demo order plan has
        # actually been run (scripts.run_lp --source demo --principal delmonte --write).
        return JSONResponse({
            **jsonable_encoder(RecommendationsResponse(items=[], count=0)),
            **demo_data.label({
                "demo_forecasts": demo_data.forecasts(db),
                "demo_stock": demo_data.stock(db),
                "order_plan": demo_data.order_plan(db),
            }),
        })
    if planning_mart.usable(db, mode):
        served = _from_mart(db, status, cycle, from_date, to_date, principal)
        if served is not None:
            # The page's period labels, as the join path below gives them: the
            # newest listed cycle's opening count, else no stock period.
            newest = max((c["cycle"] for c in served.stock_counts if c.get("cycle")), default=None)
            labels = label_context(db, opening_period(newest) if newest else None,
                                   latest_abc_period(db, principal), principal)
            if list_not_planned and served.planning_cycle_date:
                labels["not_planned"] = _not_planned(db, served.planning_cycle_date, principal)
            return _attach_demo_unilever(served.model_copy(update=labels), db, principal, mode)
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
    # Period labels for the page. No stock period until a cycle is known:
    # the rows are read at their cycle's opening count (set below).
    labels = label_context(db, None, latest_abc_period(db, principal), principal)
    if cycle == "current":
        current = current_cycle(db, principal, mode)
        if current is None:
            # Nothing pending at all: 'current' has nothing to scope to, so
            # returning every decided row would contradict the filter's
            # promise. An empty list with the reason is the honest answer.
            return _attach_demo_unilever(_with_data_mode(RecommendationsResponse(
                items=[], count=0, planning_cycle_date=None,
                superseded_count=0, freshness=freshness, lp_model=lp_model_info(),  # no cycle: defaults
                stock_counts=[],
                **labels,
            ), db, mode), db, principal, mode)
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

    # The page's period labels follow the count the rows are read at: the
    # newest listed cycle's opening count (below), not the latest count.
    if cycles:
        # ABC label = the run the newest cycle's rows are read at (its own month's, below).
        labels = label_context(db, opening_period(cycles[0]),
                               latest_abc_period(db, principal, str(cycles[0])[:7]), principal)

    rows: list = []
    counts: list[dict] = []
    abc_periods_shown: dict[str, str] = {}
    current_run = stored_run(db, freshness["cycle_date"], principal, mode)   # which stock basis the current plan used
    for planning_cycle in cycles:
        # ABC anchor = this cycle's own month: the latest run at or before it.
        cycle_abc = latest_abc_periods(db, principal, str(planning_cycle)[:7])
        if not abc_periods_shown:
            abc_periods_shown = cycle_abc  # the newest cycle's, the one the page leads with
        cycle_params = {**params, **abc_period_params(cycle_abc),
                        "inv_period": opening_period(planning_cycle),
                        "current_cycle": planning_cycle, "listed_cycle": planning_cycle}
        cycle_rows = db.execute(
            text(select_sql + " WHERE 1=1" + filters + cycle_clause + " ORDER BY lr.rop_i DESC"), cycle_params,
        ).mappings().all()
        rows.extend(cycle_rows)
        # Which count each principal on the list was checked against, and
        # when it was counted, or why there is none.
        principals = sorted({r["principal"] for r in cycle_rows})
        counts.extend(stock_counts(db, opening_period(planning_cycle), principals, cycle=planning_cycle,
                                   run=current_run if planning_cycle == freshness["cycle_date"] else None))
    items = [_to_item(r, present) for r in rows]
    return _attach_demo_unilever(_with_data_mode(RecommendationsResponse(
        items=items,
        count=len(items),
        order_count=_order_count(items),
        planning_cycle_date=freshness["cycle_date"],
        superseded_count=freshness["superseded_pending_count"] if cycle == "current" else 0,
        freshness=freshness,
        # What the run behind the current cycle used (lp_run), else the defaults, labelled.
        lp_model=lp_model_info(current_run),
        stock_counts=counts,
        **labels,
        tier_a_periods=tier_a_periods(abc_periods_shown),
        not_planned=_not_planned(db, freshness["cycle_date"], principal) if list_not_planned and freshness["cycle_date"] else None,
    ), db, mode), db, principal, mode)


# The planning mart is built on migration 0042's table and columns.
_MART_PRESENT = {"review_flag": True, "on_order": True, "decision_cols": False}


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
    # opening_basis (migration 0069): the run behind the current cycle says whether its stock was a count or a projection.
    run_counts = ((got["run"] or {}).get("inputs") or {}).get("stock_counts") or {}
    run_cycle = (got["run"] or {}).get("planning_cycle_date")
    counts = [
        with_opening_basis(
            stock_count_info(c["principal"], c["opening_period"], None if c["row_count"] is None else c,
                             c["planning_cycle_date"]),
            run_counts.get(c["principal"]) if run_cycle == c["planning_cycle_date"] else None)
        for c in got["counts"]
    ]
    # The mart's pm.revenue_share is the exact-period `abc` join's share (never the
    # carried-forward `abc_last` one), so its presence is the same signal as the join
    # path's (abc.product_key IS NOT NULL) at line 260.
    for r in rows:
        r["tier_is_current"] = r["revenue_share"] is not None
    # The planner's decision (migration 0062) is read from lp_recommendation, not the mart: only decided
    # rows have any, so a page with nothing decided costs no extra statement.
    details = _decision_details(db, [r["recommendation_key"] for r in rows if r["status"] != "pending"])
    for r in rows:
        r.update(details.get(r["recommendation_key"], {}))
    _attach_avg_pieces(db, rows)
    items = [_to_item(r, _MART_PRESENT) for r in rows]
    # Same anchor as the join path (recommendations.py's own loop above): the newest
    # displayed cycle's own month, never the mart's stored (unanchored) tier_period —
    # that column is missing for any principal with no pending rows this cycle.
    newest_cycle = rows[0]["planning_cycle_date"] if rows else None
    try:
        abc_periods_shown = latest_abc_periods(db, principal, str(newest_cycle)[:7]) if newest_cycle else {}
    except AttributeError:
        abc_periods_shown = {}
    return RecommendationsResponse(
        items=items,
        count=len(items),
        order_count=_order_count(items),
        planning_cycle_date=freshness["cycle_date"],
        superseded_count=freshness["superseded_pending_count"] if cycle == "current" else 0,
        freshness=freshness,
        lp_model=lp_model_info(got["run"]),
        stock_counts=counts,
        tier_a_periods=tier_a_periods(abc_periods_shown),
    )


def _order_count(items) -> int:
    """Items whose planned order is above zero (plan_q_i, which is q_i until a quantity is decided)."""
    return sum(1 for i in items if (i.plan_q_i if i.plan_q_i is not None else i.q_i or 0) > 0)


# Class A of the run the plan's rows are labelled with, less the plan's own rows. Unilever only: Del Monte has no
# product-level plan. Stock is the cycle's opening count and in_stock_count means what it means on a plan row; the
# forecast is the product's latest, as GET /abc reads it for the same reason.
_NOT_PLANNED_SQL = f"""
    SELECT
        COALESCE(pd.sku_code, pd.category_path) AS sku_id,
        pd.product_name,
        ac.principal,
        ac.revenue_share,
        ac.tier AS pool_tier,
        ac.classification_period AS pool_period,
        inv.stock_pieces AS current_stock,
        CASE WHEN inv.product_key IS NOT NULL THEN TRUE
             WHEN counted.principal IS NOT NULL THEN FALSE
        END AS in_stock_count,
        fc.status AS fc_status,
        fc.mase AS fc_mase
    FROM abc_classification ac
    JOIN product_dimension pd ON pd.product_key = ac.product_key
    LEFT JOIN (
        {STOCK_AT_PERIOD_SQL}
    ) inv ON inv.product_key = ac.product_key
    LEFT JOIN (
        SELECT DISTINCT principal FROM inventory_fact_real WHERE _period = :inv_period
    ) counted ON counted.principal = ac.principal
    LEFT JOIN (
        SELECT DISTINCT ON (f.product_key) f.product_key, f.status, f.mase
        FROM forecast_result f
        ORDER BY f.product_key, f.forecast_date DESC, f.generated_at DESC
    ) fc ON fc.product_key = ac.product_key
    WHERE ac.tier = 'A' AND ac.principal = 'unilever'
      AND {abc_method_sql("ac")} AND {abc_period_pred("=", "ac")}
      AND NOT EXISTS (
          SELECT 1 FROM lp_recommendation planned
          WHERE planned.product_key = ac.product_key
            AND planned.planning_cycle_date = CAST(:not_planned_cycle AS DATE)
            AND {PLAN_STATUS_SQL_BARE}
      )
"""


def _not_planned_item(r: dict) -> NotPlannedItem:
    """One row of the list. Stock and cover by _to_item's rules, so a row here compares with a row of the plan."""
    stock_not_in_count = r["in_stock_count"] is False and r["principal"] in COUNT_OMITS_ZERO_STOCK
    stock = 0.0 if stock_not_in_count else _opt_float(r, "current_stock")
    avg_pieces = _opt_float(r, "avg_monthly_pieces")
    days_of_cover, cover_reason = _cover(stock, avg_pieces)
    reason, code = _no_target_reason(r, r["pool_tier"], r["pool_period"], has_cycle=True)
    reason = reason.removeprefix("Not planned: ")
    return NotPlannedItem(
        sku_id=r["sku_id"] or "",
        product_name=r["product_name"],
        principal=r["principal"],
        reason=reason[0].upper() + reason[1:],
        reason_code=code,
        revenue_share=_opt_float(r, "revenue_share"),
        current_stock=stock,
        stock_not_in_count=stock_not_in_count,
        avg_monthly_pieces=avg_pieces,
        days_of_cover=days_of_cover,
        cover_blocked_reason=cover_reason,
    )


def _not_planned(db: Session, plan_cycle, principal: str | None) -> list[NotPlannedItem]:
    """The Class A products plan_cycle has no row for, lowest cover first; a product with no cover figure goes last,
    since its risk is unknown rather than high. Same ABC anchor as the plan's rows: the run at or before its month."""
    rows = [dict(r) for r in db.execute(text(_NOT_PLANNED_SQL), {
        **abc_period_params(latest_abc_periods(db, principal, str(plan_cycle)[:7])),
        "inv_period": opening_period(plan_cycle),
        "not_planned_cycle": plan_cycle,
    }).mappings().all()]
    if not rows:
        return []
    for r in rows:
        r["planning_cycle_date"] = plan_cycle
    _attach_avg_pieces(db, rows)
    return sorted(
        (_not_planned_item(r) for r in rows),
        key=lambda i: (i.days_of_cover is None, i.days_of_cover or 0.0, -(i.revenue_share or 0.0), i.sku_id),
    )


_DECISION_COLS_SEEN = {"value": False}


def _decision_details(db: Session, keys: list[int]) -> dict[int, dict]:
    """{recommendation_key: {decided_q_i, decision_reason, decided_at, decided_by}} for `keys`, read
    from lp_recommendation. Empty when there are no keys or migration 0062 isn't applied (remembered
    once seen, like the other optional-table checks)."""
    if not keys:
        return {}
    if not _DECISION_COLS_SEEN["value"]:
        if not _present(db)["decision_cols"]:
            return {}
        _DECISION_COLS_SEEN["value"] = True
    rows = db.execute(text("""
        SELECT recommendation_key, decided_q_i, decision_reason, decided_at, decided_by
        FROM lp_recommendation WHERE recommendation_key = ANY(:keys)
    """), {"keys": keys}).mappings().all()
    return {r["recommendation_key"]: {k: r[k] for k in ("decided_q_i", "decision_reason", "decided_at", "decided_by")}
            for r in rows}


def _attach_demo_unilever(result, db: Session, principal: str | None, mode: str):
    """Adds the Unilever demonstration order plan (demo forecast, REAL stock; backend/demo_data.py,
    migration 0057) beside the real items, for principal 'unilever', None or 'all' — it never replaces them:
    Unilever's real recommendations are good and stay exactly as they are. Off when DM_DEMO_ENABLED is off, the
    caller is not in preview (X-Data-Mode: preview — demo_data_enabled, same gate every other branch into schema
    `demo` uses), or for a Del Monte-only request (which already gets its own demo block, see the delmonte
    branch above)."""
    if not (demo_data_enabled(mode) and normalize_principal(principal) in (None, "all", "unilever")):
        return result
    extra = {"demo_unilever": demo_data.unilever_order_plan(db)}
    if isinstance(result, JSONResponse):
        return JSONResponse({**json.loads(result.body), **extra})
    return JSONResponse({**jsonable_encoder(result), **extra})


def _with_data_mode(response: RecommendationsResponse, db: Session, mode: str):
    """Real mode: the model untouched. Preview: the data_mode block beside it,
    saying whether these rows are the five-year what-if (never saved, not
    decidable) or, with no preview files built, still the real ones."""
    if mode != PREVIEW:
        return response
    block = preview_block(db, real_only=None if predictive_preview(mode) else ["items"])
    return JSONResponse({**jsonable_encoder(response), "data_mode": block})


# THE STATE MACHINE (2026-10-21, reversal and approval added 2026-10-23). A decision is made once, on a row that is
# still open and still current:
#   pending   -> accepted   legal
#   pending   -> dismissed  legal, with a reason
#   accepted  -> anything   refused (409) here
#   dismissed -> anything   refused (409) here
#   accepted | dismissed -> pending   ONLY by an admin, through POST /{key}/reverse (backend/routers/
#                           reorder_approval.py, migration 0067). The decision is copied to lp_decision_reversal
#                           first, never deleted.
# and only a row of its principal's CURRENT cycle can be decided: a pending row left behind by an earlier run
# (179 of them, 33 cycles, on 2026-10-20) is refused (409) however it is reached. Both rules sit in the
# UPDATE's own WHERE clause, so two requests racing for one row cannot both win.
# A third rule (migration 0068): while a quantity change is awaiting approval (lp_quantity_change.state =
# 'pending_approval') nobody decides the row directly. The admin approves it (which is the accept) or rejects it
# (the row stays pending) first. _OPEN_CHANGE_GUARD is that rule, in the same WHERE clause, and is added only
# where the table exists.
_UPDATE_DECISION_SQL = """
    UPDATE lp_recommendation lr
    SET status = :status, decided_at = :decided_at, decided_by = :decided_by{capture}
    FROM product_dimension pd
    WHERE lr.recommendation_key = :key
      AND pd.product_key = lr.product_key
      AND lr.status = 'pending'{guard}
      AND lr.planning_cycle_date = (
          SELECT MAX(l2.planning_cycle_date) FROM lp_recommendation l2
          JOIN product_dimension p2 ON p2.product_key = l2.product_key
          WHERE p2.principal = pd.principal)
    RETURNING COALESCE(pd.sku_code, pd.category_path) AS sku, lr.planning_cycle_date
"""
_OPEN_CHANGE_GUARD = """
      AND NOT EXISTS (SELECT 1 FROM lp_quantity_change qc
                      WHERE qc.recommendation_key = lr.recommendation_key AND qc.state = 'pending_approval')"""
# Migration 0070: the same rule for a staff member's dismissal request awaiting an admin.
_OPEN_DISMISSAL_GUARD = """
      AND NOT EXISTS (SELECT 1 FROM lp_dismissal_request dr
                      WHERE dr.recommendation_key = lr.recommendation_key AND dr.state = 'pending_approval')"""
_OPEN_DISMISSAL_SQL = """
    SELECT request_key, requested_by FROM lp_dismissal_request
    WHERE recommendation_key = :key AND state = 'pending_approval'
"""
# The pending change on a row, read only to explain a refusal.
_OPEN_CHANGE_SQL = """
    SELECT change_key, proposed_by FROM lp_quantity_change
    WHERE recommendation_key = :key AND state = 'pending_approval'
"""
# Where an update touched nothing, why: a missing row, an already-decided one, or a superseded cycle.
_WHY_NOT_DECIDED_SQL = """
    SELECT d.status, d.planning_cycle_date,
           (SELECT MAX(l2.planning_cycle_date) FROM lp_recommendation l2
            JOIN product_dimension p2 ON p2.product_key = l2.product_key
            WHERE p2.principal = pd.principal) AS current_cycle
    FROM lp_recommendation d
    JOIN product_dimension pd ON pd.product_key = d.product_key
    WHERE d.recommendation_key = :key
"""


def refusal_for(row, open_change=None, open_dismissal=None) -> HTTPException:
    """The 404 / 409 for a decision that matched no open, current row. `row` is _WHY_NOT_DECIDED_SQL's;
    `open_change` is _OPEN_CHANGE_SQL's row when the row has a quantity change awaiting approval, and
    `open_dismissal` _OPEN_DISMISSAL_SQL's when it has a dismissal request awaiting approval."""
    if row is None:
        return HTTPException(status_code=404, detail="Recommendation not found")
    if row["status"] == "pending" and open_dismissal is not None:
        return HTTPException(status_code=409, detail=(
            f"This recommendation has a dismissal request awaiting approval (request {open_dismissal['request_key']}, "
            f"requested by {open_dismissal['requested_by']}). An admin approves or rejects it before the row is decided."
        ))
    if row["status"] == "pending" and open_change is not None:
        return HTTPException(status_code=409, detail=(
            f"This recommendation has a quantity change awaiting approval (change {open_change['change_key']}, "
            f"proposed by {open_change['proposed_by']}). An admin approves or rejects it before the row is decided."
        ))
    if row["status"] != "pending":
        return HTTPException(status_code=409, detail=(
            f"This recommendation was already {row['status']}; a decision is made once and is not changed here."
        ))
    return HTTPException(status_code=409, detail=(
        f"This recommendation belongs to the {row['planning_cycle_date']} cycle, which a newer LP run "
        f"({row['current_cycle']}) has superseded, so it can no longer be decided."
    ))


def decide_row(db: Session, present: dict, *, key: int, status: str, reason: str | None,
               decided_quantity: float | None, decided_by: str, decided_at: datetime.datetime | None = None):
    """The one place a reorder decision is written: the guarded UPDATE (pending, current cycle, no quantity change
    awaiting approval), then the planning mart's copy, in the caller's transaction. Returns the UPDATE's row
    (sku, planning_cycle_date). A row that matched nothing rolls the transaction back and raises the 404 / 409.
    The caller audits and commits."""
    # Lock the row BEFORE the guarded UPDATE (audit 2026-10-23, the planner-proposal vs admin-accept race). The
    # guard reads "no open quantity change" from the UPDATE statement's own snapshot, and a proposal INSERT that has
    # not committed yet is invisible to it; both then commit and leave an open change on a decided row. The
    # proposal INSERT only takes a KEY SHARE lock on this row (its foreign key), which the UPDATE's NO KEY UPDATE
    # lock does not conflict with, so nothing made them wait. FOR UPDATE here conflicts with the proposer's own
    # FOR UPDATE re-read (reorder_approval.change_quantity); whichever is second waits, and its next statement
    # takes a fresh snapshot that sees the other's commit. READ COMMITTED gives each statement its own snapshot.
    db.execute(text("SELECT 1 FROM lp_recommendation WHERE recommendation_key = :key FOR UPDATE"), {"key": key})
    decision_params = {
        "status": status,
        "decided_at": decided_at or datetime.datetime.utcnow(),
        "decided_by": decided_by,
        "key": key,
    }
    update_params = dict(decision_params)
    capture = ""
    if present["decision_cols"]:
        # decided_q_i only where it differs from the recommendation (to the 2 decimals it is stored at);
        # q_i, rop_i and ss_i are never written here.
        capture = (", decision_reason = :reason, decided_q_i = CASE WHEN CAST(:decided_q AS numeric) IS NULL "
                   "OR ROUND(CAST(:decided_q AS numeric), 2) = lr.q_i THEN NULL ELSE ROUND(CAST(:decided_q AS numeric), 2) END")
        update_params.update(reason=reason, decided_q=decided_quantity)
    guard = (_OPEN_CHANGE_GUARD if present.get("approval") else "") + (
        _OPEN_DISMISSAL_GUARD if present.get("requests") else "")
    decided = db.execute(text(_UPDATE_DECISION_SQL.format(capture=capture, guard=guard)), update_params).mappings().first()
    if decided is None:
        why = db.execute(text(_WHY_NOT_DECIDED_SQL), {"key": key}).mappings().first()
        open_change = open_dismissal = None
        if why is not None and why["status"] == "pending" and why["planning_cycle_date"] == why["current_cycle"]:
            if present.get("approval"):
                open_change = db.execute(text(_OPEN_CHANGE_SQL), {"key": key}).mappings().first()
            if present.get("requests"):
                open_dismissal = db.execute(text(_OPEN_DISMISSAL_SQL), {"key": key}).mappings().first()
        db.rollback()
        raise refusal_for(why, open_change, open_dismissal)
    # The planning mart's row for this decision, in the same transaction (migration 0046).
    planning_mart.decide(db, decision_params)
    # The receipt ledger (migration 0069), in the same transaction: an accepted order is stock on the way, whose
    # pieces are the decided quantity, so every path that decides a quantity (a plain accept, a direct apply, an
    # approved change) keeps its receipt in step here. A dismissal cancels any live receipt.
    if present.get("receipts"):
        if status == "accepted":
            expected_receipts.record(db, key)
        else:
            expected_receipts.void(db, key, "dismissed")
    return decided


def item_for(db: Session, present: dict, key: int, cycle) -> RecommendationItem:
    """One row as GET shows it. Single row pinned by recommendation_key; scope left unfiltered (None = all),
    identical to today's behaviour - see sku.py's _one_row_params. Stock at the row's own cycle's opening count."""
    row = db.execute(
        text(_with_present(_SELECT_ONE, present) + " WHERE lr.recommendation_key = :key"),
        {
            "key": key,
            "inv_period": opening_period(cycle),
            **abc_period_params(latest_abc_periods(db, None, str(cycle)[:7])),
        },
    ).mappings().first()
    return _to_item(row, present)


REQUESTS_NOT_READY = ("Staff requests and stock counts aren't set up on this server yet "
                      "(migration 0070 isn't applied).")
# The row's product and its pieces per case, for a stock count sent with a decision or request.
_PRODUCT_PACK_SQL = f"""
    SELECT lr.product_key, {PACK_SQL} AS pack FROM lp_recommendation lr
    JOIN product_dimension pd ON pd.product_key = lr.product_key
    WHERE lr.recommendation_key = :key
"""


def may_apply_directly(db: Session, user: TokenPayload) -> bool:
    """Whether this user's quantity change applies at once: an admin always, anyone else only with a row in
    lp_direct_apply_grant (migration 0068). Read fresh on every request, like permissions."""
    if user.role == "admin":
        return True
    return db.execute(text("SELECT 1 FROM lp_direct_apply_grant WHERE user_id = :uid"),
                      {"uid": user.user_id}).first() is not None


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
    reason = (decision.reason or "").strip() or None
    # An override cannot be stored before migration 0062, so it is refused rather than dropped silently.
    if not present["decision_cols"] and decision.decided_quantity is not None:
        raise HTTPException(status_code=409, detail="Recording a different quantity needs migration 0062, which is not applied yet.")
    flagged = _review_reasons(db, recommendation_key) if present["review_flag"] else None
    if decision.status == "accepted" and flagged is not None and not decision.reviewed:
        raise HTTPException(status_code=409, detail=(
            "This product is flagged for review before ordering (" + ", ".join(flagged) + "). "
            "Accept it from its own row after checking it; it is never accepted in bulk."
        ))
    # With migration 0068 applied a different quantity is a proposed change unless the caller may apply it
    # directly. A quantity equal to the recommendation is no change and is accepted as before.
    if present.get("approval") and decision.status == "accepted" and decision.decided_quantity is not None             and not may_apply_directly(db, current_user):
        recommended = db.execute(text("SELECT q_i FROM lp_recommendation WHERE recommendation_key = :key"),
                                 {"key": recommendation_key}).scalar()
        if recommended is not None and round(float(decision.decided_quantity), 2) != round(float(recommended), 2):
            raise ApiError(403, "A change to the recommended quantity needs an admin's approval. Propose it with "
                                f"POST /recommendations/{recommendation_key}/quantity-change.",
                           code="approval_required", recommendation_key=recommendation_key)

    if decision.decided_quantity is not None:
        # A quantity the planner typed must be whole cases (backend/case_pack.py); one equal to the recommendation is no edit.
        sized = db.execute(text(f"SELECT lr.q_i, {PACK_SQL} AS pack FROM lp_recommendation lr "
                                "JOIN product_dimension pd ON pd.product_key = lr.product_key "
                                "WHERE lr.recommendation_key = :key"), {"key": recommendation_key}).mappings().first()
        if sized is not None:
            check_whole_cases(decision.decided_quantity, sized["pack"], sized["q_i"])
    # A stock count sent with a direct dismissal (migration 0070) is an observation only: backend/stock_observation.py.
    product = None
    if decision.stock_observation is not None:
        if not present.get("requests"):
            raise ApiError(503, REQUESTS_NOT_READY, code="requests_not_ready")
        product = db.execute(text(_PRODUCT_PACK_SQL), {"key": recommendation_key}).mappings().first()
        if product is None:
            raise HTTPException(status_code=404, detail="Recommendation not found")
        # refused (422) before anything is written: a cases count needs a pack size and a whole number
        stock_observation.to_pieces(decision.stock_observation.quantity, decision.stock_observation.unit, product["pack"])
    decided = decide_row(db, present, key=recommendation_key, status=decision.status, reason=reason,
                         decided_quantity=decision.decided_quantity, decided_by=current_user.email)
    detail = f"SKU {decided['sku']}" + (f": {reason}" if reason else "")
    if decision.decided_quantity is not None:
        detail += f" [quantity decided: {decision.decided_quantity:g}]"
    audit.record(
        db,
        f"Reorder Recommendation {'Accepted' if decision.status == 'accepted' else 'Dismissed'}",
        detail
        + (f" [flagged for review: {', '.join(flagged)}; reviewed]" if flagged and decision.status == "accepted" else ""),
        actor=current_user,
    )
    if product is not None:
        stock_observation.record(db, decision.stock_observation, product_key=product["product_key"],
                                 recommendation_key=recommendation_key, pack=product["pack"],
                                 context="direct_dismissal", actor=current_user, sku=decided["sku"])
    db.commit()
    response_cache.invalidate()
    return item_for(db, present, recommendation_key, decided["planning_cycle_date"])


def _review_reasons(db: Session, recommendation_key: int) -> list[str] | None:
    """The review_flag reasons when this row's product is flagged for its
    cycle, else None (not flagged, or not assessed)."""
    row = db.execute(text("""
        SELECT rf.reasons FROM lp_recommendation lr
        JOIN review_flag rf ON rf.product_key = lr.product_key AND rf.planning_cycle_date = lr.planning_cycle_date
        WHERE lr.recommendation_key = :key AND rf.needs_review
    """), {"key": recommendation_key}).mappings().first()
    return list(row["reasons"]) if row else None
