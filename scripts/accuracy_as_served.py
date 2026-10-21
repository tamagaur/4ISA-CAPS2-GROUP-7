"""
scripts/accuracy_as_served.py — the headline forecast accuracy, recomputed from the CURRENT code, scored the
way the live forecast is served. Writes docs/ACCURACY_AS_SERVED.md (aggregates only) and, git-ignored,
local/accuracy_as_served_rows.csv (per product x month: rule 9, no per-product sales in git).

    python -m scripts.accuracy_as_served                 # compute, print, write nothing
    python -m scripts.accuracy_as_served --write         # also write the doc and the local rows

HOW THIS DIFFERS FROM THE STORED RUNS (mart.forecast_run 5 and 7, scripts/backtest_forecast_run.py):
  1. The series runs to the latest demand month for every product (run_baseline_forecast.build_series
     end_month), as the live runner builds it. A product that stopped selling keeps its trailing months
     as real zero-sale months, and those months ARE scored. The stored runs, and the accuracy mart that
     scores them against sales rows, never scored a month in which a product had no row.
  2. The dead-SKU rule is applied as the live forecast applies it: a product with at least 6 months of
     history and no positive sale in the 6 calendar months before the target is served 0
     (status dead_sku, zero_no_order); returns and blank months are not sales (c0b2727).
  3. A net-negative month enters the series as 0 (c0b2727): the history every model reads AND the actual
     a forecast is scored against. A blank-quantity month is unknown and is not scored (nothing to score
     it against). The sensitivity row scores against raw net quantities instead.
  Everything else is the stored run's protocol: Tier A the month before each test month on the current
  basis (analytics.params.abc_method), XGBoost pool the same, router.route() on the history before the
  month, window 2023-10..2026-02, a product-month dropped when the router has no model for it
  (fewer than 3 sales months: the live forecast serves a provisional average there, not a forecast).
  The calendar run multiplies by the company calendar factor from calendar.company_totals(demand), the
  call the live runner makes, not the series-based totals the stored run 7 used.
"""
from __future__ import annotations

import argparse
import datetime
import getpass
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import analytics.forecasting.global_model as gm  # noqa: E402
from analytics.classification.fsn import no_sale_in_last_months  # noqa: E402
from analytics.forecasting.calendar import company_totals  # noqa: E402
from analytics.forecasting.router import route  # noqa: E402
from analytics.params import DEAD_SKU_MONTHS, abc_method  # noqa: E402
from psycopg2.extras import execute_values  # noqa: E402
from scripts.backtest_forecast_run import WINDOW, headline, read_tier_a, ym  # noqa: E402
from scripts.run_baseline_forecast import build_series, fetch_demand  # noqa: E402

CODE_PATHS = ["analytics", "scripts/run_baseline_forecast.py", "scripts/backtest_forecast_run.py",
              "scripts/accuracy_as_served.py"]


def read_inputs(db_url: str):
    """Demand frame (as the runner reads it), the latest demand month, and each product-month's pesos and raw
    pieces (the report's price rule). One read-only transaction."""
    conn = psycopg2.connect(db_url)
    try:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION READ ONLY")
        demand = fetch_demand(cur)
        cur.execute("SELECT MAX(calendar_month) FROM Unilever_SKU_Demand_Fact_Real")
        latest = cur.fetchone()[0]
        cur.execute("""SELECT product_key, calendar_month, SUM(net_amount), SUM(quantity_sold)
                       FROM Unilever_SKU_Demand_Fact_Real GROUP BY product_key, calendar_month""")
        money = pd.DataFrame(cur.fetchall(), columns=["product_key", "month", "net_amount", "quantity_raw"])
        conn.rollback()
    finally:
        conn.close()
    money["net_amount"] = pd.to_numeric(money.net_amount, errors="coerce").astype(float)
    money["quantity_raw"] = pd.to_numeric(money.quantity_raw, errors="coerce").astype(float)
    return demand, latest, money


