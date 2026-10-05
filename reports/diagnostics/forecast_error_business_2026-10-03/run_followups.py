"""
Follow-ups to the forecast-error diagnostic (2026-10-03, second request). Offline: reads only
inputs/ and the first script's outputs; nothing touches the database.

1. Long window: parts 1-3 again on every test month 2023-10..2026-02 with the router as it would
   have run (route() with no forced bin: the bin is worked out from the history known that month).
   Three columns side by side:
     A  6 months, 2025-09..2026-02, served bin held fixed      (the first report, per_product_month.csv)
     B  the same 6 months, bin re-worked each month             (subset of C)
     C  29 months, 2023-10..2026-02, bin re-worked each month
   Same 107 products as A in every column, so only the window and the bin convention change.
2. XGBoost with vs without the month_of_year feature, plus a seed-only rerun as the noise yardstick.
3. Seasonality label: candidate rules and their false-alarm rate on three no-seasonality nulls.
4. "Review before ordering": products in a 3+ month over-forecast run now, plus collapse-flagged ones.

Rules fixed before computing:
  price per piece  = run_analysis.prices() over each window's own test months, at selling price,
                     VAT-inclusive (value-added tax); cost per piece = the same stock count (2026-04-06)
  ablation         = month_of_year deleted from the feature vector in training AND forecasting
                     (global_model.build_features wrapped); everything else unchanged
  false alarm      = a rule labels a series seasonal when it has no seasonality; 5% is the level of
                     the 95% bound already used by DEC-23
  recent average   = mean of the last 3 months, 2025-12..2026-02 (= MA3 for 2026-03; the collapse rule's window)
  exposure         = max(served 2026-03 forecast - recent average, 0) x selling price per piece

    ../Capstone-Project/.venv/Scripts/python.exe reports/diagnostics/forecast_error_business_2026-10-03/run_followups.py
"""
from __future__ import annotations

import contextlib
import json
import os
import sys

import numpy as np
import pandas as pd
from statsmodels.tsa.seasonal import STL
from statsmodels.tsa.stattools import acf

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, HERE)
import run_analysis as RA  # noqa: E402  (same folder: prices, per_month, runs, aggregate_accuracy, inputs)

import analytics.forecasting.global_model as gm  # noqa: E402
from analytics.forecasting.decomposition import PERIOD, _strength  # noqa: E402
from analytics.forecasting.diagnostic_metrics import wape  # noqa: E402
from analytics.forecasting.router import route  # noqa: E402
from scripts.run_baseline_forecast import build_series  # noqa: E402

LONG_MONTHS = list(pd.date_range("2023-10-01", "2026-02-01", freq="MS"))
SHORT_MONTHS = list(RA.F.WINDOW)
PLAN = RA.F.PLANNING_MONTH
SEED = 20261003
N_BOOT, N_SHUFFLE, N_NULL, N_NULL_PRODUCT = 2000, 1000, 500, 200
CSV_TOL = 1e-4      # the first script's CSVs are written with 4 decimals, so a read-back value is within 0.00005
MONTH_IDX = gm.FEATURE_NAMES.index("month_of_year")
A, B, C = "A: 6 months, bin fixed", "B: 6 months, bin re-worked", "C: 29 months, bin re-worked"


def ym(ts) -> str:
    return pd.Timestamp(ts).strftime("%Y-%m")


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #
def load():
    keys = sorted(RA.read("tier_a.csv")["product_key"].astype(int))
    demand = RA.read("demand_real_tierA.csv", dtype={"calendar_month": str})
    demand["quantity"] = pd.to_numeric(demand["quantity"], errors="coerce").fillna(0.0)
    series = {int(k): build_series(g) for k, g in demand.groupby("product_key") if int(k) in set(keys)}
    dims = RA.read("product_dimension_tierA.csv", dtype={"sku_code": str})
    # full versions (with per-product sales and prices) live in local/, never committed
    pm_a = pd.read_csv(os.path.join(RA.LOCAL, "per_product_month.csv"), dtype={"sku_code": str})
    summ = pd.read_csv(os.path.join(RA.LOCAL, "per_product_summary.csv"), dtype={"sku_code": str})
    collapse = pd.read_csv(os.path.join(RA.LOCAL, "collapse_flag.csv"), dtype={"sku_code": str})
    return keys, series, dims, pm_a, summ, collapse


