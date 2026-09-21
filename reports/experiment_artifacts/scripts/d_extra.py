import os, numpy as np, pandas as pd
from scipy.stats import binomtest, wilcoxon
OUT = os.path.dirname(os.path.abspath(__file__))
F = pd.read_csv(os.path.join(OUT, "per_bin_full.csv"))
print(F[F.nan_boot > 0][["bin", "model", "n", "nan_boot"]].to_string(index=False))
df = pd.read_pickle(os.path.join(OUT, "b.pkl"))
W = df.pivot(index="pk", columns="model", values="wape")
binof = df.drop_duplicates("pk").set_index("pk").bin
win = {"short": "ma3", "medium": "snaive12", "long_down": "sba_a3", "long_flat": "sba"}
pk = W.index[np.isfinite(W.ma3)]
base = W.loc[pk, "ma3"].to_numpy()
rt = np.array([W.loc[p, win.get(binof[p], "ma3")] if np.isfinite(W.loc[p, win.get(binof[p], "ma3")]) else W.loc[p, "ma3"] for p in pk])
print("NaN in routed:", int(np.isnan(rt).sum()), "n:", len(rt))
rng = np.random.default_rng(20260921)
idx = rng.integers(0, len(pk), size=(1000, len(pk)))
dm = np.median(rt[idx], axis=1) - np.median(base[idx], axis=1)
print("pooled diff of medians (routed - MA3): %.3f  95%% CI [%.3f, %.3f]" % (np.median(rt) - np.median(base), *np.percentile(dm, [2.5, 97.5])))
dmean = rt[idx].mean(axis=1) - base[idx].mean(axis=1)
print("pooled diff of means: %.3f  95%% CI [%.3f, %.3f]" % (rt.mean() - base.mean(), *np.percentile(dmean, [2.5, 97.5])))
print("sign test 48 vs 27: p=%.4f" % binomtest(48, 75, 0.5).pvalue)
d = rt - base; d = d[d != 0]
print("wilcoxon signed-rank on changed SKUs: p=%.4f n=%d" % (wilcoxon(d).pvalue, len(d)))
