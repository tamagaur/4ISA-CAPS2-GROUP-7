"""tests/forecasting/test_abc_method_pinning.py — guards the Tier-A gate against
migration 0017's `method` column.

Migration 0017 added `method` to ABC_Classification and a Phase 2 session wrote
25,437 `t3m` rows to public alongside the 23,223 `single` rows (run_id
'phase2_unilever_2026-09-17_v2'). Phase B pinned method='single' across the
backend but left the analytics/scripts layer unpinned, so
run_baseline_forecast.fetch_tier_a() was returning the UNION of both methods:
275 rows / 156 distinct keys for 2026-02 instead of 132, including 24 SKUs that
are Tier A only under t3m — a method no adviser has approved and no committed
code can reproduce. Since fetch_tier_a()'s caller iterates the DataFrame without
deduplicating (run_baseline_forecast.py:280), a --write run would have forecast
those 24 and shielded them from the orphan-delete.

These tests hit the live DB because that is the only place the two methods
coexist; the existing sqlite fixtures in tests/classification cannot express it
(sqlite uses '?' paramstyle, these queries use psycopg2's '%s'). They skip
cleanly when SUPABASE_DB_URL is absent so an offline run is unaffected.

READ-ONLY: every query here is a SELECT.
"""
from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv

from analytics.params import abc_method
from scripts.run_baseline_forecast import fetch_tier_a, resolve_abc_period

load_dotenv()

# The Tier A basis in use (analytics.params.TIER_A_BASIS, DEC-38): 'single'
# until 2026-10-05, 't12m_new' since.
DEPLOYED_METHOD = abc_method("unilever")
# The cohort as of 2026-02 on the t12m_new basis: 189, measured 2026-10-05
# (kelvin/tier-a-basis f753f4e README section 7; 132 on 'single', 2026-09-20).
# Named per CLAUDE.md standing rule 8 — never a bare "Tier A". If ABC is
# legitimately re-run this number moves, and this test SHOULD fail so the
# change is noticed rather than assumed.
COHORT_PERIOD = "2026-02"
EXPECTED_TIER_A = 189

psycopg2 = pytest.importorskip("psycopg2")

pytestmark = pytest.mark.skipif(
    not os.environ.get("SUPABASE_DB_URL"),
    reason="live DB not configured (SUPABASE_DB_URL unset)",
)


@pytest.fixture(scope="module")
def cur():
    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
    with conn.cursor() as c:
        # transaction-scoped READ ONLY, never session-level (pooler leak); nothing
        # in this module commits, so every test's read stays inside it
        c.execute("SET TRANSACTION READ ONLY")
        yield c
    conn.rollback()
    conn.close()


def _keys_for_method(cur, method: str) -> set[int]:
    cur.execute(
        """
        SELECT product_key FROM ABC_Classification
        WHERE principal = 'unilever' AND classification_period = %s
          AND tier = 'A' AND method = %s
        """,
        (COHORT_PERIOD, method),
    )
    return {r[0] for r in cur.fetchall()}


def test_fetch_tier_a_returns_only_the_basis_method(cur):
    """The gate must equal the basis's cohort exactly — not the union."""
    got = fetch_tier_a(cur, COHORT_PERIOD)
    single = _keys_for_method(cur, DEPLOYED_METHOD)

    assert set(got["product_key"]) == single


def test_fetch_tier_a_excludes_t3m_only_skus(cur):
    """The 24 t3m-only keys are the actual defect — assert none leak through."""
    got = set(fetch_tier_a(cur, COHORT_PERIOD)["product_key"])
    t3m_only = _keys_for_method(cur, "t3m") - _keys_for_method(cur, DEPLOYED_METHOD)

    assert t3m_only, "expected t3m-only keys to exist; this guard is meaningless without them"
    assert not (got & t3m_only)


def test_fetch_tier_a_returns_no_duplicate_rows(cur):
    """Caller iterates without dedup, so row count must equal key count."""
    got = fetch_tier_a(cur, COHORT_PERIOD)

    assert len(got) == got["product_key"].nunique()


def test_tier_a_cohort_size_as_of_2026_02(cur):
    """Pins the measured cohort. Was 275 rows / 156 keys while unpinned."""
    got = fetch_tier_a(cur, COHORT_PERIOD)

    assert len(got) == EXPECTED_TIER_A
    assert got["product_key"].nunique() == EXPECTED_TIER_A


def test_resolve_abc_period_is_method_pinned(cur):
    """An unpinned MAX() could resolve to a period only t3m has."""
    resolved = resolve_abc_period(cur)
    cur.execute(
        """
        SELECT MAX(classification_period) FROM ABC_Classification
        WHERE principal = 'unilever' AND method = %s
          AND classification_period <= (
              SELECT MAX(calendar_month) FROM Unilever_SKU_Demand_Fact_Real
          )
        """,
        (DEPLOYED_METHOD,),
    )

    assert resolved == cur.fetchone()[0]
