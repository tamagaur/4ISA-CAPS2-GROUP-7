"""
Shared harness for the model audit (2026-10-03). Offline: reads only inputs/ (pull_inputs.py).

Every served forecast here comes from the production code path, analytics.forecasting.router.route(),
with the production series builder scripts.run_baseline_forecast.build_series. Variants (other XGBoost
objectives, blend weights, training pools) go through FastForecaster, a GlobalForecaster whose
training rows come from a feature table built once with the production build_features. Before any
variant is used, run_audit.py checks that FastForecaster with the served settings reproduces
GlobalForecaster's forecasts exactly.
"""
from __future__ import annotations

import io
import os
import subprocess
import sys

import numpy as np
import pandas as pd
import xgboost as xgb

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, REPO)

import analytics.forecasting.global_model as gm  # noqa: E402
from analytics.forecasting.diagnostic_metrics import wape  # noqa: E402,F401
from analytics.forecasting.router import route  # noqa: E402
from scripts.run_baseline_forecast import build_series  # noqa: E402

INPUTS = os.path.join(HERE, "inputs")
LOCAL = os.path.join(HERE, "local")
TEST_MONTHS = list(pd.date_range("2023-10-01", "2026-02-01", freq="MS"))   # the 29-month window
LAST_MONTH = TEST_MONTHS[-1]
# The 107 products of the 29-month figure (kelvin/forecast-error-business eebd741,
# longwindow_per_product_summary.csv): Tier A as of 2026-02 (ABC 'single') and scorable on 2025-09..2026-02.
EEBD_REF = "eebd741:reports/diagnostics/forecast_error_business_2026-10-03/"
EEBD_REPO = "C:/Users/kyuan/dsd-forecast-error-business"
COHORT_FILE = os.path.join(HERE, "cohort_107.csv")


def read(name: str, **kw) -> pd.DataFrame:
    return pd.read_csv(os.path.join(INPUTS, name), **kw)


def eebd(name: str) -> pd.DataFrame:
    out = subprocess.run(["git", "-C", EEBD_REPO, "show", EEBD_REF + name], capture_output=True, text=True, check=True)
    return pd.read_csv(io.StringIO(out.stdout), dtype={"sku_code": str})


def cohort_107() -> list[int]:
    if not os.path.exists(COHORT_FILE):
        eebd("longwindow_per_product_summary.csv")[["product_key"]].sort_values("product_key").to_csv(COHORT_FILE, index=False)
    return sorted(pd.read_csv(COHORT_FILE).product_key.astype(int))


def load():
    """(series for every real Unilever product, demand frame, dims, served Tier A keys).
    Demand is read exactly as the runner reads it (fetch_demand): NULL quantity -> 0.0."""
    d = read("demand_real_all.csv", dtype={"calendar_month": str, "sku_code": str})
    d = d.rename(columns={"any_is_demo": "is_demo"})
    d["quantity_was_null"] = d.quantity.isna()
    d["quantity"] = pd.to_numeric(d.quantity, errors="coerce").fillna(0.0)
    series = {int(k): build_series(g) for k, g in d.groupby("product_key")}
    dims = read("product_dimension_unilever.csv", dtype={"sku_code": str})
    tier_a = sorted(read("served_tier_a.csv").product_key.astype(int))
    return series, d, dims, tier_a


def backtest(series: dict, products, months, forecaster) -> pd.DataFrame:
    """route() for each product x month exactly as the 29-month follow-up did
    (run_followups.py long_window/run_jobs): month in the series and after its first row,
    no forced bin; 'insufficient' months (value None) are dropped."""
    rows = []
    for k in products:
        s = series[k]
        for m in months:
            if m not in s.index or not m > s.index[0]:
                continue
            r = route(s, m, forecaster)
            if r["value"] is None:
                continue
            prev = m - pd.offsets.MonthBegin(1)
            rows.append({"product_key": k, "month": m, "actual": float(s.loc[m]), "value": r["value"],
                         "bin": r["bin"], "sales_months": r["sales_months"], "method": r["method"],
                         "ma3": max(0.0, r["ma3_value"]), "ma3_raw": r["ma3_value"],
                         "tsb": r["components"].get("tsb", np.nan),
                         "xgb": np.nan if r["components"].get("xgb") is None else float(r["components"]["xgb"]),
                         "backup_fired": r["backup_fired"], "backup_reason": r["backup_reason"],
                         "naive": float(s.loc[prev]) if prev in s.index else np.nan})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Feature table + FastForecaster
