"""tests/etl/test_real_views.py — the `_Real` views are the data-interface
guarantee: model code reads them, and they structurally exclude synthetic rows.

Static check of analytics/db/schema.sql (no DB):
  1. every `<Table>_Real` view is `SELECT * FROM <Table> WHERE is_demo = false`
     and nothing else - no OR, no principal carve-out (the 2026 incident the
     schema comment above the views describes was exactly such a carve-out);
  2. every table that has an `is_demo` column has a `_Real` view, so a new
     demo-capable fact table cannot be added without its real-only interface.
"""
from __future__ import annotations

import re
from pathlib import Path

SCHEMA = Path(__file__).resolve().parents[2] / "analytics" / "db" / "schema.sql"

_COMMENT = re.compile(r"--[^\n]*")
_TABLE = re.compile(r"CREATE TABLE IF NOT EXISTS\s+(\w+)\s*\((.*?)\n\);", re.S | re.I)
_VIEW = re.compile(r"CREATE OR REPLACE VIEW\s+(\w+_Real)\s+AS\s+(.*?);", re.S | re.I)


def _sql() -> str:
    return _COMMENT.sub("", SCHEMA.read_text(encoding="utf-8"))


def _demo_tables() -> set[str]:
    return {name.lower() for name, body in _TABLE.findall(_sql())
            if re.search(r"^\s*is_demo\s+BOOLEAN", body, re.M | re.I)}


def _real_views() -> dict[str, str]:
    return {name.lower(): " ".join(body.split()).lower() for name, body in _VIEW.findall(_sql())}


def test_schema_has_demo_tables_and_real_views():
    assert _demo_tables(), "no is_demo tables parsed - the regex no longer matches schema.sql"
    assert _real_views(), "no _Real views parsed - the regex no longer matches schema.sql"


def test_every_real_view_is_exactly_the_is_demo_false_filter():
    for view, body in _real_views().items():
        table = view[: -len("_real")]
        assert body == f"select * from {table} where is_demo = false", f"{view}: {body!r}"


def test_every_is_demo_table_has_a_real_view():
    missing = {t for t in _demo_tables() if f"{t}_real" not in _real_views()}
    assert not missing, f"is_demo tables with no _Real view: {sorted(missing)}"


def test_no_real_view_over_a_table_without_is_demo():
    orphans = {v for v in _real_views() if v[: -len("_real")] not in _demo_tables()}
    assert not orphans, f"_Real views over tables with no is_demo column: {sorted(orphans)}"
