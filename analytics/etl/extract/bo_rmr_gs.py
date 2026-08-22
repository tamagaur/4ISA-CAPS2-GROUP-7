"""
analytics.etl.extract.bo_rmr_gs — RMR GS/BO Extract driver.

6 sheets per file: PANG/ILOCOS ONE PAGER, GS, BO. ONE PAGER = GS ∪ BO — a
dedup trap. Extract stages all three; _shared.SHEET_ROLE_PATTERNS tags
sheet_role distinctly (one_pager / gs / bo) so Transform can apply DEC-04
(pick the GS+BO split as system-of-record, demote ONE PAGER to a
cross-check) instead of double-counting. Return Type column values are
GS/BO. Grain = invoice (returns). Same invoice-level column vocabulary as
Sales Register (Del Monte variant).

Note: these sheets triggered a real fix to profiling.detect.trim_grid — a
title banner repeated every 8th column out to ~col 490 (a print-layout
artifact, present only in the title row) was defeating the old
any-non-blank trailing-column trim and making that banner's raw cell count
outscore the real 11-column header in detect_header. Fixed generically
(gap-aware trimming), not with per-file logic.
"""
from __future__ import annotations

from pathlib import Path

from analytics.etl.extract._shared import REPO_ROOT, ExtractRunResult, parse_doc_type_files

DOC_TYPE = "rmr_gs_bo"


def parse_bo_rmr_gs(raw_dir: Path | None = None, repo_root: Path = REPO_ROOT) -> ExtractRunResult:
    return parse_doc_type_files(DOC_TYPE, raw_dir=raw_dir, repo_root=repo_root)
