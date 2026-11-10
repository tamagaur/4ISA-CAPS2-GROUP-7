"""
reports/experiments/horse_race_2026-11-10/run_horse_race.py - a horse race of forecast approaches against the served
forecast, scored where it fails worst (2026-11-10). BACKTEST ONLY: reads the throwaway copy ssm_challenger
(127.0.0.1:55432, a restore of backups/full_backup_20261104T175951Z) and writes only files. Refuses any other database.

    python reports/experiments/horse_race_2026-11-10/run_horse_race.py      # with SUPABASE_DB_URL = the throwaway copy

Frame: exactly the product-months of the stored as-served backtest (forecast_challenger kind=backtest, which equals
mart run 11 row for row): Tier A the month before, 2024-01..2026-02, 4,370 rows. Every method forecasts the same rows,
ONE STEP AHEAD FROM HISTORY STRICTLY BEFORE THE MONTH (each method reads series[index < t], company/category totals
< t, and for the error-feedback method only forecasts and actuals of months < t). No parameter was tuned on the scored
months: every setting is fixed in this file (3-month windows as MA3, statsmodels' own estimates, the calendar
module's shrink) or a variant stated beside it. The dead-SKU rule zeroes the same rows for every method, as served.

Actual = the as-served actual (run_baseline_forecast.build_series: no row = 0, net-negative = 0, blank not scored).

Metrics, each named:
  pooled WAPE  sum |f - a| / sum |a| over the product-months (the Dashboard's "typical product, weighted by sales")
  MAPE         median over products of each product's mean |f - a| / a over its months with a > 0
               (analytics.forecasting.diagnostic_metrics.mape, the bake-off's convention: median across products)
  MASE         median over products of mean |f - a| / scale, scale = the product's mean |y_t - y_t-1| over its
               history before the window starts (naive_scale, in-sample, strictly before the scored months);
               also the count with MASE < 1
  bias         sum (f - a) / sum |a|
Noise: 95% interval of pooled WAPE(method) - pooled WAPE(served), resampling products (2,000 draws, seed 20261110).
"""
from __future__ import annotations

import json
import os
import sys
import warnings
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import psycopg2

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from analytics.forecasting import baseline  # noqa: E402
from analytics.forecasting.calendar import calendar_factor, company_totals  # noqa: E402
from analytics.forecasting.challenger import damped_trend_value  # noqa: E402
from analytics.forecasting.diagnostic_metrics import mape as mape_fn, naive_scale  # noqa: E402
from analytics.forecasting.global_model import from_first_sale  # noqa: E402
from scripts.run_baseline_forecast import build_series, fetch_demand  # noqa: E402

OUT = Path(__file__).resolve().parent
WINDOWS = {"main 2025-09..2026-02": ("2025-09", "2026-02"), "earlier 2024-01..2025-08": ("2024-01", "2025-08")}
SEED, DRAWS = 20261110, 2000


def url() -> str:
    u = os.environ.get("SUPABASE_DB_URL", "")
    p = urlparse(u)
    if p.hostname not in ("127.0.0.1", "localhost") or p.port != 55432:
        sys.exit("refusing: this backtest reads only the throwaway copy on 127.0.0.1:55432")
    return u


def read(u: str):
    conn = psycopg2.connect(u)
    cur = conn.cursor()
    cur.execute("SET TRANSACTION READ ONLY")
    demand = fetch_demand(cur)
    cur.execute("""SELECT product_key, to_char(month,'YYYY-MM'), served_value, calendar_factor, dead_sku, bin, served_method
                   FROM forecast_challenger WHERE kind='backtest' ORDER BY month, product_key""")
    frame = pd.DataFrame(cur.fetchall(), columns=["product_key", "month", "served", "cal", "dead", "bin", "served_method"])
    cur.execute("SELECT product_key, COALESCE(category_path,'UNCLASSIFIED') FROM product_dimension WHERE principal='unilever'")
    cat = dict(cur.fetchall())
    cur.execute("""SELECT DISTINCT product_key FROM lp_recommendation WHERE planning_cycle_date='2026-03-01'
                   AND lp_run_key = (SELECT MAX(lp_run_key) FROM lp_recommendation WHERE planning_cycle_date='2026-03-01')""")
    planned = {int(r[0]) for r in cur.fetchall()}
    conn.rollback()
    conn.close()
    frame = frame.astype({"served": float, "cal": float})
    return demand, frame, cat, planned


def totals_by(demand: pd.DataFrame, cat: dict) -> dict[str, pd.Series]:
    d = demand.assign(cat=demand.product_key.map(cat).fillna("UNCLASSIFIED"))
    out = {}
    for c, g in d.groupby("cat"):
        out[c] = company_totals(g)
    return out


