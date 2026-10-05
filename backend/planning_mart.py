"""
backend.planning_mart — the Reorder page's reads from mart.planning_mart (migration 0046).

One row per product x LP planning cycle, already joined to everything GET /recommendations
shows for it (the product, its tier, the cycle's forecast, its opening stock count, stock on
order, the review flag, the LP run, the decision). The endpoint reads it in ONE statement
(batch.prefetch of the three queries below) where the per-request joins took 12.

NEVER SERVED OUT OF STEP. usable() answers False, and the endpoint falls back to the
per-request joins (backend/routers/recommendations.py's _SELECT_ONE), when:
  - the mart isn't there (migration 0046 not applied), the request is in preview mode, or the
    session is a test's fake;
  - a source changed after the last planning refresh (mart.refresh_status.planning_stale:
    a data load, a fill, a forecast run, an LP run, a review-flag write, an ABC run or a
    product edited through the app);
  - its rows don't match lp_recommendation's (row count, pending count, latest decision).
So a missed refresh costs speed, never a wrong figure.

KEPT IN STEP by analytics/marts.py (every full refresh, and after a review-flag write),
by refresh() below (a product edited through the app) and by decide() (a reorder decision
updates its own row inside the decision's transaction).

Scope strings reach this module already allowlisted by backend.principals.principal_clause
and are bound as parameters, never interpolated.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from analytics.marts import planning_params
from backend import batch
from backend.data_mode import REAL
from backend.principals import principal_clause

# The schema the mart is read from. 'mart' always, except scripts/rehearse_planning_mart.py,
# which points it at its scratch build to compare the two read paths before 0046 is applied.
_STATE = {"schema": "mart", "present": False}


def use_schema(schema: str | None) -> None:
    """Read the mart from `schema`; None turns the mart path off (the rehearsal's way of
    asking for the per-request joins)."""
    _STATE["schema"] = schema
    _STATE["present"] = False


def present_sql() -> str:
    return f"SELECT to_regclass('{_STATE['schema']}.planning_mart') IS NOT NULL AS present"


def present(db) -> bool:
    """Whether migration 0046's mart exists. Remembered once seen on the real database,
    like backend/marts.present; a test's fake session is never asked."""
    if _STATE["schema"] is None or not isinstance(db, Session):
        return False
    if _STATE["present"]:
        return True
    row = batch.first(db, present_sql())
    _STATE["present"] = bool(row and row["present"])
    return _STATE["present"]


def usable(db, mode: str = REAL) -> bool:
    return mode == REAL and present(db)


# The row query's columns, under the names recommendations._to_item reads from _SELECT_ONE.
_COLUMNS = """
        pm.recommendation_key, pm.sku_id, pm.product_name, pm.principal, pm.pack_size,
        pm.planning_cycle_date, pm.order_pieces AS q_i, pm.target_stock AS rop_i, pm.safety_stock AS ss_i,
        pm.decision_status AS status,
        pm.stock_pieces AS current_stock, pm.stock_cases AS current_stock_cases,
        pm.stock_pesos AS stock_value_pesos, pm.in_stock_count,
        pm.revenue_share, pm.tier, pm.avg_monthly_sales_pesos, pm.forecast_pieces AS forecast_units,
        pm.on_order_pieces, pm.on_order_cases, pm.on_order_unparsed,
        pm.needs_review, pm.review_reasons, pm.review_over_run_months, pm.review_collapse_ratio,
        pm.opening_period, pm.opening_count_first_date, pm.opening_count_last_date, pm.opening_count_rows,
        pm.stock_status AS mart_stock_status, pm.urgency AS mart_urgency
"""


def _current_cycle(scope_sql: str) -> str:
    """backend/lp_cycle.current_cycle as a subquery: the latest cycle with pending rows in scope."""
    return (f"(SELECT MAX(pm.planning_cycle_date) FROM {_STATE['schema']}.planning_mart pm "
            f"WHERE pm.decision_status = 'pending'{scope_sql})")


