"""scripts/make_demo_sales_file.py - the generated March 2026 sales file a demonstration uploads (2026-11-05). READ ONLY.

    python -m scripts.make_demo_sales_file [--out local/demo/demo_march_sales.csv]

Each product's March is its own real February scaled by a fixed factor between 0.8 and 1.2 taken from a hash of its code (the rule of
scripts/local_pipeline_qa.py synth, so the same file results every time). The file is GENERATED, not SSM's: the upload page's loader
(scripts/demo_session.py) writes every row is_demo = true. It goes in the git-ignored local/ folder because it holds per-product sales
(hard rule 9), and the first line says what it is.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

SQL = """
    SELECT sku_code, GREATEST(round(quantity_sold * (0.8 + 0.4 * ((abs(hashtext(sku_code || '2026-03')) % 1000) / 1000.0))), 0) AS quantity_sold,
           round((net_amount * (0.8 + 0.4 * ((abs(hashtext(sku_code || '2026-03')) % 1000) / 1000.0)))::numeric, 2) AS net_amount, gsv, region
    FROM unilever_sku_demand_fact WHERE calendar_month = '2026-02' AND is_demo = false AND quantity_sold > 0 ORDER BY sku_code
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "local" / "demo" / "demo_march_sales.csv"))
    args = ap.parse_args()
    import psycopg2
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")
    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
    cur = conn.cursor()
    cur.execute("SET TRANSACTION READ ONLY")
    cur.execute(SQL)
    rows = cur.fetchall()
    conn.rollback()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["sku_code", "calendar_month", "quantity_sold", "net_amount", "gsv", "region"])
        for sku, qty, net, gsv, region in rows:
            w.writerow([sku, "2026-03", int(qty), net, "" if gsv is None else gsv, region or ""])
    print(f"{len(rows)} generated March 2026 rows written to {out} (GENERATED demonstration sales, not SSM's)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
