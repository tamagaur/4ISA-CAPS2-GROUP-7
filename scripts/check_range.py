import os
import psycopg2
from dotenv import load_dotenv

load_dotenv('.env')
url = os.getenv('SUPABASE_DB_URL')
conn = psycopg2.connect(url)
cur = conn.cursor()

cur.execute('SELECT MIN(_period), MAX(_period) FROM SellOut_Fact')
min_p, max_p = cur.fetchone()

print(f"Data Date Range: Start = {min_p} | End = {max_p}")
