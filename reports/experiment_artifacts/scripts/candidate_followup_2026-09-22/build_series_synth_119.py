"""SYNTH-arm series for the 119 (used by arms_local.py / score_arms.py): v2 pre-2023 placeholder rows from
staging_synthetic/unilever_sku (Phase B v2 files, never public is_demo rows) prepended to the rebuilt real series.
Quantity = 'Sale Quantity in Aggr.PC' (the column the canonical load maps to quantity_sold). -> series_synth.pkl
(The 119-SKU series_synth.csv this step also wrote was later replaced by build_series_synth_132.py.)"""
import glob, numpy as np, pandas as pd
V = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(r"C:\Users\kyuan\Capstone-Project\staging_synthetic\unilever_sku\*.parquet"))])
V["month"] = V._period; V = V[V.month < "2023-01"]
V["q"] = pd.to_numeric(V["Sale Quantity in\r\n  Aggr.PC"], errors="coerce")
d = pd.read_csv("dim_119.csv", dtype={"sku_code": str}); code2pk = dict(zip(d.sku_code.str.strip(), d.pk))
V["pk"] = V.Product.astype(str).str.strip().map(code2pk); P = V[V.pk.notna()]
S = pd.read_pickle("series_tierA.pkl"); per = [str(p) for p in pd.period_range("2021-01", "2026-02", freq="M")]; off = 24
SS = {}
for pk, (fs, x) in S.items():
    full = np.zeros(len(per)); full[off + fs: off + fs + len(x)] = x
    ph = np.zeros(len(per), bool)
    for r in P[P.pk == pk].itertuples(): full[per.index(r.month)] += r.q; ph[per.index(r.month)] = True
    f0 = int(np.nonzero(full > 0)[0][0]); SS[pk] = (f0, full[f0:], ph[f0:])
pd.to_pickle(SS, "series_synth.pkl")
