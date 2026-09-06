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
import warnings

import numpy as np
import pandas as pd
import psycopg2
from dotenv import load_dotenv
import xgboost as xgb

warnings.simplefilter("ignore")
load_dotenv()

SEAS = 12
TEST_H = 6
ABC_PERIOD = "2026-02"
REPORTS = os.path.join(os.path.dirname(__file__), os.pardir, "reports")

# native xgboost API (no sklearn dependency)
XGB_PARAMS = {"max_depth": 4, "eta": 0.04, "subsample": 0.85, "colsample_bytree": 0.85,
              "min_child_weight": 3, "lambda": 1.0, "objective": "reg:squarederror", "nthread": 4}
XGB_ROUNDS = 400


def _connect():
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


def _fetch(with_synthetic: bool):
    c = _connect()
    cur = c.cursor()
    if with_synthetic:
        cur.execute("""
            SELECT product_key, calendar_month, COALESCE(quantity_sold, 0)
            FROM unilever_sku_demand_fact
            WHERE calendar_month <= (SELECT MAX(calendar_month) FROM unilever_sku_demand_fact_real)
            ORDER BY 1, 2
        """)
    else:
        cur.execute("SELECT product_key, calendar_month, COALESCE(quantity_sold, 0) "
                    "FROM unilever_sku_demand_fact_real ORDER BY 1, 2")
    raw = pd.DataFrame(cur.fetchall(), columns=["pk", "m", "q"])
    raw["q"] = raw["q"].astype(float)
    cur.execute("SELECT product_key FROM abc_classification "
                "WHERE principal='unilever' AND classification_period=%s AND tier='A'", (ABC_PERIOD,))
    tier_a = sorted({r[0] for r in cur.fetchall()})
    cur.execute("SELECT product_key, sku_code, product_name FROM product_dimension WHERE principal='unilever'")
    names = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
    c.close()
    return raw, tier_a, names


def build_panel(raw: pd.DataFrame, tier_a: list[int]) -> pd.DataFrame:
    """One row per (sku, month) with a zero-filled monthly grid and
    lag / rolling / calendar features. Only Tier A SKUs."""
    frames = []
    for pk, g in raw[raw.pk.isin(tier_a)].groupby("pk"):
        s = pd.Series(g["q"].to_numpy(float), index=pd.to_datetime(g["m"] + "-01")).sort_index()
        s = s.resample("MS").asfreq().fillna(0.0)
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


def _metrics(actual, pred, scale):
    ae = np.abs(actual - pred)
    nz = actual > 0
    mape = float(np.mean(ae[nz] / actual[nz])) if nz.any() else np.nan
    den = np.abs(actual) + np.abs(pred)
    sm = den > 0
    smape = float(np.mean(2 * ae[sm] / den[sm])) if sm.any() else np.nan
    mae = float(ae.mean())
    rmse = float(np.sqrt(((actual - pred) ** 2).mean()))
    mase = float(mae / scale) if scale > 0 else np.nan
    return dict(mape=mape, mase=mase, smape=smape, mae=mae, rmse=rmse)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--with-synthetic", action="store_true")
    args = ap.parse_args()

    raw, tier_a, names = _fetch(args.with_synthetic)
    panel = build_panel(raw, tier_a)
    dates = np.sort(panel["date"].unique())
    real_max = pd.Timestamp(raw[["m"]].assign(d=pd.to_datetime(raw["m"] + "-01"))["d"].max())
    origins = list(pd.to_datetime(dates)[-TEST_H:])
    print(f"Tier A: {len(tier_a)} SKUs   panel rows: {len(panel)}   "
          f"test origins: {origins[0].date()}..{origins[-1].date()}   with_synthetic={args.with_synthetic}")

    # xgboost predictions per (sku, origin)
    preds = {pk: {} for pk in tier_a}
    for t in origins:
        tr = panel[(panel["date"] < t) & panel[FEATURES].notna().all(axis=1)]
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
        n = len(x)
        origin_pos = [i for i, d in enumerate(series.index) if d in origins]
        if n < 14 or len(origin_pos) < 3:
            rows.append(dict(pk=pk, sku=names.get(pk, (None,))[0], name=names.get(pk, (None, None))[1],
                             months=n, nonzero=int((series > 0).sum()), evaluable=False))
            continue
        first = origin_pos[0]
        actual = x[origin_pos]
        base = x[:first]
        scale = np.mean(np.abs(np.diff(base))) if len(base) > 1 else 0.0

        rec = dict(pk=pk, sku=names.get(pk, (None,))[0], name=names.get(pk, (None, None))[1],
                   months=n, nonzero=int((series > 0).sum()), evaluable=True)

        xgp = np.array([preds[pk].get(series.index[i], np.nan) for i in origin_pos])
        m = _metrics(actual, xgp, scale) if np.isfinite(xgp).all() else dict.fromkeys(
            ("mape", "mase", "smape", "mae", "rmse"), np.nan)
        for k, v in m.items():
            rec[f"xgboost_{k}"] = v

        for name, fn in INCUMBENTS.items():
            pr = np.array([fn(x[:i]) for i in origin_pos], float)
            pr = np.where(np.isfinite(pr), np.maximum(0, pr), np.nan)
            mm = _metrics(actual, pr, scale) if np.isfinite(pr).all() else dict.fromkeys(
                ("mape", "mase", "smape", "mae", "rmse"), np.nan)
            for k, v in mm.items():
                rec[f"{name}_{k}"] = v
        rows.append(rec)

    df = pd.DataFrame(rows)
    suffix = "_withsynth" if args.with_synthetic else ""
    out = os.path.join(REPORTS, f"xgboost_bakeoff_unilever_tierA{suffix}.csv")
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
