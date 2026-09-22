"""tests/etl/test_schema_migration_compat.py - schema.sql must stay buildable together with the migrations.

A fresh database is built by running analytics/db/schema.sql and then every migration in order
(scripts/run_canonical_load.py). A migration that ADDs a named UNIQUE constraint without first dropping that
name fails if schema.sql has already declared the same key inline, because Postgres auto-names an inline
UNIQUE (a, b) on table t as t_a_b_key. That broke the scratch build on 2026-09-21 (sku_traits / migration 0020).
Static check, no DB.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
SCHEMA = (REPO / "analytics/db/schema.sql").read_text(encoding="utf-8")
MIGRATIONS = sorted((REPO / "analytics/db/migrations").glob("0*.sql"))


def _strip_comments(sql: str) -> str:
    return re.sub(r"--[^\n]*", "", sql)


def _inline_unique_names(schema_sql: str) -> set[str]:
    names = set()
    tables = re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)\s*\((.*?)\n\);", _strip_comments(schema_sql), flags=re.S | re.I)
    for table, body in tables:
        for cols in re.findall(r"^\s*UNIQUE\s*(?:NULLS NOT DISTINCT\s*)?\(([^)]*)\)", body, flags=re.M | re.I):
            names.add(f"{table}_{'_'.join(c.strip() for c in cols.split(','))}_key".lower())
    return names


def _unguarded_clashes(schema_sql: str) -> list[str]:
    inline = _inline_unique_names(schema_sql)
    clashes = []
    for path in MIGRATIONS:
        sql = _strip_comments(path.read_text(encoding="utf-8"))
        for name in re.findall(r"ADD CONSTRAINT\s+(\w+)\s+UNIQUE", sql, flags=re.I):
            before = re.split(r"ADD CONSTRAINT\s+" + re.escape(name), sql, flags=re.I)[0]
            # guarded = the same file drops that name first, explicitly or dynamically
            # (0013 does it inside a DO block: EXECUTE format('... DROP CONSTRAINT %I', check_name))
            guarded = re.search(r"DROP CONSTRAINT\s+(IF EXISTS\s+)?(" + re.escape(name) + r"\b|%I)", before, flags=re.I)
            if name.lower() in inline and not guarded:
                clashes.append(f"{path.name}: ADD CONSTRAINT {name} is already created by schema.sql")
    return clashes


def test_the_parser_sees_inline_unique_keys():
    assert "sku_traits_product_key_cohort_period_key" in _inline_unique_names(SCHEMA)


def test_no_migration_adds_a_constraint_schema_sql_already_declares():
    assert _unguarded_clashes(SCHEMA) == []


def test_the_check_has_teeth():
    """Declaring migration 0020's three-column sku_traits key inline is exactly the 2026-09-21 breakage."""
    broken = SCHEMA.replace("    UNIQUE (product_key, cohort_period)\n", "    UNIQUE (product_key, cohort_period, abc_method)\n", 1)
    assert broken != SCHEMA
    assert any("0020" in c for c in _unguarded_clashes(broken))
