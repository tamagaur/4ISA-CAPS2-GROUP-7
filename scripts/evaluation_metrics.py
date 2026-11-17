"""
scripts/evaluation_metrics.py - the six forecast-evaluation metrics, pinned and checked against live (2026-11-17).

THE ONE AUTHORITATIVE SET. MAE, RMSE, MAPE, WAPE, MASE and R², on one basis, for three populations over two windows, each
figure with the products and product-months it covers and its exact definition (DEFINITIONS, POPULATIONS, WINDOWS below).
Any other figure for one of these measures in this repository either equals a figure here or says which other population,
window, run or measure it is (docs/EVALUATION_METRICS_INVENTORY_2026-11-17.md lists them).

    python -m scripts.evaluation_metrics --print     # compute from live and print; writes nothing (read-only)
    python -m scripts.evaluation_metrics --write     # compute from live, write the pin (docs/EVALUATION_METRICS.json + .md)
    python -m scripts.evaluation_metrics --verify    # recompute from live and compare with the pin; any divergence FAILS

--verify (run by scripts/check.sh, --fast and --full, and by tests/invariants/test_j_evaluation_metrics.py) fails, never
notices, when: a live figure or count differs from the pinned one; a pinned figure has no live counterpart or the reverse; the
backtest run, the plan (cycle, LP run) or the definitions text differ from the pin; docs/EVALUATION_METRICS.md is not the
rendering of the JSON; the full-span WAPE over every scored product is not the published headline pooled WAPE
(docs/PUBLISHED_FIGURES_SNAPSHOT_2026-10-24.json, as_served_calendar: the same 4,370 rows, so the two pins must agree); or live
cannot be read (exit 3). Re-pinning (--write) is a decision, not a side effect: the manuscript must follow.

Read-only: one transaction, SET TRANSACTION READ ONLY first, rolled back (never a session-level SET on the :6543 pooler).
Only aggregates are committed (hard rule 9): no per-product row leaves the database.

R². The benchmark of month t is the product's mean sales over its months BEFORE t (an expanding mean): what a planner could have
known when the forecast was made. A benchmark of the mean of the scored months themselves (the "in-window" R², -0.03 in an
uncommitted recon of 2026-11-17) uses the months being forecast to judge the forecast, a hindsight benchmark. It is not computed
here, nor anywhere in this repository; tests/test_evaluation_metrics.py fails if the benchmark reads month t or later.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

PIN_DATE = "2026-11-17"
PIN_JSON = REPO / "docs" / "EVALUATION_METRICS.json"
PIN_MD = REPO / "docs" / "EVALUATION_METRICS.md"
PUBLISHED_JSON = REPO / "docs" / "PUBLISHED_FIGURES_SNAPSHOT_2026-10-24.json"
PRINCIPAL = "unilever"                      # backend/marts.ACCURACY_PRINCIPAL: the only principal with per-product forecasts
LIVE_TOLERANCE = 1e-7                       # relative and absolute; counts are compared exactly
R2_MIN_MONTHS = 3                           # a product's R² needs at least this many months with a benchmark

WINDOWS = {
    "card": {"start": "2025-03", "end": "2026-02",
             "label": "Mar 2025-Feb 2026, the error card's default range on 2026-11-17"},
    "full": {"start": "2024-01", "end": "2026-02",
             "label": "Jan 2024-Feb 2026, every month the backtest run scores"},
}
POPULATION_ORDER = ("forecastable", "order_plan", "all_scored")
POPULATIONS = {
    "forecastable": ("Products with a scored month in the window, at least one month with sales above 0, and no near-zero "
                     "month (sales above 0 but under 5% of the product's usual monthly level, accuracy_mart.avg_monthly_pieces, "
                     "the mean of the 12 months before; backend/marts.NEAR_ZERO_SHARE). The error card's MAPE population."),
    "order_plan": ("The forecastable products with a row in the current order plan (backend/lp_cycle.PLAN_STATUS_SQL, Unilever, "
                   "the latest cycle). The error card's planned-products line. Backtest errors on past months, not the plan's "
                   "quantities."),
    "all_scored": ("Every product with a scored month in the window, the near-zero products and those that sold nothing "
                   "there included. The error card's two WAPEs; over the full span, the published headline's 310 products."),
}
BASIS = ("mart.accuracy_mart, the run labelled backend/marts.DEFAULT_BACKTEST_LABEL (the error card's default backtest), "
         "Unilever products (product_dimension.principal), product-months with both a forecast and an actual. One basis for "
         "every metric: actual = max(net pieces sold, 0), a net-negative month counts as 0 sold (backend/marts.POOLED_WAPE_RULE). "
         "Every figure is in pieces or a ratio of pieces.")
DEFINITIONS = {
    "MAE": "mean over the population's product-months of |forecast - actual|, in pieces.",
    "RMSE": "square root of the mean over the population's product-months of (forecast - actual)^2, in pieces.",
    "WAPE": "sum over the population's product-months of |forecast - actual| / sum of actual (pooled; bigger sellers weigh more).",
    "MAPE": ("median over the population's products of each product's mean |forecast - actual| / actual over its months with "
             "actual > 0 (months with actual = 0 have no percentage and are left out; the product count is the products with "
             "at least one such month)."),
    "MASE": ("median over the population's products of (the product's MAE over its scored months in the window) / (the mean "
             "|change from one month to the next| of the product's own demand series over its months BEFORE the window: the "
             "in-sample error of repeating last month). Demand series: Unilever_SKU_Demand_Fact_Real by product and month from "
             "the first month with a known quantity, a month with no row is 0 sold (the Unilever rule), a blank capture is "
             "unknown and pairs with it are skipped, negative months count as 0. A product with no such pair before the window, "
             "or a scale of 0, has no MASE and is not counted. Below 1 = better than repeating last month. NOT the stored MASE "
             "of Forecast_Result (the plan's entry test: the served model's rolling one-step error over the holdout, the last "
             "20% of each product's history, on the latest forecast only; backend/routers/dashboard.ENTRY_TEST_MEASURE, "
             "docs/PUBLISHED_FIGURES_SNAPSHOT_2026-10-24.json 'mase')."),
    "R2": ("median over the population's products of 1 - sum (actual - forecast)^2 / sum (actual - benchmark)^2 over the "
           "product's scored months that have a benchmark, where the benchmark of month t is the mean of the product's demand "
           "series over every known month BEFORE t (an expanding mean, knowable when the forecast was made). Products with fewer "
           "than 3 such months, or a denominator of 0, have no R² and are not counted. Above 0 = the forecast beats the "
           "product's own past average. The mean of the scored months themselves is never the benchmark (hindsight)."),
}
CONTEXT = {
    "mean_actual_pieces": "mean actual pieces per product-month (MAE and RMSE read against this).",
    "MAPE_mean": "the mean instead of the median of the same per-product percentages.",
    "MASE_share_below_1": "share of the MASE products with MASE below 1.",
    "R2_share_above_0": "share of the R² products with R² above 0.",
}


# ------------------------------------------------------------------------------------------------------------------ compute
def demand_series(demand: pd.DataFrame, last: str) -> dict[int, pd.Series]:
    """product_key -> monthly pieces from its first known month to `last`; no row = 0 sold (Unilever), blank = NaN, net < 0 = 0.
    demand columns: product_key, month ('YYYY-MM'), qty (NaN when every row of that product-month is a blank capture)."""
    out = {}
    for pk, g in demand.groupby("product_key"):
        g = g.set_index("month")
        known = g[g.qty.notna()]
        if known.empty:
            continue
        idx = pd.period_range(known.index.min(), last, freq="M").strftime("%Y-%m")
        s = known.qty.astype(float).clip(lower=0).reindex(idx, fill_value=0.0)
        s[s.index.isin(g.index[g.qty.isna()])] = np.nan
        out[int(pk)] = s
    return out


def earlier_mean(s: pd.Series | None, month: str) -> float:
    """R²'s benchmark for `month`: the mean of the known months strictly before it. NaN when there is none."""
    if s is None:
        return np.nan
    h = s[s.index < month]
    return float(h.mean()) if h.notna().any() else np.nan


