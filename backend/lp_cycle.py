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

from sqlalchemy.orm import Session

from analytics.params import LP_WEIGHTS, MASE_GATE, PLACEHOLDERS, SAFETY_STOCK_ASSUMPTION
from analytics.params import SERVICE_LEVEL_PCT as LP_SERVICE_LEVEL_PCT
from analytics.params import SERVICE_Z as LP_SERVICE_Z
from backend import batch
from backend.data_mode import REAL, forecast_source, lp_source

# Applied to every LP read. Bound (not interpolated) so it is safe to
# concatenate into a query string alongside the principal clause.
CURRENT_CYCLE_CLAUSE = " AND lr.planning_cycle_date = :current_cycle AND (lr.status = 'pending' OR lr.lp_run_key IS NOT NULL)"

# WHICH ROWS ARE "THE PLAN" (2026-10-21). Until this date every plan read
# said `status = 'pending'`, so deciding a row removed it from the plan: an
# accepted product read "NO ROP" on the inventory page, and once every row of
# a cycle was decided current_cycle() fell back to an OLDER cycle's pending
# rows (or to nothing). A decision is about one ORDER, not about the targets:
#   pending    the order is awaiting a decision          -> plan, and an open action
#   accepted   the planner took the order (maybe at a
#              different quantity)                       -> plan, not open
#   dismissed  the planner declined this cycle's order   -> plan, not open
# ss_i (safety stock) and rop_i (target stock) are the policy for the product
# in that cycle whether or not this month's order is placed; a dismissed
# order does not make the product's target disappear, and treating it as if
# it did would show "NO ROP" for a product whose target is known. What
# differs is the OPEN-ACTION reads (dashboard pending count, pending keys,
# reorder preview totals, superseded_count), which stay PENDING_ONLY: they
# count work still to do, and accepted/dismissed rows are done.
#
# A decided row belongs to the plan only if an LP run produced it (lp_run_key set, 2026-10-22). Row 4 of the
# 2026-03 cycle is a Tier C product accepted 2026-08-24, before runs were recorded (migration 0037): it has no
# run and no current forecast, so it is not this cycle's plan, though it stays in the table. A pending row is
# always plan (a legacy cycle's pending rows have no run key and must stay readable).
PLAN_STATUSES = ("pending", "accepted", "dismissed")
PLAN_STATUS_SQL = ("(lr.status IN ('pending', 'accepted', 'dismissed') "
                   "AND (lr.status = 'pending' OR lr.lp_run_key IS NOT NULL))")
PLAN_STATUS_SQL_BARE = ("(status IN ('pending', 'accepted', 'dismissed') "
                        "AND (status = 'pending' OR lp_run_key IS NOT NULL))")  # for subqueries with no `lr` alias

# The solver's fixed settings (LP_WEIGHTS, LP_SERVICE_Z, LP_SERVICE_LEVEL_PCT,
# imported above) come from analytics.params, the module analytics/
# optimization/lp.py reads too, so a label can't drift from what the solver
# does. Every screen that describes the LP reads them from here (GET
# /recommendations' lp_model, GET /dashboard's reorder_preview.lp_weights).


def stored_run(db: Session, cycle: datetime.date | None, principal: str | None = None,
               mode: str = REAL) -> dict | None:
    """The lp_run row (migration 0037) behind `cycle`'s pending rows in the
    selected scope: what that LP run actually used. None when there is
    nothing to look up — preview mode, no cycle, the table not applied yet
    (checked with to_regclass first, so a missing table never aborts the
    request's transaction), or rows written before runs were recorded."""
    if mode != REAL or cycle is None:
        return None
    if not lp_run_present(db):
        return None
    row = batch.first(db, *stored_run_query(cycle, principal))
    return dict(row) if row else None


# Remembered once seen on the real database (a migration isn't rolled back under a
# running server), so it costs a round trip only until then; a False is asked again
# next time, so applying 0037 needs no restart. Tests' fake sessions are never cached.
_LP_RUN_PRESENT = {"value": False}
LP_RUN_PRESENT_SQL = "SELECT to_regclass('lp_run') IS NOT NULL AS present"


