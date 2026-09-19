"""
scripts.model_bakeoff - forecasting model bake-off on real Unilever
per-SKU demand. Report-only, never writes to the database.

Companion diagnostic to scripts/run_baseline_forecast.py. That script ships
the production picks (MA3 / Naive / SBA); this one benchmarks 17 candidate
models against each other so the pick stays evidence-based and re-runnable.

Backtest
--------
Rolling-origin, 1-step-ahead, over the last --test-months months (default 6).
Refit at every origin. Forecasts clipped at 0. Metrics per SKU:
  - MAPE   (points with actual == 0 excluded; median reported, mean is
           unusable here - near-zero actuals blow it to 5-90)
  - MASE   (lag-1 naive scale, computed on the pre-first-origin window)
  - sMAPE  (bounded 0-2; the honest cross-run metric - unlike MASE it does
           not depend on the training-window volatility)

Models
------
naive, seasonal-naive(12), mean, drift, MA3, MA6, Croston, SBA(alpha .1),
SBA(alpha .3), TSB, SES, Holt, damped Holt, Holt-Winters additive(12),
Theta, SARIMA(1,1,1)(0,1,1)12, SARIMA(1,1,1).

Cohorts
-------
  --cohort tierA  (default) : the real Tier A set - product_keys with
      tier='A' in the latest real ABC_Classification period (2026-02).
  --cohort all              : every Unilever SKU with >= --min-train + 2
      months of span and >= 6 non-zero months.

Data source
-----------
Real path (default): Unilever_SKU_Demand_Fact_Real (the _Real view, which
structurally excludes is_demo=true rows - see CLAUDE.md data-interface rule).

--with-synthetic (DIAGNOSTIC ONLY): additionally reads the base
unilever_sku_demand_fact table and prepends the synthetic is_demo=true
months (<= 2022-12) to each series as training context, still testing on
the last --test-months REAL months. is_demo rows are frontend-validation-
approved ONLY, never reported/manuscript results (CLAUDE.md rules 2 & 3).
This flag exists to demonstrate that the synthetic history does not help -
see reports/MODEL_BAKEOFF_UNILEVER.md.

Usage
-----
  python -m scripts.model_bakeoff                       # Tier A, real only
  python -m scripts.model_bakeoff --cohort all
  python -m scripts.model_bakeoff --with-synthetic      # diagnostic what-if
"""
from __future__ import annotations

import argparse
import os
import time
import warnings

import numpy as np
import pandas as pd
import psycopg2
from dotenv import load_dotenv

warnings.simplefilter("ignore")

from statsmodels.tsa.holtwinters import ExponentialSmoothing, Holt, SimpleExpSmoothing
from statsmodels.tsa.forecasting.theta import ThetaModel
from statsmodels.tsa.statespace.sarimax import SARIMAX

SEAS = 12
REAL_START = "2023-01"          # first month of genuine per-SKU Unilever data
ABC_PERIOD = "2026-02"          # latest all-real ABC_Classification period
REPORTS = os.path.join(os.path.dirname(__file__), os.pardir, "reports")


# --------------------------------------------------------------------------- #
# DB
# --------------------------------------------------------------------------- #
def connect():
    load_dotenv()
    dsn = os.environ.get("SUPABASE_DIRECT_URL") or os.environ["SUPABASE_DB_URL"]
    conn = psycopg2.connect(dsn, options="-c statement_timeout=0")
    conn.set_session(readonly=True)
    return conn


def fetch(with_synthetic: bool):
    conn = connect()
    cur = conn.cursor()
    if with_synthetic:
        # base table, is_demo included - DIAGNOSTIC path only
        cur.execute("""
            SELECT product_key, calendar_month, COALESCE(quantity_sold, 0) AS q, is_demo
            FROM unilever_sku_demand_fact
            WHERE calendar_month <= %s
            ORDER BY product_key, calendar_month
        """, (_last_real_month(cur),))
        df = pd.DataFrame(cur.fetchall(), columns=["product_key", "calendar_month", "q", "is_demo"])
    else:
        cur.execute("""
            SELECT product_key, calendar_month, COALESCE(quantity_sold, 0) AS q
            FROM unilever_sku_demand_fact_real
            ORDER BY product_key, calendar_month
        """)
        df = pd.DataFrame(cur.fetchall(), columns=["product_key", "calendar_month", "q"])
        df["is_demo"] = False
    df["q"] = df["q"].astype(float)

    cur.execute("""
        SELECT product_key FROM abc_classification
        WHERE principal = 'unilever' AND classification_period = %s AND tier = 'A'
          AND method = 'single'
    """, (ABC_PERIOD,))
    tier_a = sorted({r[0] for r in cur.fetchall()})

    cur.execute("SELECT product_key, sku_code, product_name FROM product_dimension WHERE principal = 'unilever'")
    names = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
    conn.close()
    return df, tier_a, names