def naive_scale(s: pd.Series | None, before: str) -> float:
    """MASE's scale: mean |month-to-month change| over pairs of known months strictly before `before`. NaN when there is none."""
    if s is None:
        return np.nan
    d = np.abs(np.diff(s[s.index < before].values))
    d = d[~np.isnan(d)]
    return float(d.mean()) if len(d) else np.nan


def _median(x) -> float | None:
    x = list(x)
    return float(np.median(x)) if x else None


def cell(W: pd.DataFrame, keys: set, start: str, series: dict) -> dict:
    """The six metrics, their counts and the context figures on the window's rows W for the products `keys`."""
    X = W[W.product_key.isin(keys)].copy()
    e = X.f - X.a
    o = {"products": int(X.product_key.nunique()), "product_months": int(len(X)),
         "mean_actual_pieces": float(X.a.mean()) if len(X) else None,
         "MAE": float(np.mean(np.abs(e))) if len(X) else None,
         "RMSE": float(np.sqrt(np.mean(e ** 2))) if len(X) else None,
         "WAPE": float(np.sum(np.abs(e)) / np.sum(X.a)) if X.a.sum() > 0 else None}
    o["WAPE_products"], o["WAPE_product_months"] = o["products"], o["product_months"]
    o["MAE_products"] = o["RMSE_products"] = o["products"]
    o["MAE_product_months"] = o["RMSE_product_months"] = o["product_months"]
    pos = X[X.a > 0]
    ape = (np.abs(pos.f - pos.a) / pos.a).groupby(pos.product_key).mean()
    o["MAPE"], o["MAPE_mean"] = _median(ape), (float(ape.mean()) if len(ape) else None)
    o["MAPE_products"], o["MAPE_product_months"] = int(len(ape)), int(len(pos))
    mae_p = np.abs(e).groupby(X.product_key).mean()
    mase = {}
    for k, m in mae_p.items():
        sc = naive_scale(series.get(int(k)), start)
        if not math.isnan(sc) and sc > 0:
            mase[int(k)] = float(m) / sc
    o["MASE"] = _median(mase.values())
    o["MASE_share_below_1"] = float(np.mean([v < 1 for v in mase.values()])) if mase else None
    o["MASE_products"], o["MASE_product_months"] = len(mase), int(X.product_key.isin(list(mase)).sum())
    X["b"] = [earlier_mean(series.get(int(pk)), mo) for pk, mo in zip(X.product_key, X.month)]
    Y = X[X.b.notna()]
    r2, n_m = [], 0
    for _, g in Y.groupby("product_key"):
        if len(g) < R2_MIN_MONTHS:
            continue
        ssb = float(np.sum((g.a - g.b) ** 2))
        if ssb <= 0:
            continue
        r2.append(1 - float(np.sum((g.a - g.f) ** 2)) / ssb)
        n_m += len(g)
    o["R2"] = _median(r2)
    o["R2_share_above_0"] = float(np.mean([v > 0 for v in r2])) if r2 else None
    o["R2_products"], o["R2_product_months"] = len(r2), n_m
    return o


