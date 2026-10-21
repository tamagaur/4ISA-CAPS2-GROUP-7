"""
scripts/compute_review_flags.py — "review before ordering" flags for one
planning cycle, stored in review_flag (migration 0042).

For every Unilever product with a Forecast_Result row for the cycle (the
Tier A cohort that forecast run used), applies analytics/forecasting/
review_flag.py: the collapse rule and the 3+ month over-forecast run, each
reading only months before the cycle. GET /recommendations reads the stored
rows; PATCH refuses to accept a flagged row unless the person confirms the
review.

The over-forecast run scores the model that serves the product today
(Forecast_Result.model_params.bin, force_bin) one step ahead on each earlier
month, over the same training pool the forecast run used: every product in
the cycle's Forecast_Result, series built by run_baseline_forecast.
build_series from Unilever_SKU_Demand_Fact_Real. Before anything is written,
route() is re-run for the cycle month itself and must reproduce every stored
'ok' forecast_value; a mismatch means the pool or the series differ from the
run being flagged, and the script stops.

    python -m scripts.compute_review_flags                 # report only, read-only
    python -m scripts.compute_review_flags --write         # also replace the cycle's rows
    python -m scripts.compute_review_flags --cycle 2026-03 # default: latest forecast_date
    python -m scripts.compute_review_flags --calendar-factor --write
        # required when the forecast run was made with run_baseline_forecast --calendar-factor: the
        # reproduce check and the over-forecast run then score the calendar-adjusted values, as served.
        # Rerun it after every forecast rerun: planning_stale (migration 0061) is true while any flag
        # row's forecast_generated_at differs from the live forecast's generated_at.

Reads in BEGIN; SET TRANSACTION READ ONLY; ... ROLLBACK. --write replaces
the cycle's rows (DELETE + INSERT) in one transaction and checks the row
count before committing. Never touches Forecast_Result or LP_Recommendation.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import pandas as pd
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

from analytics.forecasting.calendar import company_totals
from analytics.forecasting.global_model import GlobalForecaster
from analytics.forecasting.review_flag import review_flag
from analytics.forecasting.router import assert_real_rows, route
from scripts.run_baseline_forecast import build_series, fetch_demand

PRINCIPAL = "unilever"
# route() re-run for the cycle must match the stored forecast once rounded the
# way the column stores it: Forecast_Result.forecast_value is NUMERIC(14,2)
# (analytics/db/schema.sql). XGBoost trains single-threaded
# (analytics.params.XGB_NTHREAD), so a faithful rerun rounds to the same cents.
STORED_DECIMALS = 2


def connect():
    load_dotenv(override=False)
    for var in ("DATABASE_URL", "SUPABASE_DIRECT_URL", "SUPABASE_DB_URL"):
        url = os.environ.get(var)
        if not url:
            continue
        try:
            return psycopg2.connect(url)
        except psycopg2.OperationalError:
            continue
    sys.exit("no database URL in .env worked (DATABASE_URL, SUPABASE_DIRECT_URL, SUPABASE_DB_URL)")


def read_inputs(conn, cycle: str | None):
    """(cycle date, forecast rows, demand) in one read-only transaction."""
    with conn.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        if cycle is None:
            cur.execute("""
                SELECT MAX(fr.forecast_date) FROM forecast_result fr
                JOIN product_dimension pd ON pd.product_key = fr.product_key WHERE pd.principal = %s
            """, (PRINCIPAL,))
            cycle_date = cur.fetchone()[0]
        else:
            cycle_date = pd.Timestamp(f"{cycle}-01").date()
        cur.execute("""
            SELECT fr.product_key, pd.sku_code, pd.product_name, fr.status, fr.forecast_value,
                   fr.model_params->>'bin' AS served_bin, fr.generated_at
            FROM forecast_result fr
            JOIN product_dimension pd ON pd.product_key = fr.product_key
            WHERE fr.forecast_date = %s AND pd.principal = %s
            ORDER BY fr.product_key
        """, (cycle_date, PRINCIPAL))
        fr = pd.DataFrame(cur.fetchall(), columns=["product_key", "sku_code", "product_name", "status",
                                                   "forecast_value", "served_bin", "generated_at"])
        demand = fetch_demand(cur)
    conn.rollback()
    return cycle_date, fr, demand


def compute(cycle_date, fr: pd.DataFrame, demand: pd.DataFrame, calendar: bool = False) -> pd.DataFrame:
    assert_real_rows(demand)
    cycle = pd.Timestamp(cycle_date)
    wanted = set(int(k) for k in fr.product_key)
    last_month = (cycle - pd.DateOffset(months=1)).strftime("%Y-%m")   # the latest real demand month
    series = {int(k): build_series(g, last_month) for k, g in demand.groupby("product_key") if int(k) in wanted}
    calendar_totals = company_totals(demand) if calendar else None
    forecaster = GlobalForecaster(series)

    gaps = []
    for r in fr[fr.status == "ok"].itertuples():
        got = route(series[int(r.product_key)], cycle, forecaster, calendar_totals=calendar_totals)["value"]
        gaps.append(abs(round(float(got), STORED_DECIMALS) - float(r.forecast_value)))
    worst = max(gaps, default=0.0)
    print(f"reproduce check: route() for {cycle:%Y-%m}, rounded to {STORED_DECIMALS} decimals, vs stored "
          f"forecast_value on {len(gaps)} 'ok' rows: max gap {worst:.3g} pieces")
    if worst > 10 ** -(STORED_DECIMALS + 2):
        sys.exit(f"stopping: the rerun does not reproduce Forecast_Result (max gap {worst}); "
                 "the pool or the series differ from the run being flagged")

    rows = []
    for r in fr.itertuples():
        k = int(r.product_key)
        s = series.get(k)
        served_bin = r.served_bin if r.status == "ok" else None
        f = review_flag(s, cycle, served_bin, forecaster, calendar_totals) if s is not None else {
            "needs_review": None, "reasons": [], "collapse": None, "collapse_ratio": None, "over_run_months": None}
        rows.append({"product_key": k, "sku_code": r.sku_code, "product_name": r.product_name,
                     "served_bin": served_bin, "forecast_generated_at": r.generated_at, **f})
    return pd.DataFrame(rows)


def write(conn, cycle_date, flags: pd.DataFrame) -> None:
    expected = len(flags)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM review_flag WHERE planning_cycle_date = %s AND principal = %s",
                    (cycle_date, PRINCIPAL))
        replaced = cur.rowcount
        psycopg2.extras.execute_values(cur, """
            INSERT INTO review_flag (product_key, planning_cycle_date, principal, needs_review, reasons,
                                     collapse, collapse_ratio, over_run_months, served_bin, forecast_generated_at)
            VALUES %s
        """, [(int(r.product_key), cycle_date, PRINCIPAL, r.needs_review, list(r.reasons), r.collapse,
               None if r.collapse_ratio is None or pd.isna(r.collapse_ratio) else round(float(r.collapse_ratio), 4),
               None if r.over_run_months is None or pd.isna(r.over_run_months) else int(r.over_run_months),
               r.served_bin, r.forecast_generated_at) for r in flags.itertuples()])
        cur.execute("SELECT COUNT(*) FROM review_flag WHERE planning_cycle_date = %s AND principal = %s",
                    (cycle_date, PRINCIPAL))
        got = cur.fetchone()[0]
        if got != expected:
            conn.rollback()
            sys.exit(f"rolled back: expected {expected} rows for {cycle_date}, the table holds {got}")
    conn.commit()
    print(f"wrote {expected} review_flag rows for {cycle_date} (replaced {replaced})")
    # Migration 0046: the Reorder page reads each row's flag from the planning mart.
    from analytics.marts import refresh_planning_conn
    refresh_planning_conn(conn, "compute_review_flags --write")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cycle", help="YYYY-MM; default: the latest Unilever forecast_date")
    ap.add_argument("--calendar-factor", action="store_true",
                    help="the forecast being flagged was made with --calendar-factor: apply it when re-running route()")
    ap.add_argument("--write", action="store_true", help="replace the cycle's review_flag rows")
    args = ap.parse_args()

    conn = connect()
    cycle_date, fr, demand = read_inputs(conn, args.cycle)
    if fr.empty:
        sys.exit(f"no Forecast_Result rows for {cycle_date}")
    flags = compute(cycle_date, fr, demand, args.calendar_factor)

    flagged = flags[flags.needs_review.eq(True)]
    summary = {
        "cycle": str(cycle_date), "products": len(flags),
        "needs_review": int(len(flagged)),
        "by_collapse": int(flags.collapse.eq(True).sum()),
        "by_over_run": int(flagged.reasons.map(lambda x: "over_forecast_run" in x).sum()),
        "not_assessed": int(flags.needs_review.isna().sum()),
        "collapse_not_assessable": int(flags.collapse.isna().sum()),
        "over_run_not_assessable": int(flags.over_run_months.isna().sum()),
    }
    print(json.dumps(summary, indent=2))
    show = flagged[["product_name", "sku_code", "served_bin", "reasons", "collapse_ratio", "over_run_months"]]
    print(show.to_string(index=False) if len(show) else "(none flagged)")
    if args.write:
        write(conn, cycle_date, flags)
    conn.close()


if __name__ == "__main__":
    main()
