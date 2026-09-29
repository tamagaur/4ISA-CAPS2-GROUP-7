"""tests/test_abc_reader_pinning.py — repo-wide invariant: every reader of
ABC_Classification pins `method`.

Migration 0017 added the `method` column and 25,437 unapproved `t3m` rows now
sit in public alongside the 23,223 `single` rows. Any query that omits the
predicate silently returns the UNION of both classification bases. Phase B
established this invariant for backend/ (backend/principals.py:104-124); this
test extends it to analytics/, scripts/ and tools/, which Phase B did not touch.

Static test — reads source, touches no database.
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SEARCH_ROOTS = ("analytics", "scripts", "tools")

# Files that name the table but issue no tier/period query against it.
ALLOWLIST = {
    "analytics/classification/abc.py":
        "pure function, DB-free by design — mentions the table in its docstring only",
    "analytics/optimization/lp.py":
        "docstring reference only; the query lives in scripts/run_lp.py",
    "scripts/backup_live_db.py":
        "SELECT * over every reflected table — a full dump must not filter",
    "scripts/apply_product_master_cleanup.py":
        "foreign-key reference check before deleting unreferenced products — a row of "
        "either method blocks the delete, so it must not filter",
    "scripts/smoke_api.py":
        "HTTP-only route driver, issues no SQL — names the table in its docstring only",
}

# The real query sites, with the predicate each must carry. Keeps the test from
# passing on an incidental 'method' appearing somewhere else in the file.
EXPECTED_PREDICATE = {
    "scripts/run_baseline_forecast.py": ("abc.method = 'single'", "method = 'single'"),
    "scripts/run_lp.py": ("ac.method = 'single'", "WHERE method = 'single'"),
    "scripts/model_bakeoff.py": ("AND method = 'single'",),
    "scripts/arima_bakeoff.py": ("AND method = 'single'",),
    "scripts/xgboost_bakeoff.py": ("AND method='single'",),
    "scripts/bakeoff_to_xlsx.py": ("ac.method='single'",),
    "scripts/check_missing_fast.py": ("abc.method = 'single'",),
    "scripts/check_missing_skus.py": ("abc.method = 'single'",),
    "scripts/run_sarima.py": ("abc.method = 'single'",),
    "scripts/archive/forecast_viewer/build.py": ("abc.method = 'single'",),
    "tools/dsd_dev_viewer/build.py": ("AND method = %(m)s",),
    "analytics/segmentation/orchestrate_segment.py": ("abc.c.method == abc_method",),
}


def _referencing_files() -> list[str]:
    found = []
    for root in SEARCH_ROOTS:
        for path in sorted((REPO / root).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            text = io.open(path, encoding="utf-8", errors="replace").read()
            if re.search(r"abc_classification", text, re.I):
                found.append(path.relative_to(REPO).as_posix())
    return found


def test_every_abc_reader_pins_method():
    """No file may query ABC_Classification without a `method` predicate."""
    unpinned = [
        rel for rel in _referencing_files()
        if rel not in ALLOWLIST
        and not re.search(r"method", io.open(REPO / rel, encoding="utf-8").read(), re.I)
    ]

    assert not unpinned, (
        "these files read ABC_Classification with no method predicate — they would "
        f"return the union of 'single' and 't3m': {unpinned}"
    )


@pytest.mark.parametrize("rel,variants", sorted(EXPECTED_PREDICATE.items()))
def test_known_query_sites_carry_the_literal_predicate(rel, variants):
    """Guards against the predicate being dropped in a future edit."""
    source = io.open(REPO / rel, encoding="utf-8").read()

    assert any(v in source for v in variants), f"{rel} lost its method predicate"


def test_allowlist_entries_still_exist_and_stay_query_free():
    """A stale allowlist would silently excuse a real reader."""
    for rel in ALLOWLIST:
        path = REPO / rel
        assert path.exists(), f"allowlisted file {rel} no longer exists — prune the allowlist"

    referencing = set(_referencing_files())
    assert set(ALLOWLIST) <= referencing, "allowlist names a file that no longer mentions the table"


def test_lp_candidate_pool_filters_tier_a():
    """run_lp.py's docstring claimed 'Category A' while the SQL had no tier
    filter at all — every forecast row qualified regardless of tier."""
    source = io.open(REPO / "scripts/run_lp.py", encoding="utf-8").read()

    assert "ac.tier = 'A'" in source
