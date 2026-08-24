import pandas as pd
from pathlib import Path

staging_dir = Path('c:/Users/kyuan/Capstone-Project/staging')
found = False
for f in staging_dir.rglob('*.parquet'):
    df = pd.read_parquet(f)
    if 'Product' in df.columns:
        match = df[df['Product'].astype(str).str.contains('9IDK70634', na=False)]
        if not match.empty:
            print(f"Found in {f.name}")
            print(match.iloc[0].to_dict())
            found = True
            break
    if 'Item Code' in df.columns:
        match = df[df['Item Code'].astype(str).str.contains('9IDK70634', na=False)]
        if not match.empty:
            print(f"Found in {f.name}")
            print(match.iloc[0].to_dict())
            found = True
            break

if not found:
    print("Not found in staging")
