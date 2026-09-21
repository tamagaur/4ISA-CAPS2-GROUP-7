"""DIAGNOSTIC ONLY: does a synthetic 2021-22 training prefix change the medium->TSB / long->XGBoost picture? Tier A, no DB."""
import os, sys, pickle, warnings
import numpy as np, pandas as pd, xgboost as xgb
warnings.simplefilter("ignore")
OUT = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, r"C:\Users\kyuan\Capstone-Project")
from scripts.model_bakeoff import m_tsb
SEED = 20260921
A = pd.read_pickle(os.path.join(OUT, "final_models_A.pkl")).sort_values(["pk", "ti"]).reset_index(drop=True)
d = pickle.load(open(os.path.join(OUT, "a.pkl"), "rb")); syn = pickle.load(open(os.path.join(OUT, "synth.pkl"), "rb")); syn = syn[syn.month <= "2022-12"]
grid = [str(p) for p in pd.period_range("2021-01", "2022-12", freq="M")]; gi = {m: i for i, m in enumerate(grid)}
ext = {}
for pk in d["cohort"]:
    e = np.zeros(24 + 38); e[24:] = d["m26"][pk]; ext[pk] = e
for r in syn.itertuples(index=False):
    ext[r.pk][gi[r.month]] += r.q
print("SKUs with synthetic prefix:", syn.pk.nunique(), "| prefix rows:", len(syn), "| Tier A test points:", len(A))

def feats(tr, ti_cal, target):
    s = tr[-6:].mean(); lag = lambda k: tr[-k] if len(tr) >= k else np.nan
    if not s > 0: return None
    u = [lag(1), lag(2), lag(3), lag(4), lag(5), lag(6), lag(12), tr[-3:].mean(), tr[-12:].mean() if len(tr) >= 12 else np.nan, tr[-6:].std()]
    return [v / s for v in u] + [float((tr[-6:] <= 0).sum()), len(tr), (tr > 0).sum() / len(tr), (ti_cal % 12) + 1, s, target / s]

first = {pk: int(np.nonzero(e > 0)[0][0]) for pk, e in ext.items()}
rows, tsb = [], []
for r in A[["pk", "ti", "actual"]].itertuples(index=False):
    tr = ext[r.pk][first[r.pk]:24 + r.ti]
    tsb.append(max(0.0, m_tsb(tr)))
    rows.append(feats(tr, r.ti, r.actual))
A["tsb_syn"] = tsb
F = np.array([f if f is not None else [np.nan] * 16 for f in rows], float); X, s, y = F[:, :14], F[:, 14], F[:, 15]; ok = np.isfinite(s)
extra = []                                     # variant (b): training rows whose TARGET is a synthetic month
for pk, e in ext.items():
    for t in range(first[pk] + 3, 24):
        f = feats(e[first[pk]:t], t - 24, e[t])
        if f is not None: extra.append(f)
E = np.array(extra, float); print("extra synthetic-target training rows:", len(E))
ti = A.ti.to_numpy(); params = dict(max_depth=4, eta=0.05, subsample=0.8, colsample_bytree=0.8, objective="reg:absoluteerror", seed=SEED, nthread=8)
for name, add in (("xgb_synA", False), ("xgb_synB", True)):
    pred = np.full(len(A), np.nan)
    for m in range(9, 38):
        trm, tem = ok & (ti < m), ok & (ti == m)
        if not tem.any() or (trm.sum() < 100 and not add): continue
        Xtr, ytr = (np.vstack([X[trm], E[:, :14]]), np.concatenate([y[trm], E[:, 15]])) if add else (X[trm], y[trm])
        pred[tem] = np.maximum(0.0, xgb.train(params, xgb.DMatrix(Xtr, label=ytr), num_boost_round=300).predict(xgb.DMatrix(X[tem])) * s[tem])
    A[name] = pred; A["ens_" + name] = A[[name, "ma3"]].mean(axis=1, skipna=False)
A.to_pickle(os.path.join(OUT, "synth_check.pkl"))
MS = ["ma3", "tsb", "tsb_syn", "xgb_abs@A", "xgb_synA", "xgb_synB", "ens_xgb_ma3@A", "ens_xgb_synA", "ens_xgb_synB"]
print("NaN preds >=2023-10:", A[A.month >= "2023-10"][MS].isna().sum()[lambda v: v > 0].to_dict(), "| inf:", int(np.isinf(A[MS]).sum().sum()))
rng = np.random.default_rng(SEED); out = []
for (pk, b), g in A[A.month >= "2023-10"].groupby(["pk", "bin"]):
    a = g.actual.to_numpy(); den = np.abs(a).sum()
    if len(g) < 3 or den <= 0: continue
    out.append({"pk": pk, "bin": b, **{m: (np.abs(a - g[m].to_numpy()).sum() / den if np.isfinite(g[m]).all() else np.nan) for m in MS}})
C = pd.DataFrame(out)
for b in ("short", "medium", "long"):
    c = C[C.bin == b]; print(f"\n{b}: n={len(c)} | MA3 {c.ma3.median():.3f}")
    for m in MS[1:]:
        okk = c[m].notna(); a, bb = c.loc[okk, m].to_numpy(), c.loc[okk, "ma3"].to_numpy(); i = rng.integers(0, len(a), (1000, len(a)))
        dd = np.median(a[i], axis=1) - np.median(bb[i], axis=1); lo, hi = np.percentile(dd, [2.5, 97.5])
        print(f"   {m:<16}{np.median(a):.3f}  [{lo:+.3f}, {hi:+.3f}]  {int((a < bb).sum()):>3}/{int((a > bb).sum()):<3} n={len(a):<4}{'BETTER' if hi < 0 else 'WORSE' if lo > 0 else 'tied'}")
