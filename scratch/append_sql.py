updates = [
    "UPDATE Product_Dimension SET product_name = 'DM EXTRA RICH KETCHUP 24/12 OZ' WHERE sku_code = '9DMP5204';",
    "UPDATE Product_Dimension SET product_name = 'DM RED CANE VINEGAR 985ML QUART ROYCE' WHERE sku_code = '9DMR1616';",
    "UPDATE Product_Dimension SET product_name = 'Kikkoman Culinary Sauce' WHERE sku_code = '9NWN37780';",
    "UPDATE Product_Dimension SET product_name = 'Del Monte Culinary General' WHERE sku_code = '9ZBI74289';",
    "UPDATE Product_Dimension SET product_name = 'Unknown Product - 9DMP55794' WHERE sku_code = '9DMP55794';"
]
with open('scratch/update_products.sql', 'a', encoding='utf-8') as f:
    f.write("\n" + "\n".join(updates))
