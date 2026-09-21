"""
scripts.arima_bakeoff - auto-ARIMA vs the simple methods, real Unilever Tier A.

The main bake-off (scripts/model_bakeoff.py) tests two FIXED SARIMA specs.
This one gives ARIMA its best shot: per-SKU order selection over
(p,d,q) x seasonal (P,D,Q,12), chosen once by AICc on the pre-test
training window (Hyndman-Khandakar style), then the same rolling-origin
1-step backtest, refitting the chosen order at each of the last 6 real
months. Head-to-head against naive / MA3 / SBA(alpha=.3) / Theta / SES.

Report-only. Reads Unilever_SKU_Demand_Fact_Real (the _Real view).

Result (see reports/MODEL_BAKEOFF_UNILEVER.md, Addendum 2): auto-ARIMA is
worse than every incumbent except naive - 38 months is too short for the
AR/MA/seasonal machinery, and AICc keeps picking seasonal models that
overfit. ARIMA is ruled out; order selection does not rescue it.

Usage:  python -m scripts.arima_bakeoff
"""
from __future__ import annotations

import os
import sys
import time
import warnings

import numpy as np
import pandas as pd
import psycopg2
from dotenv import load_dotenv

warnings.simplefilter("ignore")

from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.forecasting.theta import ThetaModel
from statsmodels.tsa.holtwinters import SimpleExpSmoothing
from statsmodels.tsa.statespace.sarimax import SARIMAX

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))
from analytics.forecasting.diagnostic_metrics import mape, mase, naive_scale, smape, wape  # noqa: E402

SEAS = 12
TEST_H = 6
ABC_PERIOD = "2026-02"
OUT = os.path.join(os.path.dirname(__file__), os.pardir, "reports", "arima_bakeoff_unilever_tierA.csv")

NS_GRID = [(p, d, q) for p in (0, 1, 2) for d in (0, 1) for q in (0, 1, 2)]
SEAS_GRID = [(0, 0, 0, 0), (0, 1, 1, SEAS), (1, 1, 0, SEAS), (0, 1, 0, SEAS)]


def _connect():
    load_dotenv()
    last = None
    for dsn in (os.environ.get("SUPABASE_DB_URL"), os.environ.get("SUPABASE_DIRECT_URL")):
        if not dsn:
            continue
        try:
            c = psycopg2.connect(dsn, connect_timeout=15)
            c.set_session(readonly=True)
            return c
        except Exception as e:  # noqa: BLE001
            last = e
    raise last


def _fetch(with_synthetic: bool = False):
    c = _connect()
    cur = c.cursor()
    if with_synthetic:
        # DIAGNOSTIC: base table, is_demo included, capped at the last real
        # month so synthetic 2026-03.. never enters the series. Synthetic
        # months are 2021-01..2022-12 (see reports/MODEL_BAKEOFF_UNILEVER.md).
        cur.execute("""
            SELECT product_key, calendar_month, COALESCE(quantity_sold, 0), is_demo
            FROM unilever_sku_demand_fact
            WHERE calendar_month <= (SELECT MAX(calendar_month) FROM unilever_sku_demand_fact_real)
            ORDER BY 1, 2
        """)
    else:
        cur.execute("SELECT product_key, calendar_month, COALESCE(quantity_sold, 0), FALSE "
                    "FROM unilever_sku_demand_fact_real ORDER BY 1, 2")
    raw = pd.DataFrame(cur.fetchall(), columns=["pk", "m", "q", "is_demo"])
    raw["q"] = raw["q"].astype(float)
    raw["is_demo"] = raw["is_demo"].astype(bool)
    cur.execute("SELECT product_key FROM abc_classification "
                "WHERE principal = 'unilever' AND classification_period = %s AND tier = 'A' "
                "AND method = 'single'", (ABC_PERIOD,))
    tier_a = sorted({r[0] for r in cur.fetchall()})
    cur.execute("SELECT product_key, sku_code, product_name FROM product_dimension WHERE principal = 'unilever'")
    names = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
    c.close()
    return raw, tier_a, names


def _series(g):
    s = pd.Series(g["q"].to_numpy(float), index=pd.to_datetime(g["m"] + "-01")).sort_index()
    return s.resample("MS").asfreq().fillna(0.0)


def _aicc(res, n):
    k = len(res.params)
    return res.aic + (2 * k * (k + 1)) / max(n - k - 1, 1)


