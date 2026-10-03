"""
tests/backend/test_stock_timing.py — which stock count a screen or a plan
reads, and when that count was taken (backend/stock_units.py, 2026-10-03).

The LP planned cycle 2026-03 from Unilever's count of 2026-04-06, the stock
left after March's sales, instead of the count of 2026-03-02 that opened
March (reports/diagnostics/lp_logic_check_2026-10-03). A plan now reads the
count of the month before its cycle or nothing; "stock now" screens keep the
latest count and say its date.
"""
from __future__ import annotations

import datetime

import pytest

from backend import data_notes
from backend.lp_cycle import lp_model_info
from backend.stock_units import (
    COUNT_DATE_NOT_LOADED,
    missing_opening_count_reason,
    month_label,
    opening_period,
    stock_count_info,
)

MARCH = datetime.date(2026, 3, 1)


def _row(row_count, first, last=None):
    return {"row_count": row_count, "first_date": first, "last_date": last or first}


@pytest.mark.parametrize("cycle, expected", [
    (MARCH, "2026-02"),
    (datetime.datetime(2026, 3, 1, 8, 0), "2026-02"),
    ("2026-03-01", "2026-02"),
    ("2026-03", "2026-02"),
    (datetime.date(2026, 1, 1), "2025-12"),  # January opens with the previous December
    ("2025-12-01", "2025-11"),
])
def test_opening_period_is_the_month_before_the_cycle(cycle, expected):
    assert opening_period(cycle) == expected


def test_month_label():
    assert month_label("2026-02") == "February 2026"
    assert month_label(MARCH) == "March 2026"


def test_unilever_count_date_is_the_files_own():
    info = stock_count_info("unilever", "2026-02", _row(812, datetime.date(2026, 3, 2)), cycle=MARCH)
    assert info["available"] is True
    assert (info["cycle"], info["period"], info["role"]) == ("2026-03-01", "2026-02", "opening")
    assert (info["counted_on"], info["counted_on_note"], info["row_count"]) == ("2026-03-02", None, 812)


def test_del_monte_count_date_is_not_shown_from_the_placeholder():
    """Del Monte's snapshot_date is the 1st of _period (DEC-12); its file's
    own "Actual as of" date isn't loaded, so no date is shown."""
    info = stock_count_info("delmonte", "2025-12", _row(415, datetime.date(2025, 12, 1)))
    assert info["available"] is True and info["role"] == "latest"
    assert info["counted_on"] is None
    assert info["counted_on_note"] == COUNT_DATE_NOT_LOADED


def test_a_count_whose_rows_carry_two_dates_names_both_and_picks_neither():
    info = stock_count_info("unilever", "2026-02", _row(10, datetime.date(2026, 3, 2), datetime.date(2026, 3, 3)))
    assert info["counted_on"] is None and "2026-03-02 to 2026-03-03" in info["counted_on_note"]


def test_no_opening_count_says_so_in_the_apps_words():
    info = stock_count_info("unilever", "2026-02", None, cycle=MARCH)
    assert info["available"] is False
    assert info["reason"] == missing_opening_count_reason("unilever", MARCH)
    assert info["reason"] == "no opening stock count for March 2026: unilever has no stock count for February 2026"


def test_a_flagged_count_without_a_ruling_is_used_and_carries_its_note(monkeypatch):
    monkeypatch.setattr(data_notes, "OPENING_COUNT_RULINGS", {})
    info = stock_count_info("unilever", "2026-02", _row(812, datetime.date(2026, 3, 2)), cycle=MARCH)
    assert info["available"] is True
    assert info["flag"] == data_notes.UNUSUAL_STOCK_SNAPSHOTS[("unilever", "2026-02")]


