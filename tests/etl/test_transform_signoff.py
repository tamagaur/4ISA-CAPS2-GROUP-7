"""
tests/etl/test_transform_signoff.py — Tests for analytics.etl.transform_signoff.

  test_build_checklist_counts_and_zero_silent_skips
  test_build_checklist_splits_blocked_expected_vs_unexpected
  test_build_checklist_row_reconciliation_match_mismatch_skipped
  test_compute_manifest_fingerprint_deterministic_and_sensitive_to_change
  test_record_signoff_writes_expected_shape
  test_record_signoff_requires_a_named_person
  test_check_signoff_gate_passes_when_approved_and_fingerprint_matches
  test_check_signoff_gate_raises_when_no_signoff
  test_check_signoff_gate_raises_when_rejected
  test_check_signoff_gate_raises_when_stale
  test_build_checklist_surfaces_quantity_issues
  test_format_checklist_text_includes_quantity_issues
"""
import json

import pytest

from analytics.etl.load import check_signoff_gate
from analytics.etl.transform_signoff import (
    build_checklist,
    compute_manifest_fingerprint,
    format_checklist_text,
    record_signoff,
)


def _rec(status, src_file="f1", src_sheet="s1", doc_type="sales_register", reason=None):
    return {
        "src_file": src_file, "src_sheet": src_sheet, "doc_type": doc_type,
        "checksum_status": status, "reason": reason, "row_count": 10,
    }


def test_build_checklist_counts_and_zero_silent_skips():
    manifest = {
        "staged": [_rec("promoted"), _rec("demoted", src_sheet="s2")],
        "reject": [_rec("conflict", src_sheet="s3"), _rec("blocked", src_sheet="s4", reason="natural_key unconfirmed for fact='sales'")],
    }
    checklist = build_checklist(manifest)
    assert checklist["counts"] == {"promoted": 1, "demoted": 1, "conflict": 1, "blocked": 1}
    assert checklist["zero_silent_skips"] is True


def test_build_checklist_splits_blocked_expected_vs_unexpected():
    manifest = {
        "staged": [],
        "reject": [
            _rec("blocked", src_sheet="expected", reason="natural_key unconfirmed for fact='sales' principal='unilever'"),
            _rec("blocked", src_sheet="unexpected", reason="transform_fact() raised: KeyError('x')"),
        ],
    }
    checklist = build_checklist(manifest)
    assert [i["src_sheet"] for i in checklist["blocked_expected"]] == ["expected"]
    assert [i["src_sheet"] for i in checklist["blocked_unexpected"]] == ["unexpected"]


def test_build_checklist_row_reconciliation_match_mismatch_skipped():
    transform_manifest = {"staged": [_rec("promoted")], "reject": []}

    matching_extract = {"staged": [{"src_file": "f1", "src_sheet": "s1", "row_count": 10}]}
    checklist = build_checklist(transform_manifest, matching_extract)
    assert checklist["row_reconciliation"]["matches"] is True

    mismatching_extract = {"staged": [{"src_file": "f1", "src_sheet": "s1", "row_count": 999}]}
    checklist = build_checklist(transform_manifest, mismatching_extract)
    assert checklist["row_reconciliation"]["matches"] is False

    checklist = build_checklist(transform_manifest, extract_manifest=None)
    assert checklist["row_reconciliation"] is None


def test_compute_manifest_fingerprint_deterministic_and_sensitive_to_change():
    manifest_a = {"staged": [_rec("promoted")], "reject": []}
    manifest_a_copy = {"staged": [_rec("promoted")], "reject": []}
    manifest_b = {"staged": [_rec("demoted")], "reject": []}

    assert compute_manifest_fingerprint(manifest_a) == compute_manifest_fingerprint(manifest_a_copy)
    assert compute_manifest_fingerprint(manifest_a) != compute_manifest_fingerprint(manifest_b)


@pytest.fixture
def transform_dir(tmp_path):
    d = tmp_path / "transform"
    d.mkdir()
    manifest = {"staged": [_rec("promoted")], "reject": []}
    (d / "_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return d


def test_record_signoff_writes_expected_shape(transform_dir):
    out_path = record_signoff(transform_dir, "approved", "Jane Dela Cruz", notes="looks fine")
    assert out_path == transform_dir / "_signoff.json"
    record = json.loads(out_path.read_text(encoding="utf-8"))
    assert record["decision"] == "approved"
    assert record["decided_by"] == "Jane Dela Cruz"
    assert record["notes"] == "looks fine"
    assert record["manifest_fingerprint"].startswith("sha256:")
    assert "checklist" in record
    assert "decided_at" in record


def test_record_signoff_requires_a_named_person(transform_dir):
    with pytest.raises(ValueError, match="decided_by is required"):
        record_signoff(transform_dir, "approved", "")


def test_check_signoff_gate_passes_when_approved_and_fingerprint_matches(transform_dir):
    record_signoff(transform_dir, "approved", "Jane Dela Cruz")
    result = check_signoff_gate(transform_dir)
    assert result.decision == "approved"
    assert result.decided_by == "Jane Dela Cruz"


def test_check_signoff_gate_raises_when_no_signoff(transform_dir):
    with pytest.raises(RuntimeError, match="Sign-off gate failed"):
        check_signoff_gate(transform_dir)


def test_check_signoff_gate_raises_when_rejected(transform_dir):
    record_signoff(transform_dir, "rejected", "Jane Dela Cruz", notes="found a real problem")
    with pytest.raises(RuntimeError, match="explicit rejection"):
        check_signoff_gate(transform_dir)


def test_check_signoff_gate_raises_when_stale(transform_dir):
    record_signoff(transform_dir, "approved", "Jane Dela Cruz")
    # Transform re-run with different results after sign-off was recorded.
    new_manifest = {"staged": [_rec("promoted"), _rec("demoted", src_sheet="new")], "reject": []}
    (transform_dir / "_manifest.json").write_text(json.dumps(new_manifest), encoding="utf-8")
    with pytest.raises(RuntimeError, match="stale"):
        check_signoff_gate(transform_dir)


def test_build_checklist_surfaces_quantity_issues():
    manifest = {
        "staged": [_rec("promoted")],
        "reject": [],
        "quantity_issues": {
            "sales_unilever_sku_demand/unilever": [
                {
                    "column": "quantity_sold", "total_rows": 4,
                    "zero_count": 1, "negative_count": 1, "outlier_count": 1,
                    "zero_rows": [], "negative_rows": [], "outlier_rows": [],
                },
            ],
        },
    }
    checklist = build_checklist(manifest)
    assert checklist["quantity_flag_total"] == 3
    assert "sales_unilever_sku_demand/unilever" in checklist["quantity_issues"]


def test_format_checklist_text_includes_quantity_issues():
    manifest = {
        "staged": [_rec("promoted")],
        "reject": [],
        "quantity_issues": {
            "sell_out/delmonte": [
                {
                    "column": "quantity", "total_rows": 10,
                    "zero_count": 2, "negative_count": 0, "outlier_count": 1,
                    "zero_rows": [], "negative_rows": [], "outlier_rows": [],
                },
            ],
        },
    }
    checklist = build_checklist(manifest)
    text = format_checklist_text(checklist)
    assert "Quantity issues flagged, never dropped (total: 3)" in text
    assert "sell_out/delmonte / quantity: zero=2 negative=0 outlier=1" in text
