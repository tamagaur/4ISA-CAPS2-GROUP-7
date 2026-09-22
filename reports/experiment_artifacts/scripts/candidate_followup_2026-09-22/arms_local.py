"""Step 1 (main env): per-arm origins, harness features (npz for the venv), local models, SYNTH reruns incl. xgb.
Every value at test month g reads only months < g (own series, peers, category totals)."""
import sys, time, json, warnings
import numpy as np, pandas as pd
warnings.simplefilter("ignore")
sys.path.insert(0, r"C:\Users\kyuan\Capstone-Project")
from scripts.model_bakeoff import m_ses, m_tsb, m_sba

SEED, OFF, NPER = 20260921, 24, 62          # global month index: 2021-01 = 0, 2023-01 = 24, 2026-02 = 61
A = pd.read_csv("preds_plus.csv.gz")
A["g"] = A.ti + OFF
cat = pd.read_csv("dim_119.csv").set_index("pk").category_path.to_dict()
S = pd.read_pickle("series_tierA.pkl"); SS = pd.read_pickle("series_synth.pkl")
ARMS = {"real": {pk: (OFF + fs, np.asarray(x, float)) for pk, (fs, x) in S.items()},
        "synth": {pk: (f0, np.asarray(x, float)) for pk, (f0, x, _) in SS.items()}}
RT = {}


def timed(key, fn):
    t0 = time.time(); out = fn(); RT[key] = RT.get(key, 0.0) + time.time() - t0; return out


def hist(ser, pk, g):
    f0, x = ser[pk]; return x[:max(0, g - f0)]


def full_calendar(ser):
    M = {}
    for pk, (f0, x) in ser.items():
        v = np.zeros(NPER); v[f0:f0 + len(x)] = x; M[pk] = v
    return M


def features(ser):
    """Harness (final_models.py) features at every origin t >= 3 from first sale, all months (training pool)."""
    rows, F = [], []
    for pk, (f0, x) in ser.items():
        for t in range(3, len(x)):
            tr = x[:t]; g = f0 + t; sales = int((tr > 0).sum()); s = tr[-6:].mean()
            lag = lambda k: tr[-k] if len(tr) >= k else np.nan
            F.append([lag(1), lag(2), lag(3), lag(4), lag(5), lag(6), lag(12), tr[-3:].mean(),
                      tr[-12:].mean() if len(tr) >= 12 else np.nan, tr[-6:].std(), float((tr[-6:] <= 0).sum()),
                      t, sales / t, (g % 12) + 1, s, x[t]])
            rows.append((pk, g))
    return pd.DataFrame(rows, columns=["pk", "g"]), np.array(F, float)


def median3(ser, R):
    return [float(np.median(hist(ser, r.pk, r.g)[-3:])) for r in R.itertuples()]


def shrink_cat(ser, R):
    """forecast = MA12_i * (w r_i + (1-w) r_cat); r = MA3/MA12 from months < g; r_cat = median r of the
    category's other Tier A SKUs with >= 3 months before g; w = tau2 / (tau2 + sigma2_i),
    tau2 = var of peer r, sigma2_i = var(last 12 months / MA12_i) / 3. Fewer than 3 peers: w = 1."""
    cache, out = {}, []
    def ratio(tr):
        m12 = tr[-12:].mean(); return (tr[-3:].mean() / m12) if m12 > 0 else np.nan
    for r in R.itertuples():
        tr = hist(ser, r.pk, r.g); m12 = tr[-12:].mean()
        if not m12 > 0:
            out.append(max(0.0, tr[-3:].mean())); continue
        key = (cat[r.pk], r.g)
        if key not in cache:
            cache[key] = {pk: ratio(h) for pk in ser if cat[pk] == cat[r.pk] and len(h := hist(ser, pk, r.g)) >= 3}
        peers = np.array([v for pk, v in cache[key].items() if pk != r.pk and np.isfinite(v)])
        ri = tr[-3:].mean() / m12
        if len(peers) < 3:
            out.append(m12 * ri); continue
        tau2 = float(peers.var()); sig2 = float((tr[-12:] / m12).var()) / 3
        w = tau2 / (tau2 + sig2) if tau2 + sig2 > 0 else 1.0
        out.append(m12 * (w * ri + (1 - w) * float(np.median(peers))))
    return out


