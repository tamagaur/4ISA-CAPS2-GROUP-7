"""
scripts/backtest_forecast_run.py — regenerate the 29-month forecast backtest and keep it in
the forecast history (mart.forecast_run, migration 0041) as forecast_source
'backtest_recreated', so the accuracy mart can score months the stored forecast_result
(next month only) never covered.

    python -m scripts.backtest_forecast_run                          # compute + verify, write nothing
    python -m scripts.backtest_forecast_run --write --mart-schema ssm_mart_rehearsal
    python -m scripts.backtest_forecast_run --write --mart-schema mart --target-public

WHAT IT RUNS. The production path, exactly as the 2026-10-03 reports did: real Unilever demand
read the way the forecast runner reads it (scripts/run_baseline_forecast.fetch_demand: the
_Real view, a blank quantity summed as 0), the runner's build_series, and for every product x
test month the router (analytics/forecasting/router.route) on the history before that month,
the bin re-worked every month (kelvin/forecast-error-business b4f6b77, run_followups.py
long_window; kelvin/model-audit 36a5548, common.backtest). Window 2023-10..2026-02. A month
is scored when it is in the product's series after its first month and the router serves a
model (an 'insufficient' month is dropped).

TWO COHORTS, two runs:
  at_the_time  Tier A the month before each test month (ABC 'single'), XGBoost trained on that
               month's Tier A only: no look-ahead. The figure to quote (decision 2026-10-03,
               kelvin/model-audit): 337 products, 3,503 product-months.
  tier_a_2026_02  the fixed 107 products of the first report (Tier A as of 2026-02 and scored
               on 2025-09..2026-02; config/forecast_cohorts/tier_a_2026-02_scored_107.csv, copied
               from kelvin/model-audit cohort_107.csv), XGBoost trained on Tier A as of 2026-02.
               Survivor cohort: kept so its 26.9% can be reproduced and labelled, never quoted alone.

VERIFIED BEFORE ANY WRITE. Each run's rows are compared with the report's own rows when its
git-ignored output is on this machine (--reference-dir), and its headline metrics, recomputed
with the report's rules (kelvin/model-audit headline_pesos.py), with the committed
headline_two_cohorts.csv. A mismatch stops the script: nothing is written.

Writes (--write) go to <mart-schema>.forecast_run / forecast_run_value in one transaction,
then the marts are refreshed. Re-running replaces a run with the same label (--replace).
"""
from __future__ import annotations

import argparse
import getpass
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import analytics.forecasting.global_model as gm  # noqa: E402
from analytics.forecasting.diagnostic_metrics import wape  # noqa: E402
from analytics.forecasting.router import route  # noqa: E402
from analytics.marts import refresh_marts_cursor, vacuum_marts  # noqa: E402
from scripts.run_baseline_forecast import build_series, fetch_demand  # noqa: E402

WINDOW = list(pd.date_range("2023-10-01", "2026-02-01", freq="MS"))
COHORT_107 = REPO / "config" / "forecast_cohorts" / "tier_a_2026-02_scored_107.csv"
HEADLINE_REF = "kelvin/model-audit:reports/diagnostics/model_audit_2026-10-03/headline_two_cohorts.csv"
REF_AT_THE_TIME = "C:/Users/kyuan/dsd-model-audit/reports/diagnostics/model_audit_2026-10-03/local/asof_cohort_backtest.csv"
REF_107 = ("C:/Users/kyuan/dsd-forecast-error-business/reports/diagnostics/forecast_error_business_2026-10-03/"
           "local/longwindow_per_product_month.csv")
TOL_EXACT = 1e-9   # same machine, same code: a regenerated forecast must equal the reference
TOL_CSV = 1e-4     # the first report's CSV carries 4 decimals

