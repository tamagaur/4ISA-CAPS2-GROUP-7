"""
tests/etl/test_load.py — Tests for analytics.etl.load.

These cover the guard logic that doesn't require a live Postgres/Supabase
connection. A real upsert against a live database is an integration test
that belongs in a separate suite once Supabase credentials are available
(see analytics/config.py, still a Phase 3A stub as of this writing).

  test_empty_dataframe_short_circuits
  test_missing_natural_key_column_raises
  test_upsert_sql_shape_is_insert_on_conflict_do_update
"""
import json

import pandas as pd
import pytest
from sqlalchemy import Column, MetaData, Numeric, String, Table
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import insert as pg_insert

from analytics.etl.load import check_reject_rate_gate, compute_reject_rate, load_to_supabase


def test_empty_dataframe_short_circuits():
    df = pd.DataFrame()
    result = load_to_supabase(df, "sales_fact", engine=None, natural_key=["invoice_num"])
    assert result.rows_attempted == 0
    assert result.rows_upserted == 0


def test_missing_natural_key_column_raises():
    df = pd.DataFrame({"net_amount": [100.0]})
    with pytest.raises(KeyError):
        load_to_supabase(df, "sales_fact", engine=None, natural_key=["invoice_num"])


def test_upsert_sql_shape_is_insert_on_conflict_do_update():
    """Confirms the upsert pattern itself (ARCHITECTURE.md DEC — no
    silent overwrites) compiles to the correct Postgres SQL, without
    needing a live connection."""
    metadata = MetaData()
    sales_fact = Table(
        "sales_fact", metadata,
        Column("invoice_num", String, primary_key=True),
        Column("net_amount", Numeric),
    )
    stmt = pg_insert(sales_fact).values([{"invoice_num": "INV-1", "net_amount": 100.0}])
    stmt = stmt.on_conflict_do_update(index_elements=["invoice_num"], set_={"net_amount": stmt.excluded.net_amount})
    compiled = str(stmt.compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (invoice_num) DO UPDATE" in compiled
    assert "INSERT INTO sales_fact" in compiled


def test_compute_reject_rate_below_threshold_passes():
    manifest = {"staged": [{}] * 98, "reject": [{}] * 2}   # exactly 2%
    result = compute_reject_rate(manifest, threshold=0.02)
    assert result.staged == 98
    assert result.rejected == 2
    assert result.reject_rate == pytest.approx(0.02)
    assert result.passed


def test_compute_reject_rate_above_threshold_fails():
    manifest = {"staged": [{}] * 90, "reject": [{}] * 10}   # 10%
    result = compute_reject_rate(manifest, threshold=0.02)
    assert result.reject_rate == pytest.approx(0.10)
    assert not result.passed


def test_compute_reject_rate_empty_manifest_is_zero_rate():
    result = compute_reject_rate({"staged": [], "reject": []})
    assert result.reject_rate == 0.0
    assert result.passed


def test_check_reject_rate_gate_raises_when_crossed(tmp_path):
    manifest_path = tmp_path / "_manifest.json"
    manifest_path.write_text(json.dumps({"staged": [{}] * 90, "reject": [{}] * 10}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="Reject-rate gate failed"):
        check_reject_rate_gate(manifest_path, threshold=0.02)


def test_check_reject_rate_gate_passes_when_under_threshold(tmp_path):
    manifest_path = tmp_path / "_manifest.json"
    manifest_path.write_text(json.dumps({"staged": [{}] * 99, "reject": [{}] * 1}), encoding="utf-8")
    result = check_reject_rate_gate(manifest_path, threshold=0.02)
    assert result.passed


def test_load_to_supabase_blocked_when_reject_rate_gate_fails(tmp_path):
    """DEC-12: Load must refuse to run at all - not even reach the
    empty-dataframe short circuit - when the reject-rate gate fails."""
    manifest_path = tmp_path / "_manifest.json"
    manifest_path.write_text(json.dumps({"staged": [{}] * 50, "reject": [{}] * 50}), encoding="utf-8")
    df = pd.DataFrame({"invoice_num": ["INV-1"], "net_amount": [100.0]})
    with pytest.raises(RuntimeError, match="Reject-rate gate failed"):
        load_to_supabase(df, "sales_fact", engine=None, natural_key=["invoice_num"], manifest_path=manifest_path)


def test_load_to_supabase_without_manifest_path_skips_gate():
    """Existing callers that don't pass manifest_path are unaffected -
    the gate is opt-in, not a hardcoded default path."""
    df = pd.DataFrame()
    result = load_to_supabase(df, "sales_fact", engine=None, natural_key=["invoice_num"])
    assert result.rows_attempted == 0


def test_load_to_supabase_blocked_when_signoff_gate_fails(tmp_path):
    """M2 sign-off story: Load must refuse to run without an explicit,
    approved, non-stale human decision when transform_dir is given."""
    transform_dir = tmp_path / "transform"
    transform_dir.mkdir()
    (transform_dir / "_manifest.json").write_text(json.dumps({"staged": [], "reject": []}), encoding="utf-8")
    df = pd.DataFrame({"invoice_num": ["INV-1"], "net_amount": [100.0]})
    with pytest.raises(RuntimeError, match="Sign-off gate failed"):
        load_to_supabase(df, "sales_fact", engine=None, natural_key=["invoice_num"], transform_dir=transform_dir)


def test_load_to_supabase_without_transform_dir_skips_signoff_gate():
    """Existing callers that don't pass transform_dir are unaffected -
    same opt-in convention as manifest_path."""
    df = pd.DataFrame()
    result = load_to_supabase(df, "sales_fact", engine=None, natural_key=["invoice_num"])
    assert result.rows_attempted == 0
