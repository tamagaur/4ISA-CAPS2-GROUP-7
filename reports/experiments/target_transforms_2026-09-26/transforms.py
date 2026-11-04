"""Target transforms for the 2026-09-26 personal experiment (not adopted, not pushed).

Every transform is fitted on ONE training series (one SKU, one forecast origin) and
never sees the month being forecast. `prepare(train)` returns the transformed series
and a context; `invert(f, ctx)` maps a one-step forecast on the transformed scale back
to original units, NaN where the inverse is undefined. A NaN is a blank forecast:
counted by the caller, never replaced.

Settings are the ones decided 2026-09-26, fixed before any result was computed:
  shift        c = 1 - min(train) when min(train) <= 0, else 0 (every restricted-domain transform)
  log1p        Duan smearing on the same model's in-sample one-step errors
  lambda       Box-Cox / Yeo-Johnson by maximum likelihood, bounded to [-1, 2] (bounds not widened)
  round trip   absolute 1e-9; Box-Cox / Yeo-Johnson max(1e-9 * |x|, 1e-9) (float64, see roundtrip_check)
  winsorize    5th / 95th percentile of the training series, no inverse
  pattern      first difference, STL (period 12): long bin only, >= 24 training months
"""
from __future__ import annotations

import numpy as np
from scipy import stats
from scipy.optimize import minimize_scalar

LAMBDA_BOUNDS = (-1.0, 2.0)
WINSOR_PCT = (5.0, 95.0)
STL_PERIOD = 12
PATTERN_MIN_MONTHS = 24
ROUNDTRIP_TOL = 1e-9


class TransformFailed(Exception):
    """The transform cannot be fitted on this training series: a blank forecast."""


def shift_for(x: np.ndarray) -> float:
    m = float(np.min(x))
    return 1.0 - m if m <= 0 else 0.0


def _bounded_mle(llf, data: np.ndarray) -> float:
    if len(data) < 3 or not np.isfinite(data).all() or np.ptp(data) == 0:
        raise TransformFailed("lambda: fewer than 3 points or a constant series")
    res = minimize_scalar(lambda lm: -llf(lm, data), bounds=LAMBDA_BOUNDS, method="bounded")
    if not res.success or not np.isfinite(res.x) or not np.isfinite(res.fun):
        raise TransformFailed("lambda: MLE did not converge")
    return float(res.x)


def _yj_fwd(x: np.ndarray, lm: float) -> np.ndarray:
    x = np.asarray(x, float)
    out = np.empty_like(x)
    pos = x >= 0
    out[pos] = np.log1p(x[pos]) if abs(lm) < 1e-12 else ((x[pos] + 1) ** lm - 1) / lm
    neg = ~pos
    out[neg] = -np.log1p(-x[neg]) if abs(lm - 2) < 1e-12 else -((1 - x[neg]) ** (2 - lm) - 1) / (2 - lm)
    return out


def _yj_inv(z: np.ndarray, lm: float) -> np.ndarray:
    z = np.asarray(z, float)
    out = np.full_like(z, np.nan)
    pos = z >= 0
    if abs(lm) < 1e-12:
        out[pos] = np.expm1(z[pos])
    else:
        base = lm * z[pos] + 1
        ok = base > 0
        tmp = np.full(base.shape, np.nan)
        tmp[ok] = base[ok] ** (1 / lm) - 1
        out[pos] = tmp
    neg = ~pos
    if abs(lm - 2) < 1e-12:
        out[neg] = -np.expm1(-z[neg])
    else:
        base = 1 - (2 - lm) * z[neg]
        ok = base > 0
        tmp = np.full(base.shape, np.nan)
        tmp[ok] = 1 - base[ok] ** (1 / (2 - lm))
        out[neg] = tmp
    return out


