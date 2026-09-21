"""Phase A: read-only load of cohort + _Real series, NaN checks, fresh combined_v1 bins."""
import os, sys, pickle
import numpy as np, pandas as pd, psycopg2
from dotenv import load_dotenv

REPO = r"C:\Users\kyuan\Capstone-Project"
sys.path.insert(0, REPO)
from analytics.segmentation import traits as T, bins as B

OUT = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(REPO, ".env"))
dsn = os.environ.get("SUPABASE_DIRECT_URL") or os.environ["SUPABASE_DB_URL"]
conn = psycopg2.connect(dsn, options="-c statement_timeout=0")
conn.set_session(readonly=True)
cur = conn.cursor()

cur.execute("""SELECT product_key FROM abc_classification
               WHERE principal='unilever' AND classification_period='2026-02'
                 AND tier='A' AND method='single'""")
rows = cur.fetchall()
cohort = sorted({r[0] for r in rows})
print(f"cohort rows={len(rows)} distinct SKUs={len(cohort)} (expected 132)")

cur.execute("""SELECT COUNT(*), COUNT(quantity_sold),
                      COUNT(*) FILTER (WHERE quantity_sold = 'NaN'),
                      COUNT(*) FILTER (WHERE quantity_sold < 0),
                      COUNT(*) FILTER (WHERE quantity_sold = 0),
                      MIN(calendar_month), MAX(calendar_month), COUNT(DISTINCT product_key)
               FROM unilever_sku_demand_fact_real WHERE product_key = ANY(%s)""", (cohort,))
n, nn, nan, neg, zero, mn, mx, nsku = cur.fetchone()
print(f"_Real rows={n} (expected 3087) non-null={nn} NULL={n-nn} NaN={nan} neg={neg} zero={zero} "
      f"span={mn}..{mx} SKUs_with_rows={nsku}")

cur.execute("""SELECT product_key, calendar_month, COUNT(*) FROM unilever_sku_demand_fact_real
               WHERE product_key = ANY(%s) GROUP BY 1,2 HAVING COUNT(*)>1""", (cohort,))
print(f"duplicate (sku,month) groups={len(cur.fetchall())} (expected 0)")

cur.execute("""SELECT product_key, calendar_month, quantity_sold FROM unilever_sku_demand_fact_real
               WHERE product_key = ANY(%s) ORDER BY 1,2""", (cohort,))
df = pd.DataFrame(cur.fetchall(), columns=["pk", "month", "q"])
print("month dtype sample:", repr(df["month"].iloc[0]))

# stored assignment, for cross-check only (bins are not model output)
cur.execute("""SELECT product_key, bin FROM sku_segment
               WHERE cohort_period='2026-02' AND abc_method='single' AND scheme='combined_v1'""")
stored = dict(cur.fetchall())
conn.close()

df["q"] = pd.to_numeric(df["q"], errors="coerce").astype(float)
print(f"pandas-side NaN in q after cast={int(df['q'].isna().sum())}")
df["q"] = df["q"].fillna(0.0)


def matrix(end):
    periods = [str(p) for p in pd.period_range("2023-01", end, freq="M")]
    ix = {p: i for i, p in enumerate(periods)}
    m = {pk: np.zeros(len(periods)) for pk in cohort}
    for r in df.itertuples(index=False):
        i = ix.get(r.month)
        if i is not None:
            m[r.pk][i] += r.q
    return m, periods


def derive(end):
    m, periods = matrix(end)
    out = {}
    for pk, qty in m.items():
        hm = T.history_months(qty)
        tr, p, sl = T.trend_stats(qty)
        out[pk] = dict(bin=B.combined_v1(hm, tr, p, sl)[0], hm=hm, active=T.active_months(qty),
                       trend=tr, p=p, slope=sl, adi=T.average_demand_interval(qty))
    return out, m, periods


b26, m26, periods = derive("2026-02")
b25, _, _ = derive("2025-08")
order = ["insufficient", "short", "medium", "long_down", "long_flat", "long_up"]
vc = pd.Series([v["bin"] for v in b26.values()]).value_counts()
print("fresh combined_v1 @2026-02:", {k: int(vc.get(k, 0)) for k in order}, "(expected 13/30/17/22/36/14)")
print(f"stored sku_segment rows={len(stored)}; mismatches vs fresh={sum(1 for pk in cohort if stored.get(pk) != b26[pk]['bin'])}")

pickle.dump(dict(cohort=cohort, m26=m26, periods=periods, b26=b26, b25=b25), open(os.path.join(OUT, "a.pkl"), "wb"))
print("saved a.pkl")
