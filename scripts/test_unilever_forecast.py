import os, psycopg2, pandas as pd
from dotenv import load_dotenv

load_dotenv('.env')

conn = psycopg2.connect(os.getenv('SUPABASE_DB_URL'))
cur = conn.cursor()

sku_id = '69704381'
principal = 'unilever'

print("Checking Product_Dimension...")
cur.execute("SELECT product_key, product_name FROM Product_Dimension WHERE principal = %s AND (sku_code = %s OR category_path = %s)", (principal, sku_id, sku_id))
product_row = cur.fetchone()
print(f"Product: {product_row}")

if product_row:
    pk = product_row[0]
    print(f"product_key: {pk}")
    
    print("Checking Unilever_SKU_Demand_Fact...")
    cur.execute("SELECT calendar_month, quantity_sold FROM Unilever_SKU_Demand_Fact WHERE product_key = %s ORDER BY calendar_month DESC LIMIT 12", (pk,))
    actuals = cur.fetchall()
    print(f"Actuals: {actuals}")

