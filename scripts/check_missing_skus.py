import os, psycopg2, pandas as pd
from dotenv import load_dotenv

load_dotenv('.env')
url = os.getenv('SUPABASE_DB_URL')
conn = psycopg2.connect(url)

query = '''
SELECT
    pd.sku_code,
    pd.principal,
    s._period,
    SUM(s.quantity) as total_quantity
FROM SellOut_Fact s
JOIN Product_Dimension pd ON s.product_key = pd.product_key
JOIN ABC_Classification abc ON abc.product_key = pd.product_key
WHERE abc.tier = 'A'
GROUP BY pd.sku_code, pd.principal, s._period
ORDER BY pd.sku_code, s._period ASC
'''
df = pd.read_sql(query, conn)
df['period'] = pd.to_datetime(df['_period'] + '-01')

missing_skus = []
for sku, group in df.groupby(['sku_code', 'principal']):
    min_p = group['period'].min()
    max_p = group['period'].max()
    expected = pd.date_range(start=min_p, end=max_p, freq='MS')
    if len(expected) > len(group):
        missing_skus.append({'sku': sku[0], 'principal': sku[1], 'missing_count': len(expected) - len(group)})

print('SKUs with missing months:')
for s in missing_skus:
    print(f"{s['sku']} ({s['principal']}) - missing {s['missing_count']} months")
