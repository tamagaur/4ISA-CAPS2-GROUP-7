"""0075 (Data API lockdown) is catalog-driven and names no live schema explicitly, but it is NOT confined to a scratch
schema: its ALTER DEFAULT PRIVILEGES statements are database-wide for the role (KNOWN_ISSUES B3), so the scratch-build guard
refuses it (2026-11-11). Static only: the behaviour was exercised on a disposable database on 127.0.0.1:55432 (STATE.md),
and the migration is not applied to live."""
from pathlib import Path

from scripts.run_canonical_load import _LIVE_SCHEMA_REF_RE, _strip_sql_file, database_wide_statements, live_schema_references

F = Path(__file__).resolve().parents[1] / "analytics" / "db" / "migrations" / "0075_lock_down_data_api.sql"


def test_names_no_live_schema_explicitly():
    assert _LIVE_SCHEMA_REF_RE.findall(_strip_sql_file(F.read_text(encoding="utf-8"))) == []


def test_its_default_privilege_statements_are_flagged_as_database_wide():
    flagged = database_wide_statements(_strip_sql_file(F.read_text(encoding="utf-8")))
    assert flagged and all("ALTER DEFAULT PRIVILEGES" in w for w in flagged)
    assert live_schema_references([F])                  # so a scratch build refuses it


def test_reads_the_catalog_and_names_no_table():
    sql = _strip_sql_file(F.read_text(encoding="utf-8")).lower()
    assert "pg_class" in sql and "current_schema()" in sql
    for name in ("audit_log", "users", "user_session", "sales_fact", "product_dimension", "backup"):
        assert name not in sql, name


def test_restricts_service_role_and_public_functions():
    sql = _strip_sql_file(F.read_text(encoding="utf-8")).lower()
    assert "revoke select, insert, update, delete on all tables" in sql and "service_role" in sql
    assert "revoke execute on all functions" in sql and "from public" in sql
