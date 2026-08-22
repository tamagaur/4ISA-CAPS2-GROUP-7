"""
tests/etl/test_transform_driver.py — Tests for analytics.etl.transform_driver.

Builds tiny synthetic staged parquet fixtures under tmp_path (matching
extract/_shared.py::write_staging_table's real staging/<doc_type>/*.parquet
layout) since no real data exists in this environment - see
ARCHITECTURE.md §7 gap 5.

  test_build_transform_manifest_classifies_promoted_demoted_conflict_blocked
  test_zero_silent_skips_every_sheet_is_accounted_for
  test_render_review_renders_transform_manifest_without_error
"""
from pathlib import Path

import pandas as pd
import pytest

from analytics.etl._review import render_review
from analytics.etl.transform_driver import build_transform_manifest


def _write_sheet(staging_dir: Path, doc_type: str, file_stem: str, sheet_stem: str, rows: dict):
    out_dir = staging_dir / doc_type
    out_dir.mkdir(parents=True, exist_ok=True)
    n = len(next(iter(rows.values())))
    full_rows = {
        "_src_file": [file_stem] * n,
        "_src_sheet": [sheet_stem] * n,
        "_doc_type": [doc_type] * n,
        **rows,
    }
    pd.DataFrame(full_rows).to_parquet(out_dir / f"{file_stem}__{sheet_stem}.parquet", index=False, engine="pyarrow")


def _base_provenance(n: int, principal: str, sheet_role: str, period: str = "2024-02", region: str = "la_union"):
    return {
        "_principal": [principal] * n,
        "_region": [region] * n,
        "_period": [period] * n,
        "_sheet_role": [sheet_role] * n,
        "_grain": ["invoice"] * n,
    }


@pytest.fixture
def staging_dir(tmp_path):
    d = tmp_path / "staging"

    # --- sales_register: promoted sheet (system-of-record, no conflict) ---
    _write_sheet(d, "sales_register", "fileA", "promoted_sheet", {
        "REFERENCE #": ["INV-1"], "AMOUNT": [100.0], "Area": ["PANGASINAN"],
        **_base_provenance(1, "delmonte", "data"),
    })

    # --- sales_register: demoted sheet (cross-check _sheet_role) ---
    _write_sheet(d, "sales_register", "fileA", "scratch_sheet", {
        "REFERENCE #": ["INV-2"], "AMOUNT": [50.0], "Area": ["PANGASINAN"],
        **_base_provenance(1, "delmonte", "scratch"),
    })

    # --- sales_register: conflict sheet (same natural key, different amount) ---
    _write_sheet(d, "sales_register", "fileB", "conflict_sheet", {
        "REFERENCE #": ["INV-3", "INV-3"], "AMOUNT": [100.0, 150.0], "Area": ["PANGASINAN", "PANGASINAN"],
        **_base_provenance(2, "delmonte", "data"),
    })

    # --- daily_sales_report: never anyone's primary doc_type -> demoted ---
    _write_sheet(d, "daily_sales_report", "fileC", "day_sheet", {
        "REFNBR": ["INV-9"], "Net Amount": [10.0],
        **_base_provenance(1, "delmonte", "data"),
    })

    # --- ssis_summary: natural_key: null for sales/unilever -> blocked ---
    _write_sheet(d, "ssis_summary", "fileD", "raw_sheet", {
        "Salesman": ["Juan"], "GSV": [500.0],
        **_base_provenance(1, "unilever", "raw_data"),
    })

    # --- unilever_sku: promoted sheet with zero/negative/outlier quantities ---
    _write_sheet(d, "unilever_sku", "fileE", "sku_sheet", {
        "Calendar\r\n  Month": ["01.2024", "01.2024", "01.2024", "01.2024"],
        "Product": ["SKU-A", "SKU-B", "SKU-C", "SKU-D"],
        "Sale Quantity in\r\n  Aggr.PC": [100.0, 0.0, -50.0, 5000.0],
        **_base_provenance(4, "unilever", "data"),
    })

    return d


def test_build_transform_manifest_classifies_promoted_demoted_conflict_blocked(staging_dir):
    manifest = build_transform_manifest(staging_dir)
    by_sheet = {(r["src_file"], r["src_sheet"]): r for r in manifest["staged"] + manifest["reject"]}

    assert by_sheet[("fileA", "promoted_sheet")]["checksum_status"] == "promoted"
    assert by_sheet[("fileA", "scratch_sheet")]["checksum_status"] == "demoted"
    assert by_sheet[("fileB", "conflict_sheet")]["checksum_status"] == "conflict"
    assert by_sheet[("fileC", "day_sheet")]["checksum_status"] == "demoted"
    assert by_sheet[("fileD", "raw_sheet")]["checksum_status"] == "blocked"
    assert "natural_key unconfirmed" in by_sheet[("fileD", "raw_sheet")]["reason"]
    assert by_sheet[("fileE", "sku_sheet")]["checksum_status"] == "promoted"


def test_zero_silent_skips_every_sheet_is_accounted_for(staging_dir):
    manifest = build_transform_manifest(staging_dir)
    all_sheets = {(r["src_file"], r["src_sheet"]) for r in manifest["staged"] + manifest["reject"]}
    assert all_sheets == {
        ("fileA", "promoted_sheet"), ("fileA", "scratch_sheet"),
        ("fileB", "conflict_sheet"), ("fileC", "day_sheet"), ("fileD", "raw_sheet"),
        ("fileE", "sku_sheet"),
    }
    # promoted + demoted -> staged (routine); conflict + blocked -> reject (needs a human look)
    staged_statuses = {r["checksum_status"] for r in manifest["staged"]}
    reject_statuses = {r["checksum_status"] for r in manifest["reject"]}
    assert staged_statuses <= {"promoted", "demoted"}
    assert reject_statuses <= {"conflict", "blocked"}


def test_quantity_issues_flags_zero_negative_outlier_without_dropping(staging_dir):
    """DEC-13: zero/negative/outlier quantities are flagged, never
    dropped - the promoted sheet still carries all 4 rows even though 3
    of them get flagged."""
    manifest = build_transform_manifest(staging_dir)
    by_sheet = {(r["src_file"], r["src_sheet"]): r for r in manifest["staged"] + manifest["reject"]}
    assert by_sheet[("fileE", "sku_sheet")]["row_count"] == 4  # nothing dropped

    reports = manifest["quantity_issues"]["sales_unilever_sku_demand/unilever"]
    (report,) = [r for r in reports if r["column"] == "quantity_sold"]
    assert report["zero_count"] == 1
    assert report["negative_count"] == 1
    assert report["outlier_count"] == 1
    assert report["total_rows"] == 4


def test_render_review_renders_transform_manifest_without_error(staging_dir, tmp_path):
    import json
    manifest = build_transform_manifest(staging_dir)
    transform_dir = tmp_path / "transform"
    transform_dir.mkdir()
    (transform_dir / "_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    out_path = render_review("transform", repo_root=tmp_path)
    assert out_path == transform_dir / "_review.html"
    html = out_path.read_text(encoding="utf-8")
    assert "Transform status" in html
    assert "promoted" in html and "demoted" in html
