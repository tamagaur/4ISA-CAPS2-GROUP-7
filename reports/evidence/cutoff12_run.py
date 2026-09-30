"""Cutoff-12 test (reports/evidence/PREREG_cutoff12.md). Stage 1 = checks, stage 2 = scoring (only if every check passes).

Stored forecasts: reports/experiment_artifacts/preds_plus.csv.gz (tsb, ma3, xgb_abs@A, ens_xgb_ma3@A). No XGBoost refit is
needed if no medium-bin SKU-month lacks ens_xgb_ma3@A. Scoring logic = cells_all.py (cells / compare), filtered first to
SKU-months where both models exist. DB: read-only transaction (BEGIN; SET TRANSACTION READ ONLY; ...; ROLLBACK).
Run from the worktree root: python reports/evidence/cutoff12_run.py
"""
import os, sys
import numpy as np, pandas as pd, psycopg2
from dotenv import dotenv_values

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
from analytics.forecasting import baseline
from analytics.forecasting.global_model import from_first_sale

OUT = os.path.join(ROOT, "reports", "evidence")
SEED, NBOOT, MIN_ORIG, MIN_N = 20260921, 1000, 3, 5
BLOCKS = [("2023-10", "2024-02"), ("2024-03", "2024-08"), ("2024-09", "2025-02"), ("2025-03", "2025-08"), ("2025-09", "2026-02")]
CH = "ens_xgb_ma3@A"
TOL = 1e-9

# ---------------------------------------------------------------- stage 1: checks
A = pd.read_csv(os.path.join(ROOT, "reports", "experiment_artifacts", "preds_plus.csv.gz"))
A["month"] = A.month.astype(str).str[:7]

url = dotenv_values(r"C:\Users\kyuan\Capstone-Project\.env")["SUPABASE_DB_URL"]
conn = psycopg2.connect(url)                      # autocommit off: first execute opens the transaction
try:
    cur = conn.cursor()
    cur.execute("SET TRANSACTION READ ONLY")
    cur.execute("SELECT current_setting('transaction_read_only')"); ro = cur.fetchone()[0]
    cur.execute("""SELECT abc.product_key FROM ABC_Classification abc
                   WHERE abc.principal = 'unilever' AND abc.method = 'single' AND abc.tier = 'A'
                     AND abc.classification_period::text LIKE '2026-02%%'""")
    tier_a = {r[0] for r in cur.fetchall()}
    cur.execute("""SELECT product_key, calendar_month, SUM(quantity_sold) AS quantity, bool_or(is_demo) AS is_demo
                   FROM Unilever_SKU_Demand_Fact_Real GROUP BY product_key, calendar_month ORDER BY product_key, calendar_month""")
    D = pd.DataFrame(cur.fetchall(), columns=["pk", "calendar_month", "quantity", "is_demo"])
finally:
    conn.rollback(); conn.close()
D["quantity"] = pd.to_numeric(D.quantity, errors="coerce").fillna(0.0)

series = {}
for pk, g in D.groupby("pk"):
    idx = pd.to_datetime(g.calendar_month.astype(str).str[:7] + "-01")
    series[pk] = pd.Series(g.quantity.to_numpy(float), index=idx).sort_index().resample("MS").asfreq().fillna(0.0)

rec = []
for r in A.itertuples(index=False):
    s = series.get(r.pk); m = pd.Timestamp(r.month + "-01")
    if s is None or m not in s.index:
        rec.append((np.nan, np.nan, np.nan, np.nan)); continue
    h = s[s.index < m]; hf = from_first_sale(h)
    rec.append((float((h.to_numpy() > 0).sum()), float(s.loc[m]), float(baseline.tsb_forecast(hf, 1)[0]),
                float(baseline.moving_average_forecast(hf, 1)[0])))
A[["sales_re", "actual_re", "tsb_re", "ma3_re"]] = np.array(rec)
A["bin_len"] = np.select([A.sales < 3, A.sales < 12, A.sales < 24], ["insufficient", "short", "medium"], "long")

def close(a, b): return np.abs(a - b) <= TOL * np.maximum(1.0, np.abs(b))
med = A.bin_len.eq("medium")
checks = [
    ("read-only transaction", ro == "on", ro),
    ("no is_demo row in _Real view", not D.is_demo.fillna(False).any(), int(D.is_demo.fillna(False).sum())),
    ("Tier A 2026-02 single = 132 SKUs", len(tier_a) == 132, len(tier_a)),
    ("preds_plus SKUs within that cohort", set(A.pk) <= tier_a, f"{len(set(A.pk) & tier_a)}/{A.pk.nunique()}"),
    ("stored sales months == recomputed", (A.sales == A.sales_re).all(), f"{int((A.sales == A.sales_re).sum())}/{len(A)}"),
    ("stored actual == _Real value", close(A.actual_re, A.actual).all(), f"{int(close(A.actual_re, A.actual).sum())}/{len(A)}"),
    ("TSB recompute == stored (all rows)", close(A.tsb_re, A.tsb).all(), f"{int(close(A.tsb_re, A.tsb).sum())}/{len(A)}, bit-identical {int((A.tsb_re == A.tsb).sum())}, max|d| {np.nanmax(np.abs(A.tsb_re - A.tsb)):.3g}"),
    ("medium rows (length rule) = 1,002", int(med.sum()) == 1002, int(med.sum())),
    ("medium rows lacking stored challenger (refits needed)", int(A.loc[med, CH].isna().sum()) == 0, int(A.loc[med, CH].isna().sum())),
    ("medium rows lacking stored TSB", int(A.loc[med, "tsb"].isna().sum()) == 0, int(A.loc[med, "tsb"].isna().sum())),
]
print("side: MA3 recompute == stored:", f"{int(close(A.ma3_re, A.ma3).sum())}/{len(A)}")
print("side: re-binned by length rule:", pd.crosstab(A.bin, A.bin_len).to_dict())
fail = [c for c in checks if not c[1]]
for name, ok, val in checks: print(f"{'PASS' if ok else 'FAIL'}  {name}: {val}")
pd.DataFrame(checks, columns=["check", "pass", "value"]).to_csv(os.path.join(OUT, "cutoff12_checks.csv"), index=False)
if fail: sys.exit("CHECK FAILED - stopping before scoring")

