"""
tests/etl/test_load.py — Tests for analytics.etl.load.

These cover the guard logic that doesn't require a live Postgres/Supabase
connection. A real upsert against a live database is an integration test
that belongs in a separate suite once Supabase credentials are available
(see analytics/config.py — implemented, despite this file's older
docstring elsewhere calling it a stub; SUPABASE_DB_URL/SUPABASE_KEY are
what's still missing, not the loader).

  test_empty_dataframe_short_circuits
  test_missing_natural_key_column_raises
  test_upsert_sql_shape_is_insert_on_conflict_do_update
  test_build_dimension_key_frame_maps_df_columns
  test_build_dimension_key_frame_applies_static_values
  test_build_dimension_key_frame_marks_null_parts_unresolvable
  test_build_dimension_key_frame_raises_on_missing_source
  test_resolve_dimension_fk_raises_before_touching_engine
  test_dimension_insert_sql_shape_is_on_conflict_do_nothing
  test_compute_reject_rate_below_threshold_passes
  test_compute_reject_rate_above_threshold_fails
  test_compute_reject_rate_empty_manifest_is_zero_rate
  test_check_reject_rate_gate_raises_when_crossed
  test_check_reject_rate_gate_passes_when_under_threshold
  test_load_to_supabase_blocked_when_reject_rate_gate_fails
  test_load_to_supabase_without_manifest_path_skips_gate
  test_load_to_supabase_blocked_when_signoff_gate_fails
  test_load_to_supabase_without_transform_dir_skips_signoff_gate
"""
import json

import pandas as pd
import pytest
from sqlalchemy import Column, MetaData, Numeric, String, Table
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import insert as pg_insert

from analytics.etl.load import (
    DimensionFKSpec,
    build_dimension_key_frame,
    check_reject_rate_gate,
    compute_reject_rate,
    load_to_supabase,
    resolve_dimension_fk,
)


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


def _unilever_demand_spec() -> DimensionFKSpec:
    """Product_Dimension's real natural key (principal, grain, sku_code,
    category_path) - sku_code comes from df, grain is static (this call
    site is entirely SKU-grain), category_path has no source for this
    fact family (Unilever never has one) so it's also static (None)."""
    return DimensionFKSpec(
        fk_column="product_key",
        dimension_table="product_dimension",
        dimension_pk="product_key",
        dimension_natural_key=["principal", "grain", "sku_code", "category_path"],
        df_to_dimension_columns={"principal": "principal", "sku_code": "sku_code"},
        static_values={"grain": "sku", "category_path": None},
    )


def test_build_dimension_key_frame_maps_df_columns():
    df = pd.DataFrame({"principal": ["unilever", "unilever"], "sku_code": ["111", "222"]})
    key_df, resolvable = build_dimension_key_frame(df, _unilever_demand_spec())
    assert list(key_df["sku_code"]) == ["111", "222"]
    assert list(key_df["principal"]) == ["unilever", "unilever"]
    assert resolvable.all()


def test_build_dimension_key_frame_applies_static_values():
    df = pd.DataFrame({"principal": ["unilever"], "sku_code": ["111"]})
    key_df, _ = build_dimension_key_frame(df, _unilever_demand_spec())
    assert key_df["grain"].iloc[0] == "sku"
    assert key_df["category_path"].iloc[0] is None


def test_build_dimension_key_frame_marks_null_parts_unresolvable():
    """Anti-fabrication: a row missing part of its natural key (e.g. a
    blank sku_code) must never get a guessed/fabricated dimension row -
    resolvable_mask flags it instead."""
    df = pd.DataFrame({"principal": ["unilever", "unilever"], "sku_code": ["111", None]})
    key_df, resolvable = build_dimension_key_frame(df, _unilever_demand_spec())
    assert list(resolvable) == [True, False]


def test_build_dimension_key_frame_raises_on_missing_source():
    """Every dimension_natural_key column must come from either
    df_to_dimension_columns or static_values - never left implicit."""
    spec = DimensionFKSpec(
        fk_column="product_key",
        dimension_table="product_dimension",
        dimension_pk="product_key",
        dimension_natural_key=["principal", "grain", "sku_code", "category_path"],
        df_to_dimension_columns={"principal": "principal", "sku_code": "sku_code"},
        static_values={"grain": "sku"},   # category_path missing on purpose
    )
    df = pd.DataFrame({"principal": ["unilever"], "sku_code": ["111"]})
    with pytest.raises(KeyError):
        build_dimension_key_frame(df, spec)


def test_resolve_dimension_fk_raises_before_touching_engine():
    """The natural-key-source guard must fire before any DB access -
    engine=None here would blow up immediately if the guard didn't run
    first, which is exactly what this test confirms."""
    spec = DimensionFKSpec(
        fk_column="product_key",
        dimension_table="product_dimension",
        dimension_pk="product_key",
        dimension_natural_key=["principal", "grain", "sku_code", "category_path"],
        df_to_dimension_columns={"principal": "principal", "sku_code": "sku_code"},
        static_values={"grain": "sku"},   # category_path missing on purpose
    )
    df = pd.DataFrame({"principal": ["unilever"], "sku_code": ["111"]})
    with pytest.raises(KeyError):
        resolve_dimension_fk(df, engine=None, spec=spec)


def test_dimension_insert_sql_shape_is_on_conflict_do_nothing():
    """Confirms the lookup-or-insert pattern (DEC-09) compiles to the
    correct Postgres SQL without needing a live connection - existing
    dimension rows are matched, never duplicated or overwritten."""
    metadata = MetaData()
    product_dimension = Table(
        "product_dimension", metadata,
        Column("product_key", Numeric, primary_key=True),
        Column("principal", String),
        Column("sku_code", String),
    )
    stmt = pg_insert(product_dimension).values([{"principal": "unilever", "sku_code": "111"}])
    stmt = stmt.on_conflict_do_nothing(index_elements=["principal", "sku_code"])
    compiled = str(stmt.compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (principal, sku_code) DO NOTHING" in compiled
    assert "INSERT INTO product_dimension" in compiled


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
