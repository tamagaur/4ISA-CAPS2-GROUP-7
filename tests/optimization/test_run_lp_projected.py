"""run_lp reads the opening stock from stock_opening_v and may plan on a PROJECTED opening (2026-10-24, 0069).

The safety property relaxed on purpose: before, a cycle with no stock count for the month before it was refused. Now it is
planned on a projection and LABELLED. What stays: no later count is ever used, a count a ruling sets aside is still
refused, --require-count restores the refusal, and with nothing decided the view equals the count.
"""
from __future__ import annotations

import datetime
import logging

import pytest

from scripts import run_lp
from scripts.run_lp import check_stock_periods, month_before, opening_counts, plan_cycle, run_notes, run_record
from tests.optimization.test_run_lp_script import (
    CYCLE, _COUNTED_2026_03_02, _COUNTED_2026_04_06, _FakeDB, _args, _count_row, _product, _run_main,
)

PROJECTION = {"unilever": {"principal": "unilever", "opening_basis": "projected", "count_period": "2026-01",
                           "count_date": datetime.date(2026, 2, 3), "products": 800, "expected_receipt_pieces": 1200.0,
                           "expected_receipts": 3, "sales_actual": 790, "sales_forecast": 0, "sales_none": 0}}
COUNT_BASIS = {"unilever": {**PROJECTION["unilever"], "opening_basis": "count", "count_period": "2026-02",
                            "count_date": _COUNTED_2026_03_02, "expected_receipt_pieces": 0.0, "expected_receipts": 0}}


def test_month_before_crosses_the_year():
    assert month_before("2026-03") == "2026-02" and month_before("2026-01") == "2025-12"


def test_a_count_basis_cycle_is_labelled_count_and_a_missing_count_is_projected_when_there_is_a_projection():
    usable, refused = opening_counts(CYCLE, {"unilever"}, {"unilever": _count_row(812, _COUNTED_2026_03_02)}, COUNT_BASIS)
    assert usable["unilever"]["opening_basis"] == "count" and refused == {}
    usable, refused = opening_counts(CYCLE, {"unilever"}, {}, PROJECTION)
    info = usable["unilever"]
    assert refused == {} and info["opening_basis"] == "projected" and info["available"]
    assert info["period"] == "2026-01"                       # the count it starts from: the month BEFORE the opening month
    assert info["projection"]["sales_actual_products"] == 790 and info["projection"]["expected_receipt_pieces"] == 1200.0


def test_require_count_restores_the_refusal():
    usable, refused = opening_counts(CYCLE, {"unilever"}, {}, PROJECTION, require_count=True)
    assert usable == {} and "no opening stock count for March 2026" in refused["unilever"]


def test_a_missing_count_with_no_projection_is_still_refused():
    usable, refused = opening_counts(CYCLE, {"unilever"}, {}, {})
    assert usable == {} and "no opening stock count for March 2026" in refused["unilever"]


def test_a_count_a_ruling_sets_aside_is_refused_and_never_projected_over(monkeypatch):
    import backend.stock_units as su
    monkeypatch.setattr(su, "opening_count_ruling", lambda principal, period: ("missing", "set aside by the team"))
    usable, refused = opening_counts(CYCLE, {"unilever"}, {"unilever": _count_row(812, _COUNTED_2026_03_02)}, PROJECTION)
    assert usable == {} and "set aside" in refused["unilever"]


def test_a_projected_product_carries_the_earlier_count_and_a_later_one_is_still_refused():
    args = _args()
    ok = _product(1, stock_period="2026-01")
    ok.opening_basis = "projected"
    assert plan_cycle([ok], args, CYCLE).orders is not None
    for wrong in ("2026-02", "2026-03", "2025-12", None):        # the opening month's own count, a later one, an older one
        bad = _product(1, stock_period=wrong)
        bad.opening_basis = "projected"
        with pytest.raises(ValueError):
            check_stock_periods([bad], CYCLE)
    with pytest.raises(ValueError, match="stock count of 2026-02"):
        check_stock_periods([_product(1, stock_period="2026-01")], CYCLE)   # a COUNT-basis product still needs 2026-02


