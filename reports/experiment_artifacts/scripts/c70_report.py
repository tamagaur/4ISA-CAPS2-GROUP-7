import os, pickle
import numpy as np, pandas as pd

OUT = os.path.dirname(os.path.abspath(__file__))
SEED, NBOOT = 20260921, 1000
d = pickle.load(open(os.path.join(OUT, "a.pkl"), "rb"))
df = pd.read_pickle(os.path.join(OUT, "b70.pkl"))
ORDER = ["insufficient", "short", "medium", "long_down", "long_flat", "long_up"]
UNDER = {"insufficient", "long_up"}
MODELS = list(df.model.unique())
binsize = df.drop_duplicates("pk").bin.value_counts()

print("== T1 fittable SKUs per bin (finite forecast at every test origin, real only) ==")
fit = df.pivot_table(index="model", columns="bin", values="fittable", aggfunc="sum").reindex(MODELS)[ORDER].astype(int)
print(fit.to_string())
print("bin size      ", {b: int(binsize[b]) for b in ORDER})
keep = {b: [m for m in MODELS if fit.loc[m, b] * 2 >= binsize[b]] for b in ORDER}
for b in ORDER:
    print(f"dropped[{b}]: {[m for m in MODELS if m not in keep[b]] or 'none'}")
g = df[df.model.isin(["sarima_seasonal", "sarima_plain"])].groupby("model").guarded.agg(["sum", lambda s: (s > 0).sum()])
print("divergence guard (origins, SKUs):", g.values.tolist(), "for", g.index.tolist())
fw = df[df.fittable & df.wape.isna()].groupby("model").size()
print("fittable but WAPE NaN (guard or sum|a|=0):", fw.to_dict())

print("\n== T2a bin windows ==")
sk = df.drop_duplicates("pk")
ev = sk[(sk.ntr >= 3) & (sk.nte >= 1)]
for b in ORDER:
    a, e = sk[sk.bin == b], ev[ev.bin == b]
    if len(e) == 0:
        print(f"{b:<13} n={len(a):>3} evaluable=0   median active months={a.n.median():.0f}  -> NOT EVALUABLE"); continue
    thin = "THIN" if e.nte.median() < 3 else ""
    print(f"{b:<13} n={len(a):>3} evaluable={len(e):>3} med_train={e.ntr.median():.1f} med_test={e.nte.median():.1f} {thin}")

W = df.pivot(index="pk", columns="model", values="wape")
S = df.pivot(index="pk", columns="model", values="smape")
M = df.pivot(index="pk", columns="model", values="mase")
binof = sk.set_index("pk").bin
rng = np.random.default_rng(SEED)
full, winners, decisive = [], {}, {}
for b in ORDER:
    pks = binof[binof == b].index.to_numpy()
    if len(ev[ev.bin == b]) == 0:
        continue
    idx = rng.integers(0, len(pks), size=(NBOOT, len(pks)))
    boot = {}
    for m in keep[b]:
        w = W.loc[pks, m].to_numpy()
        if np.isfinite(w).sum() == 0:
            continue
        with np.errstate(all="ignore"):
            boot[m] = np.nanmedian(w[idx], axis=1)
        lo, hi = np.nanpercentile(boot[m], [2.5, 97.5])
        full.append(dict(bin=b, model=m, med_wape=np.nanmedian(w), med_smape=np.nanmedian(S.loc[pks, m]),
                         med_mase=np.nanmedian(M.loc[pks, m]), n=int(np.isfinite(w).sum()), lo=lo, hi=hi,
                         nan_boot=int(np.isnan(boot[m]).sum())))
    t = pd.DataFrame([r for r in full if r["bin"] == b]).sort_values("med_wape")
    win = t.iloc[0].model
    ma3 = t[t.model == "ma3"].iloc[0]
    diff = boot[win] - boot["ma3"]
    winners[b] = (win, t.iloc[0], ma3, np.nanpercentile(diff, [2.5, 97.5]))
    decisive[b] = bool(t.iloc[0].hi < ma3.lo) and win != "ma3"
F = pd.DataFrame(full)
F.to_csv(os.path.join(OUT, "per_bin_full70.csv"), index=False)
print("NaN check on table cells:", int(F[["med_wape", "med_smape", "med_mase", "lo", "hi"]].isna().sum().sum()),
      "| all-NaN bootstrap resamples:", int(F.nan_boot.sum()))

print(f"\n== T2b per bin: top 4 by median WAPE + MA3 (full {len(F)}-row table in scratchpad per_bin_full70.csv) ==")
print(f"{'bin':<13}{'model':<16}{'WAPE':>7}{'sMAPE':>7}{'MASE':>7}{'n':>4}  95% CI med WAPE")
for b in ORDER:
    t = F[F.bin == b].sort_values("med_wape")
    if t.empty:
        continue
    show = t.head(4)
    if "ma3" not in show.model.values:
        show = pd.concat([show, t[t.model == "ma3"]])
    for r in show.itertuples():
        rank = int((t.model.values == r.model).argmax()) + 1
        print(f"{b:<13}{r.model:<16}{r.med_wape:>7.3f}{r.med_smape:>7.3f}{r.med_mase:>7.3f}{r.n:>4}  [{r.lo:.3f}, {r.hi:.3f}]  rank {rank}/{len(t)}")

