"""
analytics.etl.extract.sales_register — Sales Register Extract driver.

Selects files whose filename matches the sales_register doc-type pattern
(profiling.profile_files.infer_doc_type) and runs them through the shared
Extract core (_shared.py). Extract never renames columns — the vocab A/B/C
column-name drift documented in ARCHITECTURE.md §6.3 passes through
untouched under each file's own raw column names; reconciling that drift
is Transform's job, not Extract's. Also picks up daily-report files (same
base doc_type, split from the monthly register via _shared.refine_doc_type
into doc_type=daily_sales_report — tagged, not dropped).
"""
from __future__ import annotations

from pathlib import Path

from analytics.etl.extract._shared import REPO_ROOT, ExtractRunResult, parse_doc_type_files

DOC_TYPE = "sales_register"


def parse_sales_register(raw_dir: Path | None = None, repo_root: Path = REPO_ROOT) -> ExtractRunResult:
    return parse_doc_type_files(DOC_TYPE, raw_dir=raw_dir, repo_root=repo_root)