def served_backtest(series: dict, tier_by: dict, calendar_totals=None, pool_by: dict | None = None) -> tuple[pd.DataFrame, dict]:
    """route() per product of the cohort `tier_by` x test month, then the live dead-SKU rule. Columns: value
    (as served), value_before_dead (the router's own number), dead (the rule fired), actual (floored series;
    NaN = blank, not scored). `pool_by` is the XGBoost pool by period; it defaults to the cohort itself (Tier A),
    and is Tier A for a Tier B or C cohort, as the live runner trains one global model on Tier A."""
    rows, skipped = [], {"insufficient": 0, "blank_actual": 0}
    pool_by = tier_by if pool_by is None else pool_by
    for t in WINDOW:
        prev_period = ym(t - pd.offsets.MonthBegin(1))
        keys = sorted(k for k in tier_by.get(prev_period, set()) if k in series)
        fc = gm.GlobalForecaster({k: series[k] for k in sorted(k for k in pool_by.get(prev_period, set()) if k in series)})
        prev = ym(t - pd.offsets.MonthBegin(1))
        for k in keys:
            s = series[k]
            if t not in s.index or not t > s.index[0]:
                continue
            try:
                r = route(s, t, fc, calendar_totals=calendar_totals)
            except ValueError:  # no history before the month at all
                skipped["no_history"] = skipped.get("no_history", 0) + 1
                continue
            if r["value"] is None:
                skipped["insufficient"] += 1
                continue
            hist = s[s.index < t]
            dead = len(hist) >= DEAD_SKU_MONTHS and no_sale_in_last_months(
                hist.index.strftime("%Y-%m"), hist.to_numpy(dtype=float), prev)
            actual = float(s.loc[t])
            if np.isnan(actual):
                skipped["blank_actual"] += 1
                continue
            rows.append({"product_key": k, "month": ym(t), "actual": actual,
                         "value": 0.0 if dead else float(r["value"]), "value_before_dead": float(r["value"]),
                         "dead": bool(dead), "bin": r["bin"], "method": "zero_no_order" if dead else r["method"],
                         "ma3": max(0.0, float(r["ma3_value"])), "backup_fired": bool(r["backup_fired"])})
    return pd.DataFrame(rows), skipped


def metrics(bt: pd.DataFrame, money: pd.DataFrame, value: str = "value") -> dict:
    """backtest_forecast_run.headline() on `value`, plus the pieces-based surplus share and the count of
    products whose own WAPE is undefined (every scored actual 0)."""
    b = bt.assign(value=bt[value])
    h = headline(b, money)
    err = b.value - b.actual
    h["surplus_share_of_miss_pieces"] = float(err.clip(lower=0).sum() / err.abs().sum())
    h["products_wape_undefined"] = int((b.groupby("product_key").actual.apply(lambda a: a.abs().sum()) == 0).sum())
    h["zero_actual_product_months"] = int((b.actual == 0).sum())
    return h


def stored_run_headline(db_url: str, run_id: int, money: pd.DataFrame) -> dict:
    """A stored run (mart.forecast_run_value) scored the way the accuracy mart scores it: against the sales
    rows that exist, raw net quantity, a month with no row not scored."""
    conn = psycopg2.connect(db_url)
    try:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute("SELECT product_key, month, forecast_pieces, ma3_pieces FROM mart.forecast_run_value WHERE run_id = %s",
                    (run_id,))
        v = pd.DataFrame(cur.fetchall(), columns=["product_key", "month", "value", "ma3"]).astype({"value": float, "ma3": float})
        cur.execute("SELECT code_version FROM mart.forecast_run WHERE run_id = %s", (run_id,))
        code = cur.fetchone()[0]
        conn.rollback()
    finally:
        conn.close()
    m = v.merge(money[["product_key", "month", "quantity_raw"]], on=["product_key", "month"], how="left")
    m = m.rename(columns={"quantity_raw": "actual"}).dropna(subset=["actual"])
    return {**headline(m, money), "code_version": code, "rows_in_run": len(v)}


