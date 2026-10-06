"""
Quality check 2026-10-03 - INDEPENDENT recompute of the headline numbers. Offline: reads inputs/ only.

Imports nothing from analytics.forecasting and nothing from common.py: the series, the bins, MA3, TSB, the
XGBoost features / training rows / guards and WAPE are re-coded here from the documented design (DEC-26;
global_model.py's docstring and PARAMS; router.py's guard order). If this file and run_audit.py / quick_checks.py
agree, the headline does not depend on one implementation.

Targets (median product WAPE, 2023-10..2026-02, one month ahead, real rows only):
  26.9% served / 28.0% MA3   today's Tier A (the 107 of cohort_107.csv)
  34.8% served / 35.9% MA3   at-the-time cohort (Tier A in ABC 'single' period = month before each test month)
  ~23.5% noise floor         89 products with 13+ months, method-of-moments local level (same method, new code)
                             + a different method: maximum-likelihood local level (statsmodels UnobservedComponents)

As served, a blank quantity is read as 0 here (that is what produced the audited numbers; kelvin/blank-qty-fix
changes it for the next refresh).

    ../Capstone-Project/.venv/Scripts/python.exe reports/diagnostics/model_audit_2026-10-03/qc_recompute.py
"""
from __future__ import annotations

import json
import os
import warnings

import numpy as np
import pandas as pd
import xgboost as xgb

HERE = os.path.dirname(os.path.abspath(__file__))
INP = os.path.join(HERE, "inputs")
MONTHS = list(pd.date_range("2023-10-01", "2026-02-01", freq="MS"))
PARAMS = {"max_depth": 4, "eta": 0.05, "subsample": 0.8, "colsample_bytree": 0.8,
          "objective": "reg:absoluteerror", "seed": 20260921, "nthread": 1}
ROUNDS, MIN_HIST, MIN_ROWS = 300, 3, 100


def series_all() -> dict:
    d = pd.read_csv(os.path.join(INP, "demand_real_all.csv"), dtype={"calendar_month": str})
    out = {}
    for k, g in d.groupby("product_key"):
        idx = pd.to_datetime(g.calendar_month + "-01")
        s = pd.Series(g.quantity.fillna(0.0).to_numpy(float), index=idx).sort_index()
        full = pd.date_range(s.index.min(), s.index.max(), freq="MS")
        out[int(k)] = s.reindex(full, fill_value=0.0)
    return out


def first_sale(v: np.ndarray) -> np.ndarray:
    pos = np.flatnonzero(v > 0)
    return v[pos[0]:] if pos.size else v[:0]


def feats(h: np.ndarray, month: pd.Timestamp):
    sc = h[-6:].mean() if len(h) else 0.0
    if not sc > 0:
        return None, sc
    lag = [h[-k] / sc if len(h) >= k else np.nan for k in (1, 2, 3, 4, 5, 6, 12)]
    return np.array(lag + [h[-3:].mean() / sc, h[-12:].mean() / sc if len(h) >= 12 else np.nan, h[-6:].std() / sc,
                           float((h[-6:] <= 0).sum()), float(len(h)), float((h > 0).sum() / len(h)),
                           float(month.month)]), sc


class XGB:
    def __init__(self, series, pool_at):
        self.series, self.pool_at, self.cache = series, pool_at, {}
        rows = []                                            # every (product, month) training row, product then month
        for k in sorted(series):
            s = series[k]
            v = s.to_numpy(float)
            pos = np.flatnonzero(v > 0)
            if not pos.size:
                continue
            v, idx = v[pos[0]:], s.index[pos[0]:]
            for t in range(MIN_HIST, len(v)):
                f, sc = feats(v[:t], idx[t])
                if f is not None:
                    rows.append((k, idx[t], f, v[t] / sc))
        self.rows = rows

    def booster(self, T):
        if T not in self.cache:
            keep = self.pool_at(T)
            sel = [(f, y) for k, m, f, y in self.rows if m < T and k in keep]
            self.cache[T] = None if len(sel) < MIN_ROWS else xgb.train(
                PARAMS, xgb.DMatrix(np.vstack([f for f, _ in sel]), label=np.array([y for _, y in sel])), ROUNDS)
        return self.cache[T]

    def predict(self, h: np.ndarray, T):
        b = self.booster(T)
        f, sc = feats(h, T)
        if b is None or f is None:
            return None
        return float(b.predict(xgb.DMatrix(f.reshape(1, -1)))[0]) * sc


def tsb(h: np.ndarray) -> float:
    d = h[h > 0].mean() if (h > 0).any() else 0.0
    p = (h > 0).mean()
    for v in h:
        if v > 0:
            d += 0.3 * (v - d)
            p += 0.1 * (1 - p)
        else:
            p += 0.1 * (0 - p)
    return d * p


def forecast(s: pd.Series, T, model: XGB):
    h = first_sale(s[s.index < T].to_numpy(float))
    n_sales = int((h > 0).sum())
    if n_sales < 3:
        return None
    ma3 = h[-3:].mean()
    if n_sales < 12:
        return max(0.0, ma3), max(0.0, ma3)
    v = tsb(h) if n_sales < 24 else None
    if n_sales >= 24:
        x = model.predict(h, T)
        v = None if x is None else (x + ma3) / 2
    if v is None or v > h.max() or v < 0:
        return max(0.0, ma3), max(0.0, ma3)
    return v, max(0.0, ma3)


