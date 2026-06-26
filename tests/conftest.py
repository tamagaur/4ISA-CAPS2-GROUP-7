"""
tests/conftest.py — Shared pytest fixtures.

Phase 6 (CLAUDE.md Step 25):
  Fixtures needed across the test suite:
    - db_session: in-memory or test Supabase connection
    - sample_sales_df: minimal Sales Register DataFrame for ETL tests
    - sample_sku_series: toy daily time series for SARIMA tests
    - lp_inputs: minimal SKU set with forecasts for LP tests

TODO: Implement fixtures once Phase 3A (schema) and Phase 3B (ETL) are complete.
      Use pytest-asyncio for any async fixtures (FastAPI endpoint tests).
"""