def _bc_inv(z: np.ndarray, lm: float) -> np.ndarray:
    z = np.asarray(z, float)
    if abs(lm) < 1e-12:
        return np.exp(z)
    base = lm * z + 1
    out = np.full_like(z, np.nan)
    ok = base > 0
    out[ok] = base[ok] ** (1 / lm)
    return out


class Transform:
    """name, family, tsb_ok (maps 0 to 0 with no shift: usable on TSB demand sizes),
    pattern (long bin only), smear (log1p), invertible (round trip checked)."""
    family = "squeeze"
    tsb_ok = False
    pattern = False
    smear = False
    invertible = True
    rt_relative = False

    def __init__(self, name: str):
        self.name = name

    # elementwise transforms: prepare = fit + forward; invert maps a point forecast back
    def prepare(self, tr: np.ndarray):
        ctx = self.fit(np.asarray(tr, float))
        return self.fwd(np.asarray(tr, float), ctx), ctx

    def fit(self, tr):
        return {}

    def fwd(self, x, ctx):
        raise NotImplementedError

    def inv(self, z, ctx):
        raise NotImplementedError

    def invert(self, f: float, ctx, resid=None) -> float:
        v = float(self.inv(np.array([f], float), ctx)[0])
        return v if np.isfinite(v) else np.nan

    def reconstruct(self, z, ctx):
        return self.inv(z, ctx)


class Identity(Transform):
    family, tsb_ok = "control", True

    def fwd(self, x, ctx):
        return x.copy()

    def inv(self, z, ctx):
        return np.asarray(z, float).copy()

    def invert(self, f, ctx, resid=None):
        return f


class Sqrt(Transform):
    tsb_ok = True

    def fit(self, tr):
        return {"c": shift_for(tr)}

    def fwd(self, x, ctx):
        return np.sqrt(x + ctx["c"])

    def inv(self, z, ctx):
        z = np.asarray(z, float)
        return np.where(z >= 0, z * z, np.nan) - ctx["c"]


class Log1p(Transform):
    tsb_ok, smear = True, True

    def fit(self, tr):
        return {"c": shift_for(tr)}

    def fwd(self, x, ctx):
        return np.log1p(x + ctx["c"])

    def inv(self, z, ctx):
        return np.expm1(np.asarray(z, float)) - ctx["c"]

    def invert(self, f, ctx, resid=None):
        """Duan smearing: E[x] = mean_i exp(f + e_i) - 1 - c. No finite residual -> blank."""
        e = np.asarray(resid if resid is not None else [], float)
        e = e[np.isfinite(e)]
        if not len(e) or not np.isfinite(f):
            return np.nan
        v = float(np.exp(f) * np.mean(np.exp(e)) - 1 - ctx["c"])
        return v if np.isfinite(v) else np.nan


class BoxCox(Transform):
    rt_relative = True

    def fit(self, tr):
        c = shift_for(tr)
        return {"c": c, "lm": _bounded_mle(stats.boxcox_llf, tr + c)}

    def fwd(self, x, ctx):
        return stats.boxcox(x + ctx["c"], lmbda=ctx["lm"])

    def inv(self, z, ctx):
        return _bc_inv(z, ctx["lm"]) - ctx["c"]


class YeoJohnson(Transform):
    rt_relative = True

    def fit(self, tr):
        return {"lm": _bounded_mle(stats.yeojohnson_llf, tr)}

    def fwd(self, x, ctx):
        return _yj_fwd(x, ctx["lm"])

    def inv(self, z, ctx):
        return _yj_inv(z, ctx["lm"])


class Cbrt(Transform):
    tsb_ok = True

    def fwd(self, x, ctx):
        return np.cbrt(x)

    def inv(self, z, ctx):
        z = np.asarray(z, float)
        return z * z * z


class Asinh(Transform):
    tsb_ok = True

    def fwd(self, x, ctx):
        return np.arcsinh(x)

    def inv(self, z, ctx):
        return np.sinh(np.asarray(z, float))


