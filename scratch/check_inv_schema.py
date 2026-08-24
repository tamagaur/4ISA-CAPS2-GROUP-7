import psycopg2, os
from dotenv import load_dotenv
load_dotenv('.env')
conn = psycopg2.connect(os.getenv('SUPABASE_DB_URL'))
cur = conn.cursor()
cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'inventory_fact_real' OR table_name = 'inventory_fact' OR table_name = 'Inventory_Fact_Real' or table_name = 'Inventory_Fact'")
print(cur.fetchall())
