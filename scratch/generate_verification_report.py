import os
import psycopg2
import pandas as pd
from dotenv import load_dotenv

def generate_report():
    load_dotenv('.env')
    db_url = os.getenv('SUPABASE_DB_URL')
    if not db_url:
        print("SUPABASE_DB_URL not set.")
        return
        
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    
    query = """
        SELECT principal, snapshot_date, COUNT(DISTINCT sku_code) as sku_count
        FROM Inventory_Fact_Real
        WHERE is_demo = TRUE AND _src_file = 'Synthetic_Generator'
        GROUP BY principal, snapshot_date
        ORDER BY principal, snapshot_date
    """
    
    cur.execute(query)
    rows = cur.fetchall()
    
    df = pd.DataFrame(rows, columns=['principal', 'snapshot_date', 'sku_count'])
    df['year'] = pd.to_datetime(df['snapshot_date']).dt.year
    df['month'] = pd.to_datetime(df['snapshot_date']).dt.strftime('%B')
    
    # We want to check years 2023, 2024, 2025, 2026
    years = [2023, 2024, 2025, 2026]
    months = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
    
    markdown = "# Synthetic Inventory Coverage Verification\n\n"
    markdown += "This report verifies that the synthetic data generation script successfully populated the `Inventory_Fact_Real` table in Supabase. It checks coverage across both **Del Monte** and **Unilever** from **January 2023** to **June 2026**.\n\n"
    
    for principal in ['delmonte', 'unilever']:
        markdown += f"## {principal.upper()} Coverage\n\n"
        
        for year in years:
            markdown += f"### {year}\n"
            markdown += "| Month | Status | SKUs Populated |\n"
            markdown += "| :--- | :--- | :--- |\n"
            
            for month in months:
                # June 2026 is our cut-off based on the max date we found
                if year == 2026 and months.index(month) > 5:
                    continue
                    
                match = df[(df['principal'] == principal) & (df['year'] == year) & (df['month'] == month)]
                
                if not match.empty:
                    count = match.iloc[0]['sku_count']
                    status = "✅ Successfully Generated"
                    markdown += f"| **{month}** | {status} | {count:,} |\n"
                else:
                    status = "❌ Missing"
                    markdown += f"| **{month}** | {status} | 0 |\n"
                    
            markdown += "\n"
            
    with open('scratch/synthetic_verification_report.md', 'w', encoding='utf-8') as f:
        f.write(markdown)
        
    print("Report generated successfully.")
    conn.close()

if __name__ == '__main__':
    generate_report()