class Anscombe(Transform):
    def fit(self, tr):
        return {"c": shift_for(tr)}

    def fwd(self, x, ctx):
        return 2 * np.sqrt(x + ctx["c"] + 0.375)

    def inv(self, z, ctx):
        z = np.asarray(z, float)
        return np.where(z >= 0, (z / 2) ** 2, np.nan) - 0.375 - ctx["c"]


class Winsorize(Transform):
    family, tsb_ok, invertible = "clean", True, False

    def fit(self, tr):
        lo, hi = np.percentile(tr, WINSOR_PCT)
        return {"lo": float(lo), "hi": float(hi)}

    def fwd(self, x, ctx):
        return np.clip(x, ctx["lo"], ctx["hi"])

    def inv(self, z, ctx):
        return np.asarray(z, float).copy()         # no inverse: the forecast stays as produced

    def reconstruct(self, z, ctx):
        return None


class Square(Transform):
    family = "sanity"

    def fit(self, tr):
        return {"c": shift_for(tr)}

    def fwd(self, x, ctx):
        return (x + ctx["c"]) ** 2

    def inv(self, z, ctx):
        z = np.asarray(z, float)
        return np.where(z >= 0, np.sqrt(np.abs(z)), np.nan) - ctx["c"]


class MinMax(Transform):
    family = "sanity"

    def fit(self, tr):
        lo, hi = float(np.min(tr)), float(np.max(tr))
        if hi == lo:
            raise TransformFailed("min-max: constant series")
        return {"lo": lo, "hi": hi}

    def fwd(self, x, ctx):
        return 1 + 9 * (x - ctx["lo"]) / (ctx["hi"] - ctx["lo"])

    def inv(self, z, ctx):
        return ctx["lo"] + (np.asarray(z, float) - 1) * (ctx["hi"] - ctx["lo"]) / 9


class Diff(Transform):
    """First difference. z has one point fewer than the training series; a one-step
    forecast f of the next difference inverts to last_value + f."""
    family, pattern = "pattern", True

    def prepare(self, tr):
        tr = np.asarray(tr, float)
        if len(tr) < PATTERN_MIN_MONTHS:
            raise TransformFailed("diff: fewer than 24 training months")
        return np.diff(tr), {"first": float(tr[0]), "last": float(tr[-1])}

    def invert(self, f, ctx, resid=None):
        v = ctx["last"] + f
        return float(v) if np.isfinite(v) else np.nan

    def reconstruct(self, z, ctx):
        return ctx["first"] + np.concatenate([[0.0], np.cumsum(z)])


class STLAdjust(Transform):
    """STL seasonal adjustment, period 12, statsmodels defaults. The forecast month's
    seasonal term is the fitted seasonal component 12 months earlier."""
    family, pattern = "pattern", True

    def prepare(self, tr):
        from statsmodels.tsa.seasonal import STL
        tr = np.asarray(tr, float)
        if len(tr) < PATTERN_MIN_MONTHS:
            raise TransformFailed("stl: fewer than 24 training months")
        try:
            seas = np.asarray(STL(tr, period=STL_PERIOD).fit().seasonal, float)
        except Exception as exc:
            raise TransformFailed(f"stl: {type(exc).__name__}") from exc
        if not np.isfinite(seas).all():
            raise TransformFailed("stl: non-finite seasonal component")
        return tr - seas, {"seas": seas, "next_seas": float(seas[len(tr) - STL_PERIOD])}

    def invert(self, f, ctx, resid=None):
        v = f + ctx["next_seas"]
        return float(v) if np.isfinite(v) else np.nan

    def reconstruct(self, z, ctx):
        return z + ctx["seas"]


TRANSFORMS = {t.name: t for t in [
    Identity("identity"), Sqrt("sqrt"), Log1p("log1p"), BoxCox("boxcox"), YeoJohnson("yeojohnson"),
    Cbrt("cbrt"), Asinh("asinh"), Anscombe("anscombe"), Diff("diff1"), STLAdjust("stl12"),
    Winsorize("winsor"), Square("square"), MinMax("minmax"),
]}
TSB_TRANSFORMS = [n for n, t in TRANSFORMS.items() if t.tsb_ok]      # identity sqrt log1p cbrt asinh winsor