def _last_real_month(cur) -> str:
    cur.execute("SELECT MAX(calendar_month) FROM unilever_sku_demand_fact_real")
    return cur.fetchone()[0]


# --------------------------------------------------------------------------- #
# series
# --------------------------------------------------------------------------- #
def build_series(g: pd.DataFrame) -> pd.Series:
    idx = pd.to_datetime(g["calendar_month"] + "-01")
    s = pd.Series(g["q"].to_numpy(float), index=idx).sort_index()
    return s.resample("MS").asfreq().fillna(0.0)


# --------------------------------------------------------------------------- #
# models: fn(train: np.ndarray) -> float  (1-step point forecast)
# --------------------------------------------------------------------------- #
def m_naive(x):   return x[-1]
def m_snaive(x):  return x[-SEAS] if len(x) >= SEAS else x[-1]
def m_mean(x):    return x.mean()
def m_drift(x):   return x[-1] if len(x) < 2 else x[-1] + (x[-1] - x[0]) / (len(x) - 1)
def m_ma3(x):     return x[-3:].mean()
def m_ma6(x):     return x[-6:].mean()


def _croston(x, alpha, sba=False):
    z = p = None
    q = 1
    f = 0.0
    for v in x:
        if v > 0:
            if z is None:
                z, p = v, float(q)
            else:
                z += alpha * (v - z)
                p += alpha * (q - p)
            f = z / p if p else 0.0
            q = 1
        else:
            q += 1
    if sba:
        f *= (1 - alpha / 2)
    return f


def m_croston(x): return _croston(x, 0.1)
def m_sba(x):     return _croston(x, 0.1, sba=True)
def m_sba_a3(x):  return _croston(x, 0.3, sba=True)


def m_tsb(x):
    a, b = 0.3, 0.1
    demand = x[x > 0].mean() if (x > 0).any() else 0.0
    prob = (x > 0).mean()
    for v in x:
        if v > 0:
            demand += a * (v - demand)
            prob += b * (1 - prob)
        else:
            prob += b * (0 - prob)
    return demand * prob


def _statsmodels(fn):
    def inner(x):
        try:
            s = pd.Series(x, index=pd.date_range("2000-01-01", periods=len(x), freq="MS"))
            return float(fn(s))
        except Exception:
            return np.nan
    return inner


m_ses = _statsmodels(lambda s: SimpleExpSmoothing(s, initialization_method="estimated").fit().forecast(1).iloc[0])
m_holt = _statsmodels(lambda s: Holt(s, initialization_method="estimated").fit().forecast(1).iloc[0])
m_holt_damped = _statsmodels(lambda s: Holt(s, damped_trend=True, initialization_method="estimated").fit().forecast(1).iloc[0])


def m_hw_add(x):
    try:
        if len(x) < 2 * SEAS:
            return np.nan
        s = pd.Series(x, index=pd.date_range("2000-01-01", periods=len(x), freq="MS"))
        return float(ExponentialSmoothing(
            s, trend="add", seasonal="add", seasonal_periods=SEAS,
            initialization_method="estimated").fit().forecast(1).iloc[0])
    except Exception:
        return np.nan


def m_theta(x):
    try:
        s = pd.Series(x, index=pd.date_range("2000-01-01", periods=len(x), freq="MS"))
        period = SEAS if len(x) >= SEAS + 2 else 1
        return float(ThetaModel(s, period=period).fit().forecast(1).iloc[0])
    except Exception:
        return np.nan