def select_order(train):
    n = len(train)
    y = pd.Series(train, index=pd.date_range("2000-01-01", periods=n, freq="MS"))
    best = None
    for (p, d, q) in NS_GRID:
        for so in (SEAS_GRID if n >= 2 * SEAS + 4 else [(0, 0, 0, 0)]):
            if so[3] and (p + d + q) > 3:      # keep seasonal models parsimonious
                continue
            try:
                if so[3]:
                    r = SARIMAX(y, order=(p, d, q), seasonal_order=so,
                                enforce_stationarity=False, enforce_invertibility=False).fit(disp=0)
                else:
                    r = ARIMA(y, order=(p, d, q)).fit()
                sc = _aicc(r, n)
                if np.isfinite(sc) and (best is None or sc < best[0]):
                    best = (sc, (p, d, q), so)
            except Exception:  # noqa: BLE001
                continue
    return best[1:] if best else ((0, 1, 1), (0, 0, 0, 0))


def arima_forecast(train, order, sorder):
    try:
        y = pd.Series(train, index=pd.date_range("2000-01-01", periods=len(train), freq="MS"))
        if sorder[3]:
            r = SARIMAX(y, order=order, seasonal_order=sorder,
                        enforce_stationarity=False, enforce_invertibility=False).fit(disp=0)
        else:
            r = ARIMA(y, order=order).fit()
        return float(r.forecast(1).iloc[0])
    except Exception:  # noqa: BLE001
        return np.nan


def _sba(x, a=0.3):
    z = p = None
    q = 1
    f = 0.0
    for v in x:
        if v > 0:
            if z is None:
                z, p = v, float(q)
            else:
                z += a * (v - z)
                p += a * (q - p)
            f = z / p if p else 0.0
            q = 1
        else:
            q += 1
    return f * (1 - a / 2)


def _theta(x):
    try:
        y = pd.Series(x, index=pd.date_range("2000-01-01", periods=len(x), freq="MS"))
        return float(ThetaModel(y, period=SEAS if len(x) >= SEAS + 2 else 1).fit().forecast(1).iloc[0])
    except Exception:  # noqa: BLE001
        return np.nan


def _ses(x):
    try:
        y = pd.Series(x, index=pd.date_range("2000-01-01", periods=len(x), freq="MS"))
        return float(SimpleExpSmoothing(y, initialization_method="estimated").fit().forecast(1).iloc[0])
    except Exception:  # noqa: BLE001
        return np.nan


INCUMBENTS = {
    "naive": lambda x: x[-1],
    "ma3": lambda x: x[-3:].mean(),
    "sba_a3": _sba,
    "theta": _theta,
    "ses": _ses,
}


def _metrics(actual, pred, scale):
    return mape(actual, pred), mase(actual, pred, scale), smape(actual, pred), wape(actual, pred)


