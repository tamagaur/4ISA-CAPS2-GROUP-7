"""tests/forecasting/test_real_view_reads.py - invariant: every data read in
analytics/forecasting/ and the forecast runner goes through a *_Real view,
never a base fact table.

The _Real views (analytics/db/schema.sql, CREATE OR REPLACE VIEW *_Fact_Real)
exclude is_demo=true rows structurally. That view boundary is what keeps
placeholder rows out of a live forecast now that the router judges rows by
provenance, not by date (DEC-27): a base-table read would bring is_demo rows
back in. Same pattern as tests/test_abc_reader_pinning.py.

Static test - parses source, touches no database. Only SQL string literals
are checked, so a docstring naming a base table is not a read.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
FILES = sorted(p.relative_to(REPO).as_posix() for p in (REPO / "analytics/forecasting").glob("*.py")) + [
    "scripts/run_baseline_forecast.py",
]
# Every base table that has a *_Real view (schema.sql CREATE OR REPLACE VIEW ..._Real).
BASE_TABLES = ("sales_fact", "purchase_fact", "inventory_fact", "sellout_fact", "unilever_sku_demand_fact", "salesreturn_fact")
SQL = re.compile(r"\bselect\b[\s\S]*\bfrom\s+[a-z_\"]|\binsert\s+into\b|\bdelete\s+from\b|\bupdate\s+\w+\s+set\b", re.I)
READ = re.compile(r"\b(?:from|join)\s+(?:\"?public\"?\.)?\"?([a-z_][a-z0-9_]*)\"?", re.I)


def _sql_literals(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and SQL.search(n.value)]


def _reads(rel: str) -> list[str]:
    return [t.lower() for sql in _sql_literals(REPO / rel) for t in READ.findall(sql)]


@pytest.mark.parametrize("rel", FILES)
def test_no_base_fact_table_is_read(rel):
    bad = [t for t in _reads(rel) if t in BASE_TABLES]
    assert not bad, f"{rel} reads base table(s) {bad} - read the *_Real view instead"


def test_every_fact_read_is_a_real_view():
    fact_reads = {(rel, t) for rel in FILES for t in _reads(rel) if "_fact" in t}
    assert fact_reads, "no fact read found - the scan is not seeing the runner's queries"
    assert all(t.endswith("_real") for _, t in fact_reads), sorted(fact_reads)


def test_scan_catches_a_base_table_read(tmp_path):
    """The scan must flag the violation it exists to catch, and ignore docstrings."""
    p = tmp_path / "x.py"
    p.write_text('"""reads Unilever_SKU_Demand_Fact in prose only"""\n'
                 'Q = "SELECT q FROM public.Unilever_SKU_Demand_Fact d JOIN Sales_Fact_Real s ON true"\n', encoding="utf-8")
    found = [t.lower() for sql in _sql_literals(p) for t in READ.findall(sql)]
    assert found == ["unilever_sku_demand_fact", "sales_fact_real"]
