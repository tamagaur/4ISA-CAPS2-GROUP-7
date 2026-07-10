"""
analytics.etl.extract.unilever_sku — Unilever La Union per-SKU Extract driver.

Source: UnileverLaUnionSalesperSKU2023to2026.xls — NOT a real .xls; an
MHTML web archive (profiling.reader dispatches on magic bytes, not
extension). Header at row 11 (metadata rows 0-10 above, no comparable
totals row — checksum is always "unverified" for this file, which is
correct, not a defect). ~24.9k rows spanning 2023-01..2026-02 in one
sheet; _shared.row_periods_from_calendar_month tags each row's real
period from its own "Calendar Month" cell rather than one sheet-wide
value. Grain = sku, Principal = unilever. The sole confirmed SKU-level
demand source in the whole corpus (ARCHITECTURE.md §5.1, DEC-03).
"""
from __future__ import annotations

from pathlib import Path

from analytics.etl.extract._shared import REPO_ROOT, ExtractRunResult, parse_doc_type_files

DOC_TYPE = "unilever_sku"


def parse_unilever_sku(raw_dir: Path | None = None, repo_root: Path = REPO_ROOT) -> ExtractRunResult:
    return parse_doc_type_files(DOC_TYPE, raw_dir=raw_dir, repo_root=repo_root)
