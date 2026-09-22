import numpy as np, pandas as pd
SEED, NBOOT, MIN_ORIG, MIN_N = 20260921, 1000, 3, 5
REPO = r"C:\Users\kyuan\Capstone-Project"
A = pd.read_csv(REPO + r"\reports\experiment_artifacts\candidate_search_tierA_preds.csv.gz")
A["month"] = A.month.astype(str).str[:7]
META = ["pk", "ti", "ntr", "sales", "adi", "bin", "scale", "actual", "month", "tier", "ma_k"]
cand = [c for c in A.columns if c not in META and c != "ma3"]
print("n cand", len(cand), "ma3 in cand:", "ma3" in cand); print(cand)
BLOCKS = [("2023-10", "2024-02"), ("2024-03", "2024-08"), ("2024-09", "2025-02"), ("2025-03", "2025-08"), ("2025-09", "2026-02")]

def cells(df, models):  # verbatim logic of build_experiment_log.cells, plus scaled signed error
    out = []
    for pk, grp in df.groupby("pk"):
        a = grp.actual.to_numpy(); den = np.abs(a).sum()
        if len(grp) < MIN_ORIG or den <= 0: continue
        r = dict(pk=pk); sc = grp.scale.to_numpy(); ok = sc > 0
        for m in models:
            p = grp[m].to_numpy(); fin = np.isfinite(p).all()
            r[m] = np.abs(a - p).sum() / den if fin else np.nan
            r["mase_" + m] = float(np.mean(np.abs(a - p)[ok] / sc[ok])) if fin and ok.any() else np.nan
            r["bias_" + m] = float(np.mean((p - a)[ok] / sc[ok])) if fin and ok.any() else np.nan
        out.append(r)
    return pd.DataFrame(out)

def compare(m, b):  # build_experiment_log.compare + two-condition verdict
    m, b = np.asarray(m, float), np.asarray(b, float); ok = np.isfinite(m) & np.isfinite(b); m, b = m[ok], b[ok]
    if len(m) < MIN_N: return dict(n=len(m), v="NT")
    i = np.random.default_rng(SEED).integers(0, len(m), (NBOOT, len(m)))
    d = np.median(m[i], axis=1) - np.median(b[i], axis=1); lo, hi = np.percentile(d, [2.5, 97.5])
    nb, nw = int((m < b - 1e-12).sum()), int((m > b + 1e-12).sum())
    v = "W" if (hi < 0 and nb > nw) else "L" if (lo > 0 and nw > nb) else "T"
    return dict(n=len(m), lo=lo, hi=hi, nb=nb, nw=nw, v=v, mv=np.median(m), bv=np.median(b))

def bias(x):
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    if len(x) < MIN_N: return "NT", np.nan
    i = np.random.default_rng(SEED).integers(0, len(x), (NBOOT, len(x)))
    lo, hi = np.percentile(x[i].mean(axis=1), [2.5, 97.5])
    return ("over" if lo > 0 else "under" if hi < 0 else "none"), x.mean()

rows = []
W = A[(A.month >= "2023-10") & (A.month <= "2026-02")]
for bn in ["short", "medium", "long"]:
    full = cells(W[W.bin == bn], ["ma3"] + cand)
    blk = []
    for lo, hi in BLOCKS:
        d = A[(A.month >= lo) & (A.month <= hi) & (A.bin == bn)]
        blk.append(cells(d, ["ma3"] + cand) if len(d) else None)
    for m in cand:
        f = compare(full[m], full["ma3"])
        vs = [compare(c[m], c["ma3"])["v"] if c is not None and len(c) else "NT" for c in blk]
        bf, bm = bias(full["bias_" + m])
        mm = full["mase_" + m]; mm = mm[np.isfinite(mm)]
        rows.append(dict(bin=bn, model=m, n=f["n"], blocks="".join(vs), W=vs.count("W"), T=vs.count("T"), L=vs.count("L"),
                         testable=5 - vs.count("NT"), whole=f["v"], wape=f.get("mv"), ma3=f.get("bv"), nb=f.get("nb"), nw=f.get("nw"),
                         med_mase=float(np.median(mm)) if len(mm) else np.nan, mase_pass=100 * float((mm < 1).mean()) if len(mm) else np.nan,
                         bias=bf, bias_mean=bm))
R = pd.DataFrame(rows)
def tag(r):
    if r.L > 0: return "OUT"
    if r.testable < 3 or not (r.med_mase < 1): return "WEAK"
    return "FIT"
R["tag"] = R.apply(tag, axis=1)
R.to_csv("cells_all.csv", index=False)
pd.set_option("display.width", 250, "display.max_rows", 200)
print(R.round(4).to_string())
