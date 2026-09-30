"""The one read-only query of the SYNTH-arm turn: category/brand/sku_code for the 119 rebuilt Tier A SKUs -> dim_119.csv."""
import os, pandas as pd, psycopg2
from dotenv import load_dotenv
load_dotenv(r"C:\Users\kyuan\Capstone-Project\.env")
keys = sorted(int(k) for k in pd.read_pickle("series_tierA.pkl"))
conn = psycopg2.connect(os.environ.get("SUPABASE_DIRECT_URL") or os.environ["SUPABASE_DB_URL"])
cur = conn.cursor(); cur.execute("SET TRANSACTION READ ONLY")  # transaction-scoped READ ONLY, never session-level (pooler leak)
cur.execute("""SELECT product_key, principal, grain, sku_code, category_path, category_path_source, brand
               FROM public.product_dimension WHERE product_key = ANY(%s::bigint[])""", (keys,))
d = pd.DataFrame(cur.fetchall(), columns=["pk", "principal", "grain", "sku_code", "category_path", "category_path_source", "brand"]); conn.close()
d.to_csv("dim_119.csv", index=False)