def populations(W: pd.DataFrame, plan_keys: set, near_zero_share: float) -> dict[str, set]:
    """The three populations of POPULATIONS on the window's rows W."""
    nz = (W.a_raw > 0) & (W.avg > 0) & (W.a_raw < near_zero_share * W.avg)
    per = pd.DataFrame({"nz": nz, "pos": W.a_raw > 0, "pk": W.product_key}).groupby("pk").sum()
    scored = set(int(k) for k in per.index)
    fc = set(int(k) for k in per[(per.nz == 0) & (per.pos > 0)].index)
    return {"forecastable": fc, "order_plan": fc & plan_keys, "all_scored": scored}


def compute(rows: pd.DataFrame, demand: pd.DataFrame, plan_keys: set, near_zero_share: float) -> dict:
    """rows: product_key, month, forecast_pieces, actual_pieces (raw net), avg_monthly_pieces. Returns {window: {population: cell}}."""
    R = rows.copy()
    R["product_key"] = R.product_key.astype(int)
    R["month"] = R.month.astype(str).str[:7]
    R["f"] = R.forecast_pieces.astype(float)
    R["a_raw"] = R.actual_pieces.astype(float)
    R["a"] = R.a_raw.clip(lower=0)
    R["avg"] = pd.to_numeric(R.avg_monthly_pieces, errors="coerce").astype(float)
    last = max(w["end"] for w in WINDOWS.values())
    series = demand_series(demand, last)
    out = {}
    for wn, w in WINDOWS.items():
        W = R[(R.month >= w["start"]) & (R.month <= w["end"])]
        pops = populations(W, {int(k) for k in plan_keys}, near_zero_share)
        out[wn] = {pn: cell(W, pops[pn], w["start"], series) for pn in POPULATION_ORDER}
    return out


# --------------------------------------------------------------------------------------------------------------------- live
def connect():
    import psycopg2
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")
    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
    cur = conn.cursor()
    cur.execute("BEGIN")
    cur.execute("SET TRANSACTION READ ONLY")      # transaction-scoped, never session-level
    return conn, cur