def lp_run_present(db: Session) -> bool:
    if _LP_RUN_PRESENT["value"]:
        return True
    row = batch.first(db, LP_RUN_PRESENT_SQL)
    present = bool(row and row["present"])
    if present and isinstance(db, Session):
        _LP_RUN_PRESENT["value"] = True
    return present


def lp_run_present_known() -> bool:
    """True once lp_run_present has seen the table (no lookup needed any more)."""
    return _LP_RUN_PRESENT["value"]


def stored_run_query(cycle, principal: str | None = None) -> tuple[str, dict]:
    sql = """
        SELECT r.run_key, r.planning_cycle_date, r.principal_scope, r.inputs, r.model,
               r.code_version, r.created_at
        FROM lp_run r
        WHERE r.run_key = (
            SELECT MAX(lr.lp_run_key)
            FROM lp_recommendation lr
            JOIN product_dimension pd ON pd.product_key = lr.product_key
            WHERE lr.planning_cycle_date = :cycle AND {plan}{principal_clause}
        )
    """
    params: dict = {"cycle": cycle}
    clause = ""
    if _principal_key(principal):
        clause = " AND pd.principal = :principal"
        params["principal"] = _principal_key(principal)
    return sql.format(principal_clause=clause, plan=PLAN_STATUS_SQL), params


