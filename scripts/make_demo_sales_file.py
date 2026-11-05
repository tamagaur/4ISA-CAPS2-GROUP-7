"""scripts/make_demo_sales_file.py - the generated sales file for a month SSM has not sent (2026-11-06). READ ONLY.

    python -m scripts.make_demo_sales_file --month 2026-03 [--out local/demo/sales_2026-03.csv]
    python -m scripts.make_demo_sales_file --month 2026-04          # follows March: February scaled by March's factor, then April's

Each product's month is its own real February scaled by a fixed factor between 0.8 and 1.2 taken from a hash of its code and the month (the rule of
scripts/local_pipeline_qa.py synth, so the same file results every time); a month after March carries the factors of every month in between. The file is
GENERATED, not SSM's: the loader writes every row is_demo = true and the pages say so. The file carries its own month in a calendar_month column, which is
how the loader dates it (the file's name plays no part). It goes in the git-ignored local/ folder because it holds per-product sales (hard rule 9).
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

BASE_MONTH = "2026-02"      # the latest month SSM sent


def months_between(base: str, month: str) -> list[str]:
    out, y, m = [], int(base[:4]), int(base[5:7])
    while f"{y}-{m:02d}" < month:
        y, m = y + (m == 12), m % 12 + 1
        out.append(f"{y}-{m:02d}")
    return out


def sql_for(month: str) -> str:
    steps = months_between(BASE_MONTH, month)
    if not steps:
        raise SystemExit(f"{month} is not after {BASE_MONTH}")
    factor = " * ".join(f"(0.8 + 0.4 * ((abs(hashtext(sku_code || '{x}')) % 1000) / 1000.0))" for x in steps)
    return f"""
    SELECT sku_code, GREATEST(round(quantity_sold * {factor}), 0) AS quantity_sold,
           round((net_amount * {factor})::numeric, 2) AS net_amount, gsv, region
    FROM unilever_sku_demand_fact WHERE calendar_month = '{BASE_MONTH}' AND is_demo = false AND quantity_sold > 0 ORDER BY sku_code
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", required=True, help="YYYY-MM, after 2026-02")
    ap.add_argument("--out")
    args = ap.parse_args()
    args.out = args.out or str(REPO / "local" / "demo" / f"sales_{args.month}.csv")
    import psycopg2
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")
    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
    cur = conn.cursor()
    cur.execute("SET TRANSACTION READ ONLY")
    cur.execute(sql_for(args.month))
    rows = cur.fetchall()
    conn.rollback()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["sku_code", "calendar_month", "quantity_sold", "net_amount", "gsv", "region"])
        for sku, qty, net, gsv, region in rows:
            w.writerow([sku, args.month, int(qty), net, "" if gsv is None else gsv, region or ""])
    print(f"{len(rows)} generated {args.month} rows written to {out} (GENERATED sales, not SSM's)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
