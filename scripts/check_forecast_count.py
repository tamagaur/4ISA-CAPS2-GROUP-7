import os, psycopg2
from dotenv import load_dotenv

load_dotenv('.env')
conn = psycopg2.connect(os.getenv('SUPABASE_DB_URL'))
cur = conn.cursor()

cur.execute("SELECT pd.sku_code, COUNT(fr.forecast_date) FROM Forecast_Result fr JOIN Product_Dimension pd ON pd.product_key = fr.product_key GROUP BY pd.sku_code")
results = cur.fetchall()
print(f"SKUs with forecasts: {len(results)}")
if len(results) > 0:
    print(f"Sample: {[r[0] for r in results[:5]]}")
    if '67749041' in [r[0] for r in results]:
        print("67749041 HAS A FORECAST")
    else:
        print("67749041 IS MISSING FORECAST")

