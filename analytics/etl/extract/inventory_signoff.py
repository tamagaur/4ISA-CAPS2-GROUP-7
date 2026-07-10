"""
analytics.etl.extract.inventory_signoff — Inventory Sign-Off Extract driver.

SKU code embedded in col 0 (e.g. "9DBL58403 DM ..."), header on row 2
(title row 0, date in last col). TEXT_OVERRIDE covers the named identifier
columns (Branch Code, REFNBR, etc.); the SKU code itself lands in an
unlabeled/varying column depending on file layout — Extract preserves
whatever raw text the source gives it (no renaming), so no additional
fabrication risk there. Grain = sku (snapshot, not demand history).
"""
from __future__ import annotations

from pathlib import Path

from analytics.etl.extract._shared import REPO_ROOT, ExtractRunResult, parse_doc_type_files

DOC_TYPE = "inventory_sign_off"


def parse_inventory_signoff(raw_dir: Path | None = None, repo_root: Path = REPO_ROOT) -> ExtractRunResult:
    return parse_doc_type_files(DOC_TYPE, raw_dir=raw_dir, repo_root=repo_root)
