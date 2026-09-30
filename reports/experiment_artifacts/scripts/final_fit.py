"""FINAL DIAGNOSTIC, step 1: every-month rolling-origin forecasts for Tier A+B+C (as of 2026-02). Read-only."""
import os, sys, time, warnings
import numpy as np, pandas as pd
from concurrent.futures import ProcessPoolExecutor

warnings.simplefilter("ignore")
REPO = r"C:\Users\kyuan\Capstone-Project"
sys.path.insert(0, REPO)
OUT = os.path.dirname(os.path.abspath(__file__))
MIN_TRAIN = 3
START, END = "2023-01", "2026-02"
SKIP = {"sarima_seasonal"}
EXTRA_MA = (2, 4, 12)


def bin_of(tr):
    sales = int((tr > 0).sum())
    if sales < 3:
        return "insufficient", sales, np.nan
    adi = len(tr) / sales
    if adi >= 1.32:
        return "intermittent", sales, adi
    return ("short" if sales < 12 else "medium" if sales < 24 else "long"), sales, adi


def run_sku(args):
    pk, qty = args
    from scripts.model_bakeoff import MODELS, GUARDED
    warnings.simplefilter("ignore")
    models = {k: v for k, v in MODELS.items() if k not in SKIP}
    for k in EXTRA_MA:
        models[f"ma{k}"] = (lambda kk: (lambda x: x[-kk:].mean()))(k)
    qty = np.asarray(qty, float)
    nz = np.nonzero(qty > 0)[0]
    if not len(nz):
        return []
    fs = int(nz[0]); x = qty[fs:]
    rows = []
    for t in range(MIN_TRAIN, len(x)):
        tr = x[:t]
        b, sales, adi = bin_of(tr)
        d = np.abs(np.diff(tr))
        row = dict(pk=pk, ti=fs + t, ntr=t, sales=sales, adi=adi, bin=b, scale=float(d.mean()) if len(d) else 0.0, actual=float(x[t]))
        for name, fn in models.items():
            try:
                f = float(fn(tr))
            except Exception:
                f = np.nan
            if name in GUARDED and np.isfinite(f) and f > tr.max():
                f = np.nan
            row[name] = max(0.0, f) if np.isfinite(f) else np.nan
        rows.append(row)
    return rows


if __name__ == "__main__":
    import psycopg2
    from dotenv import load_dotenv
    load_dotenv(os.path.join(REPO, ".env"))
    conn = psycopg2.connect(os.environ.get("SUPABASE_DIRECT_URL") or os.environ["SUPABASE_DB_URL"])
    cur = conn.cursor(); cur.execute("SET TRANSACTION READ ONLY")  # transaction-scoped READ ONLY, never session-level (pooler leak)
    cur.execute("""SELECT d.product_key, a.tier, d.calendar_month, d.quantity_sold
                   FROM unilever_sku_demand_fact_real d
                   JOIN abc_classification a ON a.product_key = d.product_key AND a.principal='unilever'
                        AND a.classification_period=%s AND a.method='single'
                   WHERE d.calendar_month BETWEEN %s AND %s ORDER BY 1, 3""", (END, START, END))
    df = pd.DataFrame(cur.fetchall(), columns=["pk", "tier", "month", "q"]); conn.close()
    df["q"] = pd.to_numeric(df.q, errors="coerce").astype(float)
    tier = df.drop_duplicates("pk").set_index("pk").tier
    print("SKUs per tier:", tier.value_counts().sort_index().to_dict(), "(expected A 132 / B 194 / C 384)")
    print("rows per tier:", df.groupby("tier").size().to_dict(), "(expected A 3087) | NULL/NaN qty:", int(df.q.isna().sum()),
          "| negative:", int((df.q < 0).sum()), "| dup sku-months:", int(df.duplicated(["pk", "month"]).sum()))
    periods = [str(p) for p in pd.period_range(START, END, freq="M")]
    ix = {p: i for i, p in enumerate(periods)}
    mats = {pk: np.zeros(len(periods)) for pk in tier.index}
    for r in df.itertuples(index=False):
        if np.isfinite(r.q):
            mats[r.pk][ix[r.month]] += r.q
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=14) as ex:
        res = list(ex.map(run_sku, list(mats.items()), chunksize=4))
    P = pd.DataFrame([r for rows in res for r in rows])
    P["month"] = P.ti.map(lambda i: periods[i]); P["tier"] = P.pk.map(tier)
    P.to_pickle(os.path.join(OUT, "final_preds.pkl"))
    mcols = [c for c in P.columns if c not in ("pk", "ti", "ntr", "sales", "adi", "bin", "scale", "actual", "month", "tier")]
    print(f"done {time.time()-t0:.0f}s | origin rows={len(P)} SKUs={P.pk.nunique()} models={len(mcols)} | inf={int(np.isinf(P[mcols]).sum().sum())}")
    print("origin rows by tier x bin:\n", pd.crosstab(P.tier, P.bin).to_string())
    print("NaN preds per model:", P[mcols].isna().sum()[lambda s: s > 0].to_dict())