def with_raw_actual(bt: pd.DataFrame, money: pd.DataFrame) -> pd.DataFrame:
    """Same forecasts, scored against raw net quantity (a net-negative month stays negative; no row = 0)."""
    m = bt.drop(columns="actual").merge(money[["product_key", "month", "quantity_raw"]], on=["product_key", "month"], how="left")
    present = bt[["product_key", "month"]].merge(money[["product_key", "month"]].assign(_p=True), how="left",
                                                 on=["product_key", "month"])._p.notna().to_numpy()
    m["actual"] = np.where(present, m.quantity_raw, 0.0)
    return m.drop(columns="quantity_raw").dropna(subset=["actual"])


def code_version() -> dict:
    head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--", *CODE_PATHS],
                           capture_output=True, text=True).stdout.strip().splitlines()
    return {"head": head, "dirty_code_paths": [d for d in dirty if "accuracy_as_served" not in d]}


def pct(x: float) -> str:
    return f"{100 * x:.2f}%"


def render(res: dict, ver: dict, today: str) -> str:
    def row(label, h):
        return (f"| {label} | {pct(h['median_product_wape_served'])} | {pct(h['pooled_wape_pcs_served'])} | "
                f"{pct(h['total_wape_pesos_served'])} | {pct(h['surplus_share_of_miss_pesos'])} | "
                f"{pct(h['surplus_share_of_miss_pieces'])} | {h['products']} | {h['product_months']:,} |")
    head = "| Run | Median product WAPE | Pooled WAPE (pieces) | Total WAPE (pesos) | Surplus share of miss (pesos) | Surplus share of miss (pieces) | Products | Product-months |\n|---|---|---|---|---|---|---|---|"
    a, c = res["as_served"], res["as_served_calendar"]
    s5, s7 = res["stored5"], res["stored7"]
    lines = [
        "# Forecast accuracy, as served",
        "",
        f"Computed {today} from code version `{ver['head']}`"
        + (f" (uncommitted changes in: {', '.join(ver['dirty_code_paths'])})" if ver["dirty_code_paths"] else " (no uncommitted change in the forecasting code)")
        + f" by `scripts/accuracy_as_served.py`. Quote the **as served** rows, and quote them together with this version.",
        "",
        f"Window {ym(WINDOW[0])} to {ym(WINDOW[-1])}, Unilever Tier A the month before each test month "
        f"(basis `{abc_method('unilever')}`), one month ahead, the router as the live forecast runs it. Latest demand month: {res['latest']}.",
        "",
        "## Headline (quote these)",
        "",
        head,
        row("**As served** (no calendar factor)", a),
        row("**As served, calendar-adjusted** (the run 7 equivalent)", c),
        "",
        "*As served* means: months after a product's last sale are scored (a forecast of 0 against 0 counts); "
        "the dead-SKU rule is applied as the live forecast applies it (6 months, positive sales only, returns and blanks are not sales); "
        "a net-negative month is 0 in both the history and the actual; a blank-quantity month is not scored. "
        "Total WAPE (pesos) is the WAPE of the monthly peso totals over products with a price; surplus share of miss is "
        "(over-forecast miss) / (total miss), in the unit named. Median product WAPE is over products whose scored actuals are not all 0 "
        f"({a['products_wape_undefined']} of {a['products']} products have an undefined WAPE in the plain run, "
        f"{c['products_wape_undefined']} in the calendar run).",
        "",
        "## What the old figure was, and why it moved",
        "",
        head,
        row(f"Stored run 5 (`{s5['code_version'][:8]}`), scored as the accuracy mart scores it", s5),
        row(f"Stored run 7 (`{s7['code_version'][:8]}`), calendar-adjusted, same scoring", s7),
        "",
        "Run 5 reproduces the 38.72% median quoted before. It predates c0b2727 (net-negative months as 0, positive-sales dead test) "
        "and it never scored a month with no sales row, and it applies no dead-SKU rule. It is not a replay of today's serving code.",
        "",
        "Where the as-served number comes from, step by step on the same product-months (plain run):",
        "",
        head,
        row("As served, **dead rule off** (router's own number)", res["no_dead"]),
        row("As served (dead rule on)", a),
        row("Sensitivity: as served, scored against **raw net quantity** (returns stay negative)", res["raw_actual"]),
        row("Sensitivity: as served, **calendar-adjusted**, raw net quantity", res["raw_actual_cal"]),
        "",
        f"The dead-SKU rule fired on {res['dead_n']:,} of {a['product_months']:,} scored product-months (plain run) "
        f"and {res['dead_n_cal']:,} in the calendar run. Product-months not scored: {res['skipped']['insufficient']:,} "
        f"with fewer than 3 sales months (the live forecast serves a provisional average, not a forecast), "
        f"{res['skipped']['blank_actual']} with a blank actual.",
        "",
        "## Limits of these numbers",
        "",
        "- The cohort changes every month (Tier A the month before), so the product count is for the whole window, not for Tier A as of 2026-02 (189 products).",
        f"- The MA3 benchmark on the same product-months has a median product WAPE of {pct(a['median_product_wape_ma3'])} "
        f"(served: plain {pct(a['median_product_wape_served'])}, calendar {pct(c['median_product_wape_served'])}); MA3 is never calendar-adjusted. "
        "The served models are not shown to beat MA3 here, and the calendar factor raises the median error on these months.",
        "- Dead-SKU rule: months-with-history gate and window are the live runner's (`DEAD_SKU_MONTHS` = " f"{DEAD_SKU_MONTHS}); this script does not change them.",
        "- The dashboard card reads these forecasts from `mart.accuracy_mart` (runs stored by `--write-run`), which scores each "
        "month against the sales mart's raw net quantity: a net-negative month stays negative there, where this document floors it "
        "to 0. Over the full window the card therefore equals the **raw net quantity** sensitivity row above, not the headline row "
        "(median, total WAPE in pesos and surplus share in pesos agree to the rounding shown; the card's pooled pieces WAPE divides by "
        "net actual pieces, not absolute, so it differs in the second decimal). A shorter date range on the card is a different window.",
        "- Per product-month rows are in the git-ignored `local/accuracy_as_served_rows.csv`.",
        "",
    ]
    return "\n".join(lines)


