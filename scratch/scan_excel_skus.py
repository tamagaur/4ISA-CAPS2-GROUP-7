import os
import pandas as pd
import glob

def find_bad_skus():
    base_dir = r"c:\Users\kyuan\Capstone-Project\SAN SAN Marketing\Del Monte"
    files = glob.glob(os.path.join(base_dir, "**", "*.xlsx"), recursive=True)
    
    bad_skus = set()
    culinary_skus = set()
    
    for f in files:
        try:
            df = pd.read_excel(f, sheet_name=0) # Read first sheet
            # Look for columns that might contain SKU code / name
            for col in df.columns:
                if df[col].dtype == object:
                    for val in df[col].dropna():
                        val_str = str(val)
                        if 'culinary' in val_str.lower():
                            culinary_skus.add(val_str)
                        # Check if it starts with 9 and has no text (e.g. 9DBL58406)
                        if val_str.startswith('9') and len(val_str) >= 8 and len(val_str) <= 12 and ' ' not in val_str:
                            bad_skus.add(val_str)
        except Exception as e:
            pass
            
    print("--- SKUs that look like just codes ---")
    for b in sorted(list(bad_skus))[:20]:
        print(b)
        
    print("\n--- SKUs containing 'Culinary' ---")
    for c in sorted(list(culinary_skus))[:20]:
        print(c)

find_bad_skus()
