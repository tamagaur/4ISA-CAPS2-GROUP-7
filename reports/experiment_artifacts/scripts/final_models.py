"""MODEL SEARCH on Tier A (as of 2026-02): global ML candidates + ETS-auto vs MA3. Read-only; scratch packages only."""
import os, sys, time, warnings
OUT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(OUT, "pkgs"))
import numpy as np, pandas as pd
from concurrent.futures import ProcessPoolExecutor

warnings.simplefilter("ignore")
REPO = r"C:\Users\kyuan\Capstone-Project"
SEED, NBOOT, MIN_ORIGINS = 20260921, 1000, 3
FULL0, SPLIT, END = "2023-10", "2025-08", "2026-02"
META = ["pk", "ti", "ntr", "sales", "adi", "bin", "scale", "actual", "month", "tier"]


def ets_sku(args):
    pk, x, tis, fs = args
    warnings.simplefilter("ignore")
    from statsmodels.tsa.exponential_smoothing.ets import ETSModel
    out = []
    for ti in tis:
        tr = x[fs:ti]
        best, f = np.inf, np.nan
        forms = [(None, False)] + ([("add", False), ("add", True)] if len(tr) >= 8 else [])
        for trend, damped in forms:
            try:
                r = ETSModel(pd.Series(tr), error="add", trend=trend, damped_trend=damped).fit(disp=False)
                if np.isfinite(r.aicc) and r.aicc < best:
                    best, f = r.aicc, float(r.forecast(1).iloc[0])
            except Exception:
                pass
        out.append((pk, ti, max(0.0, f) if np.isfinite(f) else np.nan))
    return out