def score(series, cohort_at, model) -> dict:
    rows = []
    for T in MONTHS:
        for k in sorted(cohort_at(T)):
            s = series.get(k)
            if s is None or T not in s.index or not T > s.index[0]:
                continue
            r = forecast(s, T, model)
            if r is not None:
                rows.append((k, float(s.loc[T]), r[0], r[1]))
    df = pd.DataFrame(rows, columns=["k", "a", "f", "m"])
    g = df.assign(ef=(df.f - df.a).abs(), em=(df.m - df.a).abs(), aa=df.a.abs()).groupby("k")[["ef", "em", "aa"]].sum()
    return {"products": int(len(g)), "product_months": int(len(df)),
            "median_product_wape_served": float((g.ef / g.aa).median()),
            "median_product_wape_ma3": float((g.em / g.aa).median())}, df


def noise_floor(series, fixed_df) -> dict:
    """Same method of moments as run_audit.py, re-coded; then a maximum-likelihood local level per product."""
    from statsmodels.tsa.statespace.structural import UnobservedComponents
    ma3_wape = fixed_df.assign(e=(fixed_df.m - fixed_df.a).abs(), aa=fixed_df.a.abs()).groupby("k")[["e", "aa"]].sum()
    ma3_wape = ma3_wape.e / ma3_wape.aa
    mom, mle = [], []
    for k in ma3_wape.index:
        y = first_sale(series[k][series[k].index <= MONTHS[-1]].to_numpy(float))
        dy = np.diff(y)
        if len(dy) < 12:
            continue
        c = dy - dy.mean()
        g0, g1 = (c ** 2).mean(), (c[1:] * c[:-1]).mean()
        se = max(-g1, 0.0)
        sn = max(g0 - 2 * se, 0.0)
        mom.append(ma3_wape[k] * ratio(se, sn))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fit = UnobservedComponents(y, level="local level").fit(disp=False)
        p = dict(zip(fit.model.param_names, fit.params))
        mle.append(ma3_wape[k] * ratio(p["sigma2.irregular"], p["sigma2.level"]))
    return {"products": len(mom), "median_floor_method_of_moments": float(np.median(mom)),
            "median_floor_max_likelihood": float(np.nanmedian(mle))}


def ratio(s_eps: float, s_eta: float) -> float:
    """sqrt(best one-step error variance / MA3 error variance) for a local level model."""
    p = (s_eta + np.sqrt(s_eta ** 2 + 4 * s_eta * s_eps)) / 2
    v_ma3 = 14 / 9 * s_eta + 4 / 3 * s_eps
    return float(np.sqrt((p + s_eps) / v_ma3)) if v_ma3 > 0 else np.nan


def main():
    series = series_all()
    tier_a = set(pd.read_csv(os.path.join(INP, "served_tier_a.csv")).product_key.astype(int))
    coh = set(pd.read_csv(os.path.join(HERE, "cohort_107.csv")).product_key.astype(int))
    abc = pd.read_csv(os.path.join(INP, "abc_single_history.csv"), dtype={"classification_period": str})
    by_period = abc[abc.tier == "A"].groupby("classification_period").product_key.apply(lambda x: set(x.astype(int)))

    def asof(T):
        return by_period.get((T - pd.offsets.MonthBegin(1)).strftime("%Y-%m"), set())

    fixed, fixed_df = score(series, lambda T: coh, XGB({k: series[k] for k in tier_a}, lambda T: tier_a))
    at_time, _ = score(series, asof, XGB(series, asof))
    floor = noise_floor(series, fixed_df)
    claimed = {"fixed_served": 0.269, "fixed_ma3": 0.280, "asof_served": 0.348, "asof_ma3": 0.359, "floor": 0.235}
    got = {"fixed_served": fixed["median_product_wape_served"], "fixed_ma3": fixed["median_product_wape_ma3"],
           "asof_served": at_time["median_product_wape_served"], "asof_ma3": at_time["median_product_wape_ma3"],
           "floor": floor["median_floor_method_of_moments"]}
    rows = [{"number": k, "readme_value": claimed[k], "independent_value": round(got[k], 4),
             "result": "PASS" if round(got[k], 3) == claimed[k] else "FAIL"} for k in claimed]
    rows.append({"number": "floor, different method (maximum likelihood)", "readme_value": None,
                 "independent_value": round(floor["median_floor_max_likelihood"], 4), "result": "cross-check"})
    pd.DataFrame(rows).to_csv(os.path.join(HERE, "qc_recompute.csv"), index=False)
    with open(os.path.join(HERE, "qc_recompute.json"), "w") as fh:
        json.dump({"fixed_107": fixed, "at_the_time": at_time, "noise_floor": floor}, fh, indent=2)
    print(pd.DataFrame(rows).to_string(index=False))
    print(json.dumps({"fixed_107": fixed, "at_the_time": at_time, "noise_floor": floor}, indent=1))


if __name__ == "__main__":
    main()