print("\n== T2c verdict per bin ==")
for b in ORDER:
    if b not in winners:
        print(f"{b:<13} UNDERPOWERED / not evaluable - no winner named"); continue
    win, wr, mr, dci = winners[b]
    if b in UNDER:
        print(f"{b:<13} UNDERPOWERED (n={int(binsize[b])}) - no winner named; MA3 {mr.med_wape:.3f} [{mr.lo:.3f}, {mr.hi:.3f}]"); continue
    tag = "MA3 IS BEST" if win == "ma3" else ("DECISIVE" if decisive[b] else "NOT DECISIVE (intervals overlap)")
    print(f"{b:<13} best={win:<12} {wr.med_wape:.3f} [{wr.lo:.3f}, {wr.hi:.3f}] vs MA3 {mr.med_wape:.3f} [{mr.lo:.3f}, {mr.hi:.3f}]"
          f" | paired diff-of-medians CI [{dci[0]:+.3f}, {dci[1]:+.3f}] -> {tag}")

print("\n== T3 routing value ==")
evalpk = W.index[np.isfinite(W["ma3"])]
base = W.loc[evalpk, "ma3"]


def route(pick):
    out = base.copy()
    for pk in evalpk:
        m = pick(pk)
        if m and np.isfinite(W.loc[pk, m]):
            out[pk] = W.loc[pk, m]
    return out


def loo_pick(pk):
    b = binof[pk]
    if b in UNDER or b not in winners:
        return None
    others = binof[(binof == b) & (binof.index != pk)].index
    return W.loc[others, keep[b]].median().idxmin()


strat = {
    "always-MA3": base,
    "per-bin winner": route(lambda pk: winners[binof[pk]][0] if binof[pk] in winners and binof[pk] not in UNDER else None),
    "winner if decisive": route(lambda pk: winners[binof[pk]][0] if decisive.get(binof[pk]) and binof[pk] not in UNDER else None),
    "per-SKU oracle": W.loc[evalpk].min(axis=1),
    "(extra) LOO bin winner": route(loo_pick),
}
print(f"eval set = SKUs with finite MA3 WAPE: {len(evalpk)} of 132; by bin {binof[evalpk].value_counts().reindex(ORDER).fillna(0).astype(int).to_dict()}")
print(f"{'strategy':<24}{'medWAPE':>9}{'meanWAPE':>10}{'improved':>10}{'worsened':>10}{'NaN':>5}")
for k, s in strat.items():
    print(f"{k:<24}{s.median():>9.3f}{s.mean():>10.3f}{int((s < base - 1e-12).sum()):>10}{int((s > base + 1e-12).sum()):>10}{int(s.isna().sum()):>5}")
orc = W.loc[evalpk].idxmin(axis=1)
print(f"oracle: MA3 is the per-SKU best for {int((orc == 'ma3').sum())}/{len(evalpk)}; oracle picks: {orc.value_counts().head(6).to_dict()}")
o, a = strat["per-SKU oracle"], base
print(f"oracle vs MA3: median WAPE {o.median():.3f} vs {a.median():.3f} = {100 * (1 - o.median() / a.median()):.1f}% lower; "
      f"median per-SKU ratio oracle/MA3 = {(o / a).median():.3f}")

print("\n== T4 stability: combined_v1 @2025-08 -> @2026-02, same 132 SKUs ==")
t = pd.DataFrame({"b25": {pk: v["bin"] for pk, v in d["b25"].items()}, "b26": {pk: v["bin"] for pk, v in d["b26"].items()}})
print(pd.crosstab(t.b25, t.b26).reindex(index=ORDER, columns=ORDER, fill_value=0).to_string())
ch = t[t.b25 != t.b26]
longs = {"long_down", "long_flat", "long_up"}
lenmove = ch[~ch.b25.isin(longs)]
trend = ch[ch.b25.isin(longs)]
print(f"changed bin: {len(ch)}/132 ({100 * len(ch) / 132:.1f}%) | length-driven (from insufficient/short/medium): {len(lenmove)}"
      f" | trend-label flips within long_*: {len(trend)} of {int(t.b25.isin(longs).sum())} long SKUs @2025-08")
print("moves:", ch.groupby(["b25", "b26"]).size().sort_values(ascending=False).to_dict())
nohist = sum(1 for v in d["b25"].values() if v["hm"] == 0)
print(f"SKUs with zero sales months through 2025-08 (launched after): {nohist}")
