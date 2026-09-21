import os, numpy as np, pandas as pd, warnings
warnings.simplefilter("ignore")
OUT = os.path.dirname(os.path.abspath(__file__))
R = pd.read_pickle(os.path.join(OUT, "b.pkl")).assign(arm="real")
G = pd.read_pickle(os.path.join(OUT, "g.pkl"))
ALL = pd.concat([R, G]); ORDER = ["short", "medium", "long_down", "long_flat", "long_up"]
binof = R.drop_duplicates("pk").set_index("pk").bin; size = binof.value_counts()
W = {a: t.pivot(index="pk", columns="model", values="wape") for a, t in ALL.groupby("arm")}
MODELS = list(R.model.unique()); ev = W["real"].index[np.isfinite(W["real"].ma3)]
print("eval SKUs:", len(ev), "| NaN MA3 per arm:", {a: int(W[a].loc[ev, "ma3"].isna().sum()) for a in W})

print("\n== fittable SKUs (real -> A calendar-true / B spliced), models that change only ==")
fit = ALL.pivot_table(index=["model"], columns=["bin", "arm"], values="fittable", aggfunc="sum")
for m in MODELS:
    cells = [f"{b}:{int(fit.loc[m,(b,'real')])}->{int(fit.loc[m,(b,'A')])}/{int(fit.loc[m,(b,'B')])}" for b in ORDER
             if len({fit.loc[m,(b,a)] for a in ('real','A','B')}) > 1]
    if cells: print(f"{m:<16}", "  ".join(cells))
tot = ALL[ALL.pk.isin(ev)].groupby(["arm", "model"]).fittable.sum().unstack(0)
print("cohort totals  ", tot.loc[["hw_add12", "sarima_seasonal"]].to_dict("index"))

print("\n== per model, paired per-SKU WAPE change vs real-only (119 SKUs; median delta, better/worse) ==")
print(f"{'model':<16}{'real med':>9} |{'A med':>7}{'dMed':>8}{'btr':>5}{'wrs':>5} |{'B med':>7}{'dMed':>8}{'btr':>5}{'wrs':>5}")
for m in MODELS:
    r = W["real"].loc[ev, m]; line = f"{m:<16}{r.median():>9.3f} |"
    for a in "AB":
        s = W[a].loc[ev, m]; ok = r.notna() & s.notna(); dlt = (s - r)[ok]
        line += f"{s.median():>7.3f}{dlt.median():>+8.3f}{int((dlt < -1e-9).sum()):>5}{int((dlt > 1e-9).sum()):>5} |"
    print(line)

print("\n== best model per bin under each arm (kept if scored on >= half the bin) ==")
best = {}
for a in ("real", "A", "B"):
    for b in ORDER:
        pks = binof[binof == b].index; t = W[a].loc[pks]
        med = t.median()[t.notna().sum() * 2 >= len(pks)].sort_values()
        best[(a, b)] = med.index[0]
        print(f"{a:<5}{b:<11} best={med.index[0]:<16}{med.iloc[0]:.3f}  2nd={med.index[1]:<14}{med.iloc[1]:.3f}  ma3={t.ma3.median():.3f}")

print("\n== routing, all scored on REAL test months ==")
base = W["real"].loc[ev, "ma3"]
print(f"{'strategy':<44}{'medWAPE':>8}{'meanWAPE':>9}{'improved':>9}{'worsened':>9}")
def show(label, s):
    print(f"{label:<44}{s.median():>8.3f}{s.mean():>9.3f}{int((s < base-1e-12).sum()):>9}{int((s > base+1e-12).sum()):>9}")
show("always-MA3 (real-only)", base)
for a in ("real", "A", "B"):
    s = pd.Series({pk: (W[a].loc[pk, best[(a, binof[pk])]] if binof[pk] != "long_up" and np.isfinite(W[a].loc[pk, best[(a, binof[pk])]])
                        else W[a].loc[pk, "ma3"]) for pk in ev})
    show(f"per-bin winner, models trained on {a}", s)
    show(f"per-SKU oracle, models trained on {a}", W[a].loc[ev].min(axis=1))
print("NaN check: ", {a: int(W[a].loc[ev].min(axis=1).isna().sum()) for a in W})
