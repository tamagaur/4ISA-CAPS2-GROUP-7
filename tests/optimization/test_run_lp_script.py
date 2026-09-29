"""
tests/optimization/test_run_lp_script.py — the DB-free parts of scripts/run_lp.py.

Covers the 2026-09-21 options: the safety-stock protection period (default
must reproduce every earlier run), a rerun never overwriting a decided row,
and the positive-number guard on --protection-days.
"""
from __future__ import annotations

from pathlib import Path

import argparse
import math

import pytest

from analytics.optimization.lp import Z_SCORE, compute_safety_stock
from scripts.run_lp import UPSERT_QUERY, _positive_float, safety_stock_for


def test_default_protection_period_reproduces_earlier_runs():
    assert safety_stock_for(10.0) == pytest.approx(compute_safety_stock(10.0))
    assert safety_stock_for(10.0) == pytest.approx(Z_SCORE * 10.0)


def test_safety_stock_scales_with_sqrt_of_protection_days():
    # A weekly review (5 business days) covers sqrt(5) times one day's sigma.
    assert safety_stock_for(10.0, 5) == pytest.approx(Z_SCORE * 10.0 * math.sqrt(5))


def test_rerun_only_updates_rows_still_pending():
    normalized = " ".join(UPSERT_QUERY.split())
    assert "ON CONFLICT (product_key, planning_cycle_date) DO UPDATE SET" in normalized
    assert normalized.endswith("WHERE LP_Recommendation.status = 'pending'")


def test_rerun_restamps_the_rows_it_refreshes():
    # generated_at's DEFAULT now() fires only on INSERT. Live on 2026-09-23
    # every product in the pool already had a row in its cycle, so a rerun
    # was all UPDATEs and backend/lp_cycle.py still dated the LP to the old run.
    normalized = " ".join(UPSERT_QUERY.split())
    assert "generated_at = now()" in normalized


@pytest.mark.parametrize("raw", ["0", "-1", "-0.5"])
def test_protection_days_must_be_positive(raw):
    with pytest.raises(argparse.ArgumentTypeError):
        _positive_float(raw)


def test_protection_days_accepts_fractions():
    assert _positive_float("7.5") == 7.5


def test_dry_run_is_transaction_scoped_never_session_scoped():
    """set_session(readonly=True) is session-scoped: through the :6543
    transaction pooler it leaves default_transaction_read_only on the shared
    server connection, and the next client handed it can't write — it broke
    the app's sign-ins on 2026-09-28. The dry run must stay one READ ONLY
    transaction that nothing commits: with autocommit off, psycopg2 discards
    it on conn.close() and on any error exit, so no path can leave it open."""
    source = (Path(__file__).resolve().parents[2] / "scripts/run_lp.py").read_text(encoding="utf-8")
    assert "conn.set_session(readonly" not in source  # the comment may name it; the call must not
    assert "conn.set_session(autocommit=not args.dry_run)" in source
    assert source.count('cur.execute("SET TRANSACTION READ ONLY")') == 1
    assert "conn.commit()" not in source
