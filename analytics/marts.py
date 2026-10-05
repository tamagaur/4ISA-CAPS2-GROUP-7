"""
analytics.marts — keeps the `mart` schema (migration 0041) in step with the data.

Every pipeline step that writes what a mart sums calls a refresh once it has committed: the
slice loader (after its DEC-31 fill step), scripts/fill_missing.py run on its own,
scripts/run_baseline_forecast.py --write (which first keeps the run in the forecast history,
capture_forecast_cursor), scripts/run_lp.py and scripts/backtest_forecast_run.py. A refresh
is one transaction (mart.refresh(): DELETE + INSERT of every derived mart, a few seconds;
readers keep the previous rows until it commits), logged in mart.refresh_log. GET /dashboard
reads mart.refresh_status and says when a source changed after the last refresh.

After the commit, vacuum_marts() reclaims the replaced rows (VACUUM cannot run inside a
transaction), so a mart table peaks at its live rows plus one refresh's worth of dead ones.

The planning mart (migration 0046: one row per product x LP cycle, what the Reorder page
reads) is rebuilt with every full refresh, in the same transaction, and on its own after a
review-flag write (refresh_planning_conn). A reorder decision updates its own row
(backend/planning_mart.py).

Only `public` has marts. A write to a scratch schema skips the refresh (the marts read public,
not the schema just written), and so does a database without migration 0041 — both return
None and print why, never raise: a load must not fail because its summary tables could not
be rebuilt.
"""
from __future__ import annotations

import re

from analytics.params import (
    DEAD_SKU_MONTHS,
    POSSIBLY_PARTIAL_COUNTS,
    SKU_COVER_HISTORY_MONTHS,
    STOCK_LIMITED_AVG_MIN_MONTHS,
    STOCK_LIMITED_AVG_MONTHS,
    STOCK_LIMITED_WEEKS,
)

MART_SCHEMA = "mart"
# planning_mart last: on a database without migration 0046 its VACUUM fails and ends the loop.
MART_TABLES = ("sales_mart", "flow_month", "inventory_mart", "idle_stock", "accuracy_mart", "planning_mart")
# mart.refresh()'s arguments since migration 0043 (the stock-limited rule's three numbers).
REFRESH_SIGNATURE = "refresh(text,integer,text[],numeric,integer,integer)"

# mart.refresh_planning()'s arguments (migration 0046).
PLANNING_SIGNATURE = "refresh_planning(text,integer,text[])"
# Principals whose stock count never lists a zero-stock item, so a product missing from it
# has 0 on hand: backend/stock_status.COUNT_OMITS_ZERO_STOCK (pinned by tests/test_planning_mart.py).
PLANNING_ZERO_OMITTING = ("unilever",)


def planning_params(trigger: str) -> dict:
    """The arguments mart.refresh_planning() takes — one definition."""
    return {"trigger": trigger, "cover_months": SKU_COVER_HISTORY_MONTHS,
            "zero_omitting": list(PLANNING_ZERO_OMITTING)}


def refresh_params(trigger: str) -> dict:
    """The arguments mart.refresh() takes, from analytics.params — one definition."""
    return {"trigger": trigger, "idle_months": DEAD_SKU_MONTHS, "partial": list(POSSIBLY_PARTIAL_COUNTS),
            "low_weeks": STOCK_LIMITED_WEEKS, "avg_months": STOCK_LIMITED_AVG_MONTHS,
            "avg_min_months": STOCK_LIMITED_AVG_MIN_MONTHS}


def _mart(name: str) -> str:
    if name != MART_SCHEMA and not re.fullmatch(r"ssm_[a-z0-9_]+", name):
        raise ValueError(f"not a mart schema: {name!r} (use 'mart' or a scratch ssm_* schema)")
    return name


def _skip(schema: str | None) -> str | None:
    if schema is not None and schema != "public":
        return f"target schema {schema!r} is not public; the marts summarise public only"
    return None


def refresh_marts_cursor(cur, trigger: str, schema: str | None = "public", mart_schema: str = MART_SCHEMA) -> dict | None:
    """<mart_schema>.refresh() on a psycopg2 cursor, inside the caller's transaction (the
    caller commits, then calls vacuum_marts). None when skipped."""
    mart = _mart(mart_schema)
    reason = _skip(schema)
    if reason is None:
        cur.execute(f"SELECT to_regprocedure('{mart}.{REFRESH_SIGNATURE}') IS NOT NULL")
        if not cur.fetchone()[0]:
            reason = "migrations 0041/0043 (mart schema, its refresh) are not applied"
    if reason is not None:
        print(f"[marts] refresh skipped: {reason}")
        return None
    cur.execute(f"SELECT {mart}.refresh(%(trigger)s, %(idle_months)s, %(partial)s, %(low_weeks)s, %(avg_months)s, %(avg_min_months)s)", refresh_params(trigger))
    counts = cur.fetchone()[0]
    print(f"[marts] refreshed ({trigger}): {counts}")
    planning = refresh_planning_cursor(cur, trigger, schema, mart_schema)
    return {**counts, **planning} if planning else counts


def refresh_planning_cursor(cur, trigger: str, schema: str | None = "public", mart_schema: str = MART_SCHEMA) -> dict | None:
    """<mart_schema>.refresh_planning() on a psycopg2 cursor, inside the caller's transaction.
    None when skipped (a scratch target, or migration 0046 not applied)."""
    mart = _mart(mart_schema)
    reason = _skip(schema)
    if reason is None:
        cur.execute(f"SELECT to_regprocedure('{mart}.{PLANNING_SIGNATURE}') IS NOT NULL")
        if not cur.fetchone()[0]:
            reason = "migration 0046 (planning mart) is not applied"
    if reason is not None:
        print(f"[marts] planning refresh skipped: {reason}")
        return None
    cur.execute(f"SELECT {mart}.refresh_planning(%(trigger)s, %(cover_months)s, %(zero_omitting)s)", planning_params(trigger))
    counts = cur.fetchone()[0]
    print(f"[marts] planning mart refreshed ({trigger}): {counts}")
    return counts


