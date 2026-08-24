import pandas as pd, psycopg2, os
from dotenv import load_dotenv
from statsmodels.tsa.statespace.sarimax import SARIMAX
import warnings

load_dotenv('.env')
conn = psycopg2.connect(os.getenv('SUPABASE_DB_URL'))
df = pd.read_sql("""
        SELECT pd.product_key, pd.sku_code, d.period, SUM(d.quantity) as total_quantity
        FROM (
            SELECT sf.product_key, sf._period as period, sf.quantity 
            FROM SellOut_Fact_Real sf JOIN Product_Dimension p ON sf.product_key = p.product_key WHERE p.principal = 'delmonte'
            UNION ALL
            SELECT product_key, calendar_month as period, quantity_sold as quantity FROM Unilever_SKU_Demand_Fact_Real
        ) d
        JOIN Product_Dimension pd ON d.product_key = pd.product_key
        WHERE pd.sku_code = '68438413'
        GROUP BY pd.product_key, pd.sku_code, d.period
        ORDER BY d.period ASC
""", conn)
df['quantity'] = pd.to_numeric(df['total_quantity'], errors='coerce').fillna(0)
df['period'] = pd.to_datetime(df['period'] + '-01')
series = df.set_index('period')['quantity'].resample('MS').asfreq().fillna(0.0)

print('Series Max:', series.max())
print('Series Tail:', series.tail(3).values)

import sys
sys.path.insert(0, os.path.abspath('.'))
from analytics.forecasting.sarima import fit_sarima
fast_grid = {'p': (0, 1), 'd': (0, 1), 'q': (0, 1), 'P': (0,), 'D': (0,), 'Q': (0,)}
result = fit_sarima(series, sku_id='68438413', param_grid=fast_grid, holdout_fraction=0.2)
print('Best params:', result.order, result.seasonal_order)

with warnings.catch_warnings():
    warnings.simplefilter('ignore')
    full_model = SARIMAX(series, order=result.order, seasonal_order=result.seasonal_order, enforce_stationarity=True, enforce_invertibility=True)
    full_fitted = full_model.fit(disp=False)
    forecast = full_fitted.get_forecast(steps=1)
    f_val = float(forecast.predicted_mean.iloc[0])

print('Predicted f_val:', f_val)
