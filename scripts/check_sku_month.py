import os, psycopg2, pandas as pd
from dotenv import load_dotenv

load_dotenv('.env')
url = os.getenv('SUPABASE_DB_URL')
conn = psycopg2.connect(url)

query = "SELECT _period FROM SellOut_Fact s JOIN Product_Dimension pd ON s.product_key = pd.product_key WHERE pd.sku_code = '9IDK70634' ORDER BY _period;"
df = pd.read_sql(query, conn)
periods = pd.to_datetime(df['_period'] + '-01')

all_months = pd.date_range(start=periods.min(), end=periods.max(), freq='MS')
missing = all_months.difference(periods)

for m in missing:
    print(m.strftime('%Y-%m'))
