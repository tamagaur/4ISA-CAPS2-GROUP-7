"""Profile a single raw file in an isolated process.

Invoked as a subprocess by profile_files.py so that whatever causes
openpyxl's read-only iteration to degrade on some files after many prior
files have been processed in the same interpreter (observed but not
root-caused: a fresh process on the same file is fast; the same file
partway through a long-running single-process loop can degrade sharply)
cannot compound across the run, and a hard per-file wall-clock timeout
can kill a truly pathological file cleanly.

Usage: python profiling/profile_one_file.py <raw_file_path> <output_json_path>
Writes a single JSON document to output_json_path:
  {"inventory": {...}, "sheets": [ {...profile...}, ... ]}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from reader import read_workbook  # noqa: E402
import profile_files as pf  # noqa: E402


def main():
    raw_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2])

    rel = (pf.LOGICAL_RAW_DIR / raw_path.relative_to(pf.RAW_DIR)).relative_to(pf.REPO_ROOT).as_posix()
    size_kb = round(raw_path.stat().st_size / 1024, 1)

    if raw_path.name.startswith("~$"):
        result = {
            "inventory": {
                "path": rel, "real_format": "lock-file", "size_kb": size_kb,
                "sheet_count": 0, "principal": "n/a", "regions": "", "period": "",
                "doc_type": "excel_lock_file", "duplicate_group": "", "magnolia_flag": False,
                "read_error": "",
            },
            "sheets": [],
        }
        out_path.write_text(json.dumps(result, default=str, ensure_ascii=False), encoding="utf-8")
        return

    wb = read_workbook(raw_path)
    period = pf.infer_period(raw_path) or ""
    regions = pf.infer_regions(raw_path)
    path_principal = pf.infer_principal_from_path(raw_path)
    doc_type = pf.infer_doc_type(raw_path)
    magnolia_path_flag = "magnolia" in str(raw_path).lower()

    if wb.error and not wb.sheets:
        result = {
            "inventory": {
                "path": rel, "real_format": wb.real_format, "size_kb": size_kb,
                "sheet_count": 0, "principal": path_principal, "regions": ";".join(regions),
                "period": period, "doc_type": doc_type, "duplicate_group": "",
                "magnolia_flag": magnolia_path_flag, "read_error": wb.error,
            },
            "sheets": [],
        }
        out_path.write_text(json.dumps(result, default=str, ensure_ascii=False), encoding="utf-8")
        return

    sheet_profiles = []
    sheet_principals = []
    magnolia_content_flag = False
    for sheet in wb.sheets:
        prof = pf.profile_sheet(rel, sheet.name, sheet.rows, wb.real_format, getattr(sheet, "truncated", False))
        sheet_profiles.append(prof)
        sheet_principals.append(prof["principal_guess"])
        magnolia_content_flag = magnolia_content_flag or prof["magnolia_flag"]

    content_principals = set(p for p in sheet_principals if p != "ambiguous")
    if path_principal != "ambiguous":
        resolved_principal = path_principal
    elif len(content_principals) == 1:
        resolved_principal = content_principals.pop()
    elif len(content_principals) > 1:
        resolved_principal = "ambiguous"
    else:
        resolved_principal = "ambiguous"

    result = {
        "inventory": {
            "path": rel, "real_format": wb.real_format, "size_kb": size_kb,
            "sheet_count": len(wb.sheets), "principal": resolved_principal,
            "regions": ";".join(regions), "period": period, "doc_type": doc_type,
            "duplicate_group": "",  # filled in by the orchestrator (needs full-corpus view)
            "magnolia_flag": magnolia_path_flag or magnolia_content_flag,
            "read_error": wb.error or "",
        },
        "sheets": sheet_profiles,
    }
    out_path.write_text(json.dumps(result, default=str, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