def read_live(cur) -> dict:
    """Everything compute() needs, plus the identity of what was read (run, plan, actuals version)."""
    from analytics import actuals_version
    from backend.lp_cycle import PLAN_STATUS_SQL
    from backend.marts import DEFAULT_BACKTEST_LABEL
    cur.execute("SELECT run_id, label FROM mart.forecast_run WHERE label = %s", (DEFAULT_BACKTEST_LABEL,))
    run = cur.fetchall()
    if len(run) != 1:
        raise RuntimeError(f"expected one mart.forecast_run labelled DEFAULT_BACKTEST_LABEL, found {len(run)}")
    run_id = int(run[0][0])
    cur.execute("""SELECT a.product_key, a.month, a.forecast_pieces, a.actual_pieces, a.avg_monthly_pieces
                   FROM mart.accuracy_mart a JOIN product_dimension pd ON pd.product_key = a.product_key
                   WHERE a.run_id = %s AND pd.principal = %s AND a.actual_pieces IS NOT NULL AND a.forecast_pieces IS NOT NULL""",
                (run_id, PRINCIPAL))
    rows = pd.DataFrame(cur.fetchall(), columns=["product_key", "month", "forecast_pieces", "actual_pieces", "avg_monthly_pieces"])
    cur.execute("""SELECT d.product_key, left(d.calendar_month, 7), SUM(d.quantity_sold)
                   FROM Unilever_SKU_Demand_Fact_Real d GROUP BY d.product_key, left(d.calendar_month, 7)""")
    demand = pd.DataFrame(cur.fetchall(), columns=["product_key", "month", "qty"])
    demand["qty"] = pd.to_numeric(demand.qty, errors="coerce").astype(float)
    plan_from = f"""FROM lp_recommendation lr JOIN product_dimension pd ON pd.product_key = lr.product_key
                    WHERE {PLAN_STATUS_SQL} AND pd.principal = %s"""
    cur.execute(f"""SELECT to_char(lr.planning_cycle_date, 'YYYY-MM-DD'), MAX(lr.lp_run_key), COUNT(*),
                           array_agg(DISTINCT lr.product_key)
                    {plan_from} AND lr.planning_cycle_date = (SELECT MAX(lr.planning_cycle_date) {plan_from})
                    GROUP BY lr.planning_cycle_date""", (PRINCIPAL, PRINCIPAL))
    p = cur.fetchone()
    plan = {"planning_cycle_date": p[0], "lp_run_key": int(p[1]) if p[1] is not None else None, "plan_rows": int(p[2]),
            "plan_products": len(p[3])} if p else None
    return {"rows": rows, "demand": demand, "plan_keys": set(p[3]) if p else set(), "plan": plan,
            "run": {"run_id": run_id, "label": DEFAULT_BACKTEST_LABEL, "principal": PRINCIPAL,
                    "scored_product_months": int(len(rows))},
            "actuals_version": actuals_version.read(cur)}


def live_pin() -> dict:
    from backend.marts import NEAR_ZERO_SHARE
    conn, cur = connect()
    try:
        live = read_live(cur)
    finally:
        conn.rollback()
        conn.close()
    figures = compute(live["rows"], live["demand"], live["plan_keys"], NEAR_ZERO_SHARE)
    return {"pinned_on": PIN_DATE, "source": {"run": live["run"], "plan": live["plan"],
                                              "actuals_version": live["actuals_version"]},
            "basis": BASIS, "windows": WINDOWS, "populations": POPULATIONS, "definitions": DEFINITIONS, "context": CONTEXT,
            "figures": figures}


# ------------------------------------------------------------------------------------------------------------------- render
def _pct(v):
    return "n/a" if v is None else f"{v * 100:.2f}%"


def _num(v, d=1):
    return "n/a" if v is None else f"{v:,.{d}f}"


