import os, psycopg2
from dotenv import load_dotenv

load_dotenv('.env')
conn = psycopg2.connect(os.getenv('SUPABASE_DB_URL'))
cur = conn.cursor()

sku = '9IDK70634'
cur.execute(f"SELECT product_name, principal FROM Product_Dimension WHERE sku_code = '{sku}'")
row = cur.fetchone()

if row:
    print(f"Product Name: {row[0]}")
    print(f"Principal: {row[1]}")
    
    cur.execute(f"SELECT _period FROM SellOut_Fact WHERE product_key = (SELECT product_key FROM Product_Dimension WHERE sku_code = '{sku}') ORDER BY _period")
    periods = [r[0] for r in cur.fetchall()]
    if periods:
        all_months = []
        y, m = map(int, periods[0].split('-'))
        ey, em = map(int, periods[-1].split('-'))
        while (y, m) <= (ey, em):
            all_months.append(f"{y}-{m:02d}")
            m += 1
            if m > 12:
                m = 1
                y += 1
        
        missing = set(all_months) - set(periods)
        print(f"Missing Gap: {sorted(list(missing))}")
    else:
        print("No periods found.")
else:
    print(f"SKU {sku} not found in DB.")
