import os, psycopg2, pandas as pd
from dotenv import load_dotenv

load_dotenv('.env')
url = os.getenv('SUPABASE_DB_URL')
conn = psycopg2.connect(url)
cur = conn.cursor()

# Get the name and principal
cur.execute("SELECT sku_name, principal FROM Product_Dimension WHERE sku_code = '9IDK70634'")
row = cur.fetchone()
name, principal = row if row else ("Unknown", "Unknown")

# Get missing months
query = "SELECT _period FROM SellOut_Fact s JOIN Product_Dimension pd ON s.product_key = pd.product_key WHERE pd.sku_code = '9IDK70634' ORDER BY _period"
df = pd.read_sql(query, conn)
periods = pd.to_datetime(df['_period'] + '-01')

if not periods.empty:
    all_months = pd.date_range(start=periods.min(), end=periods.max(), freq='MS')
    missing = all_months.difference(periods)
    missing_strs = [m.strftime('%Y-%m') for m in missing]
else:
    missing_strs = ["No data"]

print(f"SKU: 9IDK70634")
print(f"Name: {name}")
print(f"Principal: {principal}")
print(f"Exactly Missing Months: {', '.join(missing_strs) if missing_strs else 'None'}")