RUNS = {
    "at_the_time": {
        "label": "backtest 2023-10..2026-02, Tier A the month before each month",
        "cohort": "Tier A (ABC single) as of the month before each test month; XGBoost pool the same",
        "headline_column": "at-the-time cohort (Tier A the month before each test month)",
        "reference": REF_AT_THE_TIME, "ref_value": "value", "tol": TOL_EXACT,
    },
    "tier_a_2026_02": {
        "label": "backtest 2023-10..2026-02, Tier A as of 2026-02 (107, survivor cohort)",
        "cohort": "the 107 products Tier A as of 2026-02 and scored 2025-09..2026-02; XGBoost pool Tier A as of 2026-02",
        "headline_column": "today's Tier A (Tier A as of 2026-02, the ~27% figure)",
        "reference": REF_107, "ref_value": "forecast", "tol": TOL_CSV,
    },
}


def ym(ts) -> str:
    return pd.Timestamp(ts).strftime("%Y-%m")


def read_inputs(db_url: str):
    """Real demand (as the runner reads it), each product's pesos and raw pieces (for the
    report's price rule), and Tier A by ABC period. One read-only transaction."""
    conn = psycopg2.connect(db_url)
    try:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION READ ONLY")
        demand = fetch_demand(cur)
        cur.execute("""
            SELECT product_key, calendar_month, SUM(net_amount), SUM(quantity_sold)
            FROM Unilever_SKU_Demand_Fact_Real GROUP BY product_key, calendar_month
        """)
        money = pd.DataFrame(cur.fetchall(), columns=["product_key", "month", "net_amount", "quantity_raw"])
        cur.execute("""
            SELECT product_key, classification_period FROM abc_classification
            WHERE principal = 'unilever' AND method = 'single' AND tier = 'A'
        """)
        tier_a = pd.DataFrame(cur.fetchall(), columns=["product_key", "period"])
        conn.rollback()
    finally:
        conn.close()
    money["net_amount"] = pd.to_numeric(money.net_amount, errors="coerce").astype(float)
    money["quantity_raw"] = pd.to_numeric(money.quantity_raw, errors="coerce").astype(float)
    series = {int(k): build_series(g) for k, g in demand.groupby("product_key")}
    tier_by = {p: set(g.product_key.astype(int)) for p, g in tier_a.groupby("period")}
    return series, money, tier_by


def backtest(series: dict, products, months, forecaster) -> list[dict]:
    """route() per product x month, as kelvin/model-audit common.backtest."""
    rows = []
    for k in products:
        s = series[k]
        for m in months:
            if m not in s.index or not m > s.index[0]:
                continue
            r = route(s, m, forecaster)
            if r["value"] is None:
                continue
            rows.append({"product_key": k, "month": ym(m), "actual": float(s.loc[m]), "value": float(r["value"]),
                         "bin": r["bin"], "method": r["method"], "ma3": max(0.0, float(r["ma3_value"])),
                         "backup_fired": bool(r["backup_fired"])})
    return rows


def run_at_the_time(series, tier_by) -> pd.DataFrame:
    """Per test month T: the products Tier A at T-1, XGBoost trained on those products'
    rows before T (pool dict in ascending key order, the order the audit's feature table had)."""
    rows = []
    for t in WINDOW:
        keys = sorted(k for k in tier_by.get(ym(t - pd.offsets.MonthBegin(1)), set()) if k in series)
        fc = gm.GlobalForecaster({k: series[k] for k in keys})
        rows += backtest(series, keys, [t], fc)
    return pd.DataFrame(rows)


def run_tier_a_2026_02(series, tier_by) -> pd.DataFrame:
    cohort = sorted(pd.read_csv(COHORT_107).product_key.astype(int))
    pool_keys = sorted(k for k in tier_by.get("2026-02", set()) if k in series)
    fc = gm.GlobalForecaster({k: series[k] for k in pool_keys})
    return pd.DataFrame(backtest({k: series[k] for k in cohort}, cohort, WINDOW, fc))


