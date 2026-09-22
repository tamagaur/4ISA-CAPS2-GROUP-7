"""Step 2 (scratch venv, no xgboost): lgbm@A / lgbm_q50@A / lgbm_tweedie@A / ridge@A (harness features, monthly
retrain on months < m, Tier A pool) and chronos-bolt-small zero-shot median. Args: arm."""
import sys, time, json, pickle
import numpy as np, pandas as pd, lightgbm as lgb
assert "xgboost" not in sys.modules
arm = sys.argv[1]; SEED, OFF, NPER = 20260921, 24, 62
Z = np.load(f"feat_{arm}.npz"); F, g, pk = Z["F"], Z["g"], Z["pk"]
L = pd.read_csv(f"local_{arm}.csv")[["pk", "g"]]
s = F[:, 14]; ok = s > 0; UNIT = list(range(10))
Xs = F[:, :14].copy(); Xs[:, UNIT] /= np.where(ok, s, np.nan)[:, None]; ys = F[:, 15] / np.where(ok, s, np.nan)
Xd = np.where(np.isfinite(Xs), Xs, 1.0)
LGB = dict(learning_rate=0.05, num_leaves=15, min_data_in_leaf=20, bagging_fraction=0.8, bagging_freq=1,
           feature_fraction=0.8, seed=SEED, verbose=-1, num_threads=8)
OBJ = {"lgbm@A": dict(objective="l1"), "lgbm_q50@A": dict(objective="quantile", alpha=0.5),
       "lgbm_tweedie@A": dict(objective="tweedie")}              # tweedie: labels clipped at 0 (returns), library requirement
RUN = ["lgbm@A", "lgbm_q50@A", "lgbm_tweedie@A"]   # ridge@A: sklearn DLL blocked by Application Control -> numpy closed form in main env
RT, res = {}, {}
for name in RUN:
    t0 = time.time(); pred = np.full(len(F), np.nan)
    for m in range(OFF + 9, NPER):
        trm, tem = ok & (g < m), ok & (g == m)
        if trm.sum() < 100 or not tem.any(): continue
        if name == "ridge@A":
            from sklearn.linear_model import Ridge
            from sklearn.preprocessing import StandardScaler
            sc = StandardScaler().fit(Xd[trm]); p = Ridge(alpha=1.0).fit(sc.transform(Xd[trm]), ys[trm]).predict(sc.transform(Xd[tem]))
        else:
            y = ys[trm] if name != "lgbm_tweedie@A" else np.maximum(ys[trm], 0.0)
            b = lgb.train({**LGB, **OBJ[name]}, lgb.Dataset(np.ascontiguousarray(Xs[trm]), label=np.ascontiguousarray(y, dtype=np.float32)),
                          num_boost_round=300)
            p = b.predict(np.ascontiguousarray(Xs[tem]))
        pred[tem] = np.maximum(0.0, p * s[tem])
    res[name] = pred; RT[f"{arm}:{name}"] = time.time() - t0
out = L.merge(pd.DataFrame({"pk": pk, "g": g, **res}), on=["pk", "g"], how="left")

# chronos-bolt-small: NOT RUN - torch DLL (shm.dll) blocked by Windows Application Control policy
out.to_csv(f"venv_{arm}.csv", index=False); json.dump(RT, open(f"rt_venv_{arm}.json", "w"), indent=1)
print(arm, {k: round(v, 1) for k, v in RT.items()}, "| NaN:", out.isna().sum()[lambda v: v > 0].to_dict())
