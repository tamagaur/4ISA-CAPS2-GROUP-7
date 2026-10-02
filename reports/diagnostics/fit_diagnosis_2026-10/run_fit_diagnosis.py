"""
Fit diagnosis, 2026-10 - Unilever Tier A as of 2026-02 (ABC method 'single', 132 SKUs),
REAL data only (Unilever_SKU_Demand_Fact_Real). Read-only: one READ ONLY transaction,
rolled back; nothing is written to the database.

SCOPE: Unilever only - Del Monte has no product-level sales, so it is not forecast and
has no product-level fit to diagnose.

What it does
  1. Re-runs the live router exactly as scripts/run_baseline_forecast.py --write does
     (same build_series, status rules, Tier A training pool, route(), 20% split rolling
     one-step holdout) and checks it reproduces public.forecast_result at 2026-03-01:
     status, method and forecast_value on 132/132 rows and the stored MASE on every 'ok'
     row. Any mismatch stops the run.
  2. Scores each SKU on the verdict holdout of reports/diagnostics/README.md: the common
     window 2025-09..2026-02 (MASE scale = lag-1 naive error of the real months before
     2025-09), or the stored 20% split when the common window cannot score the SKU.
  3. Overfit / underfit / bias, rules fixed before computing (README.md beside this file).

The harness functions (load_inputs, run_cohort, verdict_holdouts, score_holdouts) are
imported by reports/simulation/synthetic_2026-10/run_simulation.py, so the REAL numbers
in both outputs come from one code path.

    .venv/Scripts/python.exe reports/diagnostics/fit_diagnosis_2026-10/run_fit_diagnosis.py
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, REPO)

from analytics.forecasting import baseline  # noqa: E402
from analytics.forecasting.baseline import MIN_MONTHS_WITH_SALES  # noqa: E402
from analytics.forecasting.diagnostic_metrics import mase, naive_scale, wape  # noqa: E402
from analytics.forecasting.global_model import (  # noqa: E402
    MIN_HISTORY, GlobalForecaster, build_features, from_first_sale,
)
from analytics.forecasting.router import assert_real_rows, ma3_value, rolling_one_step, route  # noqa: E402
from analytics.forecasting.sarima import HOLDOUT_FRACTION, train_holdout_split  # noqa: E402
from scripts.run_baseline_forecast import build_series  # noqa: E402

SCOPE_NOTE = "Unilever only - Del Monte has no product-level sales, so it is not forecast"
ABC_PERIOD = "2026-02"
PLANNING_MONTH = pd.Timestamp("2026-03-01")
WINDOW = list(pd.date_range("2025-09-01", "2026-02-01", freq="MS"))
WINDOW_START = WINDOW[0]
# Verdict thresholds - reports/diagnostics/README.md "Verdict thresholds (fixed before computing, 2026-09-23)"
NOT_FIT_MASE = 1.1
BORDERLINE_MASE = 0.9
# Part 2 rules, as given 2026-10-02 (README.md beside this file)
# Overfit, MA3 as the control (MA3 has no fitted parameters, so it cannot memorise): a served model is
# overfit only if its holdout / in-sample ratio exceeds BOTH this percentile of MA3's own ratio (same
# products, same months - measured each run, 2.691 on 2026-10-02) AND that product's own MA3 ratio.
MA3_CONTROL_PERCENTILE = 95
CONTROL = "not assessable (control)"     # MA3-served products: MA3 is the yardstick, it cannot be judged against itself
NO_INSAMPLE = "not testable (no in-sample months)"
UNDERFIT_MASE = 1.0           # in-sample >= 1 and holdout >= 1
BIAS_T = 2.571                # two-sided 95% t critical value, 5 degrees of freedom (6 months)
BIAS_MONTHS = 6


# --------------------------------------------------------------------------- #
# DB (read-only transaction, rolled back)
# --------------------------------------------------------------------------- #
def read_only_cursor():
    import psycopg2
    from dotenv import load_dotenv
    load_dotenv(os.path.join(REPO, ".env"))
    load_dotenv("C:/Users/kyuan/Capstone-Project/.env")       # worktree has no .env of its own
    # Direct URL first: a client dropped on the pooler (SSL EOF) leaves its server transaction
    # "idle in transaction" indefinitely; on a direct connection the backend ends with the socket.
    url = os.environ.get("SUPABASE_DIRECT_URL") or os.environ["SUPABASE_DB_URL"]
    conn = psycopg2.connect(url)                               # non-autocommit: BEGIN is implicit
    cur = conn.cursor()
    cur.execute("SET TRANSACTION READ ONLY")
    cur.execute("SELECT current_setting('transaction_read_only')")
    if cur.fetchone()[0] != "on":
        raise RuntimeError("transaction is not read-only")
    return conn, cur


def cached_inputs(cache: str | None, loader):
    """loader(cur) inside one read-only transaction, or the pickle at `cache` if it exists
    (a local copy of the same rows, so a rerun does not re-query; delete it to refresh)."""
    import psycopg2
    if cache and os.path.exists(cache):
        return pd.read_pickle(cache)
    for attempt in (1, 2):                                     # one retry on a dropped connection
        conn, cur = read_only_cursor()
        try:
            out = loader(cur)
            break
        except psycopg2.OperationalError:
            if attempt == 2:
                raise
        finally:
            if not conn.closed:
                conn.rollback()
                conn.close()
    if cache:
        pd.to_pickle(out, cache)
    return out


def load_inputs(cur, with_placeholder_2021_22: bool = False) -> dict:
    """Tier A keys, real demand (same SQL as fetch_demand), live forecast_result rows and,
    optionally, the is_demo rows dated 2021-01..2022-12 (never the 2026-03..08 gap rows)."""
    cur.execute("""
        SELECT abc.product_key, pd.sku_code, pd.product_name
        FROM abc_classification abc JOIN product_dimension pd ON pd.product_key = abc.product_key
        WHERE abc.principal = 'unilever' AND abc.method = 'single'
          AND abc.classification_period = %s AND abc.tier = 'A'
        ORDER BY abc.product_key""", (ABC_PERIOD,))
    tier_a = pd.DataFrame(cur.fetchall(), columns=["product_key", "sku_code", "product_name"])
    cur.execute("""
        SELECT product_key, sku_code, calendar_month, SUM(quantity_sold) AS quantity, bool_or(is_demo) AS is_demo
        FROM Unilever_SKU_Demand_Fact_Real
        GROUP BY product_key, sku_code, calendar_month
        ORDER BY product_key, calendar_month""")
    demand = pd.DataFrame(cur.fetchall(), columns=["product_key", "sku_code", "calendar_month", "quantity", "is_demo"])
    demand["quantity"] = pd.to_numeric(demand["quantity"], errors="coerce").fillna(0.0)
    assert_real_rows(demand)
    cur.execute("""
        SELECT product_key, status, forecast_value::float, mase::float,
               model_params->>'method', model_params->>'bin'
        FROM forecast_result WHERE forecast_date = %s""", (PLANNING_MONTH.date(),))
    live = pd.DataFrame(cur.fetchall(), columns=["product_key", "status", "forecast_value", "mase", "method", "bin"])
    out = {"tier_a": tier_a, "demand": demand, "live": live}
    if with_placeholder_2021_22:
        cur.execute("""
            SELECT product_key, sku_code, calendar_month, SUM(quantity_sold) AS quantity, bool_or(is_demo) AS is_demo
            FROM Unilever_SKU_Demand_Fact
            WHERE is_demo = true AND calendar_month BETWEEN '2021-01' AND '2022-12'
            GROUP BY product_key, sku_code, calendar_month
            ORDER BY product_key, calendar_month""")
        ph = pd.DataFrame(cur.fetchall(), columns=["product_key", "sku_code", "calendar_month", "quantity", "is_demo"])
        ph["quantity"] = pd.to_numeric(ph["quantity"], errors="coerce").fillna(0.0)
        out["placeholder"] = ph
    return out


# --------------------------------------------------------------------------- #
# The live pipeline, per SKU (mirrors run_baseline_forecast.main + _write_forecast_result)
# --------------------------------------------------------------------------- #
def run_cohort(demand: pd.DataFrame, keys: list, allow_placeholder: bool = False,
               score_pipeline: bool = True) -> tuple[dict, dict, GlobalForecaster]:
    """({product_key: record}, {product_key: series}, forecaster). Status rules, pool and
    route() exactly as the --write path; pipeline MASE = served model, rolling one-step over
    train_holdout_split's months, scaled by the lag-1 naive error of the training months
    (skipped with score_pipeline=False: only the live-reproduction check needs it)."""
    by_key = {int(k): g for k, g in demand.groupby("product_key")}
    series_by_key = {k: build_series(g) for k, g in by_key.items() if k in set(keys)}
    forecaster = GlobalForecaster(series_by_key, allow_placeholder=allow_placeholder)
    recs = {}
    for k in keys:
        s = series_by_key.get(k)
        rec = {"product_key": k, "months_span": 0 if s is None else int(len(s)),
               "sales_months": 0 if s is None else int((s > 0).sum()),
               "placeholder_months": 0 if s is None else int(s.index.isin(list(s.attrs.get("placeholder_months", ()))).sum())}
        if s is None or rec["sales_months"] < MIN_MONTHS_WITH_SALES:
            observed = pd.Series(dtype=float) if s is None else s[s > 0]
            recs[k] = {**rec, "status": "insufficient_data", "bin": "insufficient", "method": "trailing_average",
                       "forecast": float(max(0.0, observed.mean() if len(observed) else 0.0)), "mase_pipeline": None}
            continue
        if len(s) >= 6 and s.tail(6).sum() <= 0:
            recs[k] = {**rec, "status": "dead_sku", "bin": None, "method": "zero_no_order", "forecast": 0.0,
                       "mase_pipeline": None}
            continue
        routed = route(s, PLANNING_MONTH, forecaster, allow_placeholder=allow_placeholder)
        m = float("nan")
        if score_pipeline:
            train, holdout = train_holdout_split(s, holdout_fraction=HOLDOUT_FRACTION)
            sc = rolling_one_step(s, list(holdout.index), forecaster, force_bin=routed["bin"],
                                  allow_placeholder=allow_placeholder)
            m = mase(sc["actual"].to_numpy(), sc["value"].to_numpy(), naive_scale(train.to_numpy(dtype=float)))
        recs[k] = {**rec, "status": "ok", "bin": routed["bin"], "method": routed["method"], "forecast": routed["value"],
                   "ma3_value": routed["ma3_value"], "backup_fired": routed["backup_fired"],
                   "mase_pipeline": None if not np.isfinite(m) else m}
    return recs, series_by_key, forecaster


def check_against_live(recs: dict, live: pd.DataFrame) -> list:
    """Mismatches vs public.forecast_result (empty list = reproduced). forecast_value is
    NUMERIC(14,2); mase is NUMERIC(10,3), capped at 999.999 on write (_clean_metric)."""
    lv = live.set_index("product_key")
    bad = []
    if set(lv.index) != set(recs):
        bad.append(("key set", sorted(set(lv.index) ^ set(recs))[:10]))
    for k, r in recs.items():
        if k not in lv.index:
            continue
        L = lv.loc[k]
        if L["status"] != r["status"] or (r["status"] == "ok" and L["method"] != r["method"]):
            bad.append((k, "status/method", (L["status"], L["method"]), (r["status"], r["method"])))
        if abs(float(L["forecast_value"]) - r["forecast"]) > 0.0051:
            bad.append((k, "forecast_value", L["forecast_value"], round(r["forecast"], 4)))
        if r["status"] == "ok":
            mine = None if r["mase_pipeline"] is None else min(r["mase_pipeline"], 999.999)
            theirs = None if pd.isna(L["mase"]) else float(L["mase"])
            if (mine is None) != (theirs is None) or (mine is not None and abs(mine - theirs) > 0.00051):
                bad.append((k, "mase", theirs, None if mine is None else round(mine, 4)))
    return bad


# --------------------------------------------------------------------------- #
# Verdict holdout: common window, else the stored 20% split (reports/diagnostics/README.md)
# --------------------------------------------------------------------------- #
def verdict_holdouts(recs_real: dict, series_real: dict) -> dict:
    """{product_key: {months, scale, source}} for every REAL 'ok' SKU, built from the REAL
    series only, so a simulation scored with it is on the same months and the same scale."""
    out = {}
    for k, r in recs_real.items():
        if r["status"] != "ok":
            continue
        s = series_real[k]
        present = [m for m in WINDOW if m in s.index]
        scale_c = naive_scale(s[s.index < WINDOW_START].to_numpy(dtype=float))
        if present and (s.index < WINDOW_START).any() and scale_c > 0:
            out[k] = {"months": present, "scale": scale_c, "source": "common"}
        else:
            train, holdout = train_holdout_split(s, holdout_fraction=HOLDOUT_FRACTION)
            out[k] = {"months": list(holdout.index), "scale": naive_scale(train.to_numpy(dtype=float)),
                      "source": "pipeline (20% split)"}
    return out


def score_holdouts(recs: dict, series: dict, forecaster: GlobalForecaster, holdouts: dict,
                   allow_placeholder: bool = False) -> dict:
    """{product_key: DataFrame(month, actual, value, ma3, method, backup_fired)} - the router
    with the SKU's own served bin held fixed, one step ahead, on the given months."""
    out = {}
    for k, h in holdouts.items():
        r = recs[k]
        if r["status"] != "ok":
            continue
        out[k] = rolling_one_step(series[k], h["months"], forecaster, force_bin=r["bin"], allow_placeholder=allow_placeholder)
    return out


