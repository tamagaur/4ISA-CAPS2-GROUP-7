import os
from dotenv import load_dotenv
load_dotenv(r"C:\Users\kyuan\Capstone-Project\.env")
import psycopg2

conn = psycopg2.connect(os.environ["SUPABASE_DIRECT_URL"])
conn.autocommit = False
cur = conn.cursor()

# 1. Backup
cur.execute("DROP TABLE IF EXISTS ssm_abc_phase2.abc_classification_backup_20260917;")
cur.execute("CREATE TABLE ssm_abc_phase2.abc_classification_backup_20260917 AS SELECT * FROM public.abc_classification;")
cur.execute("SELECT count(*) FROM ssm_abc_phase2.abc_classification_backup_20260917;")
backup_count = cur.fetchone()[0]
print("Backup rows:", backup_count)
conn.commit()

# 2. Apply migration 0017
with open(r"C:\Users\kyuan\Capstone-Project\analytics\db\migrations\0017_abc_classification_method_run_id.sql") as f:
    migration_sql = f.read()
cur.execute(migration_sql)
conn.commit()
print("Migration 0017 applied.")

cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='abc_classification' ORDER BY ordinal_position;")
print("abc_classification columns now:", cur.fetchall())

# 3. Write both methods from the verified scratch_v2 table to public
cur.execute("""
    INSERT INTO public.abc_classification
        (product_key, principal, classification_period, method, run_id, tier, revenue_share, cumulative_share, boundary_flag)
    SELECT product_key, 'unilever', classification_period, method, run_id, tier, revenue_share, cumulative_share, boundary_flag
    FROM ssm_abc_phase2.abc_scratch_v2
    WHERE tier IS NOT NULL
    ON CONFLICT (product_key, classification_period, method) DO UPDATE SET
        run_id = EXCLUDED.run_id,
        tier = EXCLUDED.tier,
        revenue_share = EXCLUDED.revenue_share,
        cumulative_share = EXCLUDED.cumulative_share,
        boundary_flag = EXCLUDED.boundary_flag,
        computed_at = now();
""")
print("Rows written:", cur.rowcount)
conn.commit()

cur.execute("SELECT method, count(*) FROM public.abc_classification WHERE principal='unilever' GROUP BY method;")
print("Public abc_classification counts by method:", cur.fetchall())

cur.close()
conn.close()
