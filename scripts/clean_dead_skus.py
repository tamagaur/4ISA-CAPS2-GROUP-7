import os
import psycopg2
from dotenv import load_dotenv

def clean_dead_skus():
    """
    Disables SKUs in Product_Dimension that haven't had a single sale in the last 6 months.
    """
    load_dotenv('.env')
    conn = psycopg2.connect(os.getenv('SUPABASE_DB_URL'))
    cur = conn.cursor()

    print("Identifying dead SKUs (no sales in last 6 months)...")
    
    cur.execute("SELECT MAX(calendar_month) FROM unilever_sku_demand_fact_real")
    max_month = cur.fetchone()[0]
    
    if not max_month:
        print("No sales data found.")
        return

    query = """
    WITH sku_max_dates AS (
        SELECT product_key, MAX(calendar_month) as last_sale_month
        FROM unilever_sku_demand_fact_real
        GROUP BY product_key
    )
    SELECT p.product_key, p.sku_code, s.last_sale_month
    FROM sku_max_dates s
    JOIN Product_Dimension p ON p.product_key = s.product_key
    WHERE p.principal = 'unilever' 
      AND p.status = 'ACTIVE'
      AND (
          (CAST(SUBSTRING(%s FROM 1 FOR 4) AS INTEGER) - CAST(SUBSTRING(s.last_sale_month FROM 1 FOR 4) AS INTEGER)) * 12 
          + (CAST(SUBSTRING(%s FROM 6 FOR 2) AS INTEGER) - CAST(SUBSTRING(s.last_sale_month FROM 6 FOR 2) AS INTEGER))
      ) >= 6
    """
    
    cur.execute(query, (max_month, max_month))
    dead_skus = cur.fetchall()
    
    if not dead_skus:
        print("No dead SKUs found.")
        return
        
    print(f"Found {len(dead_skus)} dead SKUs. Disabling them...")
    dead_keys = tuple([row[0] for row in dead_skus])
    
    update_query = "UPDATE Product_Dimension SET status = 'DISABLED' WHERE product_key IN %s"
    cur.execute(update_query, (dead_keys,))
    conn.commit()
    print(f"Successfully disabled {len(dead_keys)} SKUs.")

if __name__ == "__main__":
    clean_dead_skus()
