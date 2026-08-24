import os
import psycopg2
import pandas as pd
import matplotlib.pyplot as plt
from dotenv import load_dotenv

load_dotenv('.env')
conn = psycopg2.connect(os.getenv('SUPABASE_DB_URL'))

sku = '9IDK70634'

# Get Historical Data
query_hist = f"""
    SELECT _period as period, SUM(quantity) as sales
    FROM SellOut_Fact
    WHERE product_key = (SELECT product_key FROM Product_Dimension WHERE sku_code = '{sku}')
    GROUP BY _period
    ORDER BY _period
"""
df_hist = pd.read_sql(query_hist, conn)
df_hist['period'] = pd.to_datetime(df_hist['period'] + '-01')
df_hist.set_index('period', inplace=True)
df_hist = df_hist.asfreq('MS', fill_value=0) # fill gaps with 0

# Get Forecast Data
query_fcast = f"""
    SELECT forecast_date as period, forecast_quantity as sales
    FROM Forecast_Result
    WHERE product_key = (SELECT product_key FROM Product_Dimension WHERE sku_code = '{sku}')
    ORDER BY forecast_date
"""
df_fcast = pd.read_sql(query_fcast, conn)
df_fcast['period'] = pd.to_datetime(df_fcast['period'])
df_fcast.set_index('period', inplace=True)

# Plotting
plt.figure(figsize=(12, 6))
plt.plot(df_hist.index, df_hist['sales'], label='Historical Sales (Actual)', color='blue', marker='o')
plt.plot(df_fcast.index, df_fcast['sales'], label='SARIMA Forecast', color='orange', linestyle='--', marker='x')

plt.title(f'Sales History and SARIMA Forecast for {sku} (ACE/PROMO)')
plt.xlabel('Date')
plt.ylabel('Quantity Sold')
plt.grid(True, alpha=0.3)
plt.legend()

# Save to artifact directory
out_path = r'C:\Users\kyuan\.gemini\antigravity-ide\brain\d778170f-1764-4450-b014-290662536617\scratch\sarima_plot.png'
os.makedirs(os.path.dirname(out_path), exist_ok=True)
plt.savefig(out_path)
print(f"Plot saved to {out_path}")
