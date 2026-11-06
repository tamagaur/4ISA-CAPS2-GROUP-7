"""An SSIS --file under --all-slices reaches extract_soh, as it does under --slice. It used to be accepted and ignored."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from scripts import load_slices as ls


def test_an_ssis_file_reaches_the_extract_and_with_none_nothing_changes(monkeypatch, tmp_path):
    workbook = tmp_path / "SSIS MARCH 2026.xlsx"
    layouts = {workbook: SimpleNamespace(ok=True, family=ls.SOH_FILE_FAMILY, hint=None, month="2026-03")}
    monkeypatch.setattr(ls, "layout_of", lambda f: layouts[f])
    monkeypatch.setattr(ls, "discover", dict)
    monkeypatch.setattr(ls, "family_files", lambda fam: [])
    monkeypatch.setattr(ls, "rmr_allowed_periods", set)
    seen = []

    def stage(ctx, slices, files_by_family, soh_months, all_slices, soh_given=()):
        seen.append((soh_months, all_slices, list(soh_given)))
        return "stop here", [], frozenset()

    monkeypatch.setattr(ls, "_stage_and_sign", stage)
    ctx = SimpleNamespace(staging=Path("x"), dry_run=False)
    assert ls.run_full(ctx, [workbook]) == 1
    assert ls.run_full(ctx, []) == 1
    assert seen == [(None, True, [workbook]), (None, True, [])]