def verdict(m) -> str | None:
    if m is None or not np.isfinite(m):
        return None
    return "not fit" if m >= NOT_FIT_MASE else ("borderline" if m >= BORDERLINE_MASE else "fit")


# --------------------------------------------------------------------------- #
# Part 2: in-sample fit, per served model
# --------------------------------------------------------------------------- #
def _guarded(value, ma3, history: np.ndarray):
    """router.route()'s guard order: no number -> MA3; above the history's max -> MA3; below zero -> MA3."""
    if value is None or value > float(history.max()) or value < 0:
        return max(0.0, ma3)
    return value


def tsb_fitted(train: pd.Series) -> np.ndarray:
    """One-step fitted values of baseline.tsb_forecast's recursion over the training window:
    states initialised from the whole window's averages (the in-sample estimate), forecast for
    month t = demand x probability before month t updates them."""
    x = train.to_numpy(dtype=float)
    demand = x[x > 0].mean() if (x > 0).any() else 0.0
    prob = (x > 0).mean()
    fitted = np.empty(len(x))
    for i, v in enumerate(x):
        fitted[i] = demand * prob
        if v > 0:
            demand += baseline.TSB_ALPHA_DEMAND * (v - demand)
            prob += baseline.TSB_ALPHA_PROB * (1 - prob)
        else:
            prob += baseline.TSB_ALPHA_PROB * (0 - prob)
    return fitted


