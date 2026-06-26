"""
tests/etl/test_extract.py — Tests for analytics.etl.extract parsers.

Phase 3B (CLAUDE.md Step 6 — Checkpoint: each parser returns clean DataFrame, schema validated):
  test_sales_register_columns   — confirms required columns are present
  test_unilever_sku_columns     — confirms SKU-level fields present
  test_bo_rmr_gs_separation     — Good Stock and Bad Order rows separated correctly
  test_parser_schema_mismatch   — ValueError raised on unexpected column layout

TODO: Implement after extract parsers are written (Phase 3B Step 6).
"""

import pytest


def test_placeholder():
    """Placeholder — remove when real tests are implemented."""
    assert True
