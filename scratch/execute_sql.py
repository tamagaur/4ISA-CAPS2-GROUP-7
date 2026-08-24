import psycopg2, os
from dotenv import load_dotenv

load_dotenv('.env')
direct_url = os.getenv('SUPABASE_DIRECT_URL')
conn = psycopg2.connect(direct_url)
cur = conn.cursor()

with open('scratch/update_products.sql', 'r', encoding='utf-8') as f:
    sql = f.read()

print(f"Executing {len([s for s in sql.split(';') if s.strip()])} statements...")
cur.execute(sql)
conn.commit()

print("Successfully updated Product_Dimension table!")
conn.close()