# The two stored runs the dashboard's forecast-error card can read, scored as served. NEW labels: the
# older runs (5, 7) stay as they are, selectable by run_id. The calendar one is the card's default
# (backend/marts.DEFAULT_BACKTEST_LABEL), since the live forecast is calendar-adjusted.
AS_SERVED_RUNS = {
    "as_served": ("as-served backtest 2023-10..2026-02, Tier A the month before each month",
                  "Tier A (current basis) the month before each test month; months after a product's last sale "
                  "scored; dead-SKU rule applied as the live forecast applies it"),
    "as_served_calendar": ("as-served backtest 2023-10..2026-02, Tier A the month before each month, calendar-adjusted",
                           "as above; served value x the company calendar factor"),
    # Tier B and C cohorts (the error decomposition, migration 0063, scores every tier). Calendar-adjusted only,
    # the form the live forecast is served in; XGBoost pool = Tier A, as the live runner trains it.
    "as_served_calendar_B": ("COUNTERFACTUAL (never served: the live runner forecasts Tier A only) - as-served backtest 2023-10..2026-02, Tier B the month before each month, calendar-adjusted",
                             "COUNTERFACTUAL, NOT SERVED - Tier B (current basis) the month before each test month; XGBoost pool Tier A; dead-SKU rule applied; "
                             "served value x the company calendar factor"),
    "as_served_calendar_C": ("COUNTERFACTUAL (never served: the live runner forecasts Tier A only) - as-served backtest 2023-10..2026-02, Tier C the month before each month, calendar-adjusted",
                             "COUNTERFACTUAL, NOT SERVED - Tier C (current basis) the month before each test month; XGBoost pool Tier A; dead-SKU rule applied; "
                             "served value x the company calendar factor"),
}


