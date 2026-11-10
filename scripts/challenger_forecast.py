"""
scripts/challenger_forecast.py - the challenger forecast beside the served one: compute, store, compare (2026-11-10).

    python -m scripts.challenger_forecast backtest            # both forecasts, every product-month 2023-10..2026-02
    python -m scripts.challenger_forecast cycle [--cycle YYYY-MM]   # both, for a planning cycle (default: latest)
    python -m scripts.challenger_forecast compare --turn 2024 # score both the same way, apply the committed rule
    add --write to store (backtest, cycle) in forecast_challenger (migration 0076); a database other than the
    throwaway 127.0.0.1:55432 also needs --target-public.

NEVER CHANGES WHAT IS SERVED. It reads Forecast_Result, the _Real demand view, abc_classification and the mart's
stored as-served backtest, and writes only forecast_challenger. The rule is docs/CHALLENGER_SELECTION_RULE.md
(committed fe9ed9d, before any comparison); compare's verdict is a recommendation and nothing reads it.

backtest   the as-served protocol of scripts/accuracy_as_served.py, calendar-adjusted (what the live run serves):
           Tier A the month before each month, XGBoost pool the same, route() on the history before the month, the
           live dead-SKU rule, a month the router cannot forecast (insufficient) dropped. The challenger is computed on
           the same history for the same rows, with the same calendar factor and dead-SKU rule. REPRODUCE CHECK before
           anything is written: every served value must equal mart.forecast_run_value of the stored as-served
           calendar-adjusted backtest (the dashboard card's default run), same rows, within 1e-4 pieces.
cycle      the products of the cycle's Forecast_Result. served_value = the stored forecast_value. REPRODUCE CHECK
           (as compute_review_flags): route() rerun for the cycle, rounded to the column's 2 decimals, must equal every
           stored 'ok' value. A dead_sku row is 0 for both. Status 'insufficient' rows have no forecast and no row here.
compare    reads the stored pairs (cycle rows where they exist, else backtest), attaches the as-served actual
           (run_baseline_forecast.build_series to the latest demand month: net-negative 0, no row 0, blank NaN),
           and calls selection_rule.decide. Read-only.

Each read is one READ ONLY transaction. --write replaces the rows of that kind, challenger and month range in one
transaction (DELETE + INSERT) and checks the count before committing.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import analytics.forecasting.global_model as gm  # noqa: E402
from analytics.classification.fsn import no_sale_in_last_months  # noqa: E402
from analytics.forecasting import selection_rule  # noqa: E402
from analytics.forecasting.calendar import company_totals  # noqa: E402
from analytics.forecasting.challenger import CHALLENGER_ID, challenger_route  # noqa: E402
from analytics.forecasting.router import assert_real_rows, route  # noqa: E402
from analytics.params import DEAD_SKU_MONTHS, abc_method  # noqa: E402
from scripts.backtest_forecast_run import WINDOW, read_tier_a, ym  # noqa: E402
from scripts.run_baseline_forecast import build_series, fetch_demand  # noqa: E402

AS_SERVED_CAL_LABEL = ("as-served backtest 2023-10..2026-02, Tier A the month before each month, calendar-adjusted")
TOL_BACKTEST = 1e-4
STORED_DECIMALS = 2
THROWAWAY = ("127.0.0.1", 55432)


def db_url() -> str:
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env", override=False)
    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        sys.exit("SUPABASE_DB_URL is not set")
    return url


def is_throwaway(url: str) -> bool:
    u = urlparse(url)
    return (u.hostname in ("127.0.0.1", "localhost")) and u.port == THROWAWAY[1]


def code_version() -> str:
    head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "analytics", "scripts/challenger_forecast.py"],
                           capture_output=True, text=True).stdout.strip()
    return head + ("+uncommitted" if dirty else "")


def read_demand(url: str) -> pd.DataFrame:
    conn = psycopg2.connect(url)
    try:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION READ ONLY")
        demand = fetch_demand(cur)
        conn.rollback()
    finally:
        conn.close()
    assert_real_rows(demand)
    return demand


def all_series(demand: pd.DataFrame) -> dict[int, pd.Series]:
    latest = demand.calendar_month.max()
    return {int(k): build_series(g, latest) for k, g in demand.groupby("product_key")}


def is_dead(hist: pd.Series, prev: str) -> bool:
    return len(hist) >= DEAD_SKU_MONTHS and no_sale_in_last_months(hist.index.strftime("%Y-%m"), hist.to_numpy(dtype=float), prev)


def pair(s: pd.Series, t: pd.Timestamp, fc, totals, dead: bool) -> dict | None:
    """Served and challenger for one product-month, the same history, calendar factor and dead-SKU rule."""
    r = route(s, t, fc, calendar_totals=totals)
    if r["value"] is None:
        return None
    c = challenger_route(s, t, calendar_totals=totals)
    return {"served_value": 0.0 if dead else float(r["value"]), "challenger_value": 0.0 if dead else float(c["value"]),
            "served_method": "zero_no_order" if dead else r["method"],
            "challenger_method": "zero_no_order" if dead else c["method"],
            "bin": r["bin"], "dead_sku": bool(dead), "calendar_factor": float(r.get("calendar_factor", 1.0)),
            "challenger_backup_reason": c["backup_reason"]}


# --- backtest ---------------------------------------------------------------------------------------------------

def compute_backtest(url: str) -> pd.DataFrame:
    demand = read_demand(url)
    series, totals = all_series(demand), company_totals(demand)
    tier = read_tier_a(url, abc_method("unilever"))
    rows = []
    for t in WINDOW:
        prev = ym(t - pd.offsets.MonthBegin(1))
        keys = sorted(k for k in tier.get(prev, set()) if k in series)
        fc = gm.GlobalForecaster({k: series[k] for k in keys})
        for k in keys:
            s = series[k]
            if t not in s.index or not t > s.index[0] or np.isnan(float(s.loc[t])):
                continue                                   # as-served: a blank actual is not scored, so not stored
            try:
                p = pair(s, t, fc, totals, is_dead(s[s.index < t], prev))
            except ValueError:
                continue                                   # no history before the month
            if p is not None:
                rows.append({"product_key": k, "month": ym(t), "cohort_period": prev, **p})
        print(f"[backtest] {ym(t)}: {sum(1 for r in rows if r['month'] == ym(t))} product-months", flush=True)
    return pd.DataFrame(rows)


def check_backtest(url: str, bt: pd.DataFrame) -> dict:
    """Every served value equals the stored as-served calendar-adjusted backtest, row for row."""
    conn = psycopg2.connect(url)
    try:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute("""SELECT v.product_key, v.month, v.forecast_pieces FROM mart.forecast_run_value v
                       JOIN mart.forecast_run r ON r.run_id = v.run_id WHERE r.label = %s""", (AS_SERVED_CAL_LABEL,))
        ref = pd.DataFrame(cur.fetchall(), columns=["product_key", "month", "ref"])
        conn.rollback()
    finally:
        conn.close()
    if ref.empty:
        sys.exit(f"no stored run labelled {AS_SERVED_CAL_LABEL!r}: nothing to reproduce")
    ref["ref"] = ref.ref.astype(float)
    m = bt.merge(ref, on=["product_key", "month"], how="outer", indicator=True)
    gap = (m.served_value - m.ref).abs().max()
    out = {"rows": len(bt), "reference_rows": len(ref), "only_here": int((m._merge == "left_only").sum()),
           "only_reference": int((m._merge == "right_only").sum()), "max_gap_pieces": float(gap)}
    print("[reproduce] " + json.dumps(out))
    if out["only_here"] or out["only_reference"] or not gap <= TOL_BACKTEST:
        sys.exit("stopping: the served side does not reproduce the stored as-served backtest; nothing written")
    return out


# --- cycle ------------------------------------------------------------------------------------------------------

def compute_cycle(url: str, cycle: str | None) -> tuple[pd.Timestamp, pd.DataFrame]:
    conn = psycopg2.connect(url)
    try:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION READ ONLY")
        if cycle is None:
            cur.execute("""SELECT MAX(fr.forecast_date) FROM forecast_result fr
                           JOIN product_dimension pd ON pd.product_key = fr.product_key WHERE pd.principal = 'unilever'""")
            cdate = pd.Timestamp(cur.fetchone()[0])
        else:
            cdate = pd.Timestamp(f"{cycle}-01")
        cur.execute("""SELECT fr.product_key, fr.status, fr.forecast_value, fr.model_params ? 'calendar_factor'
                       FROM forecast_result fr JOIN product_dimension pd ON pd.product_key = fr.product_key
                       WHERE fr.forecast_date = %s AND pd.principal = 'unilever' ORDER BY fr.product_key""", (cdate.date(),))
        fr = pd.DataFrame(cur.fetchall(), columns=["product_key", "status", "forecast_value", "calendar"])
        conn.rollback()
    finally:
        conn.close()
    if fr.empty:
        sys.exit(f"no Forecast_Result rows for {cdate:%Y-%m}")
    ok = fr[fr.status == "ok"]
    if ok.calendar.nunique() != 1:
        sys.exit("the cycle's 'ok' rows disagree on whether the calendar factor was applied")
    demand = read_demand(url)
    last = ym(cdate - pd.offsets.MonthBegin(1))
    wanted = set(int(k) for k in fr.product_key)
    series = {int(k): build_series(g, last) for k, g in demand.groupby("product_key") if int(k) in wanted}
    totals = company_totals(demand) if bool(ok.calendar.iloc[0]) else None
    fc = gm.GlobalForecaster(series)                    # the pool the run used: every product in its Forecast_Result
    rows, gaps = [], []
    for r in fr.itertuples():
        k = int(r.product_key)
        if r.status not in ("ok", "dead_sku"):
            continue
        s = series[k]
        dead = r.status == "dead_sku"
        p = pair(s, cdate, fc, totals, dead)
        if p is None:
            sys.exit(f"product {k}: the router has no forecast for a stored '{r.status}' row")
        if not dead:
            gaps.append(abs(round(p["served_value"], STORED_DECIMALS) - float(r.forecast_value)))
        p["served_value"] = float(r.forecast_value) if not dead else 0.0
        rows.append({"product_key": k, "month": ym(cdate), "cohort_period": last, **p})
    worst = max(gaps, default=0.0)
    print(f"[reproduce] route() for {cdate:%Y-%m} vs stored forecast_value on {len(gaps)} 'ok' rows: max gap {worst:.3g}")
    if worst > 10 ** -(STORED_DECIMALS + 2):
        sys.exit("stopping: the rerun does not reproduce Forecast_Result; nothing written")
    return cdate, pd.DataFrame(rows)


# --- write ------------------------------------------------------------------------------------------------------

def write(url: str, kind: str, df: pd.DataFrame) -> None:
    months = sorted(df.month.unique())
    code = code_version()
    conn = psycopg2.connect(url)
    try:
        cur = conn.cursor()
        cur.execute("SHOW default_transaction_read_only")
        if cur.fetchone()[0] != "off":
            sys.exit("default_transaction_read_only is on for this connection; refusing to write")
        cur.execute("""DELETE FROM forecast_challenger WHERE kind = %s AND challenger = %s
                       AND month BETWEEN %s AND %s""", (kind, CHALLENGER_ID, f"{months[0]}-01", f"{months[-1]}-01"))
        replaced = cur.rowcount
        execute_values(cur, """INSERT INTO forecast_challenger (product_key, month, kind, challenger, served_value,
                                   challenger_value, served_method, challenger_method, bin, dead_sku, calendar_factor,
                                   challenger_backup_reason, cohort_period, code_version) VALUES %s""",
                       [(int(r.product_key), f"{r.month}-01", kind, CHALLENGER_ID, round(float(r.served_value), 4),
                         round(float(r.challenger_value), 4), r.served_method, r.challenger_method, r.bin, bool(r.dead_sku),
                         round(float(r.calendar_factor), 6), r.challenger_backup_reason, r.cohort_period, code)
                        for r in df.itertuples()], page_size=1000)
        cur.execute("SELECT COUNT(*) FROM forecast_challenger WHERE kind = %s AND challenger = %s AND month BETWEEN %s AND %s",
                    (kind, CHALLENGER_ID, f"{months[0]}-01", f"{months[-1]}-01"))
        got = cur.fetchone()[0]
        if got != len(df):
            conn.rollback()
            sys.exit(f"rolled back: expected {len(df)} rows, the table holds {got}")
        conn.commit()
    finally:
        conn.close()
    print(f"[write] forecast_challenger {kind}: {len(df)} rows for {months[0]}..{months[-1]} (replaced {replaced}), code {code}")


# --- compare ----------------------------------------------------------------------------------------------------

def read_pairs(url: str) -> pd.DataFrame:
    conn = psycopg2.connect(url)
    try:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute("""SELECT DISTINCT ON (product_key, month) product_key, to_char(month, 'YYYY-MM'), kind,
                              served_value, challenger_value, bin
                       FROM forecast_challenger WHERE challenger = %s
                       ORDER BY product_key, month, (kind = 'cycle') DESC""", (CHALLENGER_ID,))
        df = pd.DataFrame(cur.fetchall(), columns=["product_key", "month", "kind", "served", "challenger", "bin"])
        conn.rollback()
    finally:
        conn.close()
    return df.astype({"served": float, "challenger": float})


def attach_actuals(pairs: pd.DataFrame, demand: pd.DataFrame) -> pd.DataFrame:
    series = all_series(demand)
    def actual(r):
        s = series.get(int(r.product_key))
        t = pd.Timestamp(f"{r.month}-01")
        return float(s.loc[t]) if s is not None and t in s.index else np.nan
    return pairs.assign(actual=pairs.apply(actual, axis=1))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=("backtest", "cycle", "compare"))
    ap.add_argument("--cycle", help="YYYY-MM (cycle mode); default the latest Unilever forecast_date")
    ap.add_argument("--turn", type=int, help="compare: the closing year of the Dec/Jan turn (e.g. 2024 = the 2024/2025 turn)")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--target-public", action="store_true", help="explicit-only: allow --write on a non-throwaway database")
    args = ap.parse_args()
    url = db_url()
    if args.write and not is_throwaway(url) and not args.target_public:
        sys.exit("--write on a database other than the throwaway 127.0.0.1:55432 needs --target-public")

    if args.mode == "backtest":
        bt = compute_backtest(url)
        check_backtest(url, bt)
        print(json.dumps({"rows": len(bt), "products": int(bt.product_key.nunique()),
                          "challenger_methods": bt.challenger_method.value_counts().to_dict(),
                          "challenger_backups": int(bt.challenger_backup_reason.notna().sum())}, default=str))
        if args.write:
            write(url, "backtest", bt)
    elif args.mode == "cycle":
        cdate, df = compute_cycle(url, args.cycle)
        print(json.dumps({"cycle": f"{cdate:%Y-%m}", "rows": len(df),
                          "served_total": round(float(df.served_value.sum()), 2),
                          "challenger_total": round(float(df.challenger_value.sum()), 2),
                          "challenger_backups": int(df.challenger_backup_reason.notna().sum()),
                          "challenger_methods": df.challenger_method.value_counts().to_dict()}))
        if args.write:
            write(url, "cycle", df)
    else:
        if args.turn is None:
            sys.exit("compare needs --turn YEAR")
        rows = attach_actuals(read_pairs(url), read_demand(url))
        print(json.dumps(selection_rule.decide(rows, args.turn), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
