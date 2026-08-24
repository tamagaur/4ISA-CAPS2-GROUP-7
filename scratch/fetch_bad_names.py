import os
import urllib.request
import json
from dotenv import load_dotenv

load_dotenv('.env')
url = os.getenv('SUPABASE_URL')
key = os.getenv('SUPABASE_SERVICE_KEY')

def fetch(path):
    req = urllib.request.Request(f"{url}{path}")
    req.add_header("apikey", key)
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print("Error:", e)
        return []

print("--- 'Culinary' Products ---")
culinary = fetch("/rest/v1/Product_Dimension?product_name=ilike.*culinary*&select=sku_code,product_name")
for row in culinary[:15]:
    print(row)

print("\n--- product_name == sku_code ---")
delmonte = fetch("/rest/v1/Product_Dimension?principal=eq.delmonte&select=sku_code,product_name")
bad_skus = [row for row in delmonte if row['sku_code'] == row['product_name']]
for row in bad_skus[:15]:
    print(row)
