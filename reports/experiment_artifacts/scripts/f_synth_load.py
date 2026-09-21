"""DIAGNOSTIC ONLY: read is_demo rows for the cohort from the base table (read-only)."""
import os, sys, pickle
import numpy as np, pandas as pd, psycopg2
from dotenv import load_dotenv
REPO = r"C:\Users\kyuan\Capstone-Project"; OUT = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(REPO, ".env"))
d = pickle.load(open(os.path.join(OUT, "a.pkl"), "rb")); cohort = d["cohort"]
conn = psycopg2.connect(os.environ.get("SUPABASE_DIRECT_URL") or os.environ["SUPABASE_DB_URL"]); conn.set_session(readonly=True)
cur = conn.cursor()
cur.execute("""SELECT is_demo, COUNT(*), COUNT(quantity_sold), COUNT(*) FILTER (WHERE quantity_sold='NaN'),
                      COUNT(*) FILTER (WHERE quantity_sold<0), COUNT(*) FILTER (WHERE quantity_sold=0),
                      MIN(calendar_month), MAX(calendar_month), COUNT(DISTINCT product_key)
               FROM unilever_sku_demand_fact WHERE product_key = ANY(%s) GROUP BY 1 ORDER BY 1""", (cohort,))
for r in cur.fetchall():
    print(dict(zip(["is_demo","rows","non_null","NaN","neg","zero","min","max","skus"], r)))
cur.execute("""SELECT COUNT(*) FROM (SELECT product_key, calendar_month FROM unilever_sku_demand_fact
               WHERE product_key = ANY(%s) GROUP BY 1,2 HAVING COUNT(*)>1) x""", (cohort,))
print("SKU-months present in both demo and real (or duplicated):", cur.fetchone()[0])
cur.execute("""SELECT product_key, calendar_month, COALESCE(quantity_sold,0) FROM unilever_sku_demand_fact
               WHERE product_key = ANY(%s) AND is_demo ORDER BY 1,2""", (cohort,))
s = pd.DataFrame(cur.fetchall(), columns=["pk","month","q"]); conn.close()
s["q"] = s.q.astype(float); print("pandas NaN:", int(s.q.isna().sum()))
per = s.groupby("pk").agg(n=("month","size"), first=("month","min"), last=("month","max"))
print("demo months per SKU:", per.n.value_counts().sort_index().to_dict())
print("demo first/last month:", per["first"].value_counts().to_dict(), per["last"].value_counts().to_dict())
binof = pd.Series({pk: v["bin"] for pk, v in d["b26"].items()})
periods = d["periods"]
fs = pd.Series({pk: periods[int(np.nonzero(q > 0)[0][0])] for pk, q in d["m26"].items()})
t = pd.DataFrame({"bin": binof, "has_demo": binof.index.isin(per.index), "first_real_sale": fs})
print(t.groupby("bin").agg(skus=("has_demo","size"), with_demo=("has_demo","sum")).to_string())
g = t[t.has_demo]
print("SKUs with demo prefix whose first real sale is after 2023-01 (gap between prefix and real):", int((g.first_real_sale > "2023-01").sum()))
print(g[g.first_real_sale > "2023-01"].groupby("bin").first_real_sale.agg(["size","min","max"]).to_string())
pickle.dump(s, open(os.path.join(OUT, "synth.pkl"), "wb"))
