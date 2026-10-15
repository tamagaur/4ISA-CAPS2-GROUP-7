"""Migration 0052 rails: the demo schema carries no accuracy column and no band, and every table is labelled.
Reads the migration file, not the database, so it fails in review before anything is applied."""
import re
from pathlib import Path

SQL = (Path(__file__).resolve().parents[2] / "analytics" / "db" / "migrations" / "0052_demo_schema.sql").read_text(encoding="utf-8")
FORBIDDEN = re.compile(r"(mape|mase|wape|smape|rmse|mae|bias|confidence|lower|upper|interval|ci_lo|ci_hi)", re.I)


def _strip_comments(sql: str) -> str:
    return "\n".join(re.sub(r"--.*$", "", line) for line in sql.splitlines())


def _tables():
    for m in re.finditer(r"CREATE TABLE IF NOT EXISTS (demo\.\w+) \((.*?)\n\);", _strip_comments(SQL), re.S):
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
    assert set(tables) == {"demo.run", "demo.dm_category_sales", "demo.dm_category_param", "demo.dm_forecast", "demo.dm_excluded"}
    for name, body in tables.items():
        assert re.search(r"is_demo\s+BOOLEAN\s+NOT NULL DEFAULT true CHECK \(is_demo\)", body), name
        assert "CHECK (fill_source = 'synthetic_dm_pipeline_demo')" in re.sub(r"\s+", " ", body), name


def test_forecast_method_is_pinned_to_ma3_and_series_origin_is_two_valued():
    assert "CHECK (method = 'ma3')" in SQL
    assert "origin IN ('real_copy', 'interpolated')" in SQL


def test_migration_changes_nothing_outside_the_demo_schema():
    body = _strip_comments(SQL).replace("ON DELETE CASCADE", "")
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|ALTER|DROP|TRUNCATE)\b", body, re.I)
    assert "public." not in body.lower()
    for m in re.finditer(r"CREATE (?:TABLE|SCHEMA) IF NOT EXISTS (\S+)", body):
        assert m.group(1).rstrip(";").split(".")[0] == "demo", m.group(1)
