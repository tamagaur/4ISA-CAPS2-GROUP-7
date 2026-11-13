"""backend/stock_signal: the switches stay at today's behaviour, and at those values nothing served changes (2026-11-13 recon)."""
import pytest

from backend import marts, stock_signal as ss


def test_the_switches_are_at_todays_behaviour():
    assert ss.RULE == ss.CURRENT_RULE == "count_or_week"
    assert ss.MAPE_APART == "either_count"


def test_todays_values_give_the_stored_column_and_the_zero_count_test_unchanged():
    assert ss.flag_sql() == "possibly_stock_limited"
    sql, _ = marts.accuracy_summary_query("2025-03", "2026-02")
    assert "(COUNT(*) FILTER (WHERE possibly_stock_limited IS TRUE))::int AS possibly_stock_limited" in sql
    assert "AND (opening_pieces = 0 OR closing_pieces = 0)) AS stockout_rows" in sql
    assert sql.count("AND NOT COALESCE(opening_pieces = 0 OR closing_pieces = 0, false)") == 2
    assert "CASE WHEN closing_pieces IS NULL" not in sql
    rows = [{"possibly_stock_limited": True, "closing_pieces": 5}]
    assert ss.apply_to_rows(rows) is rows and rows[0]["possibly_stock_limited"] is True
    assert marts._zero_stock({"opening_pieces": 0, "closing_pieces": 9}) is True


def test_the_candidate_flags_absence_at_the_closing_count_only():
    assert ss.candidate_flag({"closing_pieces": 0}) is True
    assert ss.candidate_flag({"opening_pieces": 0, "closing_pieces": 40}) is False      # restocked: sold normally (0.93x)
    assert ss.candidate_flag({"closing_pieces": None}) is None                          # no count
    assert ss.candidate_flag({"closing_pieces": 0, "count_possibly_partial": True}) is None
    rows = [{"possibly_stock_limited": True, "opening_pieces": 2, "closing_pieces": 30}]
    assert ss.apply_to_rows(rows, rule=ss.CANDIDATE_RULE)[0]["possibly_stock_limited"] is False


def test_the_mape_modes():
    assert ss.zero_stock_row({"opening_pieces": 0, "closing_pieces": 3}, "closing_count") is False
    assert ss.zero_stock_row({"opening_pieces": 3, "closing_pieces": 0}, "closing_count") is True
    assert ss.zero_stock_row({"opening_pieces": 0, "closing_pieces": 0}, "none") is False
    assert ss.zero_stock_sql("none") == "false"


def test_an_unknown_setting_is_refused():
    with pytest.raises(ValueError):
        ss.flag_sql("one_week")
    with pytest.raises(ValueError):
        ss.zero_stock_sql("both")