@contextlib.contextmanager
def variant(drop_month: bool = False, seed: int | None = None):
    """Temporarily swap global_model's feature builder / seed (read at call time by training_rows,
    GlobalForecaster.booster_for and .forecast). Restored on exit."""
    orig_bf, orig_seed = gm.build_features, gm.PARAMS["seed"]
    if drop_month:
        def without_month(history, target_month):
            feats, scale = orig_bf(history, target_month)
            return (None if feats is None else np.delete(feats, MONTH_IDX)), scale
        gm.build_features = without_month
    if seed is not None:
        gm.PARAMS["seed"] = seed
    try:
        yield
    finally:
        gm.build_features, gm.PARAMS["seed"] = orig_bf, orig_seed


def run_jobs(series, pool, jobs, **spec) -> pd.DataFrame:
    """route() for each (product_key, month, force_bin), one fresh forecaster per variant."""
    rows = []
    with variant(**spec):
        fc = gm.GlobalForecaster(pool)
        for k, m, fb in jobs:
            r = route(series[k], m, fc, force_bin=fb)
            prev = m - pd.offsets.MonthBegin(1)
            rows.append({"product_key": k, "month": m, "value": r["value"], "bin": r["bin"], "method": r["method"],
                         "ma3": max(0.0, r["ma3_value"]),
                         "xgb": np.nan if r["components"].get("xgb") is None else float(r["components"]["xgb"]),
                         "backup_fired": r["backup_fired"],
                         "actual": float(series[k].loc[m]) if m in series[k].index else np.nan,
                         "naive": float(series[k].loc[prev]) if prev in series[k].index else np.nan})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# 1. Long window
# --------------------------------------------------------------------------- #
def long_window(series, prods):
    jobs = [(k, m, None) for k in prods for m in LONG_MONTHS if m in series[k].index and m > series[k].index[0]]
    out = run_jobs(series, series, jobs)
    out = out[out.value.notna()].copy()                    # 'insufficient' months: the router serves no model
    return out


def longest_over(signs) -> int:
    best = cur = 0
    for v in signs:
        cur = cur + 1 if v > 0 else 0
        best = max(best, cur)
    return best


