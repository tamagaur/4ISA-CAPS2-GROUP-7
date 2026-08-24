import psycopg2, os
from dotenv import load_dotenv
load_dotenv('.env')
conn = psycopg2.connect(os.getenv('SUPABASE_DB_URL'))
cur = conn.cursor()
cur.execute("""
SELECT principal, EXTRACT(YEAR FROM snapshot_date) as yr, COUNT(DISTINCT snapshot_date) as months, COUNT(DISTINCT sku_code) as unique_skus, COUNT(*) as total_rows
FROM Inventory_Fact_Real
WHERE is_demo = TRUE AND _src_file = 'Synthetic_Generator'
GROUP BY principal, yr
ORDER BY principal, yr
""")
print('RAW DATABASE FACTS:')
print('Principal | Year | Months Populated | Unique SKUs | Total Rows Inserted')
for row in cur.fetchall():
    print(f'{row[0]:<9} | {int(row[1])} | {int(row[2]):<16} | {row[3]:<11} | {row[4]}')
