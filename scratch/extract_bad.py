import psycopg2, os, json
from dotenv import load_dotenv

load_dotenv('.env')
direct_url = os.getenv('SUPABASE_DIRECT_URL')
conn = psycopg2.connect(direct_url)
cur = conn.cursor()

# Query bad SKUs
query = """
SELECT sku_code, product_name, principal 
FROM Product_Dimension 
WHERE sku_code = product_name 
   OR product_name ILIKE '%culinary%'
"""
cur.execute(query)
bad_skus = [{"sku": r[0], "name": r[1], "principal": r[2]} for r in cur.fetchall()]

with open('scratch/bad_skus.json', 'w') as f:
    json.dump(bad_skus, f)

print(f"Extracted {len(bad_skus)} bad SKUs directly via port 5432.")
conn.close()