def window_metrics(pm: pd.DataFrame, rng) -> tuple[dict, pd.DataFrame]:
    pm = pm.sort_values(["product_key", "month"]).copy()
    pm["actual_pesos"] = pm.actual * pm.price_sell_vat_inc
    pm["forecast_pesos"] = pm.forecast * pm.price_sell_vat_inc
    rows = []
    for k, x in pm.groupby("product_key"):
        r = {"product_key": k, "months": len(x), "wape": wape(x.actual, x.forecast), "ma3_wape": wape(x.actual, x.ma3),
             "naive_wape": wape(x.actual, x.naive) if x.naive.notna().all() else np.nan,
             "mean_abs_error_pcs": x.abs_error.mean(), "mean_abs_error_pesos_sell": x.abs_error_pesos_sell.mean(),
             "bias_pct": x.error.sum() / x.actual.abs().sum() * 100}
        r.update(RA.runs(list(x.direction)))
        rows.append(r)
    per = pd.DataFrame(rows)
    seqs = [np.sign(x.error.to_numpy()) for _, x in pm.groupby("product_key")]
    sims = np.array([sum(longest_over(rng.permutation(s)) >= 3 for s in seqs) for _ in range(N_SHUFFLE)])
    by_month = pm.groupby("month")
    agg_a, agg_f = by_month.actual_pesos.sum(), by_month.forecast_pesos.sum()
    cost_ok = pm.cost_status == "ok"
    over3 = per.longest_over_run >= 3
    m = {
        "products": int(pm.product_key.nunique()), "product_months": int(len(pm)), "months": int(pm.month.nunique()),
        "products_per_month_min": int(by_month.product_key.nunique().min()),
        "products_per_month_max": int(by_month.product_key.nunique().max()),
        "median_product_wape": per.wape.median(), "median_product_ma3_wape": per.ma3_wape.median(),
        "median_product_naive_wape": per.naive_wape.median(),
        "products_beating_naive": int((per.wape < per.naive_wape).sum()),
        "median_avg_miss_pcs": per.mean_abs_error_pcs.median(),
        "median_avg_miss_pesos_sell": per.mean_abs_error_pesos_sell.median(),
        "total_wape_pcs": wape(by_month.actual.sum(), by_month.forecast.sum()),
        "total_wape_pesos_sell": wape(agg_a, agg_f),
        "total_ma3_wape_pesos_sell": wape(agg_a, (pm.ma3 * pm.price_sell_vat_inc).groupby(pm.month).sum()),
        "miss_share_of_sales_pesos": pm.abs_error_pesos_sell.sum() / pm.actual_pesos.abs().sum(),
        "avg_monthly_miss_pesos_sell": by_month.abs_error_pesos_sell.sum().mean(),
        "avg_monthly_sales_pesos_sell": agg_a.mean(),
        "avg_monthly_surplus_pesos_sell": by_month.surplus_value_sell.sum().mean(),
        "avg_monthly_shortage_pesos_sell": by_month.shortage_value_sell.sum().mean(),
        "surplus_share_of_miss": pm.surplus_value_sell.sum() / pm.abs_error_pesos_sell.sum(),
        "shortage_share_of_miss": pm.shortage_value_sell.sum() / pm.abs_error_pesos_sell.sum(),
        "avg_monthly_surplus_at_cost_costed": pm[cost_ok].groupby("month").surplus_value_at_cost.sum()
                                              .reindex(agg_a.index, fill_value=0).mean(),
        "product_months_over": int((pm.direction == "over").sum()),
        "product_months_under": int((pm.direction == "under").sum()),
        "product_months_exact": int((pm.direction == "exact").sum()),
        "share_product_months_over": float((pm.direction == "over").mean()),
        "median_product_bias_pct": per.bias_pct.median(),
        "products_net_over": int((per.bias_pct > 0).sum()), "products_net_under": int((per.bias_pct < 0).sum()),
        "products_3plus_over_run": int(over3.sum()),
        "products_3plus_over_run_if_order_random_mean": float(sims.mean()),
        "products_3plus_over_run_if_order_random_95pct_low": float(np.percentile(sims, 2.5)),
        "products_3plus_over_run_if_order_random_95pct_high": float(np.percentile(sims, 97.5)),
        "products_currently_3plus_over": int(((per.current_run_direction == "over") & (per.current_run_months >= 3)).sum()),
        "median_longest_over_run": per.longest_over_run.median(), "max_longest_over_run": int(per.longest_over_run.max()),
        "median_longest_under_run": per.longest_under_run.median(), "max_longest_under_run": int(per.longest_under_run.max()),
    }
    return m, per


# --------------------------------------------------------------------------- #
# 2. Ablation
# --------------------------------------------------------------------------- #
def compare(base: pd.DataFrame, alt: pd.DataFrame, rng) -> dict:
    df = base.merge(alt, on=["product_key", "month"], suffixes=("_0", "_1"))
    df["actual"] = df.actual_0
    per = df.groupby("product_key").apply(lambda x: pd.Series({
        "wape_0": wape(x.actual, x.value_0), "wape_1": wape(x.actual, x.value_1)}), include_groups=False)
    w0, w1 = per.wape_0.to_numpy(), per.wape_1.to_numpy()
    idx = rng.integers(0, len(per), size=(N_BOOT, len(per)))
    boot = np.median(w1[idx], axis=1) - np.median(w0[idx], axis=1)
    d = w1 - w0
    both = df.xgb_0.notna() & df.xgb_1.notna()
    e0, e1 = df.value_0 - df.actual, df.value_1 - df.actual
    return {
        "products": int(len(per)), "product_months": int(len(df)),
        "median_wape_with": float(np.median(w0)), "median_wape_variant": float(np.median(w1)),
        "median_wape_change": float(np.median(w1) - np.median(w0)),
        "median_wape_change_95ci_low": float(np.percentile(boot, 2.5)),
        "median_wape_change_95ci_high": float(np.percentile(boot, 97.5)),
        "products_better": int((d < -1e-9).sum()), "products_worse": int((d > 1e-9).sum()),
        "products_same": int((np.abs(d) <= 1e-9).sum()),
        "pooled_wape_with": float(e0.abs().sum() / df.actual.abs().sum()),
        "pooled_wape_variant": float(e1.abs().sum() / df.actual.abs().sum()),
        "bias_pct_with": float(e0.sum() / df.actual.abs().sum() * 100),
        "bias_pct_variant": float(e1.sum() / df.actual.abs().sum() * 100),
        "product_months_direction_flipped": int((np.sign(e0) != np.sign(e1)).sum()),
        "median_abs_forecast_change_pct": float(((df.value_1 - df.value_0).abs() / df.value_0.abs()).median() * 100),
        "xgb_component_pooled_wape_with": float((df.xgb_0[both] - df.actual[both]).abs().sum() / df.actual[both].abs().sum()),
        "xgb_component_pooled_wape_variant": float((df.xgb_1[both] - df.actual[both]).abs().sum() / df.actual[both].abs().sum()),
        "backups_fired_with": int(df.backup_fired_0.sum()), "backups_fired_variant": int(df.backup_fired_1.sum()),
    }


