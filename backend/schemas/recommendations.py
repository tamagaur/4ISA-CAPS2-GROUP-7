"""
backend.schemas.recommendations — Pydantic models for GET/PATCH /recommendations.

Fields are limited to what LP_Recommendation + Product_Dimension +
Inventory_Fact_Real (+ ABC_Classification / Unilever_SKU_Demand_Fact_Real
for the ranking and cover fields added 2026-09-18) actually carry
(analytics/db/schema.sql). No unit_cost, lead_time_days, or supplier-cost
breakdown exists anywhere in the schema — those fields do not appear here
rather than being fabricated.

2026-09-18 — impact ranking + cover (see backend/routers/recommendations.py
for the derivations and the unit caveats):
  current_stock   — now None (not 0) when Inventory_Fact_Real has no row
                    for the product at the latest snapshot. It used to
                    COALESCE to 0, which _to_item then read as CRITICAL —
                    "no stock record" and "confirmed empty" are different
                    facts. urgency is 'NO DATA' in that case.
                    2026-10-01: narrowed. A product absent from a stock
                    count that did happen is 0 again — the LP reads it that
                    way and the file lists no zero-stock rows — flagged by
                    stock_not_in_count. 'NO DATA' remains for a stock row
                    with no usable pack size, or no count for the principal.
                    2026-10-02: Unilever only. Del Monte's inventory files
                    do list zero-stock items, so absence from one stays
                    'NO DATA' (backend/stock_status.py).
  revenue_share   — the SKU's share of period revenue at its latest
                    single-period ABC run; None when never classified.
  stockout_gap    — max(0, rop_i - current_stock); None when stock unknown.
                    In PIECES since 2026-09-23 (see current_stock), so it is
                    now a real shortfall quantity, not an index.
  priority_score  — revenue_share x stockout_gap, the "revenue at risk"
                    ranking key. Both inputs are now on a consistent basis
                    (revenue share x a piece shortfall) — before 2026-09-23
                    the gap mixed cases and pieces, so the ranking is no
                    longer merely ordinal. None when either input is
                    missing — such rows are unranked, never ranked as zero.
  days_of_cover   — stock at cost (₱) / average daily sales value (₱/day),
                    the same peso basis GET /dashboard's weeks_of_cover uses,
                    precisely BECAUSE stock (cases) and demand (pieces)
                    can't be divided directly. None with cover_blocked_reason
                    whenever either side is unavailable.
"""
from __future__ import annotations

import datetime

from pydantic import BaseModel, Field, model_validator


