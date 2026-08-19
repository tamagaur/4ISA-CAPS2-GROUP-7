"""
analytics.etl.extract.sales_return — Sales Return Extract driver.

Selects files whose filename matches the sales_return doc-type pattern
(profiling.profile_files.infer_doc_type - already existed and already
classifies these 19 real files correctly; the gap was never detection,
just that nothing called it). Runs them through the shared Extract core
(_shared.py). Three real shapes across 2023-2025 (single sheet/region
through Dec 2023, Branch Code/Town Display added from Jan 2024, GS/BO
sheet split + Return Type added from the 2025 reports) - _shared.py's
generic header/region/sheet-role inference already handles all three
with no shape-specific code here, same as sell_out.py/inventory_signoff.py
handle their own era drift.

KNOWN_DUPLICATES: "...APRIL 1-APRIL 30 2023 SALE RETURN (1).xlsx" is a
confirmed byte-identical copy of the unsuffixed original (every sheet,
every row, checked directly) - excluded at file selection so it isn't
staged twice, not left for QC/dedup to catch. 18 distinct real months
across 18 files feed this driver, not 19.
"""
from __future__ import annotations

from pathlib import Path

from analytics.etl.extract._shared import REPO_ROOT, ExtractRunResult, parse_doc_type_files

DOC_TYPE = "sales_return"

KNOWN_DUPLICATES = frozenset({
    "PANGASINAN&ILOCOS APRIL 1-APRIL 30 2023 SALE RETURN (1).xlsx",
})


def parse_sales_return(raw_dir: Path | None = None, repo_root: Path = REPO_ROOT) -> ExtractRunResult:
    return parse_doc_type_files(DOC_TYPE, raw_dir=raw_dir, repo_root=repo_root, exclude_files=KNOWN_DUPLICATES)
