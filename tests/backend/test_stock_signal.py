"""backend/stock_signal: the candidate label is applied (2026-11-15); the MAPE headline sets no month apart, its variant sets apart
the months the label flags."""
import pytest

from backend import marts, stock_signal as ss


def test_the_label_is_the_candidate_rule_and_the_variant_follows_it():
    assert ss.RULE == ss.CANDIDATE_RULE == "absent_at_close"
    assert ss.MAPE_VARIANT_APART == "closing_count"


def test_the_card_sql_uses_the_candidate_label_and_the_closing_count_variant():
    sql, _ = marts.accuracy_summary_query("2025-03", "2026-02")
    assert "CASE WHEN closing_pieces IS NULL OR count_possibly_partial THEN NULL ELSE closing_pieces = 0 END" in sql
    assert "(closing_pieces = 0 AND NOT COALESCE(count_possibly_partial, false))" in sql
    assert "opening_pieces = 0 OR closing_pieces = 0" not in sql
    # headline: nothing set apart but a rule-ordered month
    assert "AND actual_pieces > 0) AS ape_n," in sql


def test_the_stored_rule_is_still_selectable_and_untouched():
    assert ss.flag_sql(ss.CURRENT_RULE) == "possibly_stock_limited"
    rows = [{"possibly_stock_limited": True, "closing_pieces": 5}]
    assert ss.apply_to_rows(rows, rule=ss.CURRENT_RULE) is rows and rows[0]["possibly_stock_limited"] is True


def test_the_candidate_flags_absence_at_the_closing_count_only():
    assert ss.candidate_flag({"closing_pieces": 0}) is True
    assert ss.candidate_flag({"opening_pieces": 0, "closing_pieces": 40}) is False      # restocked: sold normally (0.93x)
    assert ss.candidate_flag({"closing_pieces": None}) is None                          # no count
    assert ss.candidate_flag({"closing_pieces": 0, "count_possibly_partial": True}) is None
    rows = [{"possibly_stock_limited": True, "opening_pieces": 2, "closing_pieces": 30}]
    assert ss.apply_to_rows(rows)[0]["possibly_stock_limited"] is False                # served rows follow the candidate


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