def topdown_cat(ser, R):
    """SES (harness m_ses) on the category's Tier A total, months < g, x SKU share of that total over the last 6 months."""
    M = full_calendar(ser); tot = {}
    for pk, v in M.items(): tot[cat[pk]] = tot.get(cat[pk], 0) + v
    ses, out = {}, []
    for r in R.itertuples():
        c = cat[r.pk]; T = tot[c][:r.g]
        if (c, r.g) not in ses:
            nz = np.nonzero(T > 0)[0]; ses[(c, r.g)] = m_ses(T[nz[0]:]) if len(nz) else np.nan
        den = T[-6:].sum(); share = M[r.pk][r.g - 6:r.g].sum() / den if den > 0 else np.nan
        out.append(ses[(c, r.g)] * share)
    return out


def knn_analog(ser, R, k=5):
    """k=5 older SKUs (first sale before this SKU's, so their age-t month is before g) closest on the last
    min(t,6) months scaled by their own last-6 mean; forecast = s_i * mean(peer x[t] / s_peer). < 5 peers: no forecast."""
    out = []
    for r in R.itertuples():
        f0, x = ser[r.pk]; t = r.g - f0; L = min(t, 6); tr = x[:t]; si = tr[-6:].mean()
        if not si > 0: out.append(np.nan); continue
        zi = tr[t - L:t] / si; cand = []
        for pk, (fj, xj) in ser.items():
            if pk == r.pk or fj + t >= r.g or len(xj) <= t: continue
            sj = xj[max(0, t - 6):t].mean()
            if not sj > 0: continue
            cand.append((float(np.sum((xj[t - L:t] / sj - zi) ** 2)), xj[t] / sj))
        if len(cand) < k: out.append(np.nan); continue
        cand.sort(key=lambda c: c[0]); out.append(si * float(np.mean([c[1] for c in cand[:k]])))
    return out


def xgb_models(Fr, F, R):
    import xgboost as xgb
    s = F[:, 14]; ok = s > 0; UNIT = list(range(10))
    Xraw, yraw = F[:, :14].copy(), F[:, 15].copy()
    Xs = Xraw.copy(); Xs[:, UNIT] /= np.where(ok, s, np.nan)[:, None]; ys = yraw / np.where(ok, s, np.nan)
    g = Fr.g.to_numpy(); res = {}
    for name in ("xgb_abs", "xgb_raw"):
        t0 = time.time(); X, y, scaled = (Xraw, yraw, False) if name == "xgb_raw" else (Xs, ys, True)
        pred = np.full(len(Fr), np.nan)
        for m in range(OFF + 9, NPER):
            trm, tem = ok & (g < m), ok & (g == m)
            if trm.sum() < 100 or not tem.any(): continue
            b = xgb.train(dict(max_depth=4, eta=0.05, subsample=0.8, colsample_bytree=0.8, objective="reg:absoluteerror",
                               seed=SEED, nthread=8), xgb.DMatrix(X[trm], label=y[trm]), num_boost_round=300)
            pred[tem] = np.maximum(0.0, b.predict(xgb.DMatrix(X[tem])) * (s[tem] if scaled else 1.0))
        res[f"{name}@A"] = pred; RT[f"synth:{name}@A"] = time.time() - t0
    P = Fr.assign(**res)
    return R[["pk", "g"]].merge(P, on=["pk", "g"], how="left")[list(res)]


if __name__ == "__main__":
    R = A[["pk", "ti", "g", "month", "bin", "scale", "actual"]].copy()
    out = {}
    for arm, ser in ARMS.items():
        Fr, F = features(ser)
        np.savez(f"feat_{arm}.npz", F=F, g=Fr.g.to_numpy(), pk=Fr.pk.to_numpy())
        L = R.copy()
        for name, fn in (("median3", median3), ("shrink_cat", shrink_cat), ("topdown_cat", topdown_cat), ("knn_analog", knn_analog)):
            L[name] = np.maximum(0.0, np.asarray(timed(f"{arm}:{name}", lambda: fn(ser, L)), float))
        if arm == "synth":
            for name, fn in (("ma3", lambda tr: tr[-3:].mean()), ("ma4", lambda tr: tr[-4:].mean()), ("ma12", lambda tr: tr[-12:].mean()),
                             ("ses", m_ses), ("tsb", m_tsb), ("sba", m_sba)):
                L[name] = timed(f"synth:{name}", lambda: [max(0.0, v) if np.isfinite(v := float(fn(hist(ser, r.pk, r.g)))) else np.nan
                                                           for r in L.itertuples()])
            for c, v in xgb_models(Fr, F, L).items(): L[c] = v.to_numpy()
        L.to_csv(f"local_{arm}.csv", index=False)
        print(arm, "feature rows", len(F), "| scored", len(L), "| NaN:", L.drop(columns=["bin"]).isna().sum()[lambda v: v > 0].to_dict(), flush=True)
    json.dump(RT, open("rt_local.json", "w"), indent=1)
    print({k: round(v, 1) for k, v in RT.items()})
