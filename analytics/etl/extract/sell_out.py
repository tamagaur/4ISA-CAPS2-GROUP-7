"""
analytics.etl.extract.sell_out — Sell Out Extract driver.

Category/brand hierarchy (e.g. "/ACE/BASE", "/TETRA/BASE"), 3-row messy
header, 3 columns, negatives present (returns/adjustments) — Extract
stages them as-is; no special-casing needed, negatives are real numeric
values the shared coercion path already preserves. Grain = category.
Principal = delmonte.
"""
from __future__ import annotations

from pathlib import Path

from analytics.etl.extract._shared import REPO_ROOT, ExtractRunResult, parse_doc_type_files

DOC_TYPE = "sell_out"


def parse_sell_out(raw_dir: Path | None = None, repo_root: Path = REPO_ROOT) -> ExtractRunResult:
    return parse_doc_type_files(DOC_TYPE, raw_dir=raw_dir, repo_root=repo_root)
