import psycopg2, os
from dotenv import load_dotenv

load_dotenv('.env')
direct_url = os.getenv('SUPABASE_DIRECT_URL')
conn = psycopg2.connect(direct_url)
cur = conn.cursor()

print("=== DEL MONTE CATEGORIES & PRODUCTS ===")
cur.execute("""
    SELECT COALESCE(category_path, 'UNKNOWN') as cat, COUNT(*), string_agg(product_name, ', ') 
    FROM (
        SELECT category_path, product_name, 
               row_number() OVER (PARTITION BY category_path ORDER BY random()) as rn
        FROM Product_Dimension 
        WHERE principal = 'delmonte'
    ) sub
    WHERE rn <= 3
    GROUP BY cat
    ORDER BY COUNT(*) DESC
    LIMIT 10
""")
for row in cur.fetchall():
    print(f"[{row[0]}] ({row[1]} SKUs)\nExamples: {row[2][:100]}...\n")

print("=== UNILEVER CATEGORIES & PRODUCTS ===")
cur.execute("""
    SELECT COALESCE(category_path, 'UNKNOWN') as cat, COUNT(*), string_agg(product_name, ', ') 
    FROM (
        SELECT category_path, product_name, 
               row_number() OVER (PARTITION BY category_path ORDER BY random()) as rn
        FROM Product_Dimension 
        WHERE principal = 'unilever'
    ) sub
    WHERE rn <= 3
    GROUP BY cat
    ORDER BY COUNT(*) DESC
    LIMIT 10
""")
for row in cur.fetchall():
    print(f"[{row[0]}] ({row[1]} SKUs)\nExamples: {row[2][:100]}...\n")

conn.close()