def headline(bt: pd.DataFrame, money: pd.DataFrame) -> dict:
    """kelvin/model-audit headline_pesos.metrics, the report's rules (blank quantity = 0 in
    the actual; price = SUM(net_amount) / SUM(quantity) over the product's scored months)."""
    test = bt[["product_key", "month"]].merge(money, on=["product_key", "month"], how="left")
    g = test.groupby("product_key")[["quantity_raw", "net_amount"]].sum()
    px = (g.net_amount / g.quantity_raw).where((g.quantity_raw > 0) & (g.net_amount > 0))
    m = bt.assign(price=bt.product_key.map(px), forecast=bt.value)
    m["error"] = m.forecast - m.actual
    priced = m[m.price.notna()]
    tot = priced.assign(a_p=priced.actual * priced.price, f_p=priced.forecast * priced.price,
                        abs_p=priced.error.abs() * priced.price,
                        sur_p=priced.error.clip(lower=0) * priced.price).groupby("month")[["a_p", "f_p", "abs_p", "sur_p"]].sum()
    per = m.groupby("product_key").apply(lambda x: pd.Series({"w": wape(x.actual, x.forecast), "w3": wape(x.actual, x.ma3)}),
                                         include_groups=False)
    a = m.actual.abs().sum()
    return {
        "products": int(m.product_key.nunique()), "product_months": int(len(m)),
        "median_product_wape_served": float(per.w.median()), "median_product_wape_ma3": float(per.w3.median()),
        "pooled_wape_pcs_served": float(m.error.abs().sum() / a),
        "total_wape_pesos_served": wape(tot.a_p, tot.f_p),
        "surplus_share_of_miss_pesos": float(tot.sur_p.sum() / tot.abs_p.sum()),
    }


