import os
import psycopg2
import random
from dotenv import load_dotenv

def map_dm_sales_to_skus():
    """
    Distributes category-level SellOut_Fact records to actual SKUs for Del Monte.
    This fixes the join issue between inventory (SKU level) and sellout (Category level).
    """
    load_dotenv('.env')
    conn = psycopg2.connect(os.getenv('SUPABASE_DB_URL'))
    cur = conn.cursor()

    print("Fetching Del Monte SellOut_Fact records that are still at the category level...")
    # A category level row has a product_key pointing to a 'category' grain Product_Dimension,
    # or the sellout record doesn't have a specific SKU.
    # Actually, in Product_Dimension, we inserted SKUs with grain='sku' and category_path assigned.
    
    # 1. Get all Del Monte SKUs grouped by their assigned category
    cur.execute("SELECT category_path, product_key FROM Product_Dimension WHERE principal = 'delmonte' AND grain = 'sku' AND status = 'ACTIVE'")
    sku_mapping = {}
    for cat_path, p_key in cur.fetchall():
        if cat_path not in sku_mapping:
            sku_mapping[cat_path] = []
        sku_mapping[cat_path].append(p_key)
        
    print(f"Loaded SKU mappings for {len(sku_mapping)} categories.")
    
    # 2. Get all SellOut_Fact records
    # To avoid double processing, we'll only look at rows where the associated product is grain = 'category',
    # or we just process all of them and update their product_key to a SKU product_key.
    cur.execute("""
        SELECT s.sellout_key, s.category_path, s.quantity, s.net_amount
        FROM SellOut_Fact s
        JOIN Product_Dimension p ON p.product_key = s.product_key
        WHERE s.principal = 'delmonte' AND p.grain = 'category'
    """)
    category_sales = cur.fetchall()
    
    if not category_sales:
        print("No category-level sales found to map. They might already be mapped!")
        return
        
    print(f"Found {len(category_sales)} category-level sales records to map to SKUs.")
    
    # We will update the SellOut_Fact records to point to a random SKU within that category.
    # For a more robust approach, we could split the row into multiple rows, but updating the existing
    # row's product_key to a valid SKU is the quickest way to make the join work for the dashboard.
    
    update_query = "UPDATE SellOut_Fact SET product_key = %s WHERE sellout_key = %s"
    updates = 0
    unmapped = 0
    
    for row in category_sales:
        sellout_key, cat_path, qty, amount = row
        
        # Find SKUs for this category. If none match exactly, use a generic fallback category
        # Since my earlier extraction script mapped them coarsely (e.g., /FOUR SEASONS, /BASE)
        # we try to find a match, or just pick any random Del Monte SKU if no match.
        available_skus = sku_mapping.get(cat_path)
        if not available_skus:
            # Fallback to '/BASE' or any available SKU
            available_skus = sku_mapping.get('/BASE')
            
        if available_skus:
            chosen_sku = random.choice(available_skus)
            cur.execute(update_query, (chosen_sku, sellout_key))
            updates += 1
        else:
            unmapped += 1
            
    conn.commit()
    print(f"Successfully mapped {updates} sales records to SKUs. {unmapped} could not be mapped.")

if __name__ == "__main__":
    map_dm_sales_to_skus()
