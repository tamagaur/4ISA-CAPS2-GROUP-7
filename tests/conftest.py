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

import pytest


@pytest.fixture(autouse=True)
def _demo_switch_off_unless_a_test_turns_it_on(monkeypatch):
    """DM_DEMO_ENABLED is off for every test unless the test turns it on itself
    (monkeypatch.setenv, as tests/backend/test_demo_series.py does). A laptop's .env
    may switch the demonstration on for the app (Audrey's, 2026-10-16); that must not
    change what the tests see. Set to empty, not deleted, so a load_dotenv(override=
    False) during a request cannot bring the .env value back."""
    monkeypatch.setenv("DM_DEMO_ENABLED", "")
