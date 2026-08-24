import os, psycopg2, pandas as pd
from dotenv import load_dotenv

load_dotenv('.env')
url = os.getenv('SUPABASE_DB_URL')
conn = psycopg2.connect(url)
cur = conn.cursor()

# Find a single SKU that has gaps
query = '''
WITH sku_months AS (
    SELECT 
        s.product_key,
        pd.sku_code,
        pd.principal,
        MIN(s._period) as min_p,
        MAX(s._period) as max_p,
        COUNT(DISTINCT s._period) as actual_months
    FROM SellOut_Fact s
    JOIN Product_Dimension pd ON s.product_key = pd.product_key
    JOIN ABC_Classification abc ON abc.product_key = pd.product_key
    WHERE abc.tier = 'A'
    GROUP BY s.product_key, pd.sku_code, pd.principal
)
SELECT sku_code, principal, min_p, max_p, actual_months
FROM sku_months;
'''
cur.execute(query)
rows = cur.fetchall()

for row in rows:
    sku, principal, min_p, max_p, actual = row
    
    # Calculate expected months
    start_y, start_m = map(int, min_p.split('-'))
    end_y, end_m = map(int, max_p.split('-'))
    expected = (end_y - start_y) * 12 + (end_m - start_m) + 1
    
    if expected > actual:
        print(f"SKU: {sku} (Principal: {principal})")
        print(f"Range: {min_p} to {max_p} (Expected {expected} months, but found {actual} months)")
        break