class RecommendationItem(BaseModel):
    recommendation_key: int
    sku_id: str
    product_name: str | None = None
    principal: str
    planning_cycle_date: datetime.date
    q_i: float  # recommended order quantity
    rop_i: float  # target stock T_i (order-up-to level) since the 2026-09-30 run; was the reorder point
    ss_i: float  # safety stock
    status: str  # 'pending' | 'accepted' | 'dismissed'
    # PIECES since 2026-09-23 (backend/stock_units.py), the same unit as
    # rop_i/ss_i/q_i — cases x pack_size + the loose remainder. None when
    # there is no snapshot row, or no usable pack size to convert with.
    current_stock: float | None = None
    current_stock_cases: float | None = None  # the raw snapshot figure, for display
    # True when the product has no row in its principal's latest stock count
    # and current_stock is therefore 0 — the LP's own reading, for a
    # principal whose stock file lists no zero-stock rows (Unilever; see
    # backend/stock_status.py COUNT_OMITS_ZERO_STOCK). Inferred, not
    # counted, so the page says so beside the 0.
    stock_not_in_count: bool = False
    # Pieces per case (Product_Dimension.pack_size), None when the column is
    # not a usable positive number. Every quantity on this row is in pieces;
    # this is only for showing the approximate case count beside them.
    pack_size: float | None = None
    # 'CRITICAL' | 'URGENT' | 'PLANNED' | 'NO DATA' — backend/stock_status.py's
    # rule: CRITICAL below ss_i, URGENT below rop_i, PLANNED at or above it.
    urgency: str
    # Why urgency is 'NO DATA': a stock row with no usable pack size, no
    # stock count for the principal at all, or absence from a count that
    # lists zero-stock items (Del Monte) — not absence from Unilever's, see
    # stock_not_in_count.
    stock_blocked_reason: str | None = None
    revenue_share: float | None = None
    # The product's tier in the latest ABC run (None when that run did not
    # rank it). The LP plans Category A, but a cycle outlives the ABC run it
    # was solved against, so a row can be for a SKU that is no longer A.
    tier: str | None = None
    # The run `tier` comes from. Older than the cycle's own ABC period = carried
    # forward: shown labelled, never ranked (no share, no priority, no cohort).
    tier_period: str | None = None
    tier_is_current: bool | None = None
    stockout_gap: float | None = None
    priority_score: float | None = None
    days_of_cover: float | None = None
    cover_blocked_reason: str | None = None
    # The cycle month's Forecast_Result.forecast_value, in pieces: with it,
    # q_i = forecast + rop_i - current_stock, less short_units.
    forecast_units: float | None = None
    # How far the order falls short of reaching rop_i (the target) because
    # the supplier allocation couldn't cover the whole need. 0 when filled;
    # None without a forecast or a stock figure to work it out from.
    short_units: float | None = None
    # The opening count's "PO Qty" (2026-10-04, migration 0042), in pieces
    # (on_order_cases: as the file records it). INFORMATION ONLY: its meaning
    # is unverified (pending SSM), so it is never subtracted from q_i or any
    # order quantity (DEC-34); on_order_note says so. None with
    # on_order_blocked_reason when unknown — never 0 for "not loaded".
    on_order: float | None = None
    on_order_cases: float | None = None
    on_order_blocked_reason: str | None = None
    on_order_note: str | None = None
    # Review before ordering (2026-10-04, review_flag, DEC-33; the full
    # contract is in backend/routers/recommendations.py): True = the forecast
    # for this cycle is likely to miss by a lot — review_reasons says why
    # ('collapse': last 3 months < half the last 12; 'over_forecast_run':
    # over-forecast 3+ months running, review_over_run_months of them, 6 =
    # "6 or more"). Not a direction to adjust. False = assessed, not
    # flagged; None = not assessed. A flagged row is never accepted in bulk:
    # PATCH needs reviewed=true to accept it.
    needs_review: bool | None = None
    review_reasons: list[str] = []
    review_over_run_months: int | None = None
    review_collapse_ratio: float | None = None
    # The planner's decision, captured beside the recommendation and never in place of it (2026-10-21,
    # migration 0062). q_i stays what the LP produced; recommended_q_i repeats it under an unambiguous
    # name so a page can show "recommended X, decided Y". decided_q_i is the quantity the planner chose
    # when it differs from q_i (None = no override: pending, dismissed, or accepted as recommended).
    # decision_reason is why (required on dismiss). Nothing in forecasting, safety stock or the LP reads
    # these, and none of them changes a recommended value. The one reader is the displayed plan total.
    recommended_q_i: float | None = None
    decided_q_i: float | None = None
    # What this row contributes to the displayed plan total and count (2026-10-24, the narrow lift of the
    # capture-only rule): decided_q_i where the planner accepted a different quantity, else q_i. Equal to
    # q_i for every undecided row, so with nothing decided the plan total is unchanged.
    plan_q_i: float | None = None
    decision_reason: str | None = None
    decided_at: datetime.datetime | None = None
    decided_by: str | None = None


class RecommendationsResponse(BaseModel):
    items: list[RecommendationItem]
    count: int
    # Of `count`, how many items plan an order above zero (audit A12, 2026-10-30): 73 of 109 in cycle 2026-03,
    # the other 36 plan a zero order. Additive; `count` and the plan total are unchanged.
    order_count: int | None = None
    # The LP cycle these rows belong to, and how many pending rows from
    # earlier runs were withheld so a superseded cycle can't be acted on
    # (backend/lp_cycle.py). Optional so older fixtures still validate.
    planning_cycle_date: str | None = None
    superseded_count: int = 0
    # {cycle_date, lp_generated_at, forecast_generated_at, is_stale,
    #  superseded_pending_count, reason} — lets the UI warn that q_i/rop_i
    #  were solved against forecasts that have since been replaced.
    freshness: dict | None = None
    # {weights: {cost, service_level, storage}, service_level_pct, z_score} —
    # the solver's own settings (backend/lp_cycle.lp_model_info), so the
    # detail view states what the LP does rather than a copy of it.
    lp_model: dict | None = None
    # The periods the row figures were read at, so the page can say which
    # month or day every number belongs to (backend/routers/recommendations.
    # label_context). Read-only labels; none of them changes a row.
    #   stock_period      'YYYY-MM' Inventory_Fact_Real._period the stock is from
    #   stock_count_date  the day that count was taken (MAX(snapshot_date) in
    #                     stock_period): Unilever's '2026-03' is 6 Apr 2026
    #   abc_period        the single-month ABC run revenue_share/tier come from
    #   cover_sales_start/end  the sales months days_of_cover averages over
    stock_period: str | None = None
    stock_count_date: datetime.date | None = None
    # Why stock_count_date is null when Del Monte's stock is in view (its stored day is a placeholder, DEC-12).
    stock_count_note: str | None = None
    abc_period: str | None = None
    cover_sales_start: str | None = None
    cover_sales_end: str | None = None
    # The stock count each principal's rows were checked against: the one
    # that opens the cycle (backend/stock_units.stock_count_info) — {cycle,
    # principal, period, role: 'opening', available, counted_on,
    # counted_on_note, row_count, flag, reason}. available False with reason
    # "no opening stock count for <month>" when the plan can't be made from it.
    stock_counts: list[dict] = []
    # {principal display name: 'YYYY-MM'} — each principal's ABC run at or before the cycle month.
    tier_a_periods: dict[str, str] = {}


