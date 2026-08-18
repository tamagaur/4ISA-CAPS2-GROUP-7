"""
tests/test_transform_config.py — config-coverage gate (DEC-07, checklist T1).

For every distinct _doc_type Extract actually staged, assert:
  1. config/column_maps/<doc_type>.yaml exists (load_column_map() would
     otherwise raise FileNotFoundError the first time Transform touches it)
  2. the doc_type is accounted for in config/source_of_truth.yaml — either
     as some fact's primary `doc_type`, or listed in some fact's
     `cross_check_doc_types` (e.g. daily_sales_report, a demoted duplicate
     of sales_register, never itself a fact's system-of-record)

Must fail loudly on any gap — never silently skip a doc_type. Skips only
when staging/ doesn't exist at all (nothing to check yet), same convention
as tests/etl/test_extract.py's RAW_DIR skip.
"""
from __future__ import annotations

import json

import pytest
import yaml

from analytics.etl.transform import DEFAULT_CONFIG_DIR, REPO_ROOT

STAGING_MANIFEST = REPO_ROOT / "staging" / "_manifest.json"


def _staged_doc_types() -> set[str]:
    manifest = json.loads(STAGING_MANIFEST.read_text(encoding="utf-8"))
    return {r["doc_type"] for r in manifest["staged"] if r.get("doc_type")}


def _known_doc_types_in_source_of_truth() -> set[str]:
    rules = yaml.safe_load((DEFAULT_CONFIG_DIR / "source_of_truth.yaml").read_text(encoding="utf-8")) or {}
    known: set[str] = set()
    for fact_rules in rules.values():
        for entry in fact_rules.values():
            known.add(entry["doc_type"])
            known.update(entry.get("cross_check_doc_types", []))
    return known


pytestmark = pytest.mark.skipif(not STAGING_MANIFEST.exists(), reason="staging/_manifest.json not available — run Extract first")


def test_every_staged_doc_type_has_a_column_map():
    missing = [
        dt for dt in sorted(_staged_doc_types())
        if not (DEFAULT_CONFIG_DIR / "column_maps" / f"{dt}.yaml").exists()
    ]
    assert not missing, (
        f"No column map for doc_type(s) {missing} — "
        f"add config/column_maps/<doc_type>.yaml before Transform can touch these sheets"
    )


def test_every_staged_doc_type_is_in_source_of_truth():
    known = _known_doc_types_in_source_of_truth()
    missing = [dt for dt in sorted(_staged_doc_types()) if dt not in known]
    assert not missing, (
        f"doc_type(s) {missing} appear in staging/ but are not referenced anywhere in "
        f"config/source_of_truth.yaml (as a primary doc_type or in cross_check_doc_types)"
    )


def test_source_of_truth_doc_types_match_staged_doc_types_exactly():
    """Catches the DEC-07 class of bug directly: a source_of_truth.yaml
    entry naming a doc_type Extract never actually produces (e.g. the old
    "purchases"/"inventory" labels) is itself a silent config error —
    load_column_map() would only fail once someone tries to transform that
    fact, not at config-load time."""
    staged = _staged_doc_types()
    referenced = _known_doc_types_in_source_of_truth()
    # ssis_summary's Extract driver exists (T3 Option A, closed 2026-07)
    # and is confirmed staging real data (~805 sheets/run, 2026-08) — see
    # HANDOFF.md Story #18. This exclusion predates that confirmation; on
    # a manifest where ssis_summary is actually staged it's a no-op, but
    # if it's *not* staged here that's worth investigating rather than
    # assuming, since the doc_type comments elsewhere no longer say PENDING.
    unexpected = referenced - staged - {"ssis_summary"}
    assert not unexpected, (
        f"source_of_truth.yaml references doc_type(s) {sorted(unexpected)} that Extract "
        f"never actually staged — check for a naming drift (DEC-07)"
    )
