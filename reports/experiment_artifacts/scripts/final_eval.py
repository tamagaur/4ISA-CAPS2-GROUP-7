"""FINAL DIAGNOSTIC, step 2: derived candidates + evaluation. Reads final_preds.pkl; one read-only DB query for the global model's lag features."""
import os, sys, warnings
import numpy as np, pandas as pd

warnings.simplefilter("ignore")
REPO = r"C:\Users\kyuan\Capstone-Project"
OUT = os.path.dirname(os.path.abspath(__file__))
SEED, NBOOT, MIN_ORIGINS = 20260921, 1000, 3
BINS = ["intermittent", "short", "medium", "long"]
FULL0, SPLIT, END = "2023-10", "2025-08", "2026-02"
META = ["pk", "ti", "ntr", "sales", "adi", "bin", "scale", "actual", "month", "tier"]

P = pd.read_pickle(os.path.join(OUT, "final_preds.pkl")).sort_values(["pk", "ti"]).reset_index(drop=True)
BASE = [c for c in P.columns if c not in META]

# ---- trained MA: window chosen per SKU, at every origin, from that SKU's own PAST one-step errors --------------
K = ["ma3", "naive", "ma2", "ma4", "ma6", "ma12"]          # ma3 first = tie-break / cold start
err = P[K].sub(P.actual, axis=0).abs()
past = err.groupby(P.pk).cumsum().groupby(P.pk).shift(1)
choice = past.idxmin(axis=1).fillna("ma3")
P["ma_trained"] = P[K].to_numpy()[np.arange(len(P)), [K.index(c) for c in choice]]
P["ma_k"] = choice
P["ens3"] = P[["ma3", "ses", "theta"]].mean(axis=1)          # mean of the finite members (ma3 is always finite)


# ---- global model: one XGBoost across all SKUs, retrained every month on strictly earlier origins ------------
def global_model():
    import psycopg2, xgboost as xgb
    from dotenv import load_dotenv
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
        x = mats[r.pk]; tr = x[r.ti - r.ntr:r.ti]
        s = tr[-6:].mean()
        if not s > 0:
            feats.append([np.nan] * 16); continue
        lag = lambda k: tr[-k] / s if len(tr) >= k else np.nan
        feats.append([lag(1), lag(2), lag(3), lag(4), lag(5), lag(6), lag(12), tr[-3:].mean() / s,
                      tr[-12:].mean() / s if len(tr) >= 12 else np.nan, tr[-6:].std() / s, float((tr[-6:] <= 0).sum()),
                      r.ntr, r.sales / r.ntr, (r.ti % 12) + 1, s, r.actual / s])
    F = np.array(feats, float); X, s, y = F[:, :14], F[:, 14], F[:, 15]
    ok = np.isfinite(s)
    pred = np.full(len(P), np.nan)
    ti = P.ti.to_numpy()
    only_a = (P.tier == "A").to_numpy() if os.environ.get("TRAIN_TIER") == "A" else np.ones(len(P), bool)
    for m in range(ix[FULL0], len(periods)):
        tr_mask, te_mask = ok & (ti < m) & only_a, ok & (ti == m)
        if tr_mask.sum() < 100 or not te_mask.any():
            continue
        params = dict(max_depth=4, eta=0.05, subsample=0.8, colsample_bytree=0.8, objective="reg:absoluteerror", seed=int(os.environ.get("XGB_SEED", SEED)), nthread=4)
        mdl = xgb.train(params, xgb.DMatrix(X[tr_mask], label=y[tr_mask]), num_boost_round=300)
        pred[te_mask] = np.maximum(0.0, mdl.predict(xgb.DMatrix(X[te_mask])) * s[te_mask])
    return pred


P["xgb_global"] = global_model()
MODELS = BASE + ["ma_trained", "ens3", "xgb_global"]
P = P[(P.bin != "insufficient")]
print(f"forecastable origin rows={len(P)} SKUs={P.pk.nunique()} | NaN xgb rows in >= {FULL0}: {int(P[P.month >= FULL0].xgb_global.isna().sum())}")
print("trained-MA window chosen (share of origins):", (P.ma_k.value_counts(normalize=True) * 100).round(1).to_dict())
P.to_pickle(os.path.join(OUT, "final_preds_all.pkl"))


# ---- scoring -------------------------------------------------------------------------------------------------
def cells(df, keys, models):
    """One row per group: WAPE per model (NaN unless finite at every origin of the group), rolling MASE, n origins."""
    out = []
    for key, g in df.groupby(keys):
        a = g.actual.to_numpy(); den = np.abs(a).sum()
        if len(g) < MIN_ORIGINS or den <= 0:
            continue
        key = key if isinstance(key, tuple) else (key,)
        row = dict(zip(keys, key)); row["n_orig"] = len(g)
        sc = g.scale.to_numpy(); oks = sc > 0
        for m in models:
            p = g[m].to_numpy()
            fin = np.isfinite(p).all()
            row[m] = np.abs(a - p).sum() / den if fin else np.nan
            row["mase_" + m] = float(np.mean(np.abs(a - p)[oks] / sc[oks])) if fin and oks.any() else np.nan
        out.append(row)
    return pd.DataFrame(out)


rng = np.random.default_rng(SEED)


def ci(v):
    v = v[np.isfinite(v)]
    b = np.median(v[rng.integers(0, len(v), (NBOOT, len(v)))], axis=1)
    return np.percentile(b, [2.5, 97.5])


def paired(a, b):
    ok = np.isfinite(a) & np.isfinite(b); a, b = a[ok], b[ok]
    i = rng.integers(0, len(a), (NBOOT, len(a)))
    d = np.median(a[i], axis=1) - np.median(b[i], axis=1)
    return np.percentile(d, [2.5, 97.5]), int((a < b - 1e-12).sum()), int((a > b + 1e-12).sum()), len(a)


