import pandas as pd
from pathlib import Path

staging_dir = Path('c:/Users/kyuan/Capstone-Project/staging')
target_sku = '9IDK70634'
found_principal = None

print("Checking unilever_sku...")
for f in (staging_dir / 'unilever_sku').glob('*.parquet'):
    df = pd.read_parquet(f, columns=['Product'])
    if df['Product'].str.contains(target_sku).any():
        found_principal = 'unilever'
        break

if not found_principal:
    print("Checking delmonte_sku (sales_register)...")
    for f in (staging_dir / 'sales_register').glob('*.parquet'):
        if 'Item Code' in pd.read_parquet(f).columns:
            df = pd.read_parquet(f, columns=['Item Code'])
            if df['Item Code'].str.contains(target_sku).any():
                found_principal = 'delmonte'
                break

print(f"Principal for {target_sku}: {found_principal}")

if found_principal == 'unilever':
    print(f"\nChecking periods for {target_sku} in Unilever data...")
    periods = set()
    for f in (staging_dir / 'unilever_sku').glob('*.parquet'):
        df = pd.read_parquet(f, columns=['Product', '_period'])
        mask = df['Product'].str.contains(target_sku, na=False)
        periods.update(df[mask]['_period'].dropna().unique())
    print(f"Found periods: {sorted(list(periods))}")
elif found_principal == 'delmonte':
    print(f"\nChecking periods for {target_sku} in Del Monte (sales_register) data...")
    periods = set()
    for f in (staging_dir / 'sales_register').glob('*.parquet'):
        if 'Item Code' in pd.read_parquet(f).columns:
            df = pd.read_parquet(f, columns=['Item Code', '_period'])
            mask = df['Item Code'].str.contains(target_sku, na=False)
            periods.update(df[mask]['_period'].dropna().unique())
    print(f"Found periods: {sorted(list(periods))}")
