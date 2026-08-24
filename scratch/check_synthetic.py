import psycopg2, os
from dotenv import load_dotenv
load_dotenv('.env')
conn = psycopg2.connect(os.getenv('SUPABASE_DB_URL'))
cur = conn.cursor()
cur.execute("SELECT COUNT(*) FROM Inventory_Fact_Real WHERE _src_file = 'Synthetic_Generator'")
count = cur.fetchone()[0]
print(f'Found {count} synthetic rows in Inventory_Fact_Real.')

cur.execute("SELECT snapshot_date, quantity_on_hand FROM Inventory_Fact_Real WHERE _src_file = 'Synthetic_Generator' LIMIT 3")
print('Sample rows:', cur.fetchall())