def yoy_total(T: pd.Series, t: pd.Timestamp) -> float | None:
    """Seasonal naive with year-over-year level: T(t-12) x [T(t-1..t-3)] / [T(t-13..t-15)], all before t."""
    need = [t - pd.DateOffset(months=m) for m in (12, 1, 2, 3, 13, 14, 15)]
    if not all(m in T.index for m in need):
        return None
    last, prev = sum(T[m] for m in need[1:4]), sum(T[m] for m in need[4:7])
    return float(T[need[0]] * last / prev) if prev > 0 else None


def hw_total(T: pd.Series, t: pd.Timestamp) -> float | None:
    """Holt-Winters on the total: damped additive trend, multiplicative 12-month season, needs 24 months."""
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
    h = T[T.index < t]
    if len(h) < 24:
        return None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            v = float(ExponentialSmoothing(h.to_numpy(float), trend="add", damped_trend=True, seasonal="mul",
                                           seasonal_periods=12, initialization_method="estimated").fit().forecast(1)[0])
        return v if np.isfinite(v) and v > 0 else None
    except Exception:  # noqa: BLE001
        return None


def month_ratio(s: pd.Series, t: pd.Timestamp) -> float | None:
    """Product's own ratio for t's calendar month: geometric mean over earlier years of y(m) / mean(3 months before)."""
    rs = []
    for y in range(t.year - 1, 2022, -1):
        m = pd.Timestamp(year=y, month=t.month, day=1)
        pr = [m - pd.DateOffset(months=i) for i in (1, 2, 3)]
        if m in s.index and all(p in s.index for p in pr):
            base = float(np.nanmean([s[p] for p in pr]))
            if base > 0 and s[m] > 0:
                rs.append(s[m] / base)
    return float(np.exp(np.mean(np.log(rs)))) if rs else None


def forecasts(frame, series, T_co, T_cat, cat) -> pd.DataFrame:
    rows = []
    cache_co, cache_cat = {}, {}
    for r in frame.itertuples():
        t = pd.Timestamp(f"{r.month}-01")
        s = series[r.product_key]
        h = s[s.index < t].dropna()
        h = from_first_sale(h) if len(from_first_sale(h)) else h
        a = float(s.loc[t])
        f = {"product_key": r.product_key, "month": r.month, "actual": a, "served": r.served}
        if r.dead:
            rows.append({**f, **{k: 0.0 for k in METHODS if k != "served"}})
            continue
        ma3 = max(0.0, float(baseline.moving_average_forecast(h, 1, 3)[0]))
        f["served_nocal"] = r.served / r.cal if r.cal > 0 else r.served
        f["naive"] = max(0.0, float(h.iloc[-1]))
        f["ma3"] = ma3
        f["tsb"] = max(0.0, float(baseline.tsb_forecast(h, 1)[0]))
        t12 = t - pd.DateOffset(months=12)
        snaive = float(s[t12]) if t12 in s.index and not np.isnan(s[t12]) and t12 >= h.index[0] else None
        f["snaive"] = ma3 if snaive is None else max(0.0, snaive)
        dt, _ = damped_trend_value(h) if len(h) >= 12 else (None, None)
        damped = ma3 if dt is None else min(max(0.0, dt), float(h.max()))
        f["combo_ma3_tsb_snaive_damped"] = float(np.mean([ma3, f["tsb"], f["snaive"], damped]))
        # Top-down: the total's forecast, allocated by the product's share of the last 3 months (= its MA3 / total MA3).
        if t not in cache_co:
            Tb = T_co[T_co.index < t]
            base = float(Tb.tail(3).mean())
            cache_co[t] = {"base": base, "yoy": yoy_total(T_co, t), "hw": hw_total(T_co, t)}
        co = cache_co[t]
        for name in ("yoy", "hw"):
            tot = co[name]
            f[f"topdown_company_{name}"] = ma3 if tot is None or co["base"] <= 0 else ma3 * tot / co["base"]
        c = cat.get(r.product_key, "UNCLASSIFIED")
        key = (c, t)
        if key not in cache_cat:
            Tc = T_cat[c]
            base = float(Tc[Tc.index < t].tail(3).mean()) if (Tc.index < t).sum() >= 3 else 0.0
            cache_cat[key] = {"base": base, "yoy": yoy_total(Tc, t)}
        cc = cache_cat[key]
        f["topdown_category_yoy"] = ma3 if cc["yoy"] is None or cc["base"] <= 0 else ma3 * cc["yoy"] / cc["base"]
        # Calendar factor at full strength (no shrink toward 1), on the served value before the factor.
        full, _ = calendar_factor(T_co, t, shrink=1.0)
        f["served_calendar_full"] = f["served_nocal"] * full
        # December/January only: the product's own ratio for that month, on the served value before the factor.
        if t.month in (12, 1):
            mr = month_ratio(s[s.index < t], t)
            f["served_decjan_own_ratio"] = f["served_nocal"] * (mr if mr is not None else 1.0)
        else:
            f["served_decjan_own_ratio"] = f["served_nocal"]
        f["combo_with_topdown"] = float(np.mean([ma3, f["tsb"], f["snaive"], damped, f["topdown_company_yoy"]]))
        f["mean_served_topdown"] = (r.served + f["topdown_company_yoy"]) / 2
        rows.append(f)
    df = pd.DataFrame(rows)
    # Error feedback: served x (sum actual / sum served) over every frame product in the 3 months before t.
    by_m = df.groupby("month")[["actual", "served"]].sum()
    ratio = {}
    for m in by_m.index:
        t = pd.Timestamp(f"{m}-01")
        prev = [(t - pd.DateOffset(months=i)).strftime("%Y-%m") for i in (1, 2, 3)]
        prev = [p for p in prev if p in by_m.index]
        ratio[m] = (by_m.loc[prev, "actual"].sum() / by_m.loc[prev, "served"].sum()) if len(prev) == 3 else 1.0
    df["served_error_feedback"] = df.served * df.month.map(ratio)
    df["topdown_company_yoy_error_feedback"] = df.topdown_company_yoy  # placeholder replaced below
    by_td = df.groupby("month")[["actual", "topdown_company_yoy"]].sum()
    r2 = {}
    for m in by_td.index:
        t = pd.Timestamp(f"{m}-01")
        prev = [p for p in ((t - pd.DateOffset(months=i)).strftime("%Y-%m") for i in (1, 2, 3)) if p in by_td.index]
        r2[m] = (by_td.loc[prev, "actual"].sum() / by_td.loc[prev, "topdown_company_yoy"].sum()) if len(prev) == 3 else 1.0
    df["topdown_company_yoy_error_feedback"] = df.topdown_company_yoy * df.month.map(r2)
    return df