def read_tier_cohort(db_url: str, method: str, tier: str) -> dict[str, set[int]]:
    """Product_keys of one ABC tier by classification_period (read_tier_a, any tier). One read-only transaction."""
    conn = psycopg2.connect(db_url)
    try:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute("""SELECT product_key, classification_period FROM abc_classification
                       WHERE principal = 'unilever' AND method = %s AND tier = %s""", (method, tier))
        df = pd.DataFrame(cur.fetchall(), columns=["product_key", "period"])
        conn.rollback()
    finally:
        conn.close()
    return {p: set(g.product_key.astype(int)) for p, g in df.groupby("period")}


def write_runs(db_url: str, runs: dict[str, pd.DataFrame], checks: dict[str, dict]) -> dict[str, int]:
    """Insert each run as a NEW mart.forecast_run (+ forecast_run_value), then refresh the marts, one
    transaction. Refuses a label that already exists: nothing is replaced or deleted."""
    from analytics.marts import refresh_marts_cursor, vacuum_marts
    code = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    ids: dict[str, int] = {}
    conn = psycopg2.connect(db_url)
    try:
        cur = conn.cursor()
        cur.execute("SHOW default_transaction_read_only")
        if cur.fetchone()[0] != "off":
            raise SystemExit("default_transaction_read_only is on for this connection; refusing to write")
        for name, bt in runs.items():
            label, cohort = AS_SERVED_RUNS[name]
            cur.execute("SELECT run_id FROM mart.forecast_run WHERE label = %s", (label,))
            if cur.fetchone():
                raise SystemExit(f"run {label!r} already exists; this script never replaces a run")
            cur.execute("""INSERT INTO mart.forecast_run (kind, label, cohort, window_start, window_end, code_version, created_by, notes)
                           VALUES ('backtest_recreated', %s, %s, %s, %s, %s, %s, %s) RETURNING run_id""",
                        (label, cohort, ym(WINDOW[0]), ym(WINDOW[-1]), code, getpass.getuser(),
                         json.dumps({"variant": name, "script": "scripts/accuracy_as_served.py", "check": checks[name]}, default=str)))
            ids[name] = cur.fetchone()[0]
            execute_values(cur, """INSERT INTO mart.forecast_run_value (run_id, product_key, month, forecast_pieces, status, method, bin,
                                                                       ma3_pieces, backup_fired) VALUES %s""",
                           [(ids[name], int(r.product_key), r.month, float(r.value), "dead_sku" if r.dead else "ok", r.method, r.bin,
                             float(r.ma3), bool(r.backup_fired)) for r in bt.itertuples()], page_size=1000)
            print(f"[write] mart.forecast_run {ids[name]}: {label} ({len(bt)} rows)")
        refresh_marts_cursor(cur, "accuracy_as_served", schema="public")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
    vacuum_marts(db_url)
    return ids


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help="write docs/ACCURACY_AS_SERVED.md and local/accuracy_as_served_rows.csv")
    ap.add_argument("--write-run", action="store_true",
                    help="also store both as-served backtests as NEW runs in mart.forecast_run on the live database and "
                         "refresh the marts (back up first, hard rule 8; needs --target-public)")
    ap.add_argument("--write-tier-runs", action="store_true",
                    help="store the calendar-adjusted as-served backtest of Tier B and Tier C as NEW runs (the error "
                         "decomposition scores every tier); computes only those two, then refreshes the marts (back up first; "
                         "needs --target-public)")
    ap.add_argument("--target-public", action="store_true", help="explicit-only: allow --write-run / --write-tier-runs to write the live mart schema")
    args = ap.parse_args()
    from analytics.config import long_read_db_url
    db_url = long_read_db_url()
    t0 = time.time()
    demand, latest, money = read_inputs(db_url)
    assert latest == ym(WINDOW[-1]), f"latest demand month {latest} is not the window end {ym(WINDOW[-1])}"
    series = {int(k): build_series(g, latest) for k, g in demand.groupby("product_key")}
    tier_by = read_tier_a(db_url, abc_method("unilever"))
    print(f"[inputs] {len(series)} products, latest demand month {latest} ({time.time() - t0:.0f}s)")

    if args.write_tier_runs:
        if not args.target_public:
            ap.error("--write-tier-runs writes the live mart schema and needs --target-public")
        cal = company_totals(demand)
        runs, checks = {}, {}
        for tier in ("B", "C"):
            cohort = read_tier_cohort(db_url, abc_method("unilever"), tier)
            btt, sk = served_backtest(series, cohort, calendar_totals=cal, pool_by=tier_by)
            name = f"as_served_calendar_{tier}"
            runs[name] = btt
            checks[name] = {"rows": len(btt), "products": int(btt.product_key.nunique()), "skipped": sk}
            print(f"[as served, calendar, Tier {tier}] {len(btt)} rows, {btt.product_key.nunique()} products, skipped {sk} "
                  f"({time.time() - t0:.0f}s)")
        print(f"[write-tier-runs] run ids {write_runs(db_url, runs, checks)}")
        return 0

    bt, skipped = served_backtest(series, tier_by)
    print(f"[as served] {len(bt)} rows in {time.time() - t0:.0f}s")
    btc, skipped_c = served_backtest(series, tier_by, calendar_totals=company_totals(demand))
    print(f"[as served, calendar] {len(btc)} rows in {time.time() - t0:.0f}s")

    res = {
        "latest": latest, "skipped": skipped,
        "as_served": metrics(bt, money), "as_served_calendar": metrics(btc, money),
        "no_dead": metrics(bt, money, "value_before_dead"),
        "raw_actual": metrics(with_raw_actual(bt, money), money),
        "raw_actual_cal": metrics(with_raw_actual(btc, money), money),
        "stored5": {**stored_run_headline(db_url, 5, money), "surplus_share_of_miss_pieces": float("nan")},
        "stored7": {**stored_run_headline(db_url, 7, money), "surplus_share_of_miss_pieces": float("nan")},
        "dead_n": int(bt.dead.sum()), "dead_n_cal": int(btc.dead.sum()),
    }
    # the stored runs' pieces-based surplus share, on the same rows their headline used
    for key, rid in (("stored5", 5), ("stored7", 7)):
        conn = psycopg2.connect(db_url)
        try:
            cur = conn.cursor()
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute("SELECT product_key, month, forecast_pieces FROM mart.forecast_run_value WHERE run_id = %s", (rid,))
            v = pd.DataFrame(cur.fetchall(), columns=["product_key", "month", "value"]).astype({"value": float})
            conn.rollback()
        finally:
            conn.close()
        m = v.merge(money[["product_key", "month", "quantity_raw"]], on=["product_key", "month"], how="left").dropna(subset=["quantity_raw"])
        e = m.value - m.quantity_raw
        res[key]["surplus_share_of_miss_pieces"] = float(e.clip(lower=0).sum() / e.abs().sum())
    if args.write_run:
        if not args.target_public:
            ap.error("--write-run writes the live mart schema and needs --target-public")
        checks = {"as_served": {k: v for k, v in res["as_served"].items()}, "as_served_calendar": {k: v for k, v in res["as_served_calendar"].items()}}
        ids = write_runs(db_url, {"as_served": bt, "as_served_calendar": btc}, checks)
        print(f"[write-run] run ids {ids}")
    ver = code_version()
    today = datetime.date.today().isoformat()
    doc = render(res, ver, today)
    print(doc)
    if args.write:
        (REPO / "docs").mkdir(exist_ok=True)
        (REPO / "docs" / "ACCURACY_AS_SERVED.md").write_text(doc, encoding="utf-8")
        (REPO / "local").mkdir(exist_ok=True)
        pd.concat([bt.assign(run="as_served"), btc.assign(run="as_served_calendar")]).to_csv(
            REPO / "local" / "accuracy_as_served_rows.csv", index=False)
        print("[write] docs/ACCURACY_AS_SERVED.md, local/accuracy_as_served_rows.csv")
    print(f"[done] {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