def refresh_planning_conn(conn, trigger: str) -> dict | None:
    """The planning refresh on a psycopg2 connection whose own work has ALREADY committed
    (the review-flag write): its own transaction; a failure is reported, not raised."""
    try:
        with conn.cursor() as cur:
            counts = refresh_planning_cursor(cur, trigger)
        conn.commit()
        return counts
    except Exception as exc:  # noqa: BLE001 - see _failed
        conn.rollback()
        _failed(trigger, exc)
        return None


def vacuum_marts(db_url: str, mart_schema: str = MART_SCHEMA) -> None:
    """VACUUM (ANALYZE) the derived marts on a fresh autocommit connection. Never raises:
    autovacuum gets to them anyway, this only keeps the peak at one refresh of dead rows."""
    import psycopg2

    mart = _mart(mart_schema)
    try:
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        try:
            cur = conn.cursor()
            cur.execute("SELECT to_regnamespace(%s) IS NOT NULL", (mart,))
            if cur.fetchone()[0]:
                for table in MART_TABLES:
                    cur.execute(f"VACUUM (ANALYZE) {mart}.{table}")
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 - housekeeping only, see docstring
        print(f"[marts] vacuum skipped: {exc}")


MANUAL_REFRESH = "python -m analytics.marts --refresh"


def _failed(trigger: str, exc: Exception) -> None:
    """A step whose own work already committed must not crash on its summary tables:
    say so loudly instead. GET /dashboard's marts.stale shows it until the next refresh."""
    print(f"[marts] !!! REFRESH FAILED after {trigger}: {exc!r}\n"
          f"[marts] !!! The dashboard reads the previous refresh until this runs: {MANUAL_REFRESH}")


def refresh_marts(db_url: str, trigger: str, schema: str | None = "public") -> dict | None:
    """Refresh in its own committed transaction, then vacuum. For callers that have already
    committed their own work (the LP run): a failure is reported, not raised."""
    import psycopg2

    reason = _skip(schema)
    if reason is not None:
        print(f"[marts] refresh skipped: {reason}")
        return None
    try:
        conn = psycopg2.connect(db_url)
        try:
            cur = conn.cursor()
            counts = refresh_marts_cursor(cur, trigger, schema)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 - see _failed
        _failed(trigger, exc)
        return None
    if counts is not None:
        vacuum_marts(db_url)
    return counts


def refresh_marts_engine(engine, trigger: str, schema: str | None = "public") -> dict | None:
    """refresh_marts() for SQLAlchemy callers (the slice loader, the fill step): its own
    committed transaction, then VACUUM on an autocommit connection. A failure is reported,
    not raised: the caller's own work has already committed."""
    reason = _skip(schema)
    if reason is not None:
        print(f"[marts] refresh skipped: {reason}")
        return None
    try:
        with engine.begin() as conn:
            cur = conn.connection.cursor()
            try:
                counts = refresh_marts_cursor(cur, trigger, schema)
            finally:
                cur.close()
    except Exception as exc:  # noqa: BLE001 - see _failed
        _failed(trigger, exc)
        return None
    if counts is not None:
        try:
            with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                for table in MART_TABLES:
                    conn.exec_driver_sql(f"VACUUM (ANALYZE) {MART_SCHEMA}.{table}")
        except Exception as exc:  # noqa: BLE001 - housekeeping only
            print(f"[marts] vacuum skipped: {exc}")
    return counts


def capture_forecast_cursor(cur, code_version: str | None, created_by: str | None) -> int | None:
    """Keeps forecast_result's current rows as a stored run in mart.forecast_run (once per
    forecast_result state). None when migration 0041 is not applied."""
    cur.execute("SELECT to_regprocedure('mart.capture_forecast_result(text,text)') IS NOT NULL")
    if not cur.fetchone()[0]:
        print("[marts] forecast history skipped: migration 0041 (mart schema) is not applied")
        return None
    cur.execute("SELECT mart.capture_forecast_result(%(code_version)s, %(created_by)s)",
                {"code_version": code_version, "created_by": created_by})
    run_id = cur.fetchone()[0]
    print(f"[marts] forecast_result kept as forecast_run {run_id}")
    return run_id


def main() -> int:
    """python -m analytics.marts --refresh [--capture-forecast] [--planning-only]: the manual
    refresh a failed hook asks for. --capture-forecast first keeps forecast_result in the
    history (a no-op when that run is already kept). --planning-only rebuilds the planning
    mart alone. Writes public's mart schema only."""
    import argparse
    import getpass

    import psycopg2

    from analytics.config import get_settings

    p = argparse.ArgumentParser(description=main.__doc__)
    p.add_argument("--refresh", action="store_true", required=True)
    p.add_argument("--capture-forecast", action="store_true")
    p.add_argument("--planning-only", action="store_true")
    p.add_argument("--trigger", default="manual")
    args = p.parse_args()
    db_url = get_settings().supabase_db_url
    conn = psycopg2.connect(db_url)
    try:
        cur = conn.cursor()
        if args.capture_forecast:
            capture_forecast_cursor(cur, None, getpass.getuser())
        refresh = refresh_planning_cursor if args.planning_only else refresh_marts_cursor
        counts = refresh(cur, args.trigger)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
    if counts is not None:
        vacuum_marts(db_url)
    return 0 if counts is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
