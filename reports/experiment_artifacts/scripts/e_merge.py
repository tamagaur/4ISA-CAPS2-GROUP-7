import os, numpy as np, pandas as pd
OUT = os.path.dirname(os.path.abspath(__file__))
df = pd.read_pickle(os.path.join(OUT, "b.pkl"))
W = df.pivot(index="pk", columns="model", values="wape")
binof = df.drop_duplicates("pk").set_index("pk").bin
rng = np.random.default_rng(20260921)
def table(pks, label, top=6):
    pks = np.array(pks); idx = rng.integers(0, len(pks), size=(1000, len(pks)))
    base = W.loc[pks, "ma3"].to_numpy()
    rows = []
    for m in W.columns:
        w = W.loc[pks, m].to_numpy()
        if np.isfinite(w).sum() * 2 < len(pks): continue
        with np.errstate(all="ignore"):
            bm = np.nanmedian(w[idx], axis=1); d = bm - np.median(base[idx], axis=1)
        ok = np.isfinite(w)
        rows.append(dict(model=m, med=np.nanmedian(w), lo=np.nanpercentile(bm, 2.5), hi=np.nanpercentile(bm, 97.5),
                         dlo=np.nanpercentile(d, 2.5), dhi=np.nanpercentile(d, 97.5), n=int(ok.sum()),
                         better=int((w[ok] < base[ok]).sum()), worse=int((w[ok] > base[ok]).sum())))
    t = pd.DataFrame(rows).sort_values("med")
    print(f"\n== {label} (n={len(pks)}) =="); print(t.head(top).round(3).to_string(index=False))
    print(t[t.model == "ma3"].round(3).to_string(index=False, header=False))
longpk = binof[binof.str.startswith("long_")].index
table(longpk, "merged long (24+ sales months)")
table(W.index[np.isfinite(W.ma3)], "pooled, one model for everyone")