class RecommendationDecision(BaseModel):
    status: str  # 'accepted' | 'dismissed'
    # Why. It is stored on the row (migration 0062) and goes into the audit log entry. REQUIRED, non-blank,
    # when status is 'dismissed'; optional when accepting with a different quantity.
    reason: str | None = Field(default=None, max_length=500)
    # The quantity the planner decided to order instead of the recommendation (pieces, the unit of q_i).
    # Only on 'accepted'. Left out = accept the recommendation as it is. A value equal to q_i is stored as
    # no override. Never overwrites q_i.
    decided_quantity: float | None = Field(default=None, ge=0, le=999_999_999_999, allow_inf_nan=False, strict=True)
    # Required (true) to ACCEPT a row flagged for review (needs_review): the
    # person confirms they checked it. The page sends it only from a single
    # row's confirm dialog, never from bulk accept.
    reviewed: bool = Field(default=False, strict=True)   # yes or 1 is not a confirmation

    @model_validator(mode="after")
    def _decision_shape(self):
        if self.status == "dismissed":
            if not (self.reason and self.reason.strip()):
                raise ValueError("a reason is required to dismiss a recommendation")
            if self.decided_quantity is not None:
                raise ValueError("decided_quantity applies to an accepted recommendation, not a dismissed one")
        return self


# ── Reorder approval flow (2026-10-23, migrations 0067 and 0068) ───────────────────────────────────────────
# backend/routers/reorder_approval.py. A planner's edit to the recommended quantity is a PROPOSED CHANGE held for
# an admin (state 'pending_approval'), unless the planner may apply directly (an admin always, anyone else with
# an admin's grant). Quantities are pieces, the unit of q_i.

class QuantityChangeRequest(BaseModel):
    """POST /recommendations/{key}/quantity-change."""
    quantity: float = Field(ge=0, le=999_999_999_999, allow_inf_nan=False, strict=True)  # the quantity wanted instead of q_i
    reason: str | None = Field(default=None, max_length=500)
    # As on PATCH: required (true) when the product is flagged for review, i.e. the person checked it.
    reviewed: bool = Field(default=False, strict=True)   # yes or 1 is not a confirmation


class QuantityChange(BaseModel):
    """One lp_quantity_change row. state: pending_approval | approved | rejected."""
    change_key: int
    recommendation_key: int
    sku_code: str | None = None
    product_name: str | None = None
    planning_cycle_date: datetime.date | None = None
    recommended_q_i: float          # q_i when proposed
    proposed_q_i: float
    reason: str | None = None       # the planner's reason (becomes decision_reason when approved)
    reviewed: bool = Field(default=False, strict=True)   # yes or 1 is not a confirmation
    state: str
    proposed_by: str
    proposed_at: datetime.datetime
    resolved_by: str | None = None  # the admin who approved or rejected
    resolved_at: datetime.datetime | None = None
    resolution_note: str | None = None  # required on a rejection
    # Set on an approved change whose accepted decision an admin later reversed (the state stays 'approved').
    reversed_by: str | None = None
    reversed_at: datetime.datetime | None = None


class QuantityChangeOutcome(BaseModel):
    """outcome 'held' (HTTP 202): the change awaits an admin, nothing was applied, `change` is set.
    outcome 'applied' (HTTP 200): the caller may apply directly, the row is now accepted, `item` is set."""
    outcome: str
    change: QuantityChange | None = None
    item: RecommendationItem | None = None


class QuantityChangeList(BaseModel):
    count: int
    items: list[QuantityChange]


class ApprovalNote(BaseModel):
    """POST /recommendations/changes/{key}/approve. The note is optional."""
    note: str | None = Field(default=None, max_length=500)


class RejectRequest(BaseModel):
    """POST /recommendations/changes/{key}/reject. A reason is required (stored as resolution_note)."""
    reason: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def _reason_not_blank(self):
        if not self.reason.strip():
            raise ValueError("a reason is required to reject a quantity change")
        return self


class ReverseRequest(BaseModel):
    """POST /recommendations/{key}/reverse. A reason is required."""
    reason: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def _reason_not_blank(self):
        if not self.reason.strip():
            raise ValueError("a reason is required to reverse a decision")
        return self


class DirectApplyGrantBody(BaseModel):
    granted: bool


class DirectApplyGrant(BaseModel):
    user_id: int
    email: str | None = None
    full_name: str | None = None
    granted_by: str
    granted_at: datetime.datetime


class DirectApplyStatus(BaseModel):
    """GET /recommendations/direct-apply-grants/me: whether the caller's quantity changes apply at once."""
    can_apply_directly: bool
    reason: str  # 'admin' | 'granted' | 'not_granted'
    approval_ready: bool  # false until migration 0068 is applied: a quantity edit then still applies at once
