"""
scripts/batch_status.py - where the monthly batch stands, as one line of JSON (2026-11-02). Read-only.

    python -m scripts.batch_status [--month YYYY-MM]

Without --month it works out the month in play (run_month.pick_month). backend/routers/monthly_batch.py reads this from a
child process, so the facts have one source: the same queries run_month prints from.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.close_cycle import PRINCIPAL, cycle_params, parse_cycle  # noqa: E402
from scripts.report_target import is_live_target  # noqa: E402
from scripts import run_month as rm  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--month", type=parse_cycle)
    args = ap.parse_args()
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")
    if not os.environ.get("SUPABASE_DB_URL"):
        sys.exit("SUPABASE_DB_URL is not set")
    month = args.month or rm.current_month()
    params = cycle_params(month, PRINCIPAL)
    status = rm._status(params)
    facts = rm._facts(params)
    row = status["cycle_row"]
    print(json.dumps({
        "month": f"{month:%Y-%m}", "next_month": f"{params['next_cycle']:%Y-%m}", "live": is_live_target(),
        "checks": status["checks"], "cycle_state": row["state"] if row else "open",
        "latest_sales_month": facts["latest_sales_month"], "synthetic_rows": facts["synthetic_rows"],
        "plan": rm._plan(params, params["cycle"]), "next_plan": rm._plan(params, params["next_cycle"]),
        "count_lines": [line.strip() for line in rm.count_lines(rm._counts(params))],
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
