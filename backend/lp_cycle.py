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

from analytics.params import LP_WEIGHTS, MASE_GATE, PLACEHOLDERS, SAFETY_STOCK_ASSUMPTION
from analytics.params import SERVICE_LEVEL_PCT as LP_SERVICE_LEVEL_PCT
from analytics.params import SERVICE_Z as LP_SERVICE_Z
from backend.data_mode import REAL, forecast_source, lp_source

# Applied to every LP read. Bound (not interpolated) so it is safe to
# concatenate into a query string alongside the principal clause.
CURRENT_CYCLE_CLAUSE = " AND lr.planning_cycle_date = :current_cycle"

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
    present = db.execute(text("SELECT to_regclass('lp_run') IS NOT NULL AS present")).mappings().first()
    if not present or not present["present"]:
        return None
    sql = """
        SELECT r.run_key, r.planning_cycle_date, r.principal_scope, r.inputs, r.model,
               r.code_version, r.created_at
        FROM lp_run r
        WHERE r.run_key = (
            SELECT MAX(lr.lp_run_key)
            FROM lp_recommendation lr
            JOIN product_dimension pd ON pd.product_key = lr.product_key
            WHERE lr.planning_cycle_date = :cycle AND lr.status = 'pending'{principal_clause}
        )
    """
    params: dict = {"cycle": cycle}
    clause = ""
    if _principal_key(principal):
        clause = " AND pd.principal = :principal"
        params["principal"] = _principal_key(principal)
    row = db.execute(text(sql.format(principal_clause=clause)), params).mappings().first()
    return dict(row) if row else None


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
        "superseded_pending_count": superseded_count(db, cycle, principal, mode),
        "reason": reason,
    }