def _sarima(order, seasonal_order):
    def inner(x):
        try:
            if seasonal_order[3] and len(x) < 2 * seasonal_order[3] + 4:
                return np.nan
            s = pd.Series(x, index=pd.date_range("2000-01-01", periods=len(x), freq="MS"))
            res = SARIMAX(s, order=order, seasonal_order=seasonal_order,
                          enforce_stationarity=False, enforce_invertibility=False).fit(disp=0)
            return float(res.forecast(1).iloc[0])
        except Exception:
            return np.nan
    return inner


m_sarima_seasonal = _sarima((1, 1, 1), (0, 1, 1, 12))
m_sarima_plain = _sarima((1, 1, 1), (0, 0, 0, 0))

MODELS = {
    "naive": m_naive, "snaive12": m_snaive, "mean": m_mean, "drift": m_drift,
    "ma3": m_ma3, "ma6": m_ma6,
    "croston": m_croston, "sba": m_sba, "sba_a3": m_sba_a3, "tsb": m_tsb,
    "ses": m_ses, "holt": m_holt, "holt_damped": m_holt_damped,
    "hw_add12": m_hw_add, "theta": m_theta,
    "sarima_seasonal": m_sarima_seasonal, "sarima_plain": m_sarima_plain,
}


# --------------------------------------------------------------------------- #
# backtest
# --------------------------------------------------------------------------- #
def backtest_sku(series: pd.Series, test_months: int, min_train: int,
                 real_test_index: pd.DatetimeIndex | None) -> dict | None:
    """Rolling-origin 1-step-ahead. If real_test_index is given (the
    --with-synthetic path), origins are pinned to those real months;
    otherwise the last `test_months` observations of the series."""
    if real_test_index is not None:
        origins = [t for t in real_test_index[-test_months:] if t in series.index]
    else:
        n = len(series)
        origins = list(series.index[max(min_train, n - test_months):n])
    if len(origins) < 3:
        return None

    actuals = np.array([series.loc[t] for t in origins], dtype=float)
    base = series[series.index < origins[0]].to_numpy(float)
    scale = float(np.mean(np.abs(np.diff(base)))) if len(base) > 1 else 0.0

    out = {}
    for name, fn in MODELS.items():
        preds = []
        for t in origins:
            tr = series[series.index < t].to_numpy(float)
            if len(tr) < 12:
                preds.append(np.nan)
                continue
            f = fn(tr)
            preds.append(max(0.0, f) if np.isfinite(f) else np.nan)
        preds = np.array(preds, dtype=float)
        if not np.isfinite(preds).all():
            out[name] = dict(mape=np.nan, mase=np.nan, smape=np.nan)
            continue
        ae = np.abs(actuals - preds)
        nz = actuals > 0
        mape = float(np.mean(ae[nz] / actuals[nz])) if nz.any() else np.nan
        den = np.abs(actuals) + np.abs(preds)
        sm = den > 0
        smape = float(np.mean(2 * ae[sm] / den[sm])) if sm.any() else np.nan
        mase = float(np.mean(ae) / scale) if scale > 0 else np.nan
        out[name] = dict(mape=mape, mase=mase, smape=smape)
    return out


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #
def summarize(df: pd.DataFrame, label: str) -> None:
    print(f"\n{'=' * 84}\n{label}   (n={len(df)} SKUs)\n{'=' * 84}")
    print(f"{'model':<16}{'MAPEmed':>9}{'MASEmed':>9}{'sMAPEmed':>10}"
          f"{'MAPE<.20':>10}{'beat naive':>12}{'n':>5}")
    naive_mape = df["naive_mape"]
    for m in MODELS:
        c = f"{m}_mape"
        col = df[c]
        valid = col.notna()
        if valid.sum() == 0:
            print(f"{m:<16}{'--':>9}")
            continue
        mase = df[f"{m}_mase"]
        smape = df[f"{m}_smape"]
        pair = pd.DataFrame({"a": col, "b": naive_mape}).dropna()
        beat = (pair["a"] < pair["b"]).mean() * 100 if len(pair) else np.nan
        print(f"{m:<16}{col[valid].median():>9.3f}"
              f"{mase[mase.notna()].median():>9.3f}"
              f"{smape[smape.notna()].median():>10.3f}"
              f"{(col[valid] < 0.20).mean() * 100:>9.0f}%"
              f"{beat:>11.0f}%{int(valid.sum()):>5}")

    for metric in ("mape", "mase", "smape"):
        cols = [f"{m}_{metric}" for m in MODELS]
        sub = df[cols].dropna(how="all")
        win = sub.idxmin(axis=1).str.replace(f"_{metric}", "", regex=False)
        vc = win.value_counts()
        print(f"\n--- best model per SKU by {metric.upper()}  (n={len(sub)}) ---")
        for name, cnt in vc.items():
            print(f"  {name:<16}{cnt:>4}   {cnt / len(sub) * 100:>5.1f}%")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cohort", choices=["tierA", "all"], default="tierA")
    ap.add_argument("--with-synthetic", action="store_true",
                    help="DIAGNOSTIC: prepend synthetic <=2022-12 history. Not for reported results.")
    ap.add_argument("--test-months", type=int, default=6)
    ap.add_argument("--min-train", type=int, default=12)
    ap.add_argument("--out", default=None, help="CSV path (default under reports/).")
    args = ap.parse_args()

    raw, tier_a, names = fetch(args.with_synthetic)
    print(f"demand rows: {len(raw)}   SKUs: {raw.product_key.nunique()}   "
          f"Tier A ({ABC_PERIOD}): {len(tier_a)}   with_synthetic={args.with_synthetic}")

    series = {pk: build_series(g) for pk, g in raw.groupby("product_key")}

    real_test_index = None
    if args.with_synthetic:
        real_months = sorted(m for m in raw["calendar_month"].unique() if m >= REAL_START)
        real_test_index = pd.to_datetime([m + "-01" for m in real_months])
        # quick seasonality contrast so the caller sees why synthetic hurts
        syn = [m for m in raw["calendar_month"].unique() if m <= "2022-12"]
        _acf_contrast(series, syn, real_months)

    if args.cohort == "tierA":
        pks = [pk for pk in tier_a if pk in series]
    else:
        pks = [pk for pk in sorted(series)
               if len(series[pk]) >= args.min_train + 2 and (series[pk] > 0).sum() >= 6]
    print(f"cohort '{args.cohort}': {len(pks)} SKUs")

    rows = []
    t0 = time.time()
    for i, pk in enumerate(pks):
        r = backtest_sku(series[pk], args.test_months, args.min_train, real_test_index)
        if r is None:
            continue
        rec = {"product_key": pk,
               "sku_code": names.get(pk, (None, None))[0],
               "product_name": names.get(pk, (None, None))[1],
               "months": len(series[pk]),
               "nonzero": int((series[pk] > 0).sum())}
        for m, d in r.items():
            rec[f"{m}_mape"] = d["mape"]
            rec[f"{m}_mase"] = d["mase"]
            rec[f"{m}_smape"] = d["smape"]
        rows.append(rec)
        if (i + 1) % 40 == 0:
            print(f"  {i + 1}/{len(pks)}  ({time.time() - t0:.0f}s)")

    df = pd.DataFrame(rows)
    out = args.out or os.path.join(
        REPORTS,
        f"model_bakeoff_unilever_{args.cohort}"
        f"{'_withsynth' if args.with_synthetic else ''}.csv",
    )
    df.to_csv(out, index=False)
    print(f"\nwrote {out}  ({len(df)} SKUs)")

    summarize(df, f"COHORT {args.cohort}"
                  f"{'  (+ synthetic 2021-22 prepended - DIAGNOSTIC)' if args.with_synthetic else '  (real only)'}")


def _acf_contrast(series: dict, synth_months, real_months) -> None:
    def portfolio(months):
        target = set(pd.to_datetime([m + "-01" for m in months]))
        tot = None
        for s in series.values():
            s2 = s[s.index.isin(target)]
            tot = s2 if tot is None else tot.add(s2, fill_value=0)
        return tot.sort_index()

    def acf12(x):
        x = np.asarray(x, float) - np.mean(x)
        if len(x) <= SEAS:
            return np.nan
        return float(np.sum(x[SEAS:] * x[:-SEAS]) / np.sum(x * x))

    p_syn, p_real = portfolio(synth_months), portfolio(real_months)
    print(f"portfolio ACF(lag 12): synthetic {acf12(p_syn):+.3f}   real {acf12(p_real):+.3f}")
    print(f"portfolio CV:          synthetic {p_syn.std() / p_syn.mean():.3f}   "
          f"real {p_real.std() / p_real.mean():.3f}")


if __name__ == "__main__":
    main()
