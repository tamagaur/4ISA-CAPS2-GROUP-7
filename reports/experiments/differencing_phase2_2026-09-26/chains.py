"""Phase 2 (2026-09-26, personal experiment): differencing chains, repeated transforms,
KPSS-chosen differencing and auto-ARIMA. Builds on phase 1's transforms.py (imported,
never modified).

A chain is  transform T (phase 1, optional)  ->  differences at the given lags.
A one-step forecast f of the last differenced series is integrated back stage by
stage to the transformed level, then T is inverted (log1p: Duan smearing on the
model's in-sample one-step errors, which equal the level errors because integration
only adds known values). Everything is fitted on the training months of one SKU at
one forecast month.

Settings (decided 2026-09-26, fixed before any result):
  history      D1, D2, D3, AUTO-d, auto-ARIMA: >= 18 training months; anything with
               lag 12: >= 24. Below that the forecast is skipped and counted.
  AUTO-d       d in 0..2 by KPSS (statsmodels, level-stationarity null, nlags="auto",
               alpha 0.05), differencing until KPSS no longer rejects. No seasonal
               order: OCSB / Canova-Hansen are not available here (pmdarima needs
               scikit-learn, blocked on this machine; no R).
  repeated     the same transform k times; the phase 1 shift c = 1 - min (min <= 0)
               is applied once, before the first pass. log1p x k smears on the full
               composite back-transform. Round trip: max(1e-9 * |x|, 1e-9), as Box-Cox.
  auto-ARIMA   Gate D's grid (scripts/arima_bakeoff.py select_order) with d in {0,1,2}:
               (p,d,q) in {0,1,2}^3, seasonal (P,D,Q,12) in {none, (0,1,1), (1,1,0),
               (0,1,0)} only with >= 24 months and p+d+q <= 3, lowest AICc wins.
               No fit at all -> blank (Gate D fell back to (0,1,1); not here).
"""
from __future__ import annotations

import os
import sys
import warnings

import numpy as np
import pandas as pd

P1 = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "target_transforms_2026-09-26")
if P1 not in sys.path:
    sys.path.insert(0, P1)

from transforms import (ROUNDTRIP_TOL, TRANSFORMS, Transform, TransformFailed,  # noqa: E402
                        shift_for)

MIN_DIFF = 18
MIN_SEAS = 24
SEAS = 12
KPSS_ALPHA = 0.05
MAX_D = 2


# --------------------------------------------------------------------------- #
# C. repeated squeezing
# --------------------------------------------------------------------------- #
_BASE = {
    "sqrt": (np.sqrt, lambda z: np.where(z >= 0, z * z, np.nan), True),
    "cbrt": (np.cbrt, lambda z: z * z * z, False),
    "asinh": (np.arcsinh, np.sinh, False),
    "log1p": (np.log1p, np.expm1, True),
}


class Repeated(Transform):
    """base applied k times. Maps 0 to 0 without a shift on positive data, so TSB may
    use it on demand sizes.

    Round trip uses phase 1's Box-Cox rule, |back - x| <= max(1e-9 * |x|, 1e-9)
    (approved 2026-09-26): each pass through a curved function and back adds rounding
    error proportional to x, and 2-3 passes on sales of 190k-300k reach 1.1e-9 to
    2.7e-9 absolute (at most 1.4e-14 relative)."""
    family, tsb_ok, pattern, rt_relative = "repeat", True, False, True

    def __init__(self, base: str, k: int):
        super().__init__(f"{base}x{k}")
        self.base, self.k = base, k
        self.f, self.finv, self.shifted = _BASE[base]
        self.smear = base == "log1p"

    def fit(self, tr):
        return {"c": shift_for(tr) if self.shifted else 0.0}

    def fwd(self, x, ctx):
        z = np.asarray(x, float) + ctx["c"]
        for _ in range(self.k):
            z = self.f(z)
        return z

    def inv(self, z, ctx):
        z = np.asarray(z, float)
        for _ in range(self.k):
            z = self.finv(z)
        return z - ctx["c"]

    def invert(self, f, ctx, resid=None):
        if not np.isfinite(f):
            return np.nan
        if self.smear:
            e = np.asarray(resid if resid is not None else [], float)
            e = e[np.isfinite(e)]
            if not len(e):
                return np.nan
            v = float(np.mean(self.inv(f + e, ctx)))
        else:
            v = float(self.inv(np.array([f], float), ctx)[0])
        return v if np.isfinite(v) else np.nan


