import os, psycopg2, pandas as pd
from dotenv import load_dotenv

load_dotenv('.env')
conn = psycopg2.connect(os.getenv('SUPABASE_DB_URL'))

query = """
SELECT 
    pd.sku_code, 
    pd.product_name, 
    fr.forecast_date, 
    fr.forecast_quantity
FROM Forecast_Result fr
JOIN Product_Dimension pd ON fr.product_key = pd.product_key
WHERE pd.sku_code IN ('9IDK70634', '9JCU24802', '9WBI34725')
ORDER BY pd.sku_code, fr.forecast_date
LIMIT 30;
"""
df = pd.read_sql(query, conn)

md_content = "# SARIMA Forecast Results\n\n"
md_content += "Here is a quick snapshot of the successful SARIMA forecasts generated for the next few months, including our promo SKU!\n\n"
md_content += "| SKU Code | Product Name | Forecast Date | Forecasted Quantity |\n"
md_content += "|---|---|---|---|\n"

for _, row in df.iterrows():
    md_content += f"| {row['sku_code']} | {row['product_name']} | {row['forecast_date']} | {row['forecast_quantity']} |\n"

out_path = r'C:\Users\kyuan\.gemini\antigravity-ide\brain\d778170f-1764-4450-b014-290662536617\sarima_results.md'
with open(out_path, 'w', encoding='utf-8') as f:
    f.write(md_content)

print(f"Artifact created at {out_path}")
