"""
scripts/batch_status.py - where the monthly batch stands, as one line of JSON (2026-11-02). Read-only.

    python -m scripts.batch_status [--month YYYY-MM] [--slice SPEC ...] [--run-key KEY]

Without --month it works out the month in play (run_month.pick_month). backend/routers/monthly_batch.py reads this from a
child process, so the facts have one source: the same queries run_month prints from. --slice says what a run would load, so
`preflight` is exactly what run_month would refuse. --run-key names a checked file's manifest, so `signoff` can say whether a
person has approved it. Where the pages have their own database (BATCH_PAGES_DB_URL, the local practice setup), `replay` compares
the two without changing either.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.close_cycle import PRINCIPAL, cycle_params, missing_checks, parse_cycle  # noqa: E402
from scripts.report_target import is_live_target  # noqa: E402
from scripts import run_month as rm  # noqa: E402


def signoff_state(run_key: str | None) -> dict | None:
    """Whether a person has approved this exact manifest: the loader's own gate answers, so an approval of a changed file does not count."""
    if not run_key:
        return None
    from scripts.load_slices import SLICE_TRANSFORM, unsigned_reason
    folder = SLICE_TRANSFORM / run_key
    if not (folder / "_manifest.json").exists():
        return {"signed": False, "reason": "no file check on record for this file"}
    why = unsigned_reason(folder)
    if why:
        return {"signed": False, "reason": why}
    record = json.loads((folder / "_signoff.json").read_text(encoding="utf-8"))
    return {"signed": True, "reason": None, "by": record.get("decided_by"), "at": record.get("decided_at")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--month", type=parse_cycle)
    ap.add_argument("--slice", action="append", default=[], metavar="SPEC", help="what a run would load")
    ap.add_argument("--run-key", help="a checked file's manifest (transform/slices/<run key>)")
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
    live = is_live_target()
    from scripts.replay_practice_decisions import preview_if_separate
    print(json.dumps({
        "month": f"{month:%Y-%m}", "next_month": f"{params['next_cycle']:%Y-%m}", "live": live,
        "checks": status["checks"], "cycle_state": row["state"] if row else "open",
        "latest_sales_month": facts["latest_sales_month"], "synthetic_rows": facts["synthetic_rows"], "generated_rows": facts["generated_rows"],
        "plan": rm._plan(params, params["cycle"]), "next_plan": rm._plan(params, params["next_cycle"]),
        "count_lines": [line.strip() for line in rm.count_lines(rm._counts(params))],
        "decisions": facts["decisions"],
        "preflight": [{"code": code, "message": sentence} for code, sentence in rm.preflight_items(month, facts, status["checks"], args.slice, live)],
        "close_missing": missing_checks(status, params),
        "signoff": signoff_state(args.run_key),
        "replay": preview_if_separate(month),
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