REPEATED = [Repeated(b, k) for b in ("sqrt", "cbrt", "asinh", "log1p") for k in (2, 3)]
for _t in REPEATED:                      # phase 1's XGBoost loops look transforms up by name
    TRANSFORMS.setdefault(_t.name, _t)
REPEATED_NAMES = [t.name for t in REPEATED]


# --------------------------------------------------------------------------- #
# A, B, D. differencing chains
# --------------------------------------------------------------------------- #
def kpss_d(y: np.ndarray) -> int:
    from statsmodels.tsa.stattools import kpss
    w, d = np.asarray(y, float), 0
    while d < MAX_D:
        if len(w) < 4 or np.ptp(w) == 0:
            break
        try:
            p = kpss(w, regression="c", nlags="auto")[1]
        except Exception as exc:
            raise TransformFailed(f"kpss: {type(exc).__name__}") from exc
        if p >= KPSS_ALPHA:
            break
        w, d = np.diff(w), d + 1
    return d


class Chain(Transform):
    """inner transform, then differences at `lags` (or KPSS-chosen lag-1 differences)."""
    family, tsb_ok, pattern = "chain", False, False

    def __init__(self, name: str, inner: Transform, lags, min_months: int, auto: bool = False):
        super().__init__(name)
        self.inner, self.lags, self.min_months, self.auto = inner, list(lags), min_months, auto
        self.smear = inner.smear
        self.rt_relative = inner.rt_relative
        self.invertible = True

    def prepare(self, tr):
        tr = np.asarray(tr, float)
        if len(tr) < self.min_months:
            raise TransformFailed(f"history {len(tr)} < {self.min_months}")
        y, tctx = self.inner.prepare(tr)
        y = np.asarray(y, float)
        lags = [1] * kpss_d(y) if self.auto else self.lags
        stages, w = [], y
        for lag in lags:
            if len(w) <= lag:
                raise TransformFailed("too short to difference")
            stages.append(w)
            w = w[lag:] - w[:-lag]
        return w, {"tctx": tctx, "lags": lags, "stages": stages, "y": y}

    def integrate(self, f, ctx):
        v = f
        for lag, stage in zip(reversed(ctx["lags"]), reversed(ctx["stages"])):
            v = v + stage[len(stage) - lag]
        return v

    def invert(self, f, ctx, resid=None):
        if not np.isfinite(f):
            return np.nan
        v = self.inner.invert(self.integrate(f, ctx), ctx["tctx"], resid)
        return float(v) if np.isfinite(v) else np.nan

    def undifference(self, z, ctx):
        w = np.asarray(z, float)
        for lag, stage in zip(reversed(ctx["lags"]), reversed(ctx["stages"])):
            out = np.empty(len(w) + lag)
            out[:lag] = stage[:lag]
            for t in range(lag, len(out)):
                out[t] = out[t - lag] + w[t - lag]
            w = out
        return w


def rt_chain(ch: Chain, tr, z, ctx):
    """Round trip for a chain, phase 1 rules: back to x when the inner transform has an
    inverse (Box-Cox / Yeo-Johnson: max(1e-9|x|, 1e-9); others absolute 1e-9); for
    winsorize (no inverse) the differencing alone is checked back to the winsorized y."""
    y = ctx["y"]
    back_y = ch.undifference(z, ctx)
    if not ch.inner.invertible:
        err = np.abs(back_y - y) if back_y.shape == y.shape else np.array([np.inf])
        return dict(abs=float(err.max()), rel=0.0, fail=bool(err.max() > ROUNDTRIP_TOL))
    tr = np.asarray(tr, float)
    back = np.asarray(ch.inner.reconstruct(back_y, ctx["tctx"]), float)
    if back.shape != tr.shape or not np.isfinite(back).all():
        return dict(abs=np.inf, rel=np.inf, fail=True)
    err = np.abs(back - tr)
    nz = tr != 0
    rel = float(np.max(err[nz] / np.abs(tr[nz]))) if nz.any() else 0.0
    fail = bool((err > np.maximum(ROUNDTRIP_TOL * np.abs(tr), ROUNDTRIP_TOL)).any()) if ch.rt_relative \
        else bool(err.max() > ROUNDTRIP_TOL)
    return dict(abs=float(err.max()), rel=rel, fail=fail)


