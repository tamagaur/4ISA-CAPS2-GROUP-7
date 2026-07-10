"""Extract QC report generator (ARCHITECTURE.md §6.6).

Per SSM_EXTRACT_FIX_AND_REVIEW_PROMPT.md: checksum status is informational
(pass/mismatch/unverified against the totals row), never a staging gate —
a mismatch is a flagged warning, not a reason to drop rows.

Per SSM_EXTRACT_CHECKSUM_REFINE_PROMPT.md Part B: generated purely from the
outcomes/rejects the driver already computed (nothing invented), a plain
diff-able markdown companion to staging/_review.html.

Deliberately produces no wall-clock timestamps or other non-deterministic
content — a second run must be byte-identical.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from analytics.etl.extract._shared import CANONICAL_CHECKSUM_COLUMN, RejectRecord, SheetOutcome


def generate_qc_report(
    label: str,
    outcomes: list[SheetOutcome],
    file_rejects: list[RejectRecord],
) -> str:
    staged = [o for o in outcomes if o.status == "staged"]
    rejected = [o for o in outcomes if o.status == "rejected"]

    lines = [f"# Extract QC Report — {label}", ""]

    lines += ["## Sheet accountability", ""]
    lines += [f"- Sheets scanned: {len(outcomes)}"]
    lines += [f"- Staged: {len(staged)}"]
    lines += [f"- Rejected (unreadable / no header / no data / magnolia): {len(rejected)}"]
    lines += [f"- Zero unaccounted: {len(staged) + len(rejected) == len(outcomes)}", ""]

    lines += ["## Checksum status (informational — never a staging gate)", ""]
    counts = {"pass": 0, "mismatch": 0, "unverified": 0}
    for o in staged:
        counts[o.checksum_status or "unverified"] += 1
    lines += [
        f"- Pass: {counts['pass']}",
        f"- Mismatch (staged anyway, flagged): {counts['mismatch']}",
        f"- Unverified (no comparable totals row, or not applicable to this doc_type): {counts['unverified']}",
        "",
    ]

    # outcome.doc_type is the refined tag (e.g. daily_sales_report split
    # out from sales_register), not just the family driver's base
    # selection type.
    by_doc_type: dict[str, list[SheetOutcome]] = defaultdict(list)
    for o in outcomes:
        by_doc_type[o.doc_type or "unknown"].append(o)

    if len(by_doc_type) > 1:
        lines += ["## Per doc_type breakdown", "",
                   "| doc_type | files | sheets | staged | rejected | rows | pass | mismatch | unverified |",
                   "|---|---|---|---|---|---|---|---|---|"]
        for dt in sorted(by_doc_type):
            fam = by_doc_type[dt]
            fam_staged = [o for o in fam if o.status == "staged"]
            fam_rejected = [o for o in fam if o.status == "rejected"]
            fam_files = len(set(o.src_file for o in fam))
            fam_rows = sum(o.row_count for o in fam_staged)
            fam_counts = {"pass": 0, "mismatch": 0, "unverified": 0}
            for o in fam_staged:
                fam_counts[o.checksum_status or "unverified"] += 1
            lines.append(
                f"| {dt} | {fam_files} | {len(fam)} | {len(fam_staged)} | {len(fam_rejected)} | {fam_rows} | "
                f"{fam_counts['pass']} | {fam_counts['mismatch']} | {fam_counts['unverified']} |"
            )
        lines.append("")

    mismatches = [o for o in staged if o.checksum_status == "mismatch"]
    lines += ["## Mismatch list — staged, needs a human look", ""]
    if mismatches:
        lines += ["| doc_type | file | sheet | column | expected | got | diff |",
                   "|---|---|---|---|---|---|---|"]
        for o in sorted(mismatches, key=lambda o: (o.doc_type or "", o.src_file, o.src_sheet)):
            lines.append(
                f"| {o.doc_type} | {o.src_file} | {o.src_sheet} | {o.checksum_column} | "
                f"{o.checksum_expected:.2f} | {o.checksum_got:.2f} | {o.checksum_diff:.2f} |"
            )
        lines.append("")
    else:
        lines += ["- None.", ""]

    unverified = [o for o in staged if (o.checksum_status or "unverified") == "unverified"]
    if unverified:
        lines += ["## Unverified breakdown by doc_type", "", "| doc_type | count | reason |", "|---|---|---|"]
        for dt in sorted(by_doc_type):
            dt_unverified = [o for o in unverified if o.doc_type == dt]
            if not dt_unverified:
                continue
            if dt not in CANONICAL_CHECKSUM_COLUMN:
                reason = "not applicable — no doc_type with a demonstrated reliable checksum column"
            else:
                col = CANONICAL_CHECKSUM_COLUMN[dt]
                no_col = sum(1 for o in dt_unverified if o.checksum_column is None)
                lines.append(f"| {dt} | {len(dt_unverified)} | no comparable totals row for \"{col}\" "
                              f"in this sheet ({no_col} had no totals row at all) |")
                continue
            lines.append(f"| {dt} | {len(dt_unverified)} | {reason} |")
        lines.append("")

    lines += ["## Reject summary", ""]
    if rejected or file_rejects:
        lines += ["| file | sheet | reason |", "|---|---|---|"]
        for r in file_rejects:
            lines.append(f"| {r.src_file} | (whole file) | {r.reason}: {r.evidence} |")
        for o in rejected:
            lines.append(f"| {o.src_file} | {o.src_sheet} | {o.reason} |")
        lines.append("")
    else:
        lines += ["- No rejects.", ""]

    lines += [
        "## Determinism",
        "",
        "This report, staging/_manifest.json, and all staged parquet tables "
        "are produced from pure, sorted-order functions over the raw file "
        "grids — no wall-clock, random, or environment-dependent content. "
        "Re-running the driver against the same `data/raw/` produces "
        "byte-identical `staging/` output (confirmed by diffing two full runs).",
        "",
    ]

    return "\n".join(lines)


def save_qc_report(text: str, staging_dir: Path) -> Path:
    out_path = staging_dir / "_extract_qc.md"
    out_path.write_text(text, encoding="utf-8")
    return out_path