SHOW = ["ma3", "ma_trained", "ses", "ens3", "xgb_global"]
for cohort, sub in (("Tier A", P[P.tier == "A"]), ("Tier A+B+C", P)):
    full = sub[sub.month >= FULL0]
    C = cells(full, ["pk", "bin"], MODELS)
    print(f"\n=== {cohort}: every-month test, origins {FULL0}..{END} — per bin (SKU needs >= {MIN_ORIGINS} origins in the bin) ===")
    print(f"{'bin':<13}{'model':<14}{'WAPE':>7}  {'95% CI':<16}{'MASE<1':>8}{'n':>5}  vs MA3 (paired CI, better/worse)")
    for b in BINS:
        c = C[C.bin == b]
        if len(c) < 5:
            print(f"{b:<13}only {len(c)} SKUs — skipped"); continue
        med = c[MODELS].median()[c[MODELS].notna().sum() * 2 >= len(c)].sort_values()
        order = list(dict.fromkeys(list(med.index[:3]) + [m for m in SHOW if m in med.index]))
        for m in order:
            lo, hi = ci(c[m].to_numpy()); ms = c["mase_" + m]
            (dlo, dhi), btr, wrs, n = paired(c[m].to_numpy(), c["ma3"].to_numpy())
            rank = list(med.index).index(m) + 1
            tail = "" if m == "ma3" else f"[{dlo:+.3f}, {dhi:+.3f}] {btr}/{wrs}" + ("  <-- CI excludes 0" if dhi < 0 or dlo > 0 else "")
            print(f"{b:<13}{m:<14}{med[m]:>7.3f}  [{lo:.3f}, {hi:.3f}]  {100 * (ms < 1).sum() / ms.notna().sum():>6.0f}%{int(c[m].notna().sum()):>5}  #{rank:<3}{tail}")

    sel, conf = sub[(sub.month >= FULL0) & (sub.month <= SPLIT)], sub[sub.month > SPLIT]
    CS, CC = cells(sel, ["pk", "bin"], MODELS), cells(conf, ["pk", "bin"], MODELS)
    print(f"\n=== {cohort}: choose per bin on {FULL0}..{SPLIT}, then score on {SPLIT}< ..{END} (unseen) ===")
    print(f"{'bin':<13}{'chosen':<14}{'select WAPE':>12}{'(MA3)':>8} |{'confirm WAPE':>13}{'(MA3)':>8}  paired CI chosen-MA3     better/worse  n")
    chosen = {}
    for b in BINS:
        s, c = CS[CS.bin == b], CC[CC.bin == b]
        if len(s) < 5 or len(c) < 5:
            print(f"{b:<13}too few SKUs (select {len(s)}, confirm {len(c)})"); continue
        med = s[MODELS].median()[s[MODELS].notna().sum() * 2 >= len(s)].sort_values()
        w = med.index[0]; chosen[b] = w
        (dlo, dhi), btr, wrs, n = paired(c[w].to_numpy(), c["ma3"].to_numpy())
        print(f"{b:<13}{w:<14}{med[w]:>12.3f}{med['ma3']:>8.3f} |{c[w].median():>13.3f}{c['ma3'].median():>8.3f}  [{dlo:+.3f}, {dhi:+.3f}]{'':<6}{btr}/{wrs}{'':<6}{n}"
              + ("  <-- CI excludes 0" if dhi < 0 or dlo > 0 else ""))
    for b in BINS:
        c = CC[CC.bin == b]
        if len(c) >= 5 and c.xgb_global.notna().sum() >= 5:
            (dlo, dhi), btr, wrs, n = paired(c.xgb_global.to_numpy(), c.ma3.to_numpy())
            print(f"  xgb_global in {b:<13} unseen months: {c.xgb_global.median():.3f} vs MA3 {c.ma3.median():.3f}  [{dlo:+.3f}, {dhi:+.3f}]  {btr}/{wrs}  n={n}" + ("  <-- CI excludes 0" if dhi < 0 or dlo > 0 else ""))
    conf = conf.copy()
    r = conf.ma3.copy()
    for b, w in chosen.items():
        m = (conf.bin == b) & conf[w].notna()
        r[m] = conf.loc[m, w]
    conf["routed"] = r
    S = cells(conf, ["pk"], ["ma3", "routed", "ma_trained", "ses", "ens3", "xgb_global", "sba_a3", "theta"])
    print(f"--- whole cohort on the unseen months, per-SKU WAPE over all its forecastable origins (n={len(S)}) ---")
    print(f"{'strategy':<26}{'medWAPE':>8}{'meanWAPE':>9}{'MASE<1':>8}  paired CI vs MA3       better/worse")
    for m in ["ma3", "routed", "ma_trained", "ses", "ens3", "xgb_global", "sba_a3", "theta"]:
        (dlo, dhi), btr, wrs, n = paired(S[m].to_numpy(), S["ma3"].to_numpy())
        ms = S["mase_" + m]
        label = {"ma3": "always-MA3", "routed": "routed (chosen per bin)"}.get(m, "always-" + m)
        print(f"{label:<26}{S[m].median():>8.3f}{S[m].mean():>9.3f}{100 * (ms < 1).sum() / ms.notna().sum():>7.0f}%  "
              + ("" if m == "ma3" else f"[{dlo:+.3f}, {dhi:+.3f}]   {btr}/{wrs}" + ("  <-- CI excludes 0" if dhi < 0 or dlo > 0 else "")))
    print("NaN check (strategy medians):", int(S[["ma3", "routed", "ma_trained", "ens3"]].median().isna().sum()))
