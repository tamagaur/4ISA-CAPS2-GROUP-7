"""
backend.planning_mart — the Reorder page's reads from mart.planning_mart (migration 0046).

One row per product x LP planning cycle, already joined to everything GET /recommendations
shows for it (the product, its tier, the cycle's forecast, its opening stock count, stock on
order, the review flag, the LP run, the decision). The endpoint reads it in ONE statement
(batch.prefetch of the four queries below) where the per-request joins took 12.

NEVER SERVED OUT OF STEP. usable() answers False, and the endpoint falls back to the
per-request joins (backend/routers/recommendations.py's _SELECT_ONE), when:
  - the mart isn't there (migration 0046 not applied), the request is in preview mode, or the
    session is a test's fake;
  - a source changed after the last planning refresh (mart.refresh_status.planning_stale:
    a data load, a fill, a forecast run, an LP run, a review-flag write, an ABC run or a
    product edited through the app);
  - the last planning refresh was built on a Tier A basis other than the current
    analytics.params.TIER_A_BASIS (mart.refresh_status.planning_tier_a_basis, migration 0047);
  - its rows don't match lp_recommendation's (row count, pending count, latest decision).
So a missed refresh costs speed, never a wrong figure.

KEPT IN STEP by analytics/marts.py (every full refresh, and after a review-flag write),
by refresh() below (a product edited through the app) and by decide() (a reorder decision
updates its own row inside the decision's transaction).

Scope strings reach this module already allowlisted by backend.principals.principal_clause
and are bound as parameters, never interpolated.
"""
from __future__ import annotations

import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from analytics.marts import planning_params
from analytics.params import TIER_A_BASIS
from backend import batch
from backend.data_mode import REAL
from backend.lp_cycle import PLAN_STATUSES
from backend.principals import principal_clause

# The rows that are the plan (backend/lp_cycle.PLAN_STATUSES), as a SQL list.
PLAN_STATUS_LIST = "('" + "', '".join(PLAN_STATUSES) + "')"

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


# The row query's columns: (the name recommendations._to_item reads from _SELECT_ONE, the
# mart column). Each row travels as ONE JSON array in this order, not an object: the column
# names are not repeated on every row, which cuts the payload to about a third (the round
# trip's time follows its bytes on a slow link, measured 2026-10-05).
ROW_COLUMNS = (
    ("recommendation_key", "pm.recommendation_key"), ("sku_id", "pm.sku_id"),
    ("product_name", "pm.product_name"), ("principal", "pm.principal"), ("pack_size", "pm.pack_size"),
    ("planning_cycle_date", "pm.planning_cycle_date"), ("q_i", "pm.order_pieces"),
    ("rop_i", "pm.target_stock"), ("ss_i", "pm.safety_stock"), ("status", "pm.decision_status"),
    ("current_stock", "pm.stock_pieces"), ("current_stock_cases", "pm.stock_cases"),
    ("stock_value_pesos", "pm.stock_pesos"), ("in_stock_count", "pm.in_stock_count"),
    ("revenue_share", "pm.revenue_share"), ("tier", "pm.tier"), ("tier_period", "pm.tier_period"),
    ("avg_monthly_sales_pesos", "pm.avg_monthly_sales_pesos"), ("forecast_units", "pm.forecast_pieces"),
    ("on_order_pieces", "pm.on_order_pieces"), ("on_order_cases", "pm.on_order_cases"),
    ("on_order_unparsed", "pm.on_order_unparsed"),
    ("needs_review", "pm.needs_review"), ("review_reasons", "pm.review_reasons"),
    ("review_over_run_months", "pm.review_over_run_months"), ("review_collapse_ratio", "pm.review_collapse_ratio"),
)
# Read only by scripts/rehearse_planning_mart.py, to check the mart's stored status columns.
STORED_STATUS_COLUMNS = (("mart_stock_status", "pm.stock_status"), ("mart_urgency", "pm.urgency"))


def _current_cycle(scope_sql: str) -> str:
    """backend/lp_cycle.current_cycle as a subquery: the latest cycle with any plan row
    (pending, accepted or dismissed) in scope."""
    return (f"(SELECT MAX(pm.planning_cycle_date) FROM {_STATE['schema']}.planning_mart pm "
            f"WHERE pm.decision_status IN {PLAN_STATUS_LIST}{scope_sql})")


