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

from analytics.etl._review import render_review
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
]


def main():
    staging_dir = REPO_ROOT / "staging"

    all_outcomes = []
    all_file_rejects = []
    written = 0

    for parse_fn in FAMILY_PARSERS:
        result = parse_fn()
        for df, outcome in result.dfs:
            # outcome.doc_type is the refined tag (may differ from the
            # family's base selection type — e.g. daily_sales_report).
            write_staging_table(df, outcome.doc_type, outcome.src_file, outcome.src_sheet, staging_dir)
            written += 1
        all_outcomes.extend(result.outcomes)
        all_file_rejects.extend(result.file_rejects)

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

    print(f"Staged {written} sheet(s) across {len(FAMILY_PARSERS)} families to {staging_dir}")
    print(f"Manifest written to {manifest_path}")
    print(f"QC report written to {qc_path}")
    print(f"Review viewer written to {review_path}")
    print()
    print(qc_text)


if __name__ == "__main__":
    main()
