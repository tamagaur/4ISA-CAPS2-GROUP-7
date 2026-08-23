import os
import psycopg2
import random
from dotenv import load_dotenv
from datetime import datetime

def generate_synthetic_inventory():
    load_dotenv('.env')
    conn = psycopg2.connect(os.getenv('SUPABASE_DB_URL'))
    cur = conn.cursor()

    print("Fetching active products without inventory...")
    # Find all active products that do NOT have a recent inventory record for our target period
    # Let's say we target '2026-08'
    target_period = '2026-08'
    snapshot_date = '2026-08-01'
    
    query = """
    SELECT p.product_key, p.principal, p.sku_code, p.category_path
    FROM Product_Dimension p
    WHERE p.status = 'ACTIVE'
      AND p.product_key NOT IN (
          SELECT product_key FROM Inventory_Fact WHERE _period = %s
      )
    """
    cur.execute(query, (target_period,))
    missing_products = cur.fetchall()
    
    print(f"Found {len(missing_products)} active products missing inventory for {target_period}.")
    if not missing_products:
        return

    print("Generating synthetic inventory...")
    insert_query = """
    INSERT INTO Inventory_Fact (
        product_key, sku_code, snapshot_date, _period, principal, region, 
        quantity_on_hand, quantity_pieces, valuation, is_demo, _src_file, _src_sheet
    ) VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, true, 'synthetic_generator', 'synthetic'
    )
    """
    
    count = 0
    for row in missing_products:
        p_key, principal, sku, cat = row
        # Fallback if SKU is missing
        sku_val = sku if sku else f"SYNTH_{p_key}"
        
        qty_on_hand = random.randint(10, 500)
        valuation = qty_on_hand * random.uniform(10.0, 50.0)
        
        for region in ['ilocos', 'pangasinan']:
            try:
                cur.execute(insert_query, (
                    p_key, sku_val, snapshot_date, target_period, principal, region,
                    qty_on_hand, qty_on_hand, valuation
                ))
                count += 1
            except Exception as e:
                pass # ignore unique constraint errors if any
                
    conn.commit()
    print(f"Successfully generated {count} synthetic inventory records!")

if __name__ == "__main__":
    generate_synthetic_inventory()
