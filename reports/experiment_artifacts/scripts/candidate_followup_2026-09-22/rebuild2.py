import numpy as np, pandas as pd
B = pd.read_csv(r"C:\Users\kyuan\Capstone-Project\reports\experiment_artifacts\rolling_origin_preds_tierABC_base_models.csv.gz")
B = B[B.tier == "A"].sort_values(["pk", "ti"])
K = {"naive": 1, "ma2": 2, "ma3": 3, "ma4": 4, "ma6": 6, "ma12": 12}
S, worst = {}, 0.0
for pk, g in B.groupby("pk"):
    fs = int(g.ti.iloc[0] - 3); act = g.actual.to_numpy(); n = 3 + len(act)
    rows, rhs = [], []
    for r in g.itertuples():              # every unclipped (>0) MA/mean value is an exact linear equation in x0..x2
        t = r.ti - fs
        for name, k in list(K.items()) + [("mean", None)]:
            v = getattr(r, name); k = t if k is None else min(k, t)
            if v <= 0: continue
            idx = range(t - k, t); c = np.zeros(3); known = 0.0
            for i in idx:
                if i < 3: c[i] += 1 / k
                else: known += act[i - 3] / k
            if c.any(): rows.append(c); rhs.append(v - known)
    sol, *_ = np.linalg.lstsq(np.array(rows), np.array(rhs), rcond=None)
    x = np.r_[sol, act]; S[pk] = (fs, x)
    for r in g.itertuples():
        tr = x[:r.ti - fs]
        for name, k in list(K.items()) + [("mean", len(tr))]:
            worst = max(worst, abs(max(0.0, tr[-k:].mean()) - getattr(r, name)))
print("SKUs", len(S), "| max abs error vs every naive/ma2/ma3/ma4/ma6/ma12/mean in the artifact:", worst)
pd.to_pickle(S, "series_tierA.pkl")
