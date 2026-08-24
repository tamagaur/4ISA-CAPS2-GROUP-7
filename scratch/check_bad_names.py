import psycopg2, os
from dotenv import load_dotenv
import pandas as pd

load_dotenv('.env')
conn = psycopg2.connect(os.getenv('SUPABASE_DB_URL'))
cur = conn.cursor()

# Query 1: SKUs where product_name is exactly the same as sku_code
query1 = """
SELECT product_key, principal, sku_code, product_name 
FROM Product_Dimension 
WHERE sku_code = product_name
"""
cur.execute(query1)
same_name_skus = cur.fetchall()

print(f"--- SKUs where product_name == sku_code ({len(same_name_skus)} found) ---")
for row in same_name_skus[:10]:
    print(row)
if len(same_name_skus) > 10: print("...")

# Query 2: SKUs related to "Culinary"
query2 = """
SELECT product_key, principal, sku_code, product_name, category 
FROM Product_Dimension 
WHERE product_name ILIKE '%culinary%' OR category ILIKE '%culinary%'
"""
cur.execute(query2)
culinary_skus = cur.fetchall()

print(f"\n--- SKUs containing 'Culinary' ({len(culinary_skus)} found) ---")
for row in culinary_skus[:10]:
    print(row)
if len(culinary_skus) > 10: print("...")

conn.close()
