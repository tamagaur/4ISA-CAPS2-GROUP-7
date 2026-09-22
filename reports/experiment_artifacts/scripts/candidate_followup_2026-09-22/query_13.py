"""The one read-only query of the guard-fix turn: real rows of the 13 insufficient Tier A (2026-02) SKUs -> q13.pkl.
cap_after_*.pkl come from capture_router.py (the live runner's own reads, read-only session)."""
import os, pandas as pd, psycopg2
from dotenv import load_dotenv
load_dotenv(r"C:\Users\kyuan\Capstone-Project\.env")
t = pd.read_pickle("cap_after_tier_a.pkl"); have = set(pd.read_pickle("series_tierA.pkl"))
k13 = sorted(int(k) for k in t.product_key if int(k) not in have)
conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"]); conn.set_session(readonly=True, autocommit=True); cur = conn.cursor()
cur.execute("""SELECT d.product_key, p.sku_code, d.calendar_month::text, d.quantity_sold::float8
               FROM public.unilever_sku_demand_fact_real d JOIN public.product_dimension p ON p.product_key = d.product_key
               WHERE d.product_key = ANY(%s::bigint[]) ORDER BY 1, 3""", (k13,))
pd.DataFrame(cur.fetchall(), columns=["product_key", "sku_code", "calendar_month", "quantity"]).to_pickle("q13.pkl"); conn.close()
