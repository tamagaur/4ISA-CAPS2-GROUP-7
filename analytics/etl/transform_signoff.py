"""
analytics.etl.transform_signoff — M2 sign-off checklist (ARCHITECTURE.md
§7 "Transform QC gate (must pass before Load)").

Builds a human-readable checklist from transform/_manifest.json (written
by transform_driver.py), and records an EXPLICIT decision by a named
person — nothing is auto-approved. `load.py::check_signoff_gate()` blocks
Load unless a matching, approved sign-off exists for the CURRENT manifest
(via a fingerprint - a stale sign-off from a prior run doesn't count).

The checklist can't require every item to be "green": transform_driver.py's
`blocked` status legitimately includes an expected, permanent gap
(ssis_summary's natural_key: null). The point of a human sign-off is to
let a person see the full picture — including known, accepted gaps — and
decide; the code only enforces that a decision was actually recorded, not
that every item passed automatically.

Usage:
  python -m analytics.etl.transform_signoff
      Prints the checklist only - a preview. Nothing is written.
  python -m analytics.etl.transform_signoff --decision approved --by "Jane Dela Cruz" [--notes "..."]
      Prints the checklist AND writes transform/_signoff.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from analytics.etl.transform import REPO_ROOT

DECISIONS = ("approved", "rejected")


def compute_manifest_fingerprint(manifest: dict) -> str:
    """Stable fingerprint tying a sign-off to one specific manifest's
    contents - if Transform is re-run and the manifest changes, an old
    sign-off's fingerprint no longer matches (see check_signoff_gate() in
    load.py), so a stale approval is never silently accepted for
    different results."""
    canonical = json.dumps(manifest, sort_keys=True, ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_checklist(transform_manifest: dict, extract_manifest: dict | None = None) -> dict:
    """Pure function (no I/O) - computes every checklist item from the
    already-loaded manifest dict(s). See ARCHITECTURE.md §7's "Transform
    QC gate" bullet for the criteria this derives from."""
    staged = transform_manifest.get("staged", [])
    reject = transform_manifest.get("reject", [])
    all_records = staged + reject

    counts: dict[str, int] = {"promoted": 0, "demoted": 0, "conflict": 0, "blocked": 0}
    for r in all_records:
        status = r.get("checksum_status")
        counts[status] = counts.get(status, 0) + 1

    zero_silent_skips = all(
        r.get("checksum_status") in counts and r.get("src_file") is not None and r.get("src_sheet") is not None
        for r in all_records
    )

    row_reconciliation = None
    if extract_manifest is not None:
        extract_total_rows = sum(r.get("row_count", 0) for r in extract_manifest.get("staged", []))
        transform_total_rows = sum(r.get("row_count", 0) for r in all_records)
        row_reconciliation = {
            "extract_total_rows": extract_total_rows,
            "transform_total_rows": transform_total_rows,
            "matches": extract_total_rows == transform_total_rows,
        }

    def _summarize(records: list[dict]) -> list[dict]:
        return [
            {"src_file": r.get("src_file"), "src_sheet": r.get("src_sheet"), "doc_type": r.get("doc_type"), "reason": r.get("reason")}
            for r in records
        ]

    conflicts = [r for r in reject if r.get("checksum_status") == "conflict"]
    blocked = [r for r in reject if r.get("checksum_status") == "blocked"]
    blocked_expected = [r for r in blocked if "natural_key unconfirmed" in (r.get("reason") or "")]
    blocked_unexpected = [r for r in blocked if "natural_key unconfirmed" not in (r.get("reason") or "")]

    # DEC-13: zero/negative/outlier quantities, never dropped, always
    # surfaced here for review — transform_driver.py's top-level
    # "quantity_issues" section, keyed "fact/principal" -> list of
    # flag_quantity_issues() reports (one per quantity column for that fact).
    quantity_issues = transform_manifest.get("quantity_issues", {})
    quantity_flag_total = sum(
        r["zero_count"] + r["negative_count"] + r["outlier_count"]
        for reports in quantity_issues.values() for r in reports
    )

    return {
        "counts": counts,
        "zero_silent_skips": zero_silent_skips,
        "row_reconciliation": row_reconciliation,
        "conflicts": _summarize(conflicts),
        "blocked_expected": _summarize(blocked_expected),
        "blocked_unexpected": _summarize(blocked_unexpected),
        "quantity_issues": quantity_issues,
        "quantity_flag_total": quantity_flag_total,
    }