def in_sample(series: pd.Series, bin_name: str, holdout_start: pd.Timestamp, forecaster: GlobalForecaster) -> pd.DataFrame:
    """In-sample one-step fits for the training window (months before the holdout), from the
    MIN_HISTORY-th month after first sale on (XGBoost's own first trainable month, used for every
    model so all four see the same months). Columns: month, actual, served_fit, ma3_fit.
      short  MA3: mean of the 3 months before t (MA3 has no fitted parameters, so its in-sample
                  error is its one-step error on the training months).
      medium TSB: tsb_fitted() over the training window, router guards applied.
      long   XGBoost+MA3: the booster trained on every pool row before the holdout (the model the
                  holdout's first month uses) predicting this SKU's own training rows, averaged
                  with MA3; router guards applied (no XGBoost number -> MA3)."""
    train = from_first_sale(series[series.index < holdout_start])
    if len(train) <= MIN_HISTORY:
        return pd.DataFrame(columns=["month", "actual", "served_fit", "ma3_fit"])
    values = train.to_numpy(dtype=float)
    tsb = tsb_fitted(train) if bin_name == "medium" else None
    booster = forecaster.booster_for(holdout_start)[0] if bin_name == "long" else None
    rows = []
    for t in range(MIN_HISTORY, len(train)):
        hist = values[:t]
        ma3 = max(0.0, ma3_value(pd.Series(hist)))
        if bin_name == "short":
            fit = ma3
        elif bin_name == "medium":
            fit = _guarded(float(tsb[t]), ma3, hist)
        else:
            xgb_v = None
            if booster is not None:
                feats, scale = build_features(hist, train.index[t])
                if feats is not None:
                    import xgboost as xgb
                    xgb_v = float(booster.predict(xgb.DMatrix(feats.reshape(1, -1)))[0]) * scale
            fit = _guarded(None if xgb_v is None else (xgb_v + ma3) / 2.0, ma3, hist)
        rows.append({"month": train.index[t], "actual": values[t], "served_fit": fit, "ma3_fit": ma3})
    return pd.DataFrame(rows)