def lp_model_info(run: dict | None = None) -> dict:
    """How the LP decides, for the reorder detail view to state.

    With a stored run (stored_run), everything is what that run used:
    inputs_source 'run'. Without one, `inputs` is analytics/params.
    PLACEHOLDERS, the dict scripts/run_lp.py takes its defaults from, and
    inputs_source says 'defaults' so no screen presents them as a run's.
    Either way the inputs are placeholders until SSM confirms them, and the
    safety stock's daily-independence assumption is stated with them."""
    if run is None:
        return {
            "weights": dict(LP_WEIGHTS),
            "service_level_pct": LP_SERVICE_LEVEL_PCT,
            "z_score": LP_SERVICE_Z,
            "inputs": dict(PLACEHOLDERS),
            "inputs_are_placeholders": True,
            "inputs_source": "defaults",
            "run": None,
            # No run, so no stock count to name.
            "stock_counts": None,
            "safety_stock_assumption": SAFETY_STOCK_ASSUMPTION,
        }
    model, inputs = run["model"], run["inputs"]
    return {
        "weights": model["weights"],
        "service_level_pct": model["service_level_pct"],
        "z_score": model["z_score"],
        "inputs": inputs,
        "inputs_are_placeholders": True,
        "inputs_source": "run",
        "inputs_differing_from_defaults": sorted(k for k, v in PLACEHOLDERS.items() if inputs.get(k) != v),
        "allocation": model.get("allocation"),
        # {principal: {period, counted_on, counted_on_note, row_count, flag}}:
        # the opening stock counts the run planned from (scripts/run_lp.py
        # run_record). None for a run recorded before 2026-10-03, which
        # didn't record its count (it used each principal's latest).
        "stock_counts": inputs.get("stock_counts"),
        "run": {
            "run_key": run["run_key"],
            "planning_cycle_date": run["planning_cycle_date"],
            "principal_scope": run["principal_scope"],
            "created_at": run["created_at"],
            "code_version": run["code_version"],
        },
        "safety_stock_assumption": model.get("safety_stock_assumption", SAFETY_STOCK_ASSUMPTION),
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
    planning_cycle_date that has any plan row (pending, accepted or
    dismissed: PLAN_STATUSES), within the selected scope. None when the LP has
    no rows at all. Deciding every row of a cycle therefore leaves it current
    (until 2026-10-21 it fell back to an older cycle's pending rows).

    Scoped by principal because LP_Recommendation carries both (today it
    holds Unilever rows only), so an unscoped MAX could resolve to a cycle
    the selected principal has no rows in."""
    row = batch.first(db, *current_cycle_query(principal, mode))
    return row["d"] if row else None


def current_cycle_query(principal: str | None = None, mode: str = REAL) -> tuple[str, dict]:
    lp, params = lp_source(mode, "lp_recommendation")
    sql = f"""
        SELECT MAX(lr.planning_cycle_date) AS d
        FROM {lp} lr
        JOIN product_dimension pd ON pd.product_key = lr.product_key
        WHERE {PLAN_STATUS_SQL}
    """
    params = dict(params)
    if _principal_key(principal):
        sql += " AND pd.principal = :principal"
        params["principal"] = _principal_key(principal)
    return sql, params


def superseded_count(
    db: Session, cycle: datetime.date | None, principal: str | None = None, mode: str = REAL,
) -> int:
    """How many pending rows from EARLIER cycles are being withheld. Shown
    in the UI so the filtering is visible rather than silent — a user who
    remembers 429 rows should be told where the other 179 went."""
    if cycle is None:
        return 0
    return int(batch.scalar(db, *superseded_count_query(cycle, principal, mode)) or 0)


def superseded_count_query(cycle, principal: str | None = None, mode: str = REAL) -> tuple[str, dict]:
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
    return sql, params


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
    fc_at = batch.scalar(db, *forecast_generated_query(mode))
    lp = batch.first(db, *freshness_query(cycle, fc_at, principal, mode)) or {}
    return freshness_from(cycle, fc_at, lp.get("t"), int(lp.get("row_count") or 0),
                          int(lp.get("stale_count") or 0), superseded_count(db, cycle, principal, mode))


def freshness_from(cycle, fc_at, lp_at, row_count: int, stale_count: int, superseded: int) -> dict:
    """freshness()'s answer from its figures, however they were read (the queries above, or
    backend/planning_mart.head_query in one statement)."""
    is_stale = None
    reason = None
    if lp_at is not None and fc_at is not None:
        is_stale = stale_count > 0
        if is_stale and stale_count == row_count:
            reason = (
                f"The LP was last run {lp_at:%Y-%m-%d %H:%M UTC}, before the forecasts were "
                f"rewritten {fc_at:%Y-%m-%d %H:%M UTC}. Order quantities (q_i) and target stock "
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
                f"but refreshes only the products in that run (Tier A, forecast status ok, MASE < {MASE_GATE:g}) "
                "and leaves the cycle's other rows as they were, so these still carry order "
                "quantities (q_i) and target stock (rop_i) solved against forecasts that are no "
                "longer the served ones. A plain rerun leaves them as they are; "
                "scripts/run_lp.py --retire-stale-pending saves them to a CSV and removes them."
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
        "superseded_pending_count": superseded,
        "reason": reason,
    }


def forecast_generated_query(mode: str = REAL) -> tuple[str, dict]:
    """When the served forecasts were written: freshness()'s comparison point."""
    fc, fc_params = forecast_source(mode, "forecast_result")
    return f"SELECT MAX(generated_at) AS t FROM {fc}", fc_params


def freshness_query(cycle, fc_at, principal: str | None = None, mode: str = REAL) -> tuple[str, dict]:
    """The cycle's pending rows: newest generated_at, how many, how many predate fc_at.
    Scoped like current_cycle(), so the count can't mix in the other principal's rows."""
    lp, lp_params = lp_source(mode, "lp_recommendation")
    sql = f"""
        SELECT MAX(lr.generated_at) AS t,
               COUNT(*) AS row_count,
               COUNT(*) FILTER (WHERE lr.generated_at < :fc_at) AS stale_count
        FROM {lp} lr
        JOIN product_dimension pd ON pd.product_key = lr.product_key
        WHERE {PLAN_STATUS_SQL}
          AND (:cycle IS NULL OR lr.planning_cycle_date = :cycle)
    """
    params: dict = {"cycle": cycle, "fc_at": fc_at, **lp_params}
    if _principal_key(principal):
        sql += " AND pd.principal = :principal"
        params["principal"] = _principal_key(principal)
    return sql, params
