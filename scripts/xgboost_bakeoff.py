"""
scripts.xgboost_bakeoff - global gradient-boosted-tree forecaster vs the
simple methods, real Unilever Tier A. Report-only.

XGBoost is not a time-series model - it needs engineered features. This
builds ONE global model across all Tier A SKUs (not one per SKU - 31
months is far too short to fit trees per series), with lag / rolling /
calendar features, refit at each of the last 6 real months (rolling
origin, 1-step-ahead). Compared head-to-head against naive / MA3 /
SBA(a=.3) / Theta.

  python -m scripts.xgboost_bakeoff                  # real data only
  python -m scripts.xgboost_bakeoff --with-synthetic # + synthetic 2021-22 in TRAINING only
"""
from __future__ import annotations

import argparse
import os
import sys
import warnings

import numpy as np
import pandas as pd
import psycopg2
from dotenv import load_dotenv
import xgboost as xgb

warnings.simplefilter("ignore")
load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))
from analytics.forecasting.diagnostic_metrics import mape, mase, naive_scale, smape, wape  # noqa: E402
from analytics.params import abc_method  # noqa: E402

SEAS = 12
TEST_H = 6
ABC_PERIOD = "2026-02"
REPORTS = os.path.join(os.path.dirname(__file__), os.pardir, "reports")

# native xgboost API (no sklearn dependency)
XGB_PARAMS = {"max_depth": 4, "eta": 0.04, "subsample": 0.85, "colsample_bytree": 0.85,
              "min_child_weight": 3, "lambda": 1.0, "objective": "reg:squarederror", "nthread": 4}
XGB_ROUNDS = 400


def _connect():
    from analytics.config import long_read_db_url
    # One URL, no fall-through to another database on a failed connection (2026-11-11).
    c = psycopg2.connect(long_read_db_url(), connect_timeout=15)
    c.cursor().execute("SET TRANSACTION READ ONLY")  # transaction-scoped, never session-level (pooler leak)
    return c


def _fetch(with_synthetic: bool):
    c = _connect()
    cur = c.cursor()
    if with_synthetic:
        cur.execute("""
            SELECT product_key, calendar_month, quantity_sold, is_demo
            FROM unilever_sku_demand_fact
            WHERE calendar_month <= (SELECT MAX(calendar_month) FROM unilever_sku_demand_fact_real)
            ORDER BY 1, 2
        """)
    else:
        cur.execute("SELECT product_key, calendar_month, quantity_sold, FALSE "
                    "FROM unilever_sku_demand_fact_real ORDER BY 1, 2")
    raw = pd.DataFrame(cur.fetchall(), columns=["pk", "m", "q", "is_demo"])
    raw["q"] = raw["q"].astype(float)
    raw["is_demo"] = raw["is_demo"].astype(bool)
    cur.execute("SELECT product_key FROM abc_classification "
                "WHERE principal='unilever' AND classification_period=%s AND tier='A' "
                "AND method=%s", (ABC_PERIOD, abc_method("unilever")))
    tier_a = sorted({r[0] for r in cur.fetchall()})
    cur.execute("SELECT product_key, sku_code, product_name FROM product_dimension WHERE principal='unilever'")
    names = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
    c.close()
    return raw, tier_a, names