METHODS = ["served", "served_nocal", "naive", "ma3", "tsb", "snaive", "combo_ma3_tsb_snaive_damped",
           "topdown_company_yoy", "topdown_company_hw", "topdown_category_yoy", "served_calendar_full",
           "served_decjan_own_ratio", "combo_with_topdown", "mean_served_topdown", "served_error_feedback",
           "topdown_company_yoy_error_feedback"]


def score(df: pd.DataFrame, m: str, scales: dict) -> dict:
    d = df.dropna(subset=["actual"])
    e = d[m] - d.actual
    a = d.actual.abs().sum()
    per = d.groupby("product_key")
    mapes = per.apply(lambda g: mape_fn(g.actual.to_numpy(), g[m].to_numpy()), include_groups=False).dropna()
    mases = per.apply(lambda g: (np.abs(g[m] - g.actual).mean() / scales[g.name])
                      if scales.get(g.name, 0) > 0 else np.nan, include_groups=False).dropna()
    return {"pooled_wape": float(np.abs(e).sum() / a), "mape": float(mapes.median()),
            "mase": float(mases.median()), "mase_lt1": f"{int((mases < 1).sum())}/{len(mases)}",
            "bias": float(e.sum() / a), "product_months": int(len(d)), "products": int(d.product_key.nunique())}


def boot(df: pd.DataFrame, m: str) -> tuple[float, float]:
    g = df.dropna(subset=["actual"]).assign(es=lambda x: (x.served - x.actual).abs(), em=lambda x: (x[m] - x.actual).abs(),
                                            aa=lambda x: x.actual.abs()).groupby("product_key")[["es", "em", "aa"]].sum()
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, len(g), size=(DRAWS, len(g)))
    es, em, aa = (g[c].to_numpy()[idx].sum(axis=1) for c in ("es", "em", "aa"))
    lo, hi = np.quantile((em - es) / aa, [0.025, 0.975])
    return float(lo), float(hi)


