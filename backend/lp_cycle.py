"""
backend.lp_cycle — the ONE place that decides which LP planning cycle is
current, and whether that cycle can still be trusted.

WHY THIS MODULE EXISTS (2026-09-23)
-----------------------------------
LP_Recommendation accumulates. Every run writes a new planning_cycle_date
and leaves earlier `pending` rows behind, because rerunning must never
overwrite a row somebody already accepted or dismissed (scripts/run_lp.py's
UPSERT_QUERY is `WHERE status = 'pending'`). Live on 2026-09-23 that was
429 pending rows: 250 from the current 2026-03 cycle and 179 left over from
33 earlier cycles going back to 2023-05.

Nothing filtered them, so:
  - the dashboard's "Pending reorder actions" card read 429 when 250 are
    actually current — a ~1.7x overstatement made of three-year-old rows;
  - reorder_preview's critical/urgent counts and GET /recommendations mixed
    cycles in one list;
  - safety_stock_rate picked each product's latest pending ss_i regardless
    of which cycle it came from.

Every LP read now goes through current_cycle() so a superseded run can
never reach a screen. NOTHING IS DELETED: the old rows stay in the database
untouched (they are somebody else's audit trail, and purging rows in the
shared `public` schema needs Yuan's explicit approval — see
scripts/apply_real_recovery_to_public.py's own "Run this yourself" note).
This is a read-side filter only, so it is fully reversible.

FRESHNESS
---------
A cycle can also be current and still be stale: the LP was last run
2026-08-24 07:12 UTC, while Forecast_Result was rewritten 2026-09-21 10:08
UTC by the per-bin router. q_i and rop_i are therefore built on forecasts
that no longer exist in the table, while anything comparing the LP against
`Forecast_Result.forecast_value` reads the new numbers — two vintages in
one figure. ss_i itself is Z x sigma_d, derived from demand history rather
than from a model, so it survives a forecast rerun; q_i and rop_i do not.

freshness() reports that as data, never as an exception, so the UI can show
the numbers with a banner instead of blanking a page. Rerunning
scripts/run_lp.py clears it for the products in the run (see
reports/PROJECT_DIAGNOSIS_2026-09-21.md); the cycle's other pending rows stay
stale until someone decides to keep or drop them.
"""
from __future__ import annotations

import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from analytics.params import PLACEHOLDERS, SAFETY_STOCK_ASSUMPTION
from backend.data_mode import REAL, forecast_source, lp_source

# Applied to every LP read. Bound (not interpolated) so it is safe to
# concatenate into a query string alongside the principal clause.
CURRENT_CYCLE_CLAUSE = " AND lr.planning_cycle_date = :current_cycle"

# The solver's fixed settings — analytics/optimization/lp.py's W1/W2/W3 and
# Z_SCORE — kept here because lp.py imports the pulp solver, a batch-job
# dependency the always-on API should not need just to read four numbers.
# tests/backend/test_recommendations.py pins them to lp.py. Every screen that
# describes the LP reads them from here (GET /recommendations' lp_model,
# GET /dashboard's reorder_preview.lp_weights), so a label can't drift from
# what the solver does.
LP_WEIGHTS = {"cost": 0.45, "service_level": 0.35, "storage": 0.20}
LP_SERVICE_Z = 1.28
LP_SERVICE_LEVEL_PCT = 90  # the cycle service level Z = 1.28 stands for


def lp_model_info() -> dict:
    """How the LP decides, for the reorder detail view to state.

    `inputs` is analytics/params.PLACEHOLDERS, the dict
    scripts/run_lp.py takes its defaults from: the allocation %, review and
    lead days, target weeks, cover rule, warehouse capacity and costs.
    Placeholders until SSM confirms them, so they're flagged as such, and the
    safety stock's daily-independence assumption is stated with them."""
    return {
        "weights": dict(LP_WEIGHTS),
        "service_level_pct": LP_SERVICE_LEVEL_PCT,
        "z_score": LP_SERVICE_Z,
        "inputs": dict(PLACEHOLDERS),
        "inputs_are_placeholders": True,
        "safety_stock_assumption": SAFETY_STOCK_ASSUMPTION,
    }


def _principal_key(principal: str | None) -> str | None:
    """The principal the way backend.principals.normalize_principal reads it
    for the rows: case-insensitive ('Unilever' and 'unilever' are one
    scope), and 'all' or blank meaning no filter. Every anchor here resolves
    through this, so an LP cycle is always found under the SAME scope as the
    rows it anchors (the rule of commit fd4dded); a raw 'Unilever' used to
    match no product_dimension row and leave the cycle None."""
    value = (principal or "").strip().lower()
    return None if value in ("", "all") else value


def current_cycle(db: Session, principal: str | None = None, mode: str = REAL) -> datetime.date | None:
    """The planning cycle the LP is currently proposing: the most recent
    planning_cycle_date that still has undecided (pending) rows, within the
    selected scope. None when nothing is pending at all.

    Scoped by principal because LP_Recommendation carries both (today it
    holds Unilever rows only), so an unscoped MAX could resolve to a cycle
    the selected principal has no rows in."""
    lp, params = lp_source(mode, "lp_recommendation")
    sql = f"""
        SELECT MAX(lr.planning_cycle_date) AS d
        FROM {lp} lr
        JOIN product_dimension pd ON pd.product_key = lr.product_key
        WHERE lr.status = 'pending'
    """
    params = dict(params)
    if _principal_key(principal):
        sql += " AND pd.principal = :principal"
        params["principal"] = _principal_key(principal)
    row = db.execute(text(sql), params).mappings().first()
    return row["d"] if row else None


