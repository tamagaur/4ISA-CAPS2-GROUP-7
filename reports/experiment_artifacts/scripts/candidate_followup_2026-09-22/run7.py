"""6 of the 7 pre-declared models on the candidate_search_tierA origins (lgbm@A blocked: lightgbm not installed)."""
import sys, time, warnings
import numpy as np, pandas as pd
from concurrent.futures import ProcessPoolExecutor
warnings.simplefilter("ignore")
R = r"C:\Users\kyuan\Capstone-Project\reports\experiment_artifacts"

def ses_bounded(y):
    """statsforecast _optimized_ses_forecast semantics: level starts at y[0], alpha in [0.1, 0.3] minimising SSE; via statsmodels."""
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
    if len(y) < 2: return float(y[-1])
    m = ExponentialSmoothing(y, trend=None, initialization_method="known", initial_level=float(y[0]),
                             bounds={"smoothing_level": (0.1, 0.3)})
    return float(m.fit(optimized=True).forecast(1)[0])

def agg_fc(y, lvl):
    y = y[len(y) % lvl:]; n = len(y) // lvl
    return ses_bounded(y[:n * lvl].reshape(n, lvl).sum(axis=1)) / lvl

def level_of(y):
    nz = np.nonzero(y != 0)[0]
    return max(1, int(round(np.diff(nz + 1, prepend=0).mean())))

def adida(y):
    return 0.0 if (y == 0).all() else agg_fc(y, level_of(y))

def imapa(y):
    return 0.0 if (y == 0).all() else float(np.mean([agg_fc(y, l) for l in range(1, level_of(y) + 1)]))

def _otm_path(p, y):
    ell0, a, th = p; n = len(y)
    lvl = a * y[0] + (1 - a) * ell0; meany = An = y[0]; Bn = 0.0; err = []
    for i in range(1, n + 1):
        mu = lvl + (1 - 1 / th) * ((1 - a) ** i * An + (1 - (1 - a) ** (i + 1)) / a * Bn)
        if i == n: return err, mu
        err.append(y[i] - mu)
        lvl = a * y[i] + (1 - a) * lvl
        Bn = ((i - 1) * Bn + 6 * (y[i] - meany) / (i + 1)) / (i + 2)
        meany = (i * meany + y[i]) / (i + 1)
        An = meany - Bn * (i + 2) / 2

def otm(y):
    """Optimized Theta (Fiorucci et al. 2016 state-space form, as in statsforecast OTM, no seasonal adjustment): ell0, alpha, theta by MSE."""
    from scipy.optimize import minimize
    if len(y) < 2: return float(y[-1])
    sc = max(np.abs(y).max(), 1.0); z = y / sc
    obj = lambda p: float(np.mean(np.square(_otm_path(p, z)[0])))
    r = minimize(obj, [z[0] / 2, 0.5, 2.0], method="L-BFGS-B", bounds=[(-10, 10), (0.1, 0.99), (1.0, 1e3)])
    return float(_otm_path(r.x, z)[1] * sc)

FN = {"adida": adida, "imapa": imapa, "otm": otm}

def run(args):
    name, pk, fs, x, tis = args
    out = []
    for ti in tis:
        try: f = FN[name](np.asarray(x[:ti - fs], float))
        except Exception: f = np.nan
        out.append((pk, ti, max(0.0, f) if np.isfinite(f) else np.nan))
    return out

if __name__ == "__main__":
    A = pd.read_csv(R + r"\candidate_search_tierA_preds.csv.gz"); S = pd.read_pickle("series_tierA.pkl")
    n0, c0 = A.shape
    # harness check: rebuilt series + model_bakeoff.m_ses must reproduce the artifact's ses column
    sys.path.insert(0, r"C:\Users\kyuan\Capstone-Project"); from scripts.model_bakeoff import m_ses
    smp = A.sample(150, random_state=1); d = [abs(max(0, m_ses(S[r.pk][1][:r.ti - S[r.pk][0]])) - r.ses) for r in smp.itertuples()]
    print(f"ses reproduction on 150 sampled origins: max abs diff {np.nanmax(d):.3g}", flush=True)
    jobs = {pk: (S[pk][0], S[pk][1], g.ti.tolist()) for pk, g in A.groupby("pk")}
    rt = {}
    for name in FN:
        t0 = time.time()
        with ProcessPoolExecutor(max_workers=12) as ex:
            res = [r for rows in ex.map(run, [(name, pk, *v) for pk, v in jobs.items()]) for r in rows]
        A = A.merge(pd.DataFrame(res, columns=["pk", "ti", name]), on=["pk", "ti"], how="left"); rt[name] = time.time() - t0
        print(f"{name}: {rt[name]:.1f}s NaN={int(A[name].isna().sum())}", flush=True)
    for name, cols, agg in (("comb_m4", ["ses", "holt", "holt_damped"], "mean"), ("comb_simple", ["ma4", "ma12", "ses"], "mean"),
                            ("med_3", ["ma3", "ses", "theta"], "median")):
        t0 = time.time(); A[name] = getattr(A[cols], agg)(axis=1, skipna=False); rt[name] = time.time() - t0
        print(f"{name}: {rt[name]:.3f}s NaN={int(A[name].isna().sum())}")
    print(f"rows {n0} -> {len(A)} | cols {c0} -> {A.shape[1]}")
    A.to_csv("preds_plus.csv.gz", index=False); pd.Series(rt).to_csv("runtime7.csv")
