"""lgbm@A exactly as final_models.py (features, scaling, monthly retrain, Tier A pool), own process, no xgboost."""
import sys, time, numpy as np, pandas as pd, lightgbm as lgb
assert "xgboost" not in sys.modules
SEED = 20260921
R = r"C:\Users\kyuan\Capstone-Project\reports\experiment_artifacts"
P = pd.read_csv(R + r"\rolling_origin_preds_tierABC_base_models.csv.gz")
P = P[P.tier == "A"].sort_values(["pk", "ti"]).reset_index(drop=True)   # pool=isA, so only Tier A rows ever enter train or test
S = pd.read_pickle("series_tierA.pkl")
periods = [str(p) for p in pd.period_range("2023-01", "2026-02", freq="M")]; ix = {p: i for i, p in enumerate(periods)}
t0 = time.time()
feats = []
for r in P[["pk", "ti", "ntr", "sales", "actual"]].itertuples(index=False):
    fs, x = S[r.pk]; assert r.ti - r.ntr == fs
    tr = x[:r.ti - fs]
    s = tr[-6:].mean()
    lag = lambda k: tr[-k] if len(tr) >= k else np.nan
    feats.append([lag(1), lag(2), lag(3), lag(4), lag(5), lag(6), lag(12), tr[-3:].mean(),
                  tr[-12:].mean() if len(tr) >= 12 else np.nan, tr[-6:].std(), float((tr[-6:] <= 0).sum()),
                  r.ntr, r.sales / r.ntr, (r.ti % 12) + 1, s, r.actual])
F = np.array(feats, float)
UNIT = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
s = F[:, 14]; ok = s > 0
Xs = F[:, :14].copy(); Xs[:, UNIT] = Xs[:, UNIT] / np.where(ok, s, np.nan)[:, None]; ys = F[:, 15] / np.where(ok, s, np.nan)
ti = P.ti.to_numpy(); pred = np.full(len(P), np.nan)
for m in range(ix["2023-10"], len(periods)):
    trm, tem = ok & (ti < m), ok & (ti == m)
    if trm.sum() < 100 or not tem.any(): continue
    mdl = lgb.train(dict(objective="l1", learning_rate=0.05, num_leaves=15, min_data_in_leaf=20, bagging_fraction=0.8, bagging_freq=1,
                         feature_fraction=0.8, seed=SEED, verbose=-1, num_threads=8),
                    lgb.Dataset(np.ascontiguousarray(Xs[trm]), label=np.ascontiguousarray(ys[trm], dtype=np.float32)), num_boost_round=300)
    pred[tem] = np.maximum(0.0, mdl.predict(np.ascontiguousarray(Xs[tem])) * s[tem])
P["lgbm@A"] = pred
rt = time.time() - t0
A = pd.read_csv("preds_plus.csv.gz"); n0, c0 = A.shape
A = A.drop(columns=["lgbm@A"], errors="ignore").merge(P[["pk", "ti", "lgbm@A"]], on=["pk", "ti"], how="left")
print(f"lgbm@A: {rt:.1f}s | rows {n0}->{len(A)} cols {c0}->{A.shape[1]} | NaN in >=2023-10: {int(A.loc[A.month >= '2023-10', 'lgbm@A'].isna().sum())}")
A.to_csv("preds_plus.csv.gz", index=False)
