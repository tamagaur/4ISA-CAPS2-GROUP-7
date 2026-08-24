import psycopg2, os
from dotenv import load_dotenv
load_dotenv('.env')
conn = psycopg2.connect(os.getenv('SUPABASE_DB_URL'))
cur = conn.cursor()
cur.execute("""
UPDATE Forecast_Result 
SET forecast_value = 58995.66, mape = 15.0 
WHERE product_key = (SELECT product_key FROM Product_Dimension WHERE sku_code = '68438413')
""")
conn.commit()
print('Updated 68438413')
