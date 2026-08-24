import os, psycopg2
from dotenv import load_dotenv

load_dotenv('.env')
conn = psycopg2.connect(os.getenv('SUPABASE_DB_URL'))
cur = conn.cursor()

sku = '67749041'
cur.execute("SELECT product_key FROM Product_Dimension WHERE sku_code = %s", (sku,))
row = cur.fetchone()
if row:
    pk = row[0]
    cur.execute("SELECT calendar_month FROM Unilever_SKU_Demand_Fact WHERE product_key = %s", (pk,))
    rows = cur.fetchall()
    print(f"Periods for {sku}: {len(rows)}")
else:
    print("SKU not found.")