def ablation(series, summ, pm_c, rng):
    long_a = sorted(summ[(summ.score_source == "common") & (summ.bin == "long")].product_key.astype(int))
    long_plan = sorted(summ[(summ.status == "ok") & (summ.bin == "long")].product_key.astype(int))
    jobs_i = [(k, m, "long") for k in long_a for m in SHORT_MONTHS if m in series[k].index]
    c_long = pm_c[pm_c.bin == "long"]
    jobs_ii = [(int(k), pd.Timestamp(m + "-01"), None) for k, m in zip(c_long.product_key, c_long.month)]
    jobs_iii = [(k, PLAN, None) for k in long_plan]
    jobs = jobs_i + jobs_ii + jobs_iii
    specs = {"with month (served)": {}, "without month": {"drop_month": True},
             "with month, other seed (noise check)": {"seed": gm.SEED + 1}}
    res = {name: run_jobs(series, series, jobs, **spec) for name, spec in specs.items()}
    n1, n2 = len(jobs_i), len(jobs_i) + len(jobs_ii)
    parts = {name: (r.iloc[:n1], r.iloc[n1:n2], r.iloc[n2:]) for name, r in res.items()}
    return long_a, long_plan, parts


# --------------------------------------------------------------------------- #
# 3. Seasonality rules
# --------------------------------------------------------------------------- #
def stl_strength(y: np.ndarray) -> float:
    """analytics.forecasting.decomposition.stl_summary's seasonal_strength, without its
    leading-non-positive trim (real series here already start at the first sale)."""
    fit = STL(np.asarray(y, dtype=float), period=PERIOD, robust=True).fit()
    return _strength(np.asarray(fit.seasonal), np.asarray(fit.resid))


def acf12(y: np.ndarray) -> float:
    return float(acf(y, nlags=12, fft=False)[12]) if np.std(y) > 0 else np.nan


def flags(y: np.ndarray) -> dict:
    n = len(y)
    bound = 1.96 / np.sqrt(n)
    t = np.arange(n)
    out = {"R0": None, "R1": None, "R2": None, "R3": None}
    if n >= 24:
        out["R1"] = bool(abs(acf12(y)) > bound)
        resid = y - np.polyval(np.polyfit(t, y, 1), t)
        out["R2"] = bool(abs(acf12(resid)) > bound)
    if n >= 36:
        out["R0"] = bool(stl_strength(y) >= RA.STL_STRONG)
        out["R3"] = out["R0"] and out["R1"]
    return out


RULES = {"R0": "current: STL seasonal strength >= 0.6 (36+ months)",
         "R1": "lag-12 autocorrelation outside the 95% bound, raw series (24+ months) - DEC-23's test",
         "R2": "lag-12 autocorrelation outside the 95% bound after removing a straight-line trend (24+ months)",
         "R3": "both R0 and R1 (36+ months)"}