# ---------------------------------------------------------------- stage 2: scoring
def cells(df, models):  # cells_all.py logic
    out = []
    for pk, grp in df.groupby("pk"):
        a = grp.actual.to_numpy(); den = np.abs(a).sum()
        if len(grp) < MIN_ORIG or den <= 0: continue
        r = dict(pk=pk); sc = grp.scale.to_numpy(); ok = sc > 0
        for m in models:
            p = grp[m].to_numpy(); fin = np.isfinite(p).all()
            r[m] = np.abs(a - p).sum() / den if fin else np.nan
            r["mase_" + m] = float(np.mean(np.abs(a - p)[ok] / sc[ok])) if fin and ok.any() else np.nan
        out.append(r)
    return pd.DataFrame(out, columns=["pk"] + models + ["mase_" + m for m in models])

def compare(m, b):  # cells_all.py compare: two-condition verdict
    m, b = np.asarray(m, float), np.asarray(b, float); ok = np.isfinite(m) & np.isfinite(b); m, b = m[ok], b[ok]
    if len(m) < MIN_N: return dict(n=len(m), v="NT")
    i = np.random.default_rng(SEED).integers(0, len(m), (NBOOT, len(m)))
    d = np.median(m[i], axis=1) - np.median(b[i], axis=1); lo, hi = np.percentile(d, [2.5, 97.5])
    nb, nw = int((m < b - 1e-12).sum()), int((m > b + 1e-12).sum())
    v = "W" if (hi < 0 and nb > nw) else "L" if (lo > 0 and nw > nb) else "T"
    return dict(n=len(m), lo=lo, hi=hi, nb=nb, nw=nw, v=v, ch=np.median(m), inc=np.median(b))

def run(bin_name, inc):
    W = A[(A.month >= "2023-10") & (A.month <= "2026-02") & (A.bin_len == bin_name)]
    W = W[np.isfinite(W[CH]) & np.isfinite(W[inc])]            # per SKU-month where both exist
    rows = []
    for label, lo, hi in [("full", "2023-10", "2026-02")] + [(f"{a}..{b}", a, b) for a, b in BLOCKS]:
        c = cells(W[(W.month >= lo) & (W.month <= hi)], [inc, CH])
        f = compare(c[CH], c[inc]) if len(c) else dict(n=0, v="NT")
        rows.append(dict(bin=bin_name, incumbent=inc, window=label, sku_months=int(((W.month >= lo) & (W.month <= hi)).sum()), **f))
        if label == "full":
            mp = {m: (c["mase_" + m].dropna() < 1).mean() * 100 for m in (inc, CH)}
            npass = {m: f"{int((c['mase_' + m].dropna() < 1).sum())}/{int(c['mase_' + m].notna().sum())}" for m in (inc, CH)}
    return pd.DataFrame(rows), mp, npass

def verdict(R):
    full = R[R.window == "full"].v.iloc[0]; b = R[R.window != "full"].v.tolist()
    testable = [v for v in b if v != "NT"]; nW, nL = testable.count("W"), testable.count("L")
    rules = {"SWITCH-CANDIDATE": full == "W" and nW > len(testable) / 2 and nL == 0,
             "KEEP": full in ("T", "L") or nL > 0,
             "INCONCLUSIVE": len(testable) < 3}
    return [k for k, on in rules.items() if on], "".join(b), len(testable)

Rm, mp_m, np_m = run("medium", "tsb")
Rs, mp_s, np_s = run("short", "ma3")
R = pd.concat([Rm, Rs]); R.to_csv(os.path.join(OUT, "cutoff12_results.csv"), index=False)
pd.set_option("display.width", 220)
for name, Rx, mp, npass in (("MEDIUM (verdict) avg vs TSB", Rm, mp_m, np_m), ("SHORT (side) avg vs MA3", Rs, mp_s, np_s)):
    v, blocks, nt = verdict(Rx)
    print(f"\n{name}: rules firing {v}  blocks {blocks}  testable {nt}")
    print(Rx.drop(columns=["bin", "incumbent"]).round(4).to_string(index=False))
    print("MASE<1 pass %:", {k: round(x, 1) for k, x in mp.items()}, npass)
