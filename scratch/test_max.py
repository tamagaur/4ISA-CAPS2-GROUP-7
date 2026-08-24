import pandas as pd
import psycopg2
import os
from dotenv import load_dotenv
load_dotenv('.env')
conn = psycopg2.connect(os.getenv('SUPABASE_DB_URL'))
df = pd.read_sql("""
        SELECT
            pd.product_key,
            pd.sku_code,
            d.period,
            SUM(d.quantity) as total_quantity
        FROM (
            SELECT sf.product_key, sf._period as period, sf.quantity 
            FROM SellOut_Fact_Real sf
            JOIN Product_Dimension p ON sf.product_key = p.product_key
            WHERE p.principal = 'delmonte'
            
            UNION ALL
            
            SELECT product_key, calendar_month as period, quantity_sold as quantity 
            FROM Unilever_SKU_Demand_Fact_Real
        ) d
        JOIN Product_Dimension pd ON d.product_key = pd.product_key
        WHERE pd.sku_code = '68438413'
        GROUP BY pd.product_key, pd.sku_code, d.period
        ORDER BY pd.product_key, d.period ASC
""", conn)
df['quantity'] = pd.to_numeric(df['total_quantity'], errors='coerce').fillna(0)
df['period'] = pd.to_datetime(df['period'] + '-01')
series = df.set_index('period')['quantity']
series = series.resample('MS').asfreq().fillna(0.0)
print('Max:', series.max())
print('Max * 5:', series.max() * 5)
