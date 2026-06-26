"""
tests/classification/test_abc.py — Tests for analytics.classification.abc.

Phase 3C (CLAUDE.md Steps 10–11 — Checkpoint: all active SKUs have a tier; no nulls):
  test_tier_assignment_coverage   — every SKU receives a tier (no nulls)
  test_pareto_split               — A-tier cumulative share ≤ 80%, C-tier ≥ 95%
  test_revenue_sort_descending    — SKUs sorted correctly before cumulative sum
  test_no_negative_revenue        — guard against data cleaning gaps upstream

TODO: Implement after ETL pipeline is complete (Phase 3B).
"""

import pytest


def test_placeholder():
    """Placeholder — remove when real tests are implemented."""
    assert True