def reference_headline(column: str) -> dict | None:
    try:
        out = subprocess.run(["git", "-C", str(REPO), "show", HEADLINE_REF], capture_output=True, text=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    ref = pd.read_csv(io.StringIO(out.stdout)).set_index("measure")[column]
    return {k: float(v) for k, v in ref.items()}


def verify(name: str, spec: dict, bt: pd.DataFrame, money: pd.DataFrame) -> dict:
    """Row-level check against the report's own output (when present) and headline check
    against the committed table. Raises SystemExit on any mismatch."""
    result = {"rows": len(bt), "products": int(bt.product_key.nunique())}
    ref_path = spec["reference"]
    if os.path.exists(ref_path):
        ref = (pd.read_csv(ref_path, dtype={"month": str})[["product_key", "month", spec["ref_value"]]]
               .rename(columns={spec["ref_value"]: "reference_forecast"}))
        j = bt.merge(ref, on=["product_key", "month"], how="outer", indicator=True)
        only = j._merge.value_counts().to_dict()
        diff = float((j.value - j.reference_forecast).abs().max())
        result["reference_rows"] = len(ref)
        result["reference_only_rows"] = int(only.get("right_only", 0))
        result["regenerated_only_rows"] = int(only.get("left_only", 0))
        result["max_abs_forecast_diff"] = diff
        if only.get("right_only", 0) or only.get("left_only", 0) or not diff <= spec["tol"]:
            raise SystemExit(f"[{name}] regenerated rows do not match the reference: {result}")
    else:
        result["reference_rows"] = "not on this machine"
    ref_head = reference_headline(spec["headline_column"])
    got = headline(bt, money)
    result["headline"] = got
    if ref_head is not None:
        bad = {k: (v, ref_head[k]) for k, v in got.items() if k in ref_head and abs(v - ref_head[k]) > 1e-6}
        result["headline_matches_committed"] = not bad
        if bad:
            raise SystemExit(f"[{name}] headline differs from {HEADLINE_REF}: {bad}")
    else:
        result["headline_matches_committed"] = "reference not reachable"
    return result


def write(db_url: str, mart: str, runs: dict, replace: bool) -> None:
    code_version = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    conn = psycopg2.connect(db_url)
    try:
        cur = conn.cursor()
        cur.execute("SHOW default_transaction_read_only")
        if cur.fetchone()[0] != "off":
            raise SystemExit("default_transaction_read_only is on for this connection; refusing to write")
        for name, (spec, bt, check) in runs.items():
            cur.execute(f"SELECT run_id FROM {mart}.forecast_run WHERE label = %s", (spec["label"],))
            existing = cur.fetchone()
            if existing and not replace:
                raise SystemExit(f"run {spec['label']!r} already exists (run_id {existing[0]}); pass --replace")
            if existing:
                cur.execute(f"DELETE FROM {mart}.forecast_run WHERE run_id = %s", (existing[0],))
            cur.execute(
                f"""INSERT INTO {mart}.forecast_run (kind, label, cohort, window_start, window_end, code_version, created_by, notes)
                    VALUES ('backtest_recreated', %s, %s, %s, %s, %s, %s, %s) RETURNING run_id""",
                (spec["label"], spec["cohort"], ym(WINDOW[0]), ym(WINDOW[-1]), code_version, getpass.getuser(),
                 json.dumps({"variant": name, "script": "scripts/backtest_forecast_run.py", "verification": check},
                            default=str)),
            )
            run_id = cur.fetchone()[0]
            execute_values(cur, f"""
                INSERT INTO {mart}.forecast_run_value (run_id, product_key, month, forecast_pieces, status, method, bin,
                                                      ma3_pieces, backup_fired) VALUES %s""",
                [(run_id, int(r.product_key), r.month, float(r.value), "ok", r.method, r.bin, float(r.ma3),
                  bool(r.backup_fired)) for r in bt.itertuples()], page_size=1000)
            print(f"[write] {mart}.forecast_run {run_id}: {spec['label']} ({len(bt)} rows)")
        refresh_marts_cursor(cur, "backtest_forecast_run", schema="public", mart_schema=mart)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
    vacuum_marts(db_url, mart)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--write", action="store_true", help="write the verified runs (default: compute and verify only)")
    p.add_argument("--mart-schema", default="mart", help="'mart' (live, needs --target-public) or a scratch ssm_* schema")
    p.add_argument("--target-public", action="store_true", help="explicit-only: allow writing the live mart schema")
    p.add_argument("--replace", action="store_true", help="replace runs with the same label")
    p.add_argument("--only", choices=sorted(RUNS), help="run one cohort only")
    args = p.parse_args()
    if args.write and args.mart_schema == "mart" and not args.target_public:
        p.error("writing the live mart schema needs --target-public")
    if args.mart_schema != "mart" and not args.mart_schema.startswith("ssm_"):
        p.error("--mart-schema is 'mart' or a scratch schema named ssm_*")
    from analytics.config import get_settings
    db_url = get_settings().supabase_db_url

    t0 = time.time()
    series, money, tier_by = read_inputs(db_url)
    print(f"[inputs] {len(series)} real Unilever products, Tier A periods {min(tier_by)}..{max(tier_by)} ({time.time() - t0:.1f}s)")
    builders = {"at_the_time": run_at_the_time, "tier_a_2026_02": run_tier_a_2026_02}
    runs = {}
    for name, spec in RUNS.items():
        if args.only and name != args.only:
            continue
        t0 = time.time()
        bt = builders[name](series, tier_by)
        check = verify(name, spec, bt, money)
        print(f"[{name}] {check['rows']} rows, {check['products']} products in {time.time() - t0:.0f}s; "
              f"reference: {check.get('reference_rows')} rows, max |diff| {check.get('max_abs_forecast_diff')}; "
              f"headline matches committed: {check['headline_matches_committed']}")
        print(f"    {json.dumps({k: round(v, 6) if isinstance(v, float) else v for k, v in check['headline'].items()})}")
        runs[name] = (spec, bt, check)
    if args.write:
        write(db_url, args.mart_schema, runs, args.replace)
    else:
        print("[dry] verified; nothing written (pass --write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
