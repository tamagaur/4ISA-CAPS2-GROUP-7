import os
import psycopg2
from dotenv import load_dotenv

load_dotenv('.env')
conn = psycopg2.connect(os.getenv('SUPABASE_DB_URL'))
cur = conn.cursor()
cur.execute("SELECT status FROM Product_Dimension WHERE sku_code = '68438413'")
print('Status:', cur.fetchone())
