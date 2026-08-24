import json

def build_mapping():
    mapping = {}
    with open('data/delmonte_real_skus.txt', 'r', encoding='latin-1') as f:
        lines = [line.strip() for line in f if line.strip()]
        
    for line in lines:
        parts = line.split(' ', 1)
        sku = parts[0]
        if len(parts) > 1:
            name = parts[1].strip()
            # Some names are just '-' or empty, ignore those
            if len(name) > 2 and name != sku:
                mapping[sku] = name
    return mapping

mapping = build_mapping()
bad_skus = json.load(open('scratch/bad_skus.json'))

sql_statements = []
unmapped = []

for item in bad_skus:
    sku = item['sku']
    if sku in mapping:
        new_name = mapping[sku].replace("'", "''") # escape for SQL
        sql_statements.append(f"UPDATE Product_Dimension SET product_name = '{new_name}' WHERE sku_code = '{sku}';")
    else:
        unmapped.append(item)

with open('scratch/update_products.sql', 'w', encoding='utf-8') as f:
    f.write("\n".join(sql_statements))

print(f"Generated {len(sql_statements)} UPDATE statements.")
print(f"Unmapped SKUs: {len(unmapped)}")
if unmapped:
    for u in unmapped[:5]:
        print(u)