def diagnose(recs: dict, series: dict, forecaster: GlobalForecaster, holdouts: dict, scored: dict,
             names: pd.DataFrame) -> pd.DataFrame:
    nm = names.set_index("product_key")
    rows = []
    for k, h in holdouts.items():
        r, sc = recs[k], scored[k]
        a, p, m3 = sc["actual"].to_numpy(), sc["value"].to_numpy(), sc["ma3"].to_numpy()
        ins = in_sample(series[k], r["bin"], h["months"][0], forecaster)
        hold_mase, hold_ma3 = mase(a, p, h["scale"]), mase(a, m3, h["scale"])
        if len(ins):
            ins_mase = mase(ins["actual"].to_numpy(), ins["served_fit"].to_numpy(), h["scale"])
            ins_ma3 = mase(ins["actual"].to_numpy(), ins["ma3_fit"].to_numpy(), h["scale"])
        else:
            ins_mase = ins_ma3 = float("nan")
        e = p - a
        n = len(e)
        sd = float(np.std(e, ddof=1)) if n > 1 else float("nan")
        t = float(np.mean(e) / (sd / np.sqrt(n))) if n > 1 and sd > 0 else float("nan")
        ratio = hold_mase / ins_mase if np.isfinite(ins_mase) and ins_mase > 0 else float("nan")
        ma3_ratio = hold_ma3 / ins_ma3 if np.isfinite(ins_ma3) and ins_ma3 > 0 else float("nan")
        rows.append({
            "scope": SCOPE_NOTE, "product_key": k, "sku_code": nm.loc[k, "sku_code"], "product_name": nm.loc[k, "product_name"],
            "bin": r["bin"], "served_model": r["method"], "verdict_source": h["source"],
            "holdout_first": h["months"][0].strftime("%Y-%m"), "holdout_months": n, "insample_months": int(len(ins)),
            "mase_scale": h["scale"], "holdout_mase": hold_mase, "insample_mase": ins_mase, "ratio": ratio,
            "ma3_holdout_mase": hold_ma3, "ma3_insample_mase": ins_ma3, "ma3_ratio": ma3_ratio,
            "holdout_wape": wape(a, p), "mean_error": float(np.mean(e)), "sd_error": sd, "t_stat": t,
            "sum_forecast_minus_actual": float(e.sum()), "sum_actual": float(a.sum()),
            "verdict": verdict(hold_mase),
        })
    df = pd.DataFrame(rows)
    ma3_p95 = float(np.nanpercentile(df["ma3_ratio"], MA3_CONTROL_PERCENTILE))
    df["ma3_p95_ratio"] = ma3_p95

    def overfit_status(r):
        if r.served_model == "ma3":
            return CONTROL
        if not (np.isfinite(r.ratio) and np.isfinite(r.ma3_ratio)):
            return NO_INSAMPLE
        return "overfit" if (r.ratio > ma3_p95 and r.ratio > r.ma3_ratio) else "not overfit"

    df["overfit_status"] = df.apply(overfit_status, axis=1)
    df["overfit"] = pd.array([True if s == "overfit" else False if s == "not overfit" else pd.NA
                              for s in df["overfit_status"]], dtype="boolean")
    df["underfit"] = (df["insample_mase"] >= UNDERFIT_MASE) & (df["holdout_mase"] >= UNDERFIT_MASE)
    df["bias_tested"] = df["holdout_months"] == BIAS_MONTHS
    df["biased"] = df["bias_tested"] & (df["t_stat"].abs() >= BIAS_T)
    df["bias_direction"] = np.where(df["biased"], np.where(df["mean_error"] > 0, "over-forecast", "under-forecast"), "")
    return df