def build_panel(raw: pd.DataFrame, tier_a: list[int]) -> pd.DataFrame:
    """One row per (sku, month) on a monthly grid and lag / rolling / calendar
    features. Only Tier A SKUs. A month with no row is 0; a row whose
    quantity_sold is NULL is a blank capture and stays NaN (never a zero)."""
    frames = []
    for pk, g in raw[raw.pk.isin(tier_a)].groupby("pk"):
        s = pd.Series(g["q"].to_numpy(float), index=pd.to_datetime(g["m"] + "-01")).sort_index()
        s = s.reindex(pd.date_range(s.index.min(), s.index.max(), freq="MS"), fill_value=0.0)  # fills absent months only; a NaN row stays NaN
        df = pd.DataFrame({"pk": pk, "date": s.index, "q": s.values})
        for L in (1, 2, 3, 6, 12):
            df[f"lag{L}"] = df["q"].shift(L)
        df["roll3"] = df["q"].shift(1).rolling(3).mean()
        df["roll6"] = df["q"].shift(1).rolling(6).mean()
        df["rollstd3"] = df["q"].shift(1).rolling(3).std()
        df["mom"] = df["date"].dt.month
        df["month_sin"] = np.sin(2 * np.pi * df["mom"] / 12)
        df["month_cos"] = np.cos(2 * np.pi * df["mom"] / 12)
        df["t"] = np.arange(len(df))
        frames.append(df)
    panel = pd.concat(frames, ignore_index=True)
    panel["pk_code"] = panel["pk"].astype("category").cat.codes
    return panel


FEATURES = ["lag1", "lag2", "lag3", "lag6", "lag12", "roll3", "roll6", "rollstd3",
            "month_sin", "month_cos", "t", "pk_code"]


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
    from statsmodels.tsa.forecasting.theta import ThetaModel
    try:
        y = pd.Series(x, index=pd.date_range("2000-01-01", periods=len(x), freq="MS"))
        return float(ThetaModel(y, period=SEAS if len(x) >= SEAS + 2 else 1).fit().forecast(1).iloc[0])
    except Exception:  # noqa: BLE001
        return np.nan


INCUMBENTS = {"naive": lambda x: x[-1], "ma3": lambda x: x[-3:].mean(),
              "sba_a3": _sba, "theta": _theta}


METRIC_KEYS = ("mape", "mase", "smape", "wape", "mae", "rmse")