def decjan_effect(T: pd.Series, series: dict, frame: pd.DataFrame) -> dict:
    """Is there a December trough / January peak, or are those just the months a lagging model hurts most?"""
    out = {"company": {}}
    for y in (2023, 2024, 2025):
        dec = pd.Timestamp(f"{y}-12-01")
        jan = pd.Timestamp(f"{y + 1}-01-01")
        sn = [pd.Timestamp(f"{y}-{m:02d}-01") for m in (9, 10, 11)]
        if all(x in T.index for x in [dec, *sn]):
            out["company"][f"Dec {y} / mean(Sep-Nov)"] = round(float(T[dec] / np.mean([T[x] for x in sn])), 3)
        if jan in T.index and dec in T.index:
            out["company"][f"Jan {y + 1} / Dec {y}"] = round(float(T[jan] / T[dec]), 3)
            out["company"][f"Jan {y + 1} / mean(Oct-Dec {y})"] = round(float(T[jan] / np.mean([T[x] for x in [*sn[1:], dec]])), 3)
    # Every calendar month's ratio to the mean of its 3 prior months, company level: where do Dec and Jan rank?
    ratios = {}
    for t in T.index:
        pr = [t - pd.DateOffset(months=i) for i in (1, 2, 3)]
        if all(p in T.index for p in pr):
            ratios[t] = T[t] / np.mean([T[p] for p in pr])
    r = pd.Series(ratios)
    by_cal = r.groupby(r.index.month).agg(["mean", "min", "max", "count"]).round(3)
    out["company_month_over_prior3_by_calendar_month"] = {int(k): v for k, v in by_cal.to_dict("index").items()}
    # Product level: share of products (Tier A frame) whose month is below the mean of its prior 3, by month.
    keys = set(frame.product_key)
    share = {}
    for t in pd.date_range("2024-01-01", "2026-02-01", freq="MS"):
        below = n = 0
        for k in keys:
            s = series[k]
            pr = [t - pd.DateOffset(months=i) for i in (1, 2, 3)]
            if t in s.index and all(p in s.index for p in pr) and not np.isnan(s[t]):
                base = np.nanmean([s[p] for p in pr])
                if base > 0:
                    n += 1
                    below += int(s[t] < base)
        share[t.strftime("%Y-%m")] = round(below / n, 3) if n else None
    out["share_of_products_below_their_prior3_mean"] = share
    return out


def main() -> int:
    u = url()
    demand, frame, cat, planned = read(u)
    latest = demand.calendar_month.max()
    series = {int(k): build_series(g, latest) for k, g in demand.groupby("product_key")}
    T_co = company_totals(demand)
    T_cat = totals_by(demand, cat)
    df = forecasts(frame, series, T_co, T_cat, cat)
    df.to_csv(REPO / "local" / "horse_race_rows_2026-11-10.csv", index=False)   # per product: git-ignored (rule 9)

    results = {"frame_rows": len(df), "planned_products": len(planned), "windows": {}}
    table = []
    for wname, (a, b) in WINDOWS.items():
        w = df[(df.month >= a) & (df.month <= b)]
        start = pd.Timestamp(f"{a}-01")
        scales = {}
        for k in w.product_key.unique():
            h = series[k][series[k].index < start].dropna()
            h = from_first_sale(h) if len(from_first_sale(h)) else h
            scales[k] = naive_scale(h.to_numpy(float)) if len(h) >= 2 else np.nan
        sets = {"all": w, "planned 109": w[w.product_key.isin(planned)]}
        for sname, sdf in sets.items():
            lines = {"all months": sdf, "December": sdf[sdf.month.str.endswith("-12")],
                     "January": sdf[sdf.month.str.endswith("-01")]}
            for lname, ldf in lines.items():
                if ldf.empty:
                    continue
                for m in METHODS:
                    sc = score(ldf, m, scales)
                    lo, hi = boot(ldf, m) if m != "served" else (0.0, 0.0)
                    table.append({"window": wname, "set": sname, "line": lname, "method": m, **sc,
                                  "d_pooled_vs_served": sc["pooled_wape"] - score(ldf, "served", scales)["pooled_wape"],
                                  "ci95_lo": lo, "ci95_hi": hi})
    t = pd.DataFrame(table)
    t.to_csv(OUT / "results_table.csv", index=False)   # aggregates only
    results["decjan"] = decjan_effect(T_co, series, frame)
    (OUT / "results_decjan.json").write_text(json.dumps(results["decjan"], indent=1, default=str), encoding="utf-8")
    pd.set_option("display.width", 250)
    for (wname, sname, lname), g in t.groupby(["window", "set", "line"], sort=False):
        print(f"\n=== {wname} | {sname} | {lname} | {g.product_months.iloc[0]} product-months, {g.products.iloc[0]} products")
        print(g.sort_values("pooled_wape")[["method", "pooled_wape", "mape", "mase", "mase_lt1", "bias",
                                            "d_pooled_vs_served", "ci95_lo", "ci95_hi"]].round(4).to_string(index=False))
    print(json.dumps(results["decjan"], indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
