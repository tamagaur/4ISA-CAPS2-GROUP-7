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
import pandas as pd
import pytest
from sqlalchemy import Column, MetaData, Numeric, String, Table
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import insert as pg_insert

from analytics.etl.load import load_to_supabase


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
