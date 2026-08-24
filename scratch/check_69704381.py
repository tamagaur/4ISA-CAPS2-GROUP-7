import os, psycopg2
from dotenv import load_dotenv
load_dotenv('.env')
conn = psycopg2.connect(os.getenv('SUPABASE_DB_URL'))
cur = conn.cursor()
cur.execute("SELECT calendar_month, quantity_sold FROM Unilever_SKU_Demand_Fact_Real WHERE product_key = (SELECT product_key FROM Product_Dimension WHERE sku_code = '69704381') ORDER BY calendar_month ASC")
print('Actuals:', cur.fetchall())
