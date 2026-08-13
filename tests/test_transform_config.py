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
    fact, not at config-load time.

    One exemption below — daily_sales_report: PERMANENT. Investigated
    2026-08 (Transform reconciliation, story #16) — the current corpus
    has zero files matching the true daily-report naming convention (see
    the comment on DAILY_REPORT_RE in analytics/etl/extract/_shared.py).
    This is a structural fact about the corpus, not an accident, so it
    stays exempt permanently.

    (unilever_sku and ssis_summary were both previously listed here as
    temporary exemptions — "no Extract driver yet" for ssis_summary,
    "source file not in our possession" for unilever_sku. Both are now
    resolved: T3 shipped ssis_summary's driver, and the La Union SKU
    file was delivered 2026-08 and stages 24,906 real rows every run —
    removed rather than left as stale no-op exemptions. Mixing a
    permanent structural fact with a temporary data-availability gap
    under one exemption set would encode an accident as config truth,
    the exact failure mode DEC-07 itself exists to catch — that's why
    this docstring calls out daily_sales_report's permanence explicitly
    rather than just listing names.)
    """
    staged = _staged_doc_types()
    referenced = _known_doc_types_in_source_of_truth()
    permanent_exemptions = {"daily_sales_report"}
    unexpected = referenced - staged - permanent_exemptions
    assert not unexpected, (
        f"source_of_truth.yaml references doc_type(s) {sorted(unexpected)} that Extract "
        f"never actually staged — check for a naming drift (DEC-07)"
    )