def seasonality_rules(series, dims, rng):
    real = []
    for k, s in series.items():
        s = s[s.index <= RA.LAST_MONTH]
        sold = np.flatnonzero(s.to_numpy() > 0)
        if not sold.size:
            continue
        y = s.to_numpy(dtype=float)[int(sold[0]):]
        if len(y) < 24:
            continue
        t = np.arange(len(y))
        resid = y - np.polyval(np.polyfit(t, y, 1), t)
        real.append({"product_key": k, "months": len(y), "y": y, "resid": resid, "trend": y - resid,
                     "acf1": float(acf(y, nlags=1, fft=False)[1]), "acf12_raw": acf12(y), "acf12_detrended": acf12(resid),
                     "stl_strength": stl_strength(y) if len(y) >= 36 else np.nan, **flags(y)})
    phi = float(np.median([r["acf1"] for r in real]))
    lengths = sorted({r["months"] for r in real})

    def rate_table(gen, label):
        rows = []
        for n in lengths:
            hits = {r: 0 for r in RULES}
            for _ in range(N_NULL):
                f = flags(gen(n))
                for r in RULES:
                    hits[r] += bool(f[r])
            rows.append({"null": label, "months": n, **{r: (hits[r] / N_NULL if (n >= 36 or r in ("R1", "R2")) else np.nan)
                                                     for r in RULES}})
        return pd.DataFrame(rows)

    def white(n):
        return rng.normal(100, 20, n)

    def ar1(n):
        e = rng.normal(0, 20 * np.sqrt(1 - phi ** 2), n + 50)
        x = np.zeros(n + 50)
        for i in range(1, n + 50):
            x[i] = phi * x[i - 1] + e[i]
        return 100 + x[50:]

    tables = [rate_table(white, "white noise"), rate_table(ar1, f"AR(1), phi = {phi:.3f} (cohort median lag-1 autocorrelation)")]
    own = []
    for r in real:
        hits = {q: 0 for q in RULES}
        for _ in range(N_NULL_PRODUCT):
            f = flags(r["trend"] + rng.permutation(r["resid"]))
            for q in RULES:
                hits[q] += bool(f[q])
        own.append({"product_key": r["product_key"], "months": r["months"],
                    **{q: hits[q] / N_NULL_PRODUCT if (r["months"] >= 36 or q in ("R1", "R2")) else np.nan for q in RULES}})
    own = pd.DataFrame(own)
    by_len = pd.concat(tables)
    # Expected false labels among OUR products if none were seasonal, and the average rate over them
    count = {q: (pd.Series([r["months"] for r in real]) >= (36 if q in ("R0", "R3") else 24)).sum() for q in RULES}
    summary = []
    for t in tables:
        lab = t["null"].iloc[0]
        rate = t.set_index("months")
        summary.append({"null": lab, **{f"{q}_rate": float(np.nanmean([rate.loc[r["months"], q] for r in real
                                                                       if not np.isnan(rate.loc[r["months"], q])])) for q in RULES}})
    summary.append({"null": "each product's own trend + its own residual months in random order",
                    **{f"{q}_rate": float(own[q].mean()) for q in RULES}})
    summary = pd.DataFrame(summary)
    for q in RULES:
        summary[f"{q}_expected_false_labels"] = summary[f"{q}_rate"] * count[q]
    labels = dims[["product_key", "product_name", "sku_code"]].merge(
        pd.DataFrame([{k: v for k, v in r.items() if k not in ("y", "resid", "trend")} for r in real]), on="product_key")
    return phi, by_len, own, summary, labels, count


