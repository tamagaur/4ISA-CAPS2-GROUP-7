import psycopg2, os
from dotenv import load_dotenv

load_dotenv('.env')
direct_url = os.getenv('SUPABASE_DIRECT_URL')
conn = psycopg2.connect(direct_url)
cur = conn.cursor()

# Get top categories and sample products for Del Monte
print("=== DEL MONTE ===")
cur.execute("""
    SELECT category, COUNT(*), MIN(product_name) 
    FROM Product_Dimension 
    WHERE principal = 'delmonte' AND category IS NOT NULL 
    GROUP BY category 
    ORDER BY COUNT(*) DESC 
    LIMIT 10
""")
for row in cur.fetchall():
    print(f"Category: {row[0]:<20} | Count: {row[1]:<4} | Example: {row[2]}")

# Get top categories and sample products for Unilever
print("\n=== UNILEVER ===")
cur.execute("""
    SELECT category, COUNT(*), MIN(product_name) 
    FROM Product_Dimension 
    WHERE principal = 'unilever' AND category IS NOT NULL 
    GROUP BY category 
    ORDER BY COUNT(*) DESC 
    LIMIT 10
""")
for row in cur.fetchall():
    print(f"Category: {row[0]:<20} | Count: {row[1]:<4} | Example: {row[2]}")

conn.close()