ID = TRANSFORMS["identity"]
DIFF_SPECS = {"D1": ([1], MIN_DIFF), "D2": ([1, 1], MIN_DIFF), "D3": ([1, 1, 1], MIN_DIFF),
              "S12": ([SEAS], MIN_SEAS), "S12D1": ([SEAS, 1], MIN_SEAS)}
CHAINS = {}
for _n, (_lags, _m) in DIFF_SPECS.items():                                     # A (D1 = reference)
    CHAINS[_n] = Chain(_n, ID, _lags, _m)
for _t in ("sqrt", "log1p", "boxcox", "yeojohnson", "cbrt", "asinh", "anscombe", "winsor"):   # B
    for _n in ("D1", "S12"):
        _lags, _m = DIFF_SPECS[_n]
        CHAINS[f"{_t}+{_n}"] = Chain(f"{_t}+{_n}", TRANSFORMS[_t], _lags, _m)
CHAINS["AUTOd"] = Chain("AUTOd", ID, [], MIN_DIFF, auto=True)                  # D


# --------------------------------------------------------------------------- #
# E. ARIMA
# --------------------------------------------------------------------------- #
NS_GRID = [(p, d, q) for p in (0, 1, 2) for d in (0, 1, 2) for q in (0, 1, 2)]
SEAS_GRID = [(0, 0, 0, 0), (0, 1, 1, SEAS), (1, 1, 0, SEAS), (0, 1, 0, SEAS)]   # Gate D's


def _aicc(res, n):                                                               # arima_bakeoff._aicc
    k = len(res.params)
    return res.aic + (2 * k * (k + 1)) / max(n - k - 1, 1)


def auto_arima(train):
    """(forecast, order, seasonal_order, in-sample residuals after burn-in) or NaN forecast."""
    from statsmodels.tsa.arima.model import ARIMA
    from statsmodels.tsa.statespace.sarimax import SARIMAX
    warnings.simplefilter("ignore")
    n = len(train)
    y = pd.Series(np.asarray(train, float), index=pd.date_range("2000-01-01", periods=n, freq="MS"))
    best = None
    for order in NS_GRID:
        for so in (SEAS_GRID if n >= MIN_SEAS else [(0, 0, 0, 0)]):
            if so[3] and sum(order) > 3:
                continue
            try:
                r = SARIMAX(y, order=order, seasonal_order=so, enforce_stationarity=False,
                            enforce_invertibility=False).fit(disp=0) if so[3] else ARIMA(y, order=order).fit()
                sc = _aicc(r, n)
                if np.isfinite(sc) and (best is None or sc < best[0]):
                    best = (sc, order, so, r)
            except Exception:
                continue
    if best is None:
        return np.nan, None, None, np.array([])
    _, order, so, r = best
    try:
        f = float(r.forecast(1).iloc[0])
    except Exception:
        f = np.nan
    burn = order[1] + so[1] * so[3]
    resid = np.asarray(r.resid, float)[burn:]
    return f, order, so, resid


def e_forecasts(tr, long_ok: bool):
    """E1 auto-ARIMA, E2 auto-ARIMA on log1p with smearing, E3 fixed SARIMA(1,1,1)(0,1,1,12)
    (scripts.model_bakeoff.m_sarima_seasonal, unchanged: its own 28-month floor). Raw
    values, before any guard or clip."""
    warnings.simplefilter("ignore")
    out = {}
    tr = np.asarray(tr, float)
    if len(tr) >= MIN_DIFF:
        f, order, so, _ = auto_arima(tr)
        out["E1"] = f
        out["E1_order"] = None if order is None else f"{order}x{so}"
        lg = TRANSFORMS["log1p"]
        z, ctx = lg.prepare(tr)
        f2, order2, so2, res2 = auto_arima(z)
        out["E2"] = lg.invert(f2, ctx, res2) if np.isfinite(f2) else np.nan
        out["E2_order"] = None if order2 is None else f"{order2}x{so2}"
    if long_ok and len(tr) >= MIN_SEAS:
        from scripts.model_bakeoff import m_sarima_seasonal
        v = m_sarima_seasonal(tr)
        out["E3"] = float(v) if np.isfinite(v) else np.nan
    return out
