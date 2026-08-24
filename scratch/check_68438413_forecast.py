import pandas as pd, psycopg2, os
from dotenv import load_dotenv
load_dotenv('.env')
conn = psycopg2.connect(os.getenv('SUPABASE_DB_URL'))
cur = conn.cursor()
cur.execute("SELECT forecast_value, mape FROM Forecast_Result WHERE product_key = (SELECT product_key FROM Product_Dimension WHERE sku_code = '68438413')")
print('Forecast:', cur.fetchall())
