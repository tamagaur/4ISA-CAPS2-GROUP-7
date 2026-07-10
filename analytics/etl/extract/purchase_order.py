"""
analytics.etl.extract.purchase_order — Purchases / Purchase Order Extract driver.

Invoice-level like Sales Register (header ~row 1, per-region sheets, same
money/code type fidelity rules apply). Grain = invoice.
"""
from __future__ import annotations

from pathlib import Path

from analytics.etl.extract._shared import REPO_ROOT, ExtractRunResult, parse_doc_type_files

DOC_TYPE = "purchase_order"


def parse_purchase_order(raw_dir: Path | None = None, repo_root: Path = REPO_ROOT) -> ExtractRunResult:
    return parse_doc_type_files(DOC_TYPE, raw_dir=raw_dir, repo_root=repo_root)