# --------------------------------------------------------------------------- #
def feature_table(pool: dict) -> pd.DataFrame:
    """Every training row global_model.training_rows would produce for `pool`, for every month,
    in the same order (pool order, then month). Filtering it to month < T reproduces
    training_rows(pool, before=T) row for row."""
    recs = []
    for k, series in pool.items():
        s = gm.from_first_sale(series)
        v = s.to_numpy(dtype=float)
        for t in range(gm.MIN_HISTORY, len(s)):
            feats, scale = gm.build_features(v[:t], s.index[t])
            if feats is not None:
                recs.append((k, s.index[t], v[t] / scale, scale, feats))
    out = pd.DataFrame([r[:4] for r in recs], columns=["product_key", "month", "y", "scale"])
    out["feats"] = [r[4] for r in recs]
    return out


class FastForecaster(gm.GlobalForecaster):
    """GlobalForecaster with training rows from a prebuilt feature table.
    params: XGBoost params (default: production PARAMS). label_floor: clip scaled targets below this
    (Poisson / Tweedie need labels >= 0). pool_at: None = every product in the table, or a function
    month -> set of product keys allowed in training for that target month."""

    def __init__(self, series: dict, table: pd.DataFrame, params: dict | None = None,
                 label_floor: float | None = None, pool_at=None, num_rounds: int | None = None):
        super().__init__(series)
        self.table, self.params = table, dict(gm.PARAMS if params is None else params)
        self.label_floor, self.pool_at = label_floor, pool_at
        self.num_rounds = gm.NUM_ROUNDS if num_rounds is None else num_rounds

    def booster_for(self, target_month):
        if target_month not in self._cache:
            t = self.table[self.table.month < target_month]
            if self.pool_at is not None:
                t = t[t.product_key.isin(self.pool_at(target_month))]
            booster = None
            if len(t) >= gm.MIN_TRAINING_ROWS:
                y = t.y.to_numpy(dtype=float)
                if self.label_floor is not None:
                    y = np.maximum(y, self.label_floor)
                booster = xgb.train(self.params, xgb.DMatrix(np.vstack(t.feats.to_numpy()), label=y),
                                    num_boost_round=self.num_rounds)
            self._cache[target_month] = (booster, int(len(t)))
        return self._cache[target_month]


def xgb_all(series: dict, products, months, forecaster) -> pd.DataFrame:
    """The XGBoost component for every product x month (every bin, not only 'long'), from the
    history before the month - what the long bin would get if XGBoost served it."""
    rows = []
    for k in products:
        s = series[k]
        for m in months:
            if m not in s.index or not m > s.index[0]:
                continue
            v, n, reason = forecaster.forecast(s, m)
            rows.append({"product_key": k, "month": m, "xgb": np.nan if v is None else v, "xgb_reason": reason,
                         "training_rows": n})
    return pd.DataFrame(rows)


def per_product_wape(df: pd.DataFrame, col: str) -> pd.Series:
    g = df.assign(_e=(df[col] - df.actual).abs(), _a=df.actual.abs()).groupby("product_key")
    return g._e.sum() / g._a.sum()


def paired_ci(a: pd.Series, b: pd.Series, rng, n_boot: int = 2000) -> tuple[float, float, float, int, int]:
    """(median(b) - median(a), 95% bootstrap low, high, products better under b, worse) over products."""
    j = pd.concat([a, b], axis=1, keys=["a", "b"]).dropna()
    x, y = j.a.to_numpy(), j.b.to_numpy()
    idx = rng.integers(0, len(j), size=(n_boot, len(j)))
    boot = np.median(y[idx], axis=1) - np.median(x[idx], axis=1)
    d = y - x
    return (float(np.median(y) - np.median(x)), float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5)),
            int((d < -1e-12).sum()), int((d > 1e-12).sum()))