def roundtrip_check(t: Transform, tr: np.ndarray, z: np.ndarray, ctx):
    """inverse(transform(x)) vs x on one training series. None for winsorize (no inverse).

    Absolute tolerance |back - x| <= 1e-9 for every transform except Box-Cox and
    Yeo-Johnson, which use |back - x| <= max(1e-9 * |x|, 1e-9) element by element
    (approved 2026-09-26): relative for large values - at lambda near -1 the
    transform stores x as about 1 - 1/x, and a float64 keeps only ~16 significant
    digits of that, so large x cannot come back to within an absolute 1e-9 however
    the formula is written - and identical to the absolute rule at zero, where a
    purely relative bound would demand an exact 0 after a shift."""
    if not t.invertible:
        return None
    tr = np.asarray(tr, float)
    back = np.asarray(t.reconstruct(z, ctx), float)
    if back.shape != tr.shape or not np.isfinite(back).all():
        return dict(abs=np.inf, rel=np.inf, fail=True)
    err = np.abs(back - tr)
    nz = tr != 0
    rel = float(np.max(err[nz] / np.abs(tr[nz]))) if nz.any() else 0.0
    if t.rt_relative:
        fail = bool((err > np.maximum(ROUNDTRIP_TOL * np.abs(tr), ROUNDTRIP_TOL)).any())
    else:
        fail = bool(err.max() > ROUNDTRIP_TOL)
    return dict(abs=float(err.max()), rel=rel, fail=fail)


# --------------------------------------------------------------------------- #
# per-SKU models on a (possibly transformed) series, with in-sample one-step errors
# --------------------------------------------------------------------------- #
def ma_forecast(z: np.ndarray, k: int) -> float:
    return z[-k:].mean()


def ma_resid(z: np.ndarray, k: int) -> np.ndarray:
    return np.array([z[t] - z[max(0, t - k):t].mean() for t in range(1, len(z))], float)


def ses_fit(z: np.ndarray):
    """scripts.model_bakeoff.m_ses's exact call, plus its in-sample one-step errors."""
    import pandas as pd
    from statsmodels.tsa.holtwinters import SimpleExpSmoothing
    try:
        s = pd.Series(z, index=pd.date_range("2000-01-01", periods=len(z), freq="MS"))
        r = SimpleExpSmoothing(s, initialization_method="estimated").fit()
        return float(r.forecast(1).iloc[0]), np.asarray(s - r.fittedvalues, float)
    except Exception:
        return np.nan, np.array([])


def tsb_sizes(x: np.ndarray, t: Transform, a: float = 0.3, b: float = 0.1):
    """TSB (scripts.model_bakeoff.m_tsb / baseline.tsb_forecast arithmetic) with the
    transform applied to demand SIZES only (months > 0). Zero and negative months keep
    TSB's handling: no demand, probability decays. Returns (forecast, n_blank_reason)."""
    x = np.asarray(x, float)
    pos = x > 0
    if t.name == "identity":
        y, ctx = x, None
    else:
        if not pos.any():
            return 0.0 * float((x > 0).mean()), None      # no sizes to transform: m_tsb gives 0
        zs, ctx = t.prepare(x[pos])
        y = x.copy()
        y[pos] = zs
    demand = y[y > 0].mean() if (y > 0).any() else 0.0
    prob = (y > 0).mean()
    errs = []
    for v in y:
        if v > 0:
            errs.append(v - demand)
            demand += a * (v - demand)
            prob += b * (1 - prob)
        else:
            prob += b * (0 - prob)
    if t.name == "identity":
        return demand * prob, None
    size = t.invert(float(demand), ctx, resid=np.asarray(errs, float))
    return (size * prob if np.isfinite(size) else np.nan), None