def test_the_2_march_2026_count_is_accepted_pending_ssm_confirmation():
    """Decided 2026-10-03: March 2026 plans from the count of 2 March 2026,
    labelled pending SSM confirmation. The outlier note stays for the charts."""
    treat_as, label = data_notes.opening_count_ruling("unilever", "2026-02")
    assert treat_as == "use" and "pending SSM confirmation" in label
    info = stock_count_info("unilever", "2026-02", _row(812, datetime.date(2026, 3, 2)), cycle=MARCH)
    assert info["available"] is True and info["flag"] == label
    assert ("unilever", "2026-02") in data_notes.UNUSUAL_STOCK_SNAPSHOTS
    assert "territory match unverified" in data_notes.PLANNING_NOTES["unilever"]


def test_a_count_ruled_missing_is_refused_like_no_count(monkeypatch):
    monkeypatch.setattr(data_notes, "OPENING_COUNT_RULINGS",
                        {("unilever", "2026-02"): ("missing", "team decision, 2026-10-03")})
    info = stock_count_info("unilever", "2026-02", _row(812, datetime.date(2026, 3, 2)), cycle=MARCH)
    assert info["available"] is False
    assert info["reason"].startswith("no opening stock count for March 2026")
    assert "set aside (team decision, 2026-10-03)" in info["reason"]
    # A ruling is about planning from the count, not about showing it.
    assert stock_count_info("unilever", "2026-02", _row(812, datetime.date(2026, 3, 2)))["available"] is True


def test_a_count_ruled_usable_carries_the_rulings_label(monkeypatch):
    monkeypatch.setattr(data_notes, "OPENING_COUNT_RULINGS",
                        {("unilever", "2026-02"): ("use", "pending SSM confirmation")})
    info = stock_count_info("unilever", "2026-02", _row(812, datetime.date(2026, 3, 2)), cycle=MARCH)
    assert info["available"] is True and info["flag"] == "pending SSM confirmation"


def test_an_unknown_ruling_fails_loudly(monkeypatch):
    monkeypatch.setattr(data_notes, "OPENING_COUNT_RULINGS", {("unilever", "2026-02"): ("ignore", "x")})
    with pytest.raises(ValueError, match="'use' or 'missing'"):
        stock_count_info("unilever", "2026-02", _row(812, datetime.date(2026, 3, 2)), cycle=MARCH)


def test_migration_0039_reaches_the_database_whole():
    """The runner strips comment lines and bare BEGIN;/COMMIT; lines before
    sending a file (scripts/run_canonical_load._strip_sql_file). The trigger
    body's own BEGIN (no semicolon) must survive, and the number must be
    free."""
    from scripts.run_canonical_load import MIGRATIONS_DIR, _assert_no_new_number_collision, _strip_sql_file

    sql = _strip_sql_file((MIGRATIONS_DIR / "0039_inventory_count_month.sql").read_text(encoding="utf-8"))
    lines = [line.strip() for line in sql.splitlines()]
    assert "BEGIN" in lines and "END;" in lines and "RETURN NEW;" in lines
    assert "BEFORE INSERT OR UPDATE OF _period, snapshot_date, principal ON Inventory_Fact" in sql
    assert "UPDATE Inventory_Fact SET _period = _period;" in sql  # the backfill fires the same rule
    assert "NEW.principal = 'unilever'" in sql  # Del Monte's placeholder date gets no offset
    _assert_no_new_number_collision(sorted(MIGRATIONS_DIR.glob("0*.sql")))


def test_lp_model_states_the_stock_count_the_run_planned_from():
    counts = {"unilever": {"period": "2026-02", "counted_on": "2026-03-02", "counted_on_note": None,
                           "row_count": 812, "flag": None}}
    run = {"run_key": 41, "planning_cycle_date": MARCH, "principal_scope": "both", "code_version": "abc",
           "created_at": datetime.datetime(2026, 10, 3, tzinfo=datetime.timezone.utc),
           "inputs": {"allocation_pct": 103.0, "stock_counts": counts},
           "model": {"weights": {}, "service_level_pct": 90.0, "z_score": 1.2816}}
    assert lp_model_info(run)["stock_counts"] == counts
    assert lp_model_info(None)["stock_counts"] is None  # no run, no count to name
    # A run recorded before 2026-10-03 has no count on file.
    assert lp_model_info({**run, "inputs": {"allocation_pct": 105.0}})["stock_counts"] is None
