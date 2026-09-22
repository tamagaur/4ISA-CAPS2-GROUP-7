"""ridge@A = sklearn StandardScaler + Ridge(alpha=1, fit_intercept) in closed form (sklearn DLL blocked). Harness Xd features."""
import sys, time, json, numpy as np, pandas as pd
OFF, NPER = 24, 62
def run(arm):
    Z = np.load(f"feat_{arm}.npz"); F, g, pk = Z["F"], Z["g"], Z["pk"]
    s = F[:, 14]; ok = s > 0; Xs = F[:, :14].copy(); Xs[:, :10] /= np.where(ok, s, np.nan)[:, None]; ys = F[:, 15] / np.where(ok, s, np.nan)
    Xd = np.where(np.isfinite(Xs), Xs, 1.0); pred = np.full(len(F), np.nan); t0 = time.time()
    for m in range(OFF + 9, NPER):
        trm, tem = ok & (g < m), ok & (g == m)
        if trm.sum() < 100 or not tem.any(): continue
        X, y = Xd[trm], ys[trm]; mu, sd = X.mean(0), X.std(0); sd[sd == 0] = 1.0
        Xz = (X - mu) / sd; xm, ym = Xz.mean(0), y.mean(); Xc = Xz - xm
        beta = np.linalg.solve(Xc.T @ Xc + np.eye(Xc.shape[1]), Xc.T @ (y - ym))
        pred[tem] = np.maximum(0.0, (((Xd[tem] - mu) / sd) @ beta + ym - xm @ beta) * s[tem])
    return pd.DataFrame({"pk": pk, "g": g, "ridge@A": pred}), time.time() - t0
A = pd.read_csv("preds_plus.csv.gz"); A["g"] = A.ti + OFF
r, _ = run("real"); m = A.merge(r, on=["pk", "g"], suffixes=("", "_np"))
d = (m["ridge@A"] - m["ridge@A_np"]).abs(); rel = d / m["ridge@A"].abs().clip(lower=1)
print("REAL check vs artifact ridge@A: max abs", float(d.max()), "| max rel", float(rel.max()), "| NaN mismatch", int((m["ridge@A"].isna() != m["ridge@A_np"].isna()).sum()))
r, t = run("synth"); L = pd.read_csv("local_synth.csv")[["pk", "g"]].merge(r, on=["pk", "g"], how="left")
L.to_csv("ridge_synth.csv", index=False); json.dump({"synth:ridge@A": t}, open("rt_ridge.json", "w")); print("synth ridge", round(t, 1), "s | NaN", int(L["ridge@A"].isna().sum()))