def render_md(pin: dict) -> str:
    """docs/EVALUATION_METRICS.md: a rendering of the JSON and nothing else (--verify fails when they differ)."""
    s = pin["source"]
    L = ["# Evaluation metrics, pinned (the one authoritative set)", "",
         f"GENERATED by `python -m scripts.evaluation_metrics --write` on {pin['pinned_on']} from live, read-only. Do not edit: "
         "`--verify` (run by `scripts/check.sh`) fails when this file is not the rendering of `docs/EVALUATION_METRICS.json`, "
         "or when live no longer gives these figures.", "",
         f"**Source.** {pin['basis']}", "",
         f"Run {s['run']['run_id']} ({s['run']['label']}), {s['run']['scored_product_months']:,} scored product-months; "
         f"order plan: cycle {s['plan']['planning_cycle_date']}, LP run {s['plan']['lp_run_key']}, {s['plan']['plan_products']} "
         f"products; actuals version {s['actuals_version']['key']}.", ""]
    for wn, w in pin["windows"].items():
        L += [f"## {w['label']} ({w['start']} to {w['end']})", "",
              "| Population | Products / product-months | MAE (pieces) | RMSE (pieces) | WAPE | MAPE (median) | MASE (median) | R² (median) |",
              "|---|---|---|---|---|---|---|---|"]
        for pn in POPULATION_ORDER:
            c = pin["figures"][wn][pn]
            L.append(f"| {pn.replace('_', ' ')} | {c['products']:,} / {c['product_months']:,} | {_num(c['MAE'])} | "
                     f"{_num(c['RMSE'])} | {_pct(c['WAPE'])} | {_pct(c['MAPE'])} ({c['MAPE_products']} / "
                     f"{c['MAPE_product_months']:,}) | {_num(c['MASE'], 3)} ({c['MASE_products']} / {c['MASE_product_months']:,}) | "
                     f"{_num(c['R2'], 3)} ({c['R2_products']} / {c['R2_product_months']:,}) |")
        L += ["", "| Population | mean actual pieces | MAPE (mean) | MASE below 1 | R² above 0 |", "|---|---|---|---|---|"]
        for pn in POPULATION_ORDER:
            c = pin["figures"][wn][pn]
            L.append(f"| {pn.replace('_', ' ')} | {_num(c['mean_actual_pieces'])} | {_pct(c['MAPE_mean'])} | "
                     f"{_pct(c['MASE_share_below_1'])} | {_pct(c['R2_share_above_0'])} |")
        L.append("")
    L += ["Counts in brackets are the products / product-months that metric covers, where they differ from the population's.", "",
          "## Populations", ""] + [f"- **{k.replace('_', ' ')}**: {v}" for k, v in pin["populations"].items()]
    L += ["", "## Definitions", ""] + [f"- **{k if k != 'R2' else 'R²'}**: {v}" for k, v in pin["definitions"].items()]
    L += ["", "## Context figures", ""] + [f"- **{k}**: {v}" for k, v in pin["context"].items()]
    L += ["", "## Not these measures", "",
          "- The stored MASE of the latest forecast (Forecast_Result.mase, the plan's entry test) and the headline WAPE in pesos "
          "are other measures, pinned in `docs/PUBLISHED_FIGURES_SNAPSHOT_2026-10-24.json`.",
          "- The error card's near-zero line (MAE and RMSE of the near-zero products only, on raw net pieces) covers a population "
          "that is in none of the three above.",
          "- Every other place a value of these measures is stated, and whether it agrees: "
          "`docs/EVALUATION_METRICS_INVENTORY_2026-11-17.md`.", ""]
    return "\n".join(L)


# ------------------------------------------------------------------------------------------------------------------ compare
def flatten(d, prefix=""):
    for k, v in d.items():
        if isinstance(v, dict):
            yield from flatten(v, f"{prefix}{k}.")
        else:
            yield f"{prefix}{k}", v


def _same(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, int) and isinstance(b, int):
        return a == b
    return bool(np.isclose(float(a), float(b), rtol=LIVE_TOLERANCE, atol=LIVE_TOLERANCE))


def compare(pinned: dict, live: dict) -> list[str]:
    """Every divergence between the pin and a live recomputation, as one line each; [] when they agree."""
    bad = []
    for key in ("basis", "windows", "populations", "definitions", "context"):
        if pinned.get(key) != live.get(key):
            bad.append(f"{key}: the pinned text differs from this code's (a definition changed without a re-pin)")
    ps, ls = pinned["source"], live["source"]
    if (ps["run"]["label"], ps["run"]["run_id"]) != (ls["run"]["label"], ls["run"]["run_id"]):
        bad.append(f"backtest run: pinned {ps['run']['run_id']}, live {ls['run']['run_id']}")
    for k in ("planning_cycle_date", "lp_run_key", "plan_products"):
        if (ps["plan"] or {}).get(k) != (ls["plan"] or {}).get(k):
            bad.append(f"order plan {k}: pinned {(ps['plan'] or {}).get(k)!r}, live {(ls['plan'] or {}).get(k)!r}")
    p, n = dict(flatten(pinned["figures"])), dict(flatten(live["figures"]))
    for k in sorted(set(p) | set(n)):
        if k not in n:
            bad.append(f"pinned {k} = {p[k]!r}, but live gives no such figure")
        elif k not in p:
            bad.append(f"live {k} = {n[k]!r} has no pinned figure")
        elif not _same(p[k], n[k]):
            bad.append(f"{k}: pinned {p[k]!r}, live {n[k]!r}")
    return bad