def head_query(principal: str | None) -> tuple[str, dict]:
    """One row: the current cycle, backend/lp_cycle.freshness's figures for it, and whether
    the mart may be served (see the module docstring)."""
    scope_sql, params = principal_clause(principal, "pm.principal")
    mart = _STATE["schema"]
    return f"""
        WITH cur AS (SELECT {_current_cycle(scope_sql)} AS d),
        fc AS (SELECT MAX(generated_at) AS t FROM forecast_result),
        pending AS (
            SELECT pm.planning_cycle_date, pm.generated_at, pm.decision_status FROM {mart}.planning_mart pm
            WHERE pm.decision_status IN {PLAN_STATUS_LIST}{scope_sql}
        )
        SELECT cur.d AS cycle, fc.t AS fc_at,
               (SELECT MAX(p.generated_at) FROM pending p WHERE p.planning_cycle_date = cur.d) AS lp_at,
               (SELECT COUNT(*) FROM pending p WHERE p.planning_cycle_date = cur.d) AS row_count,
               (SELECT COUNT(*) FROM pending p WHERE p.planning_cycle_date = cur.d AND p.generated_at < fc.t) AS stale_count,
               (SELECT COUNT(*) FROM pending p WHERE p.planning_cycle_date < cur.d AND p.decision_status = 'pending') AS superseded,
               (SELECT planning_stale FROM {mart}.refresh_status) AS planning_stale,
               (SELECT planning_tier_a_basis FROM {mart}.refresh_status)
                   IS NOT DISTINCT FROM :tier_a_basis AS basis_current,
               (SELECT ROW(COUNT(*), COUNT(*) FILTER (WHERE status = 'pending'), MAX(decided_at)) FROM lp_recommendation)
                   IS NOT DISTINCT FROM
               (SELECT ROW(COUNT(*), COUNT(*) FILTER (WHERE decision_status = 'pending'), MAX(decided_at)) FROM {mart}.planning_mart)
                   AS in_step
        FROM cur CROSS JOIN fc
    """, {**params, "tier_a_basis": TIER_A_BASIS}


def _where(principal: str | None, status: str | None, cycle: str,
           from_date: str | None, to_date: str | None) -> tuple[str, dict]:
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
    return where, params


def rows_query(principal: str | None, status: str | None, cycle: str,
               from_date: str | None, to_date: str | None, columns=ROW_COLUMNS, packed: bool = True) -> tuple[str, dict]:
    """The page's rows: the current cycle's ('current') or every cycle's ('all'), newest
    cycle first, highest target stock first within one. packed: each row as one JSON array
    `r` in `columns` order (unpack() names them); otherwise ordinary named columns."""
    where, params = _where(principal, status, cycle, from_date, to_date)
    select = (f"json_build_array({', '.join(expr for _, expr in columns)}) AS r" if packed
              else ", ".join(f"{expr} AS {name}" for name, expr in columns))
    return f"""
        SELECT {select}
        FROM {_STATE['schema']}.planning_mart pm
        WHERE 1=1{where}
        ORDER BY pm.planning_cycle_date DESC, pm.target_stock DESC, pm.recommendation_key
    """, params


def unpack(rows, columns=ROW_COLUMNS) -> list[dict]:
    """rows_query's packed rows as dicts under the column names. A date inside the array
    arrives as ISO text (backend/batch.py revives top-level values only)."""
    names = [name for name, _ in columns]
    out = []
    for row in rows:
        item = dict(zip(names, row["r"]))
        item["planning_cycle_date"] = datetime.date.fromisoformat(item["planning_cycle_date"])
        out.append(item)
    return out


def counts_query(principal: str | None, status: str | None, cycle: str,
                 from_date: str | None, to_date: str | None) -> tuple[str, dict]:
    """The opening stock count behind those rows: one row per cycle x principal (the count's
    month, its dates and its row count; all NULL when the principal has no count)."""
    where, params = _where(principal, status, cycle, from_date, to_date)
    return f"""
        SELECT DISTINCT pm.planning_cycle_date, pm.principal, pm.opening_period,
               pm.opening_count_first_date AS first_date, pm.opening_count_last_date AS last_date,
               pm.opening_count_rows AS row_count
        FROM {_STATE['schema']}.planning_mart pm
        WHERE 1=1{where}
        ORDER BY pm.planning_cycle_date DESC, pm.principal
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
            WHERE pm.decision_status IN {PLAN_STATUS_LIST}{scope_sql}
              AND pm.planning_cycle_date = {_current_cycle(scope_sql)}
        )
    """, params


def read(db, principal: str | None, status: str | None, cycle: str,
         from_date: str | None, to_date: str | None) -> dict | None:
    """{head, rows, counts, run} in one round trip, or None when the mart must not be served."""
    head_q = head_query(principal)
    rows_q = rows_query(principal, status, cycle, from_date, to_date)
    counts_q = counts_query(principal, status, cycle, from_date, to_date)
    run_q = run_query(principal)
    batch.prefetch(db, [head_q, rows_q, counts_q, run_q])
    head = batch.first(db, *head_q)
    if (head is None or head["planning_stale"] is not False or not head["in_step"]
            or head["basis_current"] is not True):
        return None
    run = batch.first(db, *run_q)
    return {"head": head, "rows": unpack(batch.rows(db, *rows_q)), "counts": batch.rows(db, *counts_q),
            "run": dict(run) if run else None}


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