def test_the_run_record_and_notes_say_projected():
    usable, _ = opening_counts(CYCLE, {"unilever"}, {}, PROJECTION)
    plan = plan_cycle([_product(1, stock_period="2026-01")], _args(), None)
    record = run_record(_args(), plan, CYCLE, usable)
    assert record["inputs"]["opening_basis"] == "projected"
    entry = record["inputs"]["stock_counts"]["unilever"]
    assert entry["opening_basis"] == "projected" and entry["period"] == "2026-01"
    assert entry["projection"]["expected_receipt_pieces"] == 1200.0
    note = next(n for n in record["inputs"]["notes"] if "PROJECTED OPENING, NOT A COUNT" in n)
    assert "count of 2026-01" in note and "790 products from actual sales" in note
    assert any("PROJECTED OPENING" in n for n in run_notes(usable))


def test_main_plans_on_a_projection_when_the_opening_count_is_not_loaded(monkeypatch, caplog):
    db = _FakeDB(counts={"2026-01": [("unilever", 747, datetime.date(2026, 2, 3))]}, stock={},
                 view={"basis": PROJECTION, "stock": {1: (True, 900.0)}})
    with caplog.at_level(logging.INFO, logger="scripts.run_lp"):
        _run_main(monkeypatch, db)
    sent = [s for s, _ in db.statements]
    run_at = next(i for i, s in enumerate(sent) if s.startswith("INSERT INTO lp_run"))
    inputs = db.statements[run_at][1][2].adapted
    assert inputs["opening_basis"] == "projected"
    assert inputs["stock_counts"]["unilever"]["opening_basis"] == "projected"
    assert "PROJECTED opening" in caplog.text
    cycle_param = [p for s, p in db.statements if "FROM stock_opening_v" in s and "AS in_stock_file" in s]
    assert cycle_param and cycle_param[0]["cycle"] == CYCLE      # the stock came from the view, for that cycle


def test_main_refuses_the_same_cycle_with_require_count(monkeypatch, caplog):
    db = _FakeDB(counts={"2026-01": [("unilever", 747, datetime.date(2026, 2, 3))]}, stock={},
                 view={"basis": PROJECTION, "stock": {1: (True, 900.0)}})
    with caplog.at_level(logging.INFO, logger="scripts.run_lp"):
        _run_main(monkeypatch, db, "--require-count")
    assert not any(s.startswith("INSERT") for s, _ in db.statements)
    assert "no opening stock count for March 2026" in caplog.text


def test_main_with_the_count_and_nothing_decided_reads_the_view_as_the_count_alone(monkeypatch):
    db = _FakeDB(counts={"2026-02": [("unilever", 812, _COUNTED_2026_03_02)]}, stock={},
                 view={"basis": COUNT_BASIS, "stock": {1: (True, 2000.0)}})
    _run_main(monkeypatch, db)
    run_at = next(i for i, (s, _) in enumerate(db.statements) if s.startswith("INSERT INTO lp_run"))
    stock = db.statements[run_at][1][2].adapted["stock_counts"]["unilever"]
    assert stock["opening_basis"] == "count" and stock["period"] == "2026-02"


def test_the_view_query_binds_one_cycle_and_never_the_latest_count():
    q = " ".join(run_lp.STOCK_AND_COST_FROM_VIEW_QUERY.split())
    assert "WHERE principal = 'unilever' AND cycle = %(cycle)s" in q
    assert "MAX(" not in q.split("LEFT JOIN LATERAL")[0]


def test_the_docstring_states_the_loosening_plainly():
    assert "SAFETY PROPERTY RELAXED, DELIBERATELY" in run_lp.__doc__
    assert "PLANS ON A PROJECTED" in run_lp.__doc__ and "--require-count" in run_lp.__doc__


def test_receipts_reach_only_the_stock_on_hand_never_the_forecast_safety_stock_or_the_objective():
    """The boundary that stays (2026-10-24): expected receipts and decided quantities move the opening stock and
    nothing else. No forecasting or optimisation module so much as names the ledger or the view."""
    import pathlib
    repo = pathlib.Path(__file__).resolve().parents[2]
    for root in ("analytics/forecasting", "analytics/optimization"):
        for path in (repo / root).rglob("*.py"):
            text_ = path.read_text(encoding="utf-8")
            for name in ("expected_receipt", "stock_opening_v", "decided_q_i", "plan_q_i"):
                assert name not in text_, (path, name)
    source = (repo / "scripts/run_lp.py").read_text(encoding="utf-8")
    assert "decided_q_i" not in source and "expected_receipt " not in source.replace("expected_receipt_pieces", "")