def classify(df: pd.DataFrame) -> pd.DataFrame:
    def yes(v) -> bool:
        return v is not pd.NA and v is not None and bool(v)

    def label(r):
        parts = [x for x, f in (("overfit", r.overfit), ("underfit", r.underfit), (f"biased ({r.bias_direction})", r.biased))
                 if yes(f)]
        if parts:
            return " + ".join(parts)
        if not np.isfinite(r.insample_mase):
            return "fit not testable (no in-sample months)"
        return "none (overfit not assessable: MA3 is the control)" if r.overfit_status == CONTROL else "none of the three"
    out = df[["scope", "product_key", "sku_code", "product_name", "bin", "served_model", "verdict_source", "verdict",
              "holdout_mase", "insample_mase", "ratio", "ma3_ratio", "ma3_p95_ratio", "overfit_status", "overfit",
              "underfit", "bias_tested", "t_stat", "biased", "bias_direction"]].copy()
    out["fit_class"] = df.apply(label, axis=1)
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", help="optional pickle of the loaded rows (read if present, else written)")
    inp = cached_inputs(ap.parse_args().cache, load_inputs)
    keys = [int(k) for k in inp["tier_a"]["product_key"]]
    print(f"[{SCOPE_NOTE}]")
    print(f"Tier A as of {ABC_PERIOD}: {len(keys)} SKUs (expected 132); real demand rows {len(inp['demand'])}; "
          f"live forecast_result rows at {PLANNING_MONTH.date()}: {len(inp['live'])}")
    recs, series, fc = run_cohort(inp["demand"], keys)
    bad = check_against_live(recs, inp["live"])
    n_ok = sum(r["status"] == "ok" for r in recs.values())
    print(f"REPRODUCTION vs live forecast_result: {len(recs) - len({b[0] for b in bad})}/{len(recs)} rows match; "
          f"stored MASE checked on {n_ok} 'ok' rows; mismatches={len(bad)}")
    if bad:
        for b in bad[:20]:
            print("   MISMATCH", b)
        sys.exit("STOP: the real run does not reproduce live forecast_result")

    hold = verdict_holdouts(recs, series)
    scored = score_holdouts(recs, series, fc, hold)
    df = diagnose(recs, series, fc, hold, scored, inp["tier_a"])
    cls = classify(df)
    p95 = float(df["ma3_p95_ratio"].iloc[0])
    os.makedirs(HERE, exist_ok=True)
    df.to_csv(os.path.join(HERE, "per_sku.csv"), index=False)
    cls.to_csv(os.path.join(HERE, "classified.csv"), index=False)

    print(f"scored {len(df)} SKUs: common {int((df.verdict_source == 'common').sum())}, "
          f"20% split {int((df.verdict_source != 'common').sum())}; verdicts {df.verdict.value_counts().to_dict()}")
    print(f"MA3 control: p{MA3_CONTROL_PERCENTILE} of MA3's own ratio = {p95:.3f} over {int(df.ma3_ratio.notna().sum())} SKUs "
          f"with a defined ratio; overfit_status {df.overfit_status.value_counts().to_dict()}")
    print(f"non-MA3 products above p95 only (not above own MA3 ratio): "
          f"{int(((df.served_model != 'ma3') & (df.ratio > p95) & ~(df.ratio > df.ma3_ratio)).sum())}; "
          f"above own MA3 ratio only (not above p95): {int(((df.served_model != 'ma3') & ~(df.ratio > p95) & (df.ratio > df.ma3_ratio)).sum())}")
    print(f"underfit {int(df.underfit.sum())} | bias tested {int(df.bias_tested.sum())}, biased {int(df.biased.sum())}")
    print("pooled bias sum(f-a)/sum(a) by served model:")
    for m, g in df.groupby("served_model"):
        print(f"   {m:<12} n={len(g):>3}  {g.sum_forecast_minus_actual.sum() / g.sum_actual.sum():+.4f}")
    print("\nOVERFIT:")
    print(df[df.overfit_status == "overfit"][["sku_code", "product_name", "served_model", "verdict", "insample_mase",
                                              "holdout_mase", "ratio", "ma3_ratio", "insample_months"]]
          .sort_values("ratio", ascending=False).to_string(index=False, float_format=lambda v: f"{v:.3f}"))
    print("\nBIASED:")
    print(df[df.biased][["sku_code", "product_name", "served_model", "mean_error", "t_stat", "bias_direction"]]
          .to_string(index=False, float_format=lambda v: f"{v:.2f}"))
    unfit = cls[cls.verdict == "not fit"]
    print(f"\nNOT FIT ({len(unfit)}) by bin x class:")
    print(pd.crosstab(unfit["fit_class"], unfit["bin"], margins=True).to_string())
    return df, cls, p95


if __name__ == "__main__":
    main()