def cross_pin(pin: dict) -> list[str]:
    """The full-span WAPE over every scored product is the published headline pooled WAPE: same run, rows and rule."""
    pub = json.loads(PUBLISHED_JSON.read_text(encoding="utf-8"))["figures"]["headline_wape"]["as_served_calendar"]
    c = pin["figures"]["full"]["all_scored"]
    bad = []
    if (c["products"], c["product_months"]) != (pub["products"], pub["product_months"]):
        bad.append(f"full-span all-scored counts {c['products']} / {c['product_months']} are not the published headline's "
                   f"{pub['products']} / {pub['product_months']}")
    if not _same(c["WAPE"], pub["pooled_wape_pcs_served"]):
        bad.append(f"full-span all-scored WAPE {c['WAPE']!r} is not the published headline pooled WAPE "
                   f"{pub['pooled_wape_pcs_served']!r} ({PUBLISHED_JSON.name})")
    return bad


# --------------------------------------------------------------------------------------------------------------------- cmds
def _json(pin: dict) -> str:
    return json.dumps(pin, indent=1, default=str, ensure_ascii=False) + "\n"


def cmd_print() -> int:
    pin = live_pin()
    print(render_md(pin))
    for b in cross_pin(pin):
        print("CROSS-PIN", b)
    return 0


def cmd_write() -> int:
    from scripts.report_target import report_path
    pin = live_pin()
    bad = cross_pin(pin)
    for b in bad:
        print("FAIL", b)
    if bad:
        print("nothing written: the published headline and this set would disagree")
        return 1
    report_path(PIN_JSON).parent.mkdir(parents=True, exist_ok=True)
    for path, text in ((PIN_JSON, _json(pin)), (PIN_MD, render_md(pin))):   # LF on every platform, like the rest of docs/
        report_path(path).write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {report_path(PIN_JSON)} and {report_path(PIN_MD)}")
    return 0


def cmd_verify() -> int:
    if not PIN_JSON.exists():
        print(f"FAIL: {PIN_JSON.relative_to(REPO)} is missing")
        return 1
    pinned = json.loads(PIN_JSON.read_text(encoding="utf-8"))
    bad = []
    if not PIN_MD.exists() or PIN_MD.read_text(encoding="utf-8") != render_md(pinned):
        bad.append(f"{PIN_MD.relative_to(REPO)} is not the rendering of {PIN_JSON.name} (edited by hand, or not re-generated)")
    bad += cross_pin(pinned)
    try:
        live = live_pin()
    except Exception as exc:   # nothing compared to live is not a pass
        for b in bad:
            print("FAIL", b)
        print(f"FAIL: live not read, nothing compared to live: {exc}")
        return 3
    bad += compare(pinned, live)
    if pinned["source"]["actuals_version"]["key"] != live["source"]["actuals_version"]["key"]:
        print(f"NOTE actuals version: pinned {pinned['source']['actuals_version']['key']}, live "
              f"{live['source']['actuals_version']['key']} (the figures are compared one by one above)")
    for b in bad:
        print("FAIL", b)
    if bad:
        print("FAIL: the pinned evaluation metrics are no longer what live gives. Decide whether the pin or the manuscript is "
              "stale (python -m scripts.evaluation_metrics --write re-pins; the manuscript must follow).")
        return 1
    n = sum(1 for _ in flatten(pinned["figures"]))
    print(f"OK: all {n} pinned evaluation figures (6 metrics x 3 populations x 2 windows, with their counts) equal live; "
          f"run {live['source']['run']['run_id']}, plan {live['source']['plan']['planning_cycle_date']} LP run "
          f"{live['source']['plan']['lp_run_key']}; the full-span WAPE equals the published headline")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--print", action="store_true", dest="do_print")
    g.add_argument("--write", action="store_true")
    g.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    return cmd_print() if a.do_print else cmd_write() if a.write else cmd_verify()


if __name__ == "__main__":
    sys.exit(main())