# --------------------------------------------------------------------------- #
def main():
    rng = np.random.default_rng(SEED)
    keys, series, dims, pm_a, summ, collapse = load()
    prods = sorted(summ[summ.score_source == "common"].product_key.astype(int))

    # ---- 1. long window
    raw_c = long_window(series, prods)
    bt_c = raw_c.rename(columns={"value": "forecast"}).assign(score_source=C)
    px_c = RA.prices(bt_c, dims)
    pm_c = RA.per_month(bt_c, px_c, dims)
    bt_b = bt_c[bt_c.month.isin(SHORT_MONTHS)].assign(score_source=B)
    px_b = RA.prices(bt_b, dims)
    pm_b = RA.per_month(bt_b, px_b, dims)
    # check: where the re-worked bin equals the served bin, B must equal A exactly
    served_bin = summ.set_index("product_key").bin
    chk = pm_a.merge(pm_b, on=["product_key", "month"], suffixes=("_a", "_b"))
    same_bin = chk.bin_b == chk.product_key.map(served_bin)
    gap = float((chk.forecast_a - chk.forecast_b)[same_bin].abs().max())
    if gap > CSV_TOL:
        raise SystemExit(f"B does not reproduce A where the bin is unchanged: {gap}")
    bin_changed = chk[~same_bin]
    metrics, pers, cats = {}, {}, []
    for label, pm in ((A, pm_a[pm_a.score_source == "common"].assign(score_source=A)), (B, pm_b), (C, pm_c)):
        metrics[label], pers[label] = window_metrics(pm, rng)
        cats.append(RA.aggregate_accuracy(pm, source=label).assign(window=label))
    comp = pd.DataFrame(metrics)
    cat = pd.concat(cats)
    cat_wide = cat.pivot_table(index="level", columns="window",
                               values=["aggregate_wape_pesos_sell", "aggregate_wape_pcs", "product_median_wape"])
    cat_wide.columns = [f"{v} | {w}" for v, w in cat_wide.columns]
    per_c = pers[C].merge(dims[["product_key", "product_name", "sku_code"]], on="product_key")

    # ---- 2. ablation
    long_a, long_plan, parts = ablation(series, summ, pm_c, rng)
    base_i, base_ii, base_iii = parts["with month (served)"]
    pm_a_i = pm_a.assign(month=pd.to_datetime(pm_a.month + "-01")).merge(base_i, on=["product_key", "month"])
    gap_i = float((pm_a_i.forecast - pm_a_i.value).abs().max())
    c_l = pm_c[pm_c.bin == "long"].assign(month=lambda d: pd.to_datetime(d.month + "-01")).merge(base_ii, on=["product_key", "month"])
    gap_ii = float((c_l.forecast - c_l.value).abs().max())
    gap_iii = float((base_iii.set_index("product_key").value - summ.set_index("product_key").forecast_2026_03
                     .reindex(base_iii.product_key)).abs().max())
    if max(gap_i, gap_iii) > CSV_TOL or gap_ii > 1e-6 or len(pm_a_i) != len(base_i) or len(c_l) != len(base_ii):
        raise SystemExit(f"served variant does not reproduce: {gap_i} {gap_ii} {gap_iii}")
    abl = []
    for name in ("without month", "with month, other seed (noise check)"):
        alt_i, alt_ii, alt_iii = parts[name]
        abl.append({"variant": name, "test": "A: 6 months, long products, bin fixed", **compare(base_i, alt_i, rng)})
        abl.append({"variant": name, "test": "C: long-bin months 2025-01..2026-02, bin re-worked", **compare(base_ii, alt_ii, rng)})
        ch = (alt_iii.value.to_numpy() - base_iii.value.to_numpy()) / base_iii.value.to_numpy() * 100
        abl.append({"variant": name, "test": "2026-03 forecast, long products", "products": int(len(ch)),
                    "products_forecast_changed": int((np.abs(ch) > 0.0001).sum()),
                    "median_abs_forecast_change_pct": float(np.median(np.abs(ch))),
                    "p90_abs_forecast_change_pct": float(np.percentile(np.abs(ch), 90)),
                    "max_abs_forecast_change_pct": float(np.abs(ch).max()),
                    "backups_fired_with": int(base_iii.backup_fired.sum()),
                    "backups_fired_variant": int(alt_iii.backup_fired.sum())})
    abl = pd.DataFrame(abl)
    plan_detail = base_iii[["product_key", "value"]].rename(columns={"value": "forecast_with_month"}).assign(
        forecast_without_month=parts["without month"][2].value.to_numpy(),
        forecast_other_seed=parts["with month, other seed (noise check)"][2].value.to_numpy())
    plan_detail = dims[["product_key", "product_name", "sku_code"]].merge(plan_detail, on="product_key")

    # ---- 3. seasonality rules
    phi, by_len, own, seas_sum, seas_labels, eligible = seasonality_rules(series, dims, rng)
    prev = pd.read_csv(os.path.join(HERE, "seasonality_reconciliation.csv"))
    chk_s = seas_labels.merge(prev[["product_key", "stl_seasonal_strength"]], on="product_key")
    s_gap = float((chk_s.stl_strength - chk_s.stl_seasonal_strength).abs().max())  # stored rounded to 3 dp
    if s_gap > 0.0006:
        raise SystemExit(f"STL strength differs from the dashboard function: {s_gap}")

    # ---- 4. review before ordering
    over_now = summ[summ.currently_over_3plus == True].product_key.astype(int)  # noqa: E712
    coll = collapse[collapse.collapse_flag == True].product_key.astype(int)  # noqa: E712
    rk = sorted(set(over_now) | set(coll))
    s_ = summ.set_index("product_key")
    pc = pers[C].set_index("product_key")
    rows = []
    for k in rk:
        h = series[k][series[k].index <= RA.LAST_MONTH]
        recent = float(h.tail(3).mean())
        fc_ = float(s_.loc[k, "forecast_2026_03"])
        price = float(s_.loc[k, "price_sell_vat_inc"])
        why = " + ".join(w for w, ok in (("over-forecast 3+ months running", k in set(over_now)),
                                          ("collapse flag", k in set(coll))) if ok)
        run_a = s_.loc[k, "current_run_months"] if s_.loc[k, "current_run_direction"] == "over" else 0
        run_c = pc.loc[k, "current_run_months"] if k in pc.index and pc.loc[k, "current_run_direction"] == "over" else 0
        rows.append({"product_name": s_.loc[k, "product_name"], "sku_code": s_.loc[k, "sku_code"], "product_key": k,
                     "why_listed": why, "served_method": s_.loc[k, "served_method"],
                     "forecast_2026_03_pcs": fc_, "recent_avg_last3_pcs": recent, "avg_last12_pcs": float(h.tail(12).mean()),
                     "forecast_over_recent_avg": fc_ / recent if recent > 0 else np.nan,
                     "months_in_over_run_6m_window": run_a, "months_in_over_run_29m_window": run_c,
                     "price_sell_vat_inc": price,
                     "exposure_pesos_sell_vat_inc": max(fc_ - recent, 0.0) * price})
    review = pd.DataFrame(rows).sort_values("exposure_pesos_sell_vat_inc", ascending=False)

    # ---- write
    write = RA.publish           # full table to local/, committed copy without RA.CLIENT_COLUMNS
    write(pm_c, "longwindow_per_product_month.csv")
    write(per_c, "longwindow_per_product_summary.csv")
    write(comp, "window_comparison.csv", index=True, fmt="%.6f")          # 6 decimals: shown as % to 1 decimal
    write(cat_wide, "window_category_total_accuracy.csv", index=True, fmt="%.6f")
    write(bin_changed[["product_key", "month", "bin_a", "bin_b", "forecast_a", "forecast_b"]], "window_bin_changes.csv")
    write(abl, "xgb_month_ablation.csv")
    write(plan_detail, "xgb_month_ablation_2026-03.csv")
    write(by_len, "seasonality_rule_false_alarm_by_length.csv")
    write(own, "seasonality_rule_false_alarm_own_series.csv")
    write(seas_sum, "seasonality_rule_false_alarm_summary.csv")
    write(seas_labels, "seasonality_rule_labels.csv")
    write(review, "review_before_ordering.csv")
    out = {"checks": {"B_equals_A_where_bin_unchanged_max_gap": gap, "A_product_months_with_bin_changed": int(len(bin_changed)),
                      "served_variant_gaps": [gap_i, gap_ii, gap_iii], "stl_strength_max_gap_vs_dashboard_function": s_gap},
           "window_comparison": metrics, "ablation_long_products": {"bin_fixed": len(long_a), "planning_month": len(long_plan)},
           "seasonality": {"phi": phi, "eligible": {k: int(v) for k, v in eligible.items()}, "rules": RULES,
                           "labelled_seasonal": {q: int(seas_labels[q].map(lambda v: v is True).sum()) for q in RULES}},
           "review_products": len(review),
           "review_exposure_total_pesos_sell_vat_inc": float(review.exposure_pesos_sell_vat_inc.sum()),
           "bin_changes": {"product_months": int(len(bin_changed)), "products": int(bin_changed.product_key.nunique()),
                           **{f"{a}_to_{b}": int(n) for (a, b), n in bin_changed.groupby(["bin_a", "bin_b"]).size().items()}},
           "window_c_months_per_product": {"median": float(per_c.months.median()), "min": int(per_c.months.min()),
                                           "max": int(per_c.months.max())},
           "planning_month_without_month": {
               "up": int((plan_detail.forecast_without_month > plan_detail.forecast_with_month).sum()),
               "down": int((plan_detail.forecast_without_month < plan_detail.forecast_with_month).sum())}}
    with open(os.path.join(HERE, "followups_results.json"), "w") as fh:
        json.dump(out, fh, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    pd.set_option("display.width", 250)
    print(json.dumps(out["checks"], indent=2, default=str))
    print(comp.to_string())
    print(cat_wide.to_string())
    print(abl.T.to_string())
    print(seas_sum.T.to_string())
    print(seas_labels[["product_name", "sku_code", "months", "acf12_raw", "acf12_detrended", "stl_strength", "R0", "R1", "R2", "R3"]]
          .sort_values("acf12_detrended", ascending=False).head(15).to_string())
    print(review.drop(columns=[c for c in review.columns if c in RA.CLIENT_COLUMNS]).to_string())


if __name__ == "__main__":
    main()
