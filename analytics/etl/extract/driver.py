"""
analytics.etl.extract.driver — Extract CLI entrypoint, all 7 doc families.

Runs every family's shared-core driver end-to-end: reads data/raw/, writes
typed staging tables (one folder per *refined* doc_type — e.g.
daily_sales_report lands separately from sales_register even though both
share Sales Register's file-selection pattern) + rejects + a combined
manifest + a review HTML viewer, prints and saves the QC report, then
stops (no Transform/Load).

T3 (CHECKLIST_BACKEND.md) — ssis_summary added as the 7th family (Option A).
DEC-04: only raw_data sheets from ssis_summary are promoted to the
sales_unilever_ssis_summary fact in Transform/Load; other sheet roles
are staged here for auditability.

Usage: python -m analytics.etl.extract.driver
"""
from __future__ import annotations

import sys
import time

from analytics.etl._review import render_review
from analytics.etl._timeline import render_timeline
from analytics.etl.events import EventLog
from analytics.etl.extract._qc import generate_qc_report, save_qc_report
from analytics.etl.extract._shared import (
    REPO_ROOT,
    build_manifest,
    save_manifest,
    write_reject,
    write_staging_table,
)
from analytics.etl.extract.bo_rmr_gs import parse_bo_rmr_gs
from analytics.etl.extract.inventory_signoff import parse_inventory_signoff
from analytics.etl.extract.purchase_order import parse_purchase_order
from analytics.etl.extract.sales_register import parse_sales_register
from analytics.etl.extract.sales_return import parse_sales_return
from analytics.etl.extract.sell_out import parse_sell_out
from analytics.etl.extract.ssis_summary import parse_ssis_summary
from analytics.etl.extract.unilever_sku import parse_unilever_sku

FAMILY_PARSERS = [
    parse_sales_register,
    parse_unilever_sku,
    parse_inventory_signoff,
    parse_sell_out,
    parse_purchase_order,
    parse_bo_rmr_gs,
    parse_ssis_summary,       # T3 Option A — 7th family (SSIS Sales Summary)
    parse_sales_return,       # 2026-08 — 8th family, real data existed, no driver ever attempted it
]


def main():
    staging_dir = REPO_ROOT / "staging"

    # Opt-in event log (DSD_EVENTS=1) for the live/replay timeline viewer.
    # EventLog.emit() is a true no-op when unset - see analytics/etl/events.py.
    # Phase A instrumentation only: family-level events here in the driver.
    # File/sheet-level events are emitted one layer down, inside
    # extract/_shared.py's own per-file/per-sheet loops (Phase B) - not yet
    # wired in, so live mode currently only reflects family boundaries.
    events = EventLog(staging_dir / "_events.jsonl", stage="extract")
    run_t0 = time.perf_counter()
    events.emit({"event": "run_start", "message": f"{len(FAMILY_PARSERS)} families"})

    try:
        all_outcomes = []
        all_file_rejects = []
        written = 0

        for parse_fn in FAMILY_PARSERS:
            family_t0 = time.perf_counter()
            events.emit({"event": "family_start", "message": parse_fn.__name__})

            result = parse_fn()
            for df, outcome in result.dfs:
                # outcome.doc_type is the refined tag (may differ from the
                # family's base selection type — e.g. daily_sales_report).
                write_staging_table(df, outcome.doc_type, outcome.src_file, outcome.src_sheet, staging_dir)
                written += 1
            all_outcomes.extend(result.outcomes)
            all_file_rejects.extend(result.file_rejects)

            family_rows_in = sum(o.row_count for o in result.outcomes)
            family_rows_out = sum(o.row_count for o in result.outcomes if o.status == "staged")
            family_rejects = sum(1 for o in result.outcomes if o.status == "rejected") + len(result.file_rejects)
            events.emit({
                "event": "family_done", "message": parse_fn.__name__,
                "status": "ok" if family_rejects == 0 else "partial",
                "rows_in": family_rows_in, "rows_out": family_rows_out,
                "reject_count": family_rejects,
                "duration_ms": (time.perf_counter() - family_t0) * 1000,
            })

        # staging/_rejects/ is reserved for unreadable files and sheets with no
        # detectable header/data or Magnolia content — never a checksum
        # mismatch (that's staged with its status recorded instead).
        rejects_dir = staging_dir / "_rejects"
        for r in all_file_rejects:
            write_reject(rejects_dir, r.src_file, r.src_sheet, r.reason, r.evidence)
        for o in all_outcomes:
            if o.status == "rejected":
                write_reject(rejects_dir, o.src_file, o.src_sheet, o.reason or "rejected", o.reason or "")

        manifest = build_manifest(all_outcomes, all_file_rejects)
        manifest_path = save_manifest(manifest, staging_dir)

        qc_text = generate_qc_report("all 7 families", all_outcomes, all_file_rejects)
        qc_path = save_qc_report(qc_text, staging_dir)

        review_path = render_review("staging", repo_root=REPO_ROOT)
        # Only written when events are actually on - otherwise staging/'s
        # directory listing stays identical to a run with no instrumentation.
        timeline_path = render_timeline("staging", repo_root=REPO_ROOT) if events.enabled else None
    finally:
        # No `except` here on purpose: sys.exc_info() reports an in-flight
        # exception without intercepting it, so whatever happened above
        # (success or a crash) propagates completely unchanged afterward -
        # same type, same traceback, same exit code as if this try/finally
        # didn't exist. This only guarantees run_end is always emitted.
        exc_type, exc_val, _ = sys.exc_info()
        events.emit({
            "event": "run_end",
            "status": "error" if exc_type is not None else "ok",
            "message": str(exc_val) if exc_val else None,
            "duration_ms": (time.perf_counter() - run_t0) * 1000,
        })

    print(f"Staged {written} sheet(s) across {len(FAMILY_PARSERS)} families to {staging_dir}")
    print(f"Manifest written to {manifest_path}")
    print(f"QC report written to {qc_path}")
    print(f"Review viewer written to {review_path}")
    if timeline_path:
        print(f"Timeline viewer written to {timeline_path}")
    print()
    print(qc_text)


if __name__ == "__main__":
    main()