if __name__ == "__main__":
    import psycopg2, xgboost as xgb
    from dotenv import load_dotenv
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.linear_model import Ridge
    from sklearn.neural_network import MLPRegressor
    from sklearn.preprocessing import StandardScaler
    t0 = time.time()
    P = pd.read_pickle(os.path.join(OUT, "final_preds.pkl")).sort_values(["pk", "ti"]).reset_index(drop=True)
    BASE = [c for c in P.columns if c not in META]
    K = ["ma3", "naive", "ma2", "ma4", "ma6", "ma12"]
    past = P[K].sub(P.actual, axis=0).abs().groupby(P.pk).cumsum().groupby(P.pk).shift(1)
    choice = past.idxmin(axis=1).fillna("ma3")
    P["ma_trained"] = P[K].to_numpy()[np.arange(len(P)), [K.index(c) for c in choice]]

    load_dotenv(os.path.join(REPO, ".env"))
    conn = psycopg2.connect(os.environ.get("SUPABASE_DIRECT_URL") or os.environ["SUPABASE_DB_URL"])
    cur = conn.cursor(); cur.execute("SET TRANSACTION READ ONLY")  # transaction-scoped READ ONLY, never session-level (pooler leak)
    cur.execute("""SELECT product_key, calendar_month, quantity_sold FROM unilever_sku_demand_fact_real
                   WHERE product_key = ANY(%s) AND calendar_month BETWEEN '2023-01' AND %s""", (sorted(P.pk.unique().tolist()), END))
    d = pd.DataFrame(cur.fetchall(), columns=["pk", "month", "q"]); conn.close()
    d["q"] = pd.to_numeric(d.q, errors="coerce").astype(float).fillna(0.0)
    periods = [str(p) for p in pd.period_range("2023-01", END, freq="M")]; ix = {p: i for i, p in enumerate(periods)}
    mats = {}
    for r in d.itertuples(index=False):
        mats.setdefault(r.pk, np.zeros(len(periods)))[ix[r.month]] += r.q

    feats = []
    for r in P[["pk", "ti", "ntr", "sales", "actual"]].itertuples(index=False):
        tr = mats[r.pk][r.ti - r.ntr:r.ti]
        s = tr[-6:].mean()
        lag = lambda k: tr[-k] if len(tr) >= k else np.nan
        feats.append([lag(1), lag(2), lag(3), lag(4), lag(5), lag(6), lag(12), tr[-3:].mean(),
                      tr[-12:].mean() if len(tr) >= 12 else np.nan, tr[-6:].std(), float((tr[-6:] <= 0).sum()),
                      r.ntr, r.sales / r.ntr, (r.ti % 12) + 1, s, r.actual])
    F = np.array(feats, float)
    UNIT = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]                      # columns measured in units -> divided by s when scaled
    s = F[:, 14]; ok = s > 0
    Xraw, yraw = F[:, :14].copy(), F[:, 15].copy()
    Xs = Xraw.copy(); Xs[:, UNIT] = Xs[:, UNIT] / np.where(ok, s, np.nan)[:, None]; ys = yraw / np.where(ok, s, np.nan)
    Xd = np.where(np.isfinite(Xs), Xs, 1.0)                     # dense version: a missing scaled lag = "same as recent average"
    ti, isA = P.ti.to_numpy(), (P.tier == "A").to_numpy()

    def fit_predict(name, Xtr, ytr, Xte):
        if name in ("xgb_abs", "xgb_sq", "xgb_raw"):
            obj = "reg:squarederror" if name == "xgb_sq" else "reg:absoluteerror"
            m = xgb.train(dict(max_depth=4, eta=0.05, subsample=0.8, colsample_bytree=0.8, objective=obj, seed=SEED, nthread=8),
                          xgb.DMatrix(Xtr, label=ytr), num_boost_round=300)
            return m.predict(xgb.DMatrix(Xte))
        if name == "lgbm":
            m = lgb.train(dict(objective="l1", learning_rate=0.05, num_leaves=15, min_data_in_leaf=20, bagging_fraction=0.8, bagging_freq=1,
                               feature_fraction=0.8, seed=SEED, verbose=-1, num_threads=8),
                          lgb.Dataset(np.ascontiguousarray(Xtr), label=np.ascontiguousarray(ytr, dtype=np.float32)), num_boost_round=300)
            return m.predict(np.ascontiguousarray(Xte))
        if name == "rf":
            return RandomForestRegressor(n_estimators=200, min_samples_leaf=5, max_features=0.5, random_state=SEED, n_jobs=8).fit(Xtr, ytr).predict(Xte)
        sc = StandardScaler().fit(Xtr)
        if name == "ridge":
            return Ridge(alpha=1.0).fit(sc.transform(Xtr), ytr).predict(sc.transform(Xte))
        if name == "mlp":
            return MLPRegressor(hidden_layer_sizes=(32, 16), alpha=1e-3, max_iter=500, random_state=SEED).fit(sc.transform(Xtr), ytr).predict(sc.transform(Xte))

    GLOBAL = ["xgb_abs", "xgb_sq", "xgb_raw", "rf", "ridge", "mlp"]
    for scope in ("A", "ABC"):
        pool = isA if scope == "A" else np.ones(len(P), bool)
        for name in GLOBAL:
            X, y, scaled = (Xraw, yraw, False) if name == "xgb_raw" else (Xs if name.startswith(("xgb", "lgbm")) else Xd, ys, True)
            pred = np.full(len(P), np.nan)
            for m in range(ix[FULL0], len(periods)):
                trm, tem = ok & pool & (ti < m), ok & isA & (ti == m)
                if trm.sum() < 100 or not tem.any():
                    continue
                p = fit_predict(name, X[trm], y[trm], X[tem])
                pred[tem] = np.maximum(0.0, p * (s[tem] if scaled else 1.0))
            P[f"{name}@{scope}"] = pred
        print(f"scope {scope} done {time.time()-t0:.0f}s", flush=True)

    A = P[isA & (P.bin != "insufficient")].copy()
    jobs = []
    for pk, g in A.groupby("pk"):
        x = mats[pk]; fs = int(g.ti.iloc[0] - g.ntr.iloc[0])
        jobs.append((pk, x, g.ti.tolist(), fs))
    with ProcessPoolExecutor(max_workers=14) as ex:
        ets = [r for rows in ex.map(ets_sku, jobs, chunksize=2) for r in rows]
    A = A.merge(pd.DataFrame(ets, columns=["pk", "ti", "ets_auto"]), on=["pk", "ti"], how="left")
    for sc_ in ("A", "ABC"):
        A[f"ens_xgb_ma3@{sc_}"] = A[[f"xgb_abs@{sc_}", "ma3"]].mean(axis=1, skipna=False)
        A[f"ens_4global@{sc_}"] = A[[f"{g}@{sc_}" for g in ("xgb_abs", "rf", "ridge", "mlp")]].median(axis=1, skipna=False)
    A.to_pickle(os.path.join(OUT, "final_models_A.pkl"))
    NEW = [c for c in A.columns if "@" in c] + ["ets_auto", "ma_trained"]
    MODELS = [m for m in BASE if m != "hw_add12"] + NEW
    print(f"Tier A forecastable origins={len(A)} SKUs={A.pk.nunique()} | total {time.time()-t0:.0f}s")
    print("NaN preds in >= %s:" % FULL0, A[A.month >= FULL0][NEW].isna().sum()[lambda v: v > 0].to_dict(), "| inf:", int(np.isinf(A[MODELS]).sum().sum()))

    def cells(df, keys, models):
        out = []
        for key, g in df.groupby(keys):
            a = g.actual.to_numpy(); den = np.abs(a).sum()
            if len(g) < MIN_ORIGINS or den <= 0:
                continue
            key = key if isinstance(key, tuple) else (key,)
            row = dict(zip(keys, key)); sc = g.scale.to_numpy(); oks = sc > 0
            for m in models:
                p = g[m].to_numpy(); fin = np.isfinite(p).all()
                row[m] = np.abs(a - p).sum() / den if fin else np.nan
                row["mase_" + m] = float(np.mean(np.abs(a - p)[oks] / sc[oks])) if fin and oks.any() else np.nan
            out.append(row)
        return pd.DataFrame(out)

    rng = np.random.default_rng(SEED)

    def paired(a, b):
        okk = np.isfinite(a) & np.isfinite(b); a, b = a[okk], b[okk]
        i = rng.integers(0, len(a), (NBOOT, len(a)))
        dd = np.median(a[i], axis=1) - np.median(b[i], axis=1)
        return np.percentile(dd, [2.5, 97.5]), int((a < b - 1e-12).sum()), int((a > b + 1e-12).sum()), len(a)

    sel = cells(A[(A.month >= FULL0) & (A.month <= SPLIT)], ["pk"], MODELS)
    con = cells(A[A.month > SPLIT], ["pk"], MODELS)
    rank = sel[MODELS].median()[sel[MODELS].notna().sum() * 2 >= len(sel)].sort_values()
    print(f"\n=== Tier A, all forecastable origins per SKU. SELECT = {FULL0}..{SPLIT} (n={len(sel)}), CONFIRM = unseen months (n={len(con)}) ===")
    print(f"{'rank':<5}{'model':<22}{'select WAPE':>12} |{'confirm WAPE':>13}{'mean':>8}{'MASE<1':>8}  paired CI vs MA3      better/worse")
    for i, m in enumerate(rank.index, 1):
        if i > 14 and m not in ("ma3", "ets_auto", "ma_trained", "ses", "xgb_sq@A", "xgb_raw@A", "mlp@A", "ridge@A", "rf@A"):
            continue
        (lo, hi), btr, wrs, n = paired(con[m].to_numpy(), con["ma3"].to_numpy()); ms = con["mase_" + m]
        tail = "" if m == "ma3" else f"[{lo:+.3f}, {hi:+.3f}]   {btr}/{wrs}" + ("  <-- excludes 0" if hi < 0 or lo > 0 else "")
        print(f"{i:<5}{m:<22}{rank[m]:>12.3f} |{con[m].median():>13.3f}{con[m].mean():>8.3f}{100 * (ms < 1).sum() / ms.notna().sum():>7.0f}%  {tail}")

    top = rank.index[0]
    print(f"\n=== chosen on SELECT = {top}; by bin on the unseen months, vs MA3 (and xgb_abs@A for reference) ===")
    cb = cells(A[A.month > SPLIT], ["pk", "bin"], MODELS)
    for b in ("short", "medium", "long"):
        c = cb[cb.bin == b]
        for m in dict.fromkeys([top, "xgb_abs@A", "rf@A"]):
            (lo, hi), btr, wrs, n = paired(c[m].to_numpy(), c["ma3"].to_numpy())
            print(f"{b:<8}{m:<22}{c[m].median():.3f} vs MA3 {c['ma3'].median():.3f}  [{lo:+.3f}, {hi:+.3f}]  {btr}/{wrs}  n={n}" + ("  <-- excludes 0" if hi < 0 or lo > 0 else ""))
    print("NaN check on reported medians:", int(con[list(rank.index)].median().isna().sum()))
