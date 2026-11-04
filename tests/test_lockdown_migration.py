"""0075 (Data API lockdown) is catalog-driven and safe to replay into a scratch schema. Static only: the behaviour was
exercised on a disposable database on 127.0.0.1:55432 (STATE.md), and the migration is not applied to live."""
from pathlib import Path

from scripts.run_canonical_load import _strip_sql_file, live_schema_references

F = Path(__file__).resolve().parents[1] / "analytics" / "db" / "migrations" / "0075_lock_down_data_api.sql"


def test_names_no_live_schema_explicitly():
    assert live_schema_references([F]) == []


def test_reads_the_catalog_and_names_no_table():
    sql = _strip_sql_file(F.read_text(encoding="utf-8")).lower()
    assert "pg_class" in sql and "current_schema()" in sql
    for name in ("audit_log", "users", "user_session", "sales_fact", "product_dimension", "backup"):
        assert name not in sql, name


def test_restricts_service_role_and_public_functions():
    sql = _strip_sql_file(F.read_text(encoding="utf-8")).lower()
    assert "revoke select, insert, update, delete on all tables" in sql and "service_role" in sql
    assert "revoke execute on all functions" in sql and "from public" in sql
