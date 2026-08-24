import os, psycopg2
from dotenv import load_dotenv
load_dotenv('.env')
conn = psycopg2.connect(os.getenv('SUPABASE_DB_URL'))
cur = conn.cursor()
cur.execute("SELECT forecast_date, forecast_value, mape FROM Forecast_Result WHERE product_key = (SELECT product_key FROM Product_Dimension WHERE sku_code = '67749043')")
print('Forecast:', cur.fetchall())
