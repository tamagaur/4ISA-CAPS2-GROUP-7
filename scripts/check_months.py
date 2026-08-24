import os
import psycopg2
import pandas as pd
from dotenv import load_dotenv

load_dotenv('.env')
url = os.getenv('SUPABASE_DB_URL')
conn = psycopg2.connect(url)
query = 'SELECT DISTINCT _period FROM SellOut_Fact ORDER BY _period;'
df = pd.read_sql(query, conn)
periods = pd.to_datetime(df['_period'] + '-01')
all_months = pd.date_range(start=periods.min(), end=periods.max(), freq='MS')
missing = all_months.difference(periods)
print('Missing Months in SellOut_Fact:')
for m in missing:
    print(m.strftime('%Y-%m'))