def head_query(principal: str | None) -> tuple[str, dict]:
    """One row: the current cycle, backend/lp_cycle.freshness's figures for it, and whether
    the mart may be served (see the module docstring)."""
    scope_sql, params = principal_clause(principal, "pm.principal")
    mart = _STATE["schema"]
    return f"""
        WITH cur AS (SELECT {_current_cycle(scope_sql)} AS d),
        fc AS (SELECT MAX(generated_at) AS t FROM forecast_result),
        pending AS (
            SELECT pm.planning_cycle_date, pm.generated_at FROM {mart}.planning_mart pm
            WHERE pm.decision_status = 'pending'{scope_sql}
        )
        SELECT cur.d AS cycle, fc.t AS fc_at,
               (SELECT MAX(p.generated_at) FROM pending p WHERE p.planning_cycle_date = cur.d) AS lp_at,
               (SELECT COUNT(*) FROM pending p WHERE p.planning_cycle_date = cur.d) AS row_count,
               (SELECT COUNT(*) FROM pending p WHERE p.planning_cycle_date = cur.d AND p.generated_at < fc.t) AS stale_count,
               (SELECT COUNT(*) FROM pending p WHERE p.planning_cycle_date < cur.d) AS superseded,
               (SELECT planning_stale FROM {mart}.refresh_status) AS planning_stale,
               (SELECT ROW(COUNT(*), COUNT(*) FILTER (WHERE status = 'pending'), MAX(decided_at)) FROM lp_recommendation)
                   IS NOT DISTINCT FROM
               (SELECT ROW(COUNT(*), COUNT(*) FILTER (WHERE decision_status = 'pending'), MAX(decided_at)) FROM {mart}.planning_mart)
                   AS in_step
        FROM cur CROSS JOIN fc
    """, params


def rows_query(principal: str | None, status: str | None, cycle: str,
               from_date: str | None, to_date: str | None) -> tuple[str, dict]:
    """The page's rows: the current cycle's ('current') or every cycle's ('all'), newest
    cycle first, highest target stock first within one."""
    scope_sql, params = principal_clause(principal, "pm.principal")
    where = scope_sql
    params = dict(params)
    if status:
        where += " AND pm.decision_status = :status"
        params["status"] = status
    if from_date and to_date:
        where += " AND pm.planning_cycle_date >= :from_date AND pm.planning_cycle_date <= :to_date"
        params["from_date"] = from_date
        params["to_date"] = to_date
    if cycle == "current":
        where += f" AND pm.planning_cycle_date = {_current_cycle(scope_sql)}"
    return f"""
        SELECT {_COLUMNS}
        FROM {_STATE['schema']}.planning_mart pm
        WHERE 1=1{where}
        ORDER BY pm.planning_cycle_date DESC, pm.target_stock DESC, pm.recommendation_key
    """, params


def run_query(principal: str | None) -> tuple[str, dict]:
    """backend/lp_cycle.stored_run_query for the current cycle: the lp_run behind its pending rows."""
    scope_sql, params = principal_clause(principal, "pm.principal")
    return f"""
        SELECT r.run_key, r.planning_cycle_date, r.principal_scope, r.inputs, r.model,
               r.code_version, r.created_at
        FROM lp_run r
        WHERE r.run_key = (
            SELECT MAX(pm.lp_run_key) FROM {_STATE['schema']}.planning_mart pm
            WHERE pm.decision_status = 'pending'{scope_sql}
              AND pm.planning_cycle_date = {_current_cycle(scope_sql)}
        )
    """, params


def read(db, principal: str | None, status: str | None, cycle: str,
         from_date: str | None, to_date: str | None) -> dict | None:
    """{head, rows, run} in one round trip, or None when the mart must not be served."""
    head_q = head_query(principal)
    rows_q = rows_query(principal, status, cycle, from_date, to_date)
    run_q = run_query(principal)
    batch.prefetch(db, [head_q, rows_q, run_q])
    head = batch.first(db, *head_q)
    if head is None or head["planning_stale"] is not False or not head["in_step"]:
        return None
    run = batch.first(db, *run_q)
    return {"head": head, "rows": batch.rows(db, *rows_q), "run": dict(run) if run else None}


def decide(db, params: dict) -> bool:
    """A reorder decision ({status, decided_at, decided_by, key}: the values just written to
    lp_recommendation) copied to the mart's own row, inside the decision's transaction and
    behind a savepoint: a failure leaves the decision intact (the mart then no longer matches
    lp_recommendation and isn't served, see head_query's in_step). False when skipped or failed."""
    if not present(db):
        return False
    try:
        with db.begin_nested():
            db.execute(text(f"""
                UPDATE {_STATE['schema']}.planning_mart
                SET decision_status = :status, decided_at = :decided_at, decided_by = :decided_by
                WHERE recommendation_key = :key
            """), params)
        return True
    except Exception as exc:  # noqa: BLE001 - the decision must not fail on a summary table
        print(f"[planning_mart] decision not copied to the mart: {exc!r}")
        return False


def refresh(db, trigger: str) -> bool:
    """mart.refresh_planning() inside the caller's transaction, behind a savepoint: a failure
    is reported and leaves the caller's own write intact (the mart then reads as stale and
    isn't served). False when skipped or failed."""
    if not present(db):
        return False
    try:
        with db.begin_nested():
            db.execute(text(f"SELECT {_STATE['schema']}.refresh_planning(:trigger, :cover_months, :zero_omitting, :tier_a_basis)"),
                       planning_params(trigger))
        return True
    except Exception as exc:  # noqa: BLE001 - the caller's write must not fail on a summary table
        print(f"[planning_mart] refresh failed after {trigger}: {exc!r}")
        return False