def _metrics(actual, pred, scale):
    err = actual - pred
    return dict(mape=mape(actual, pred), mase=mase(actual, pred, scale), smape=smape(actual, pred),
                wape=wape(actual, pred), mae=float(np.abs(err).mean()), rmse=float(np.sqrt((err ** 2).mean())))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--with-synthetic", action="store_true")
    ap.add_argument("--out", default=None, help="CSV path (default under reports/).")
    args = ap.parse_args()

    raw, tier_a, names = _fetch(args.with_synthetic)
    panel = build_panel(raw, tier_a)
    # first REAL month per SKU: the cohort test, origins and MASE scale are
    # taken from the real months only, identically in both arms. Synthetic
    # rows reach the model as training rows / lag features, nothing else.
    real_raw = raw[~raw["is_demo"]]
    real_start = pd.to_datetime(real_raw.groupby("pk")["m"].min() + "-01").to_dict()
    dates = np.sort(panel["date"].unique())
    real_max = pd.Timestamp(raw[["m"]].assign(d=pd.to_datetime(raw["m"] + "-01"))["d"].max())
    origins = list(pd.to_datetime(dates)[-TEST_H:])
    print(f"Tier A: {len(tier_a)} SKUs   panel rows: {len(panel)}   "
          f"test origins: {origins[0].date()}..{origins[-1].date()}   with_synthetic={args.with_synthetic}")

    # xgboost predictions per (sku, origin)
    preds = {pk: {} for pk in tier_a}
    for t in origins:
        tr = panel[(panel["date"] < t) & panel[FEATURES].notna().all(axis=1) & panel["q"].notna()]
        te = panel[(panel["date"] == t) & panel[FEATURES].notna().all(axis=1)]
        dtrain = xgb.DMatrix(tr[FEATURES].to_numpy(), label=tr["q"].to_numpy())
        dtest = xgb.DMatrix(te[FEATURES].to_numpy())
        bst = xgb.train(XGB_PARAMS, dtrain, num_boost_round=XGB_ROUNDS)
        p = np.clip(bst.predict(dtest), 0, None)
        for pk, val in zip(te["pk"].to_numpy(), p):
            preds[pk][t] = float(val)

    # per-SKU scoring
    rows = []
    for pk in tier_a:
        g = panel[panel.pk == pk].sort_values("date")
        series = g.set_index("date")["q"]
        x = series.to_numpy(float)
        r0 = int(np.searchsorted(series.index.values, np.datetime64(real_start[pk]))) if pk in real_start else len(x)
        n = len(x) - r0                       # REAL months only
        nonzero = int((series.iloc[r0:] > 0).sum())
        origin_pos = [i for i, d in enumerate(series.index) if d in origins and i >= r0]
        blank_months = int(np.isnan(x[r0:]).sum())  # blank captures in the real span: unavailable, not zero
        if n < 14 or len(origin_pos) < 3 or blank_months:
            rows.append(dict(pk=pk, sku=names.get(pk, (None,))[0], name=names.get(pk, (None, None))[1],
                             months=n, nonzero=nonzero, evaluable=False, blank_months=blank_months))
            continue
        first = origin_pos[0]
        actual = x[origin_pos]
        scale = naive_scale(x[r0:first])

        rec = dict(pk=pk, sku=names.get(pk, (None,))[0], name=names.get(pk, (None, None))[1],
                   months=n, nonzero=nonzero, evaluable=True)

        xgp = np.array([preds[pk].get(series.index[i], np.nan) for i in origin_pos])
        m = _metrics(actual, xgp, scale) if np.isfinite(xgp).all() else dict.fromkeys(METRIC_KEYS, np.nan)
        for k, v in m.items():
            rec[f"xgboost_{k}"] = v

        for name, fn in INCUMBENTS.items():
            pr = np.array([fn(x[:i]) for i in origin_pos], float)
            pr = np.where(np.isfinite(pr), np.maximum(0, pr), np.nan)
            mm = _metrics(actual, pr, scale) if np.isfinite(pr).all() else dict.fromkeys(METRIC_KEYS, np.nan)
            for k, v in mm.items():
                rec[f"{name}_{k}"] = v
        rows.append(rec)

    df = pd.DataFrame(rows)
    suffix = "_withsynth" if args.with_synthetic else ""
    out = args.out or os.path.join(REPORTS, f"xgboost_bakeoff_unilever_tierA{suffix}.csv")
    df.to_csv(out, index=False)
    print(f"wrote {out}  ({int(df.evaluable.sum())} evaluable)\n")

    ev = df[df.evaluable]
    models = ["xgboost", "naive", "ma3", "sba_a3", "theta"]
    print(f"{'model':<12}{'MAPEmed':>9}{'MASEmed':>9}{'sMAPEmed':>10}{'MAEmed':>10}"
          f"{'MAPE<.20':>10}{'beat naive':>12}")
    nv = ev["naive_smape"]
    for mdl in models:
        sp = ev[f"{mdl}_smape"]
        pair = pd.DataFrame({"a": sp, "b": nv}).dropna()
        beat = (pair.a < pair.b).mean() * 100 if len(pair) else np.nan
        print(f"{mdl:<12}{ev[f'{mdl}_mape'].median():>9.3f}"
              f"{ev[f'{mdl}_mase'][ev[f'{mdl}_mase'].notna()].median():>9.3f}"
              f"{sp.median():>10.3f}{ev[f'{mdl}_mae'].median():>10.0f}"
              f"{(ev[f'{mdl}_mape'] < 0.20).mean() * 100:>9.0f}%{beat:>11.0f}%")

    cols = [f"{m}_smape" for m in models]
    win = ev[cols].dropna(how="all").idxmin(axis=1).str.replace("_smape", "", regex=False)
    print(f"\nbest per SKU by sMAPE (n={win.notna().sum()}):")
    for k, v in win.value_counts().items():
        print(f"  {k:<12}{v:>3}  {v / len(win) * 100:>5.1f}%")


if __name__ == "__main__":
    main()
