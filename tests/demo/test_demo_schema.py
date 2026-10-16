"""Demo-schema rails (migrations 0052, 0053): no accuracy column and no band in any demo table, every table
labelled, one origin taxonomy, nothing outside schema demo touched.
Reads the migration files, not the database, so it fails in review before anything is applied."""
import re
from pathlib import Path

MIG = Path(__file__).resolve().parents[2] / "analytics" / "db" / "migrations"
SQL = (MIG / "0052_demo_schema.sql").read_text(encoding="utf-8")
SQL_ALL = "\n".join(f.read_text(encoding="utf-8") for f in sorted(MIG.glob("005[2-9]_demo*.sql")))
FORBIDDEN = re.compile(r"(mape|mase|wape|smape|rmse|mae|bias|confidence|lower|upper|interval|ci_lo|ci_hi)", re.I)
EXPECTED_TABLES = {"demo.run", "demo.dm_category_sales", "demo.dm_category_param", "demo.dm_forecast",
                   "demo.dm_excluded", "demo.unilever_sku_sales", "demo.backcast_excluded",
                   "demo.dm_category_stock", "demo.unilever_sku_forecast", "demo.dm_category_lp"}


def _strip_comments(sql: str) -> str:
    return "\n".join(re.sub(r"--.*$", "", line) for line in sql.splitlines())


def _tables():
    for m in re.finditer(r"CREATE TABLE IF NOT EXISTS (demo\.\w+) \((.*?)\n\);", _strip_comments(SQL_ALL), re.S):
        yield m.group(1), m.group(2)


def _columns(body: str):
    for line in body.splitlines():
        first = line.strip().split(" ", 1)[0].strip('"')
        if first and first.islower() and first not in {"primary", "unique", "check", "foreign", "constraint"}:
            yield first


def test_no_accuracy_or_band_column_in_any_demo_table():
    found = [(t, c) for t, body in _tables() for c in _columns(body) if FORBIDDEN.search(c)]
    assert found == [], f"accuracy/band column in demo.*: {found}"


def test_the_forbidden_column_check_actually_catches_one():
    body = "    mape NUMERIC,\n    confidence_lower NUMERIC,\n    category_path TEXT"
    assert [c for c in _columns(body) if FORBIDDEN.search(c)] == ["mape", "confidence_lower"]


def test_every_demo_table_is_labelled_demo_and_synthetic():
    tables = dict(_tables())
    assert set(tables) == EXPECTED_TABLES
    for name, body in tables.items():
        assert re.search(r"is_demo\s+BOOLEAN\s+NOT NULL DEFAULT true CHECK \(is_demo\)", body), name
        assert "CHECK (fill_source = 'synthetic_dm_pipeline_demo')" in re.sub(r"\s+", " ", body), name


def test_forecast_method_is_pinned_to_ma3_and_the_origin_taxonomy_is_four_distinct_values():
    flat = re.sub(r"\s+", " ", SQL_ALL)
    assert "CHECK (method = 'ma3')" in flat
    assert "CHECK (origin IN ('real_copy', 'interpolated', 'bridged', 'backcast'))" in flat
    # Unilever never carries a generated gap-fill: only real copies and the 2021-2022 back-cast
    assert "CHECK (origin IN ('real_copy', 'backcast'))" in flat


def test_0052_changes_nothing_outside_the_demo_schema():
    body = _strip_comments(SQL).replace("ON DELETE CASCADE", "")
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|ALTER|DROP|TRUNCATE)\b", body, re.I)
    assert "public." not in body.lower()


def test_every_statement_in_every_demo_migration_targets_the_demo_schema():
    body = _strip_comments(SQL_ALL).replace("ON DELETE CASCADE", "")
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|TRUNCATE)\b", body, re.I)
    for m in re.finditer(r"\b(ALTER TABLE|DROP TABLE|CREATE TABLE IF NOT EXISTS|CREATE SCHEMA IF NOT EXISTS)\s+(\S+)", body):
        assert m.group(2).rstrip(";").split(".")[0] == "demo", m.group(0)
    assert "public." not in body.lower()
