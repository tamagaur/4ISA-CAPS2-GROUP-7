import os
import psycopg2
from psycopg2.extras import execute_values
import pandas as pd
import numpy as np
from datetime import datetime
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv

def main():
    load_dotenv('.env')
    db_url = os.getenv('SUPABASE_DB_URL')
    if not db_url:
        print("SUPABASE_DB_URL not set.")
        return
        
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    cur = conn.cursor()

    print("Fetching historical sales data for 3-week rule inventory calculation...")
    
    # Query all demand data across both principals
    query = """
        SELECT
            pd.product_key,
            pd.sku_code,
            pd.principal,
            d.period,
            SUM(d.quantity) as monthly_sales
        FROM (
            SELECT sf.product_key, sf._period as period, sf.quantity
            FROM SellOut_Fact_Real sf
            
            UNION ALL
            
            SELECT product_key, calendar_month as period, quantity_sold as quantity
            FROM Unilever_SKU_Demand_Fact_Real
        ) d
        JOIN Product_Dimension pd ON d.product_key = pd.product_key
        WHERE d.period IS NOT NULL
        GROUP BY pd.product_key, pd.sku_code, pd.principal, d.period
    """
    cur.execute(query)
    rows = cur.fetchall()
    
    df = pd.DataFrame(rows, columns=['product_key', 'sku_code', 'principal', 'period', 'monthly_sales'])
    
    # Clean up period
    def parse_period(p):
        if isinstance(p, str):
            if '-' in p:
                return datetime.strptime(p[:7], '%Y-%m').date()
        elif isinstance(p, datetime):
            return p.date()
        return p

    df['snapshot_date'] = df['period'].apply(parse_period)
    df = df.dropna(subset=['snapshot_date'])
    df['monthly_sales'] = pd.to_numeric(df['monthly_sales'], errors='coerce').fillna(0)
    
    # Target range: dynamic start date to dynamic end date
    start_date = df['snapshot_date'].min()
    if pd.isna(start_date):
        start_date = datetime(2021, 1, 1).date() # Fallback
        
    end_date = df['snapshot_date'].max()
    if pd.isna(end_date):
        end_date = datetime(2026, 6, 1).date() # Fallback
    
    # Generate all month periods
    all_months = []
    curr = start_date
    while curr <= end_date:
        all_months.append(curr)
        curr = (curr + relativedelta(months=1))
        
    # Get all unique SKUs
    skus = df[['product_key', 'sku_code', 'principal']].drop_duplicates()
    
    print(f"Generating synthetic inventory for {len(skus)} SKUs across {len(all_months)} months...")
    
    inventory_records = []
    np.random.seed(42) # For reproducible noise
    
    for _, sku in skus.iterrows():
        p_key = sku['product_key']
        sku_code = sku['sku_code']
        principal = sku['principal']
        
        sku_sales = df[df['product_key'] == p_key].set_index('snapshot_date')['monthly_sales']
        
        # Calculate historical 3-week average for this SKU across all its active months
        # 3 weeks is roughly 0.75 of a month
        avg_monthly_sales = sku_sales.mean() if not sku_sales.empty else 0
        fallback_3_week_stock = avg_monthly_sales * 0.75
        
        for month in all_months:
            sales = sku_sales.get(month, 0)
            
            # The 3-week rule target inventory
            if sales > 0:
                target_inv = sales * 0.75
            else:
                # If no sales, assume dead stock sits there (historical 3-week target)
                target_inv = fallback_3_week_stock
                
            # Add realistic noise (+/- 15%)
            noise = np.random.uniform(0.85, 1.15)
            final_qty = round(target_inv * noise, 2)
            
            # Prevent negative inventory
            final_qty = max(0.0, final_qty)
            
            # Split roughly between regions (Pangasinan vs Ilocos)
            # We'll just generate one row per region for completeness
            for region in ['Pangasinan', 'Ilocos']:
                # 60/40 split roughly
                region_qty = final_qty * (0.6 if region == 'Pangasinan' else 0.4)
                
                inventory_records.append((
                    int(p_key),
                    sku_code,
                    month,
                    principal,
                    region,
                    float(region_qty),
                    True, # is_demo
                    month.strftime('%Y-%m'), # _period
                    'Synthetic_Generator', # _src_file
                    '3-Week-Rule' # _src_sheet
                ))
                
    # Create CSV
    import csv
    csv_path = 'data/processed/inventory_fact_synthetic.csv'
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['product_key', 'sku_code', 'snapshot_date', 'principal', 'region', 'quantity_on_hand', 'is_demo', '_period', '_src_file', '_src_sheet'])
        writer.writerows(inventory_records)
        
    print(f"Generated {len(inventory_records)} rows. Saved to {csv_path}")
    
    # Insert directly to DB
    print("Inserting data into Inventory_Fact_Real...")
    
    cur.execute("DELETE FROM Inventory_Fact_Real WHERE is_demo = TRUE AND _src_file = 'Synthetic_Generator'")
    
    insert_query = """
        INSERT INTO Inventory_Fact_Real 
        (product_key, sku_code, snapshot_date, principal, region, quantity_on_hand, is_demo, _period, _src_file, _src_sheet)
        VALUES %s
        ON CONFLICT DO NOTHING
    """
    
    execute_values(cur, insert_query, inventory_records)
    print("Successfully inserted clean synthetic inventory data into the database.")
    
    conn.close()

if __name__ == '__main__':
    main()
