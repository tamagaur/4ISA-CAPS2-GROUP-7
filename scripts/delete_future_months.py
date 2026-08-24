import os
import psycopg2
from dotenv import load_dotenv

load_dotenv('.env')
url = os.getenv('SUPABASE_DB_URL')
conn = psycopg2.connect(url)
cur = conn.cursor()

# Delete July and August 2026 from all relevant fact tables
cur.execute("DELETE FROM SellOut_Fact WHERE _period >= '2026-07'")
print(f"Deleted {cur.rowcount} rows from SellOut_Fact")

cur.execute("DELETE FROM Inventory_Fact WHERE _period >= '2026-07'")
print(f"Deleted {cur.rowcount} rows from Inventory_Fact")

# Forecast_Result uses date format YYYY-MM-DD
cur.execute("DELETE FROM Forecast_Result WHERE forecast_date >= '2026-07-01'")
print(f"Deleted {cur.rowcount} rows from Forecast_Result")

conn.commit()
conn.close()