def superseded_count(
    db: Session, cycle: datetime.date | None, principal: str | None = None, mode: str = REAL,
) -> int:
    """How many pending rows from EARLIER cycles are being withheld. Shown
    in the UI so the filtering is visible rather than silent — a user who
    remembers 429 rows should be told where the other 179 went."""
    if cycle is None:
        return 0
    lp, lp_params = lp_source(mode, "lp_recommendation")
    sql = f"""
        SELECT COUNT(*) FROM {lp} lr
        JOIN product_dimension pd ON pd.product_key = lr.product_key
        WHERE lr.status = 'pending' AND lr.planning_cycle_date < :cycle
    """
    params: dict = {"cycle": cycle, **lp_params}
    if _principal_key(principal):
        sql += " AND pd.principal = :principal"
        params["principal"] = _principal_key(principal)
    return int(db.execute(text(sql), params).scalar() or 0)


def freshness(db: Session, principal: str | None = None, mode: str = REAL) -> dict:
    """Whether the current cycle's rows predate the forecast run they should
    have been built from.

    Returns data, never raises: {cycle_date, lp_generated_at,
    forecast_generated_at, is_stale, row_count, stale_row_count,
    superseded_pending_count, reason}. is_stale is None when either
    timestamp is missing (nothing to compare), False when every pending row
    in the cycle is at least as new as the forecasts.

    Judged per row, not by the newest one: a rerun refreshes only the
    products in that run and leaves the cycle's other pending rows as they
    were (scripts/run_lp.py never deletes one), so after a rerun one cycle
    can hold both. Live on 2026-09-23 a rerun would refresh 73 of the 250
    rows; MAX(generated_at) alone would then call the cycle fresh while 177
    rows still carried q_i and rop_i from the old forecasts."""
    cycle = current_cycle(db, principal, mode)
    fc, fc_params = forecast_source(mode, "forecast_result")
    fc_at = db.execute(text(f"SELECT MAX(generated_at) AS t FROM {fc}"), fc_params).scalar()

    # Scoped like current_cycle(), so the count can't mix in the other
    # principal's rows.
    lp, lp_params = lp_source(mode, "lp_recommendation")
    sql = f"""
        SELECT MAX(lr.generated_at) AS t,
               COUNT(*) AS row_count,
               COUNT(*) FILTER (WHERE lr.generated_at < :fc_at) AS stale_count
        FROM {lp} lr
        JOIN product_dimension pd ON pd.product_key = lr.product_key
        WHERE lr.status = 'pending'
          AND (:cycle IS NULL OR lr.planning_cycle_date = :cycle)
    """
    params: dict = {"cycle": cycle, "fc_at": fc_at, **lp_params}
    if _principal_key(principal):
        sql += " AND pd.principal = :principal"
        params["principal"] = _principal_key(principal)
    lp = db.execute(text(sql), params).mappings().first() or {}
    lp_at = lp.get("t")
    row_count = int(lp.get("row_count") or 0)
    stale_count = int(lp.get("stale_count") or 0)

    is_stale = None
    reason = None
    if lp_at is not None and fc_at is not None:
        is_stale = stale_count > 0
        if is_stale and stale_count == row_count:
            reason = (
                f"The LP was last run {lp_at:%Y-%m-%d %H:%M UTC}, before the forecasts were "
                f"rewritten {fc_at:%Y-%m-%d %H:%M UTC}. Order quantities (q_i) and reorder points "
                "(rop_i) were solved against forecasts that are no longer the served ones. Safety "
                "stock (ss_i) doesn't use the forecasts, but it reflects the demand history as of that "
                "run, and the history has changed since. Rerun scripts/run_lp.py "
                "to clear this."
            )
        elif is_stale:
            # Rerunning can't clear this case, so the text must not say it will.
            reason = (
                f"{stale_count:,} of the {row_count:,} rows in this cycle predate the forecasts "
                f"rewritten {fc_at:%Y-%m-%d %H:%M UTC}. The LP last ran {lp_at:%Y-%m-%d %H:%M UTC} "
                "but refreshes only the products in that run (Tier A, forecast status ok, MASE < 1) "
                "and leaves the cycle's other rows as they were, so these still carry order "
                "quantities (q_i) and reorder points (rop_i) solved against forecasts that are no "
                "longer the served ones. A rerun will not change them; keeping or dropping them is "
                "a planning decision."
            )
    elif lp_at is None:
        reason = "No pending LP recommendations, so there is nothing to date."
    elif fc_at is None:
        reason = "No forecast run exists to compare the LP against."

    return {
        "cycle_date": cycle.isoformat() if cycle is not None else None,
        "lp_generated_at": lp_at.isoformat() if lp_at is not None else None,
        "forecast_generated_at": fc_at.isoformat() if fc_at is not None else None,
        "is_stale": is_stale,
        "row_count": row_count,
        "stale_row_count": stale_count,
        "superseded_pending_count": superseded_count(db, cycle, principal, mode),
        "reason": reason,
    }