def format_checklist_text(checklist: dict) -> str:
    c = checklist["counts"]
    lines = [
        "=== Transform (M2) sign-off checklist ===",
        "",
        f"promoted={c.get('promoted', 0)} demoted={c.get('demoted', 0)} "
        f"conflict={c.get('conflict', 0)} blocked={c.get('blocked', 0)}",
        f"Zero silent skips: {'PASS' if checklist['zero_silent_skips'] else 'FAIL'}",
    ]

    rr = checklist["row_reconciliation"]
    if rr is None:
        lines.append("Row-count reconciliation vs Extract: SKIPPED (no staging/_manifest.json available)")
    else:
        status = "PASS" if rr["matches"] else "MISMATCH"
        lines.append(
            f"Row-count reconciliation vs Extract: {status} "
            f"(extract={rr['extract_total_rows']}, transform={rr['transform_total_rows']})"
        )

    def _section(title: str, items: list[dict]):
        lines.append("")
        lines.append(f"{title} ({len(items)}):")
        if not items:
            lines.append("  (none)")
        for item in items:
            lines.append(f"  - {item['src_file']} / {item['src_sheet']} ({item['doc_type']}): {item['reason']}")

    _section("Conflicts needing review", checklist["conflicts"])
    _section("Blocked - EXPECTED, known gap", checklist["blocked_expected"])
    _section("Blocked - UNEXPECTED, needs investigation", checklist["blocked_unexpected"])

    lines.append("")
    lines.append(f"Quantity issues flagged, never dropped (total: {checklist['quantity_flag_total']}):")
    if not checklist["quantity_issues"]:
        lines.append("  (none)")
    for fact_principal, reports in checklist["quantity_issues"].items():
        for r in reports:
            lines.append(
                f"  - {fact_principal} / {r['column']}: zero={r['zero_count']} "
                f"negative={r['negative_count']} outlier={r['outlier_count']} "
                f"(of {r['total_rows']} rows)"
            )

    lines.append("")
    lines.append(
        "Reminder: confirm this was a deterministic re-run (same staging/ input "
        "-> same transform/ output) if reproducibility matters for this cycle - "
        "not machine-checkable from a single manifest."
    )
    return "\n".join(lines)


def record_signoff(
    transform_dir: Path, decision: str, decided_by: str,
    notes: str | None = None, staging_dir: Path | None = None,
) -> Path:
    """Writes transform_dir/_signoff.json — the ONLY way a sign-off record
    comes into existence (no default/auto-approve path). Requires a real
    decision and a named person; raises otherwise rather than recording an
    ambiguous or anonymous "decision"."""
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {DECISIONS}, got {decision!r}")
    if not decided_by or not decided_by.strip():
        raise ValueError("decided_by is required - an explicit sign-off must name a person")

    manifest = json.loads((transform_dir / "_manifest.json").read_text(encoding="utf-8"))
    extract_manifest = None
    if staging_dir is not None:
        extract_manifest_path = staging_dir / "_manifest.json"
        if extract_manifest_path.exists():
            extract_manifest = json.loads(extract_manifest_path.read_text(encoding="utf-8"))

    checklist = build_checklist(manifest, extract_manifest)
    record = {
        "decision": decision,
        "decided_by": decided_by,
        "decided_at": datetime.now(timezone.utc).isoformat(),
        "notes": notes,
        "manifest_fingerprint": compute_manifest_fingerprint(manifest),
        "checklist": checklist,
    }
    out_path = transform_dir / "_signoff.json"
    out_path.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Transform (M2) sign-off checklist")
    parser.add_argument("--decision", choices=list(DECISIONS), default=None)
    parser.add_argument("--by", default=None, help="name of the person making the decision")
    parser.add_argument("--notes", default=None)
    args = parser.parse_args()

    transform_dir = REPO_ROOT / "transform"
    staging_dir = REPO_ROOT / "staging"

    manifest = json.loads((transform_dir / "_manifest.json").read_text(encoding="utf-8"))
    extract_manifest = None
    extract_manifest_path = staging_dir / "_manifest.json"
    if extract_manifest_path.exists():
        extract_manifest = json.loads(extract_manifest_path.read_text(encoding="utf-8"))

    checklist = build_checklist(manifest, extract_manifest)
    print(format_checklist_text(checklist))

    if args.decision is None or args.by is None:
        print("\n(No --decision/--by given - this was a preview only. Nothing was recorded.)")
        return

    out_path = record_signoff(transform_dir, args.decision, args.by, args.notes, staging_dir)
    print(f"\nSign-off recorded: {out_path} (decision={args.decision}, by={args.by})")


if __name__ == "__main__":
    main()
