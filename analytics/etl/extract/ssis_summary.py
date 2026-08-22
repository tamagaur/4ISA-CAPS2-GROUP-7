"""
analytics.etl.extract.ssis_summary — SSIS Sales Summary Extract driver.

T3 (CHECKLIST_BACKEND.md) — Option A: build the ssis_summary Extract driver.

Source: ~60 Unilever SSIS Sales Summary Reports (Excel workbooks).
These are the system-of-record for Unilever's actual sales numbers per
DEC-04 in ARCHITECTURE.md. Each workbook contains ~10 sheets with
distinct roles that infer_sheet_role() already handles:

  RAW DATA            → sheet_role = raw_data   (the fact rows — the SOR)
  Invoice Reg         → sheet_role = invoice_reg (reference / cross-check)
  Per Customer Summary→ sheet_role = per_customer_summary
  Sheet1 / SheetN     → sheet_role = scratch    (leftover tabs — excluded by Transform)

Architecture boundary (DEC-04): only the raw_data sheets are promoted to
the sales_unilever_ssis_summary fact in Transform/Load. The other roles are
staged here for auditability but Transform will demote them.

This module is intentionally thin — all file-reading, header detection,
sheet-role tagging, column coercion, provenance stamping, and checksum
logic lives in _shared.py and is reused here unchanged.

Usage (from repo root):
    python -m analytics.etl.extract.driver   # runs all 7 families
"""
from __future__ import annotations

from pathlib import Path

from analytics.etl.extract._shared import REPO_ROOT, ExtractRunResult, parse_doc_type_files

DOC_TYPE = "ssis_summary"


def parse_ssis_summary(raw_dir: Path | None = None, repo_root: Path = REPO_ROOT) -> ExtractRunResult:
    """Select all SSIS Sales Summary workbooks from raw_dir and run them
    through the shared Extract core.

    File selection uses profiling.profile_files.infer_doc_type(), which
    already has a pattern for 'ssis_summary' (matches filenames containing
    'ssis', case-insensitive). Every sheet in every matched workbook is
    processed; sheet roles are tagged by infer_sheet_role() — no manual
    per-sheet logic needed.
    """
    return parse_doc_type_files(DOC_TYPE, raw_dir=raw_dir, repo_root=repo_root)
