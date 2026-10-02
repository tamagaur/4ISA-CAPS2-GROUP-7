"""tests/etl/test_layout_regression.py - content identification over EVERY real
raw file must reproduce today's file-name assignment (2026-09-30, layout guard).

For each file under data/raw (Synthetic Data excluded) identified by content
(analytics.etl.extract.layout.identify, header rows only):
  - family == profiling.profile_files.infer_doc_type(file name)
  - month  == profiling.profile_files.infer_period(path)
  - the file is accepted (a refusal of a real file is a difference too)
  - every verified sheet's header row == profiling.detect.detect_header's row
  - no verified sheet has a header the column map neither maps nor ignores
Any difference fails. Reads every file's header rows: ~1 minute. Skipped where
data/raw holds no client files (they are gitignored; only .gitkeep is tracked).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from analytics.etl.extract import layout as L
from analytics.etl.extract._shared import REPO_ROOT, select_source_files
from profiling.detect import detect_header, trim_grid
from profiling.profile_files import infer_doc_type, infer_period
from profiling.reader import read_workbook

RAW = REPO_ROOT / "data" / "raw"
# data/raw exists in every checkout (git tracks its .gitkeep), so skip on the client
# files themselves, not the folder. Checked off disk, not via select_source_files, so a
# selector that finds nothing while client files are present still fails `assert files`.
_CLIENT_FILES = RAW.is_dir() and any(
    f.is_file() and f.name != ".gitkeep" and RAW / "Synthetic Data" not in f.parents
    for f in RAW.rglob("*")
)
pytestmark = pytest.mark.skipif(
    not _CLIENT_FILES, reason="data/raw client files (gitignored) not present"
)


def _real_files() -> list[Path]:
    return [f for f in select_source_files(RAW) if RAW / "Synthetic Data" not in f.parents]


def test_content_identification_reproduces_todays_family_and_month_for_every_file():
    files = _real_files()
    assert files
    family_month, refused, header_rows, unknown_headers = [], [], [], []
    for f in files:
        wb = read_workbook(f, max_rows=L.HEAD_ROWS)
        fl = L.identify(f, wb.sheets, wb.real_format)
        rel = f.relative_to(RAW).as_posix()
        if (fl.family, fl.month) != (infer_doc_type(f), infer_period(f)):
            family_month.append((rel, (infer_doc_type(f), infer_period(f)), (fl.family, fl.month)))
        if not fl.ok:
            refused.append((rel, fl.reason, fl.problem))
        for s in wb.sheets:
            if s.name in fl.sheets:
                today = detect_header(trim_grid(s.rows)).header_row_index
                if today != fl.sheets[s.name].header_row:
                    header_rows.append((rel, s.name, today, fl.sheets[s.name].header_row))
        if fl.unmapped:
            unknown_headers.append((rel, fl.unmapped))
    print(f"\n{len(files)} real files identified by content")
    assert family_month == [], family_month
    assert refused == [], refused
    assert header_rows == [], header_rows
    assert unknown_headers == [], unknown_headers
