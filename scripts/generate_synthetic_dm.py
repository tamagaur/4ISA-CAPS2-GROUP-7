import os
import random
import psycopg2
from dotenv import load_dotenv

def generate_synthetic_dm_skus():
    """
    Reads extracted Del Monte SKUs from data/delmonte_real_skus.txt 
    and generates synthetic product rows for them in Product_Dimension, 
    so the synthetic sales can be mapped to real SKUs.
    """
    load_dotenv('.env')
    conn = psycopg2.connect(os.getenv('SUPABASE_DB_URL'))
    cur = conn.cursor()

    try:
        with open('data/delmonte_real_skus.txt', 'r') as f:
            skus = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        print("data/delmonte_real_skus.txt not found. Run extract_dm.py first.")
        return

    print(f"Loaded {len(skus)} real Del Monte SKUs. Pushing to Product_Dimension...")
    
    insert_query = """
    INSERT INTO Product_Dimension (principal, grain, sku_code, category_path, product_name, status)
    VALUES ('delmonte', 'sku', %s, %s, %s, 'ACTIVE')
    ON CONFLICT (principal, grain, sku_code, category_path) DO NOTHING
    """
    
    # Simple heuristic to extract a fake category from the SKU description for mapping
    # e.g., "9DBL58406 DMJD Four Seasons 202 6-Pack" -> category "/FOUR SEASONS"
    count = 0
    for sku_line in skus:
        parts = sku_line.split(' ', 1)
        sku_code = parts[0]
        desc = parts[1] if len(parts) > 1 else sku_code
        
        # Determine category mapping based on keywords
        category = "/BASE"
        if "FOUR SEASONS" in desc.upper(): category = "/FOUR SEASONS"
        elif "PINE" in desc.upper() and "JUICE" in desc.upper(): category = "/PINEAPPLE JUICE"
        elif "KETCHUP" in desc.upper(): category = "/KETCHUP"
        elif "SPAG" in desc.upper(): category = "/SPAGHETTI SAUCE"
        
        try:
            cur.execute(insert_query, (sku_code, category, desc))
            count += cur.rowcount
        except Exception as e:
            print(f"Error inserting {sku_code}: {e}")
            conn.rollback()
            continue
            
    conn.commit()
    print(f"Successfully inserted/verified {count} SKU rows in Product_Dimension!")

if __name__ == "__main__":
    generate_synthetic_dm_skus()