def guard_divergent(preds, train_max):
    """Divergence guard: a forecast that is non-finite or above the maximum
    of its own training window becomes NaN. Returns (guarded preds, count) -
    the count is reported per arm, never dropped silently."""
    preds = np.asarray(preds, float)
    bad = ~np.isfinite(preds) | (preds > np.asarray(train_max, float))
    return np.where(bad, np.nan, preds), int(bad.sum())


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--with-synthetic", action="store_true",
                    help="DIAGNOSTIC: prepend synthetic 2021-22 history. Not for reported results.")
    ap.add_argument("--out", default=None, help="CSV path (default under reports/).")
    args = ap.parse_args()

    raw, tier_a, names = _fetch(args.with_synthetic)
    # R = real-only series: decides the cohort, origins, actuals and MASE
    # scale in BOTH arms. S = training input (real + synthetic prefix).
    R = {pk: _series(g) for pk, g in raw[~raw["is_demo"]].groupby("pk")}
    S = {pk: _series(g) for pk, g in raw.groupby("pk")} if args.with_synthetic else R
    pks = [pk for pk in tier_a if pk in R]
    out_path = args.out or (OUT.replace(".csv", "_withsynth.csv") if args.with_synthetic else OUT)
    print(f"Tier A ({ABC_PERIOD}): {len(pks)} SKUs   with_synthetic={args.with_synthetic}")

    rows = []
    t0 = time.time()
    for i, pk in enumerate(pks):
        xr = R[pk].to_numpy(float)
        n = len(xr)
        if n < 14:
            continue
        real_origins = list(range(max(12, n - TEST_H), n))
        if len(real_origins) < 3:
            continue
        x = S[pk].to_numpy(float)
        if S[pk].index[-1] != R[pk].index[-1]:
            raise RuntimeError(f"pk {pk}: training series does not end on the last real month")
        off = len(x) - n                      # synthetic-prefix length (0 in the real arm)
        origins = [off + t for t in real_origins]
        actual = np.array([xr[t] for t in real_origins])
        scale = naive_scale(xr[:real_origins[0]])

        order, sorder = select_order(x[:origins[0]])
        rec = {"pk": pk,
               "sku_code": names.get(pk, (None, None))[0],
               "product_name": names.get(pk, (None, None))[1],
               "months": n, "months_train": len(x), "nonzero": int((R[pk] > 0).sum()),
               "arima_order": f"{order}x{sorder if sorder[3] else '-'}"}

        preds, n_guarded = guard_divergent([arima_forecast(x[:t], order, sorder) for t in origins],
                                           [x[:t].max() for t in origins])
        preds = np.where(np.isfinite(preds), np.maximum(0, preds), np.nan)
        rec["arima_auto_guarded"] = n_guarded
        mp, ms, sp, wp = _metrics(actual, preds, scale) if np.isfinite(preds).all() else (np.nan,) * 4
        rec["arima_auto_mape"], rec["arima_auto_mase"], rec["arima_auto_smape"], rec["arima_auto_wape"] = mp, ms, sp, wp

        for name, fn in INCUMBENTS.items():
            pr = np.array([fn(x[:t]) for t in origins], float)
            pr = np.where(np.isfinite(pr), np.maximum(0, pr), np.nan)
            a, b, cc, w = _metrics(actual, pr, scale) if np.isfinite(pr).all() else (np.nan,) * 4
            rec[f"{name}_mape"], rec[f"{name}_mase"], rec[f"{name}_smape"], rec[f"{name}_wape"] = a, b, cc, w

        rows.append(rec)
        if (i + 1) % 20 == 0:
            print(f"  {i + 1}/{len(pks)}  ({time.time() - t0:.0f}s)")

    df = pd.DataFrame(rows)
    df.to_csv(out_path, index=False)
    print(f"\nwrote {out_path}  ({len(df)} SKUs)\n")
    g = df["arima_auto_guarded"]
    print(f"divergence guard arima_auto: {int(g.sum())} forecasts -> NaN across {int((g > 0).sum())} SKUs "
          f"(with_synthetic={args.with_synthetic})\n")

    models = ["arima_auto", "naive", "ma3", "sba_a3", "theta", "ses"]
    print(f"{'model':<14}{'MAPEmed':>9}{'MASEmed':>9}{'sMAPEmed':>10}{'MAPE<.20':>10}{'beat naive':>12}{'n':>5}")
    nv = df["naive_mape"]
    for m in models:
        col = df[f"{m}_mape"]
        v = col.notna()
        if v.sum() == 0:
            continue
        ms = df[f"{m}_mase"]
        sp = df[f"{m}_smape"]
        pair = pd.DataFrame({"a": col, "b": nv}).dropna()
        beat = (pair.a < pair.b).mean() * 100 if len(pair) else np.nan
        print(f"{m:<14}{col[v].median():>9.3f}{ms[ms.notna()].median():>9.3f}"
              f"{sp[sp.notna()].median():>10.3f}{(col[v] < 0.2).mean() * 100:>9.0f}%"
              f"{beat:>11.0f}%{int(v.sum()):>5}")

    for metric in ("mase", "smape"):
        cols = [f"{m}_{metric}" for m in models]
        sub = df[cols].dropna(how="all")
        win = sub.idxmin(axis=1).str.replace(f"_{metric}", "", regex=False)
        print(f"\n--- best per SKU by {metric.upper()} (n={len(sub)}) ---")
        for k, vv in win.value_counts().items():
            print(f"  {k:<14}{vv:>3}  {vv / len(sub) * 100:>5.1f}%")

    for opp in ("sba_a3", "ma3", "theta"):
        d = df[["arima_auto_smape", f"{opp}_smape"]].dropna()
        print(f"arima_auto sMAPE < {opp}: {(d.iloc[:, 0] < d.iloc[:, 1]).mean() * 100:.0f}%  (n={len(d)})")

    print("\nselected orders (top 10):")
    print(df["arima_order"].value_counts().head(10).to_string())


if __name__ == "__main__":
    main()
