"""The calendar factor as GET /dashboard reports it (2026-10-19): the forecast card's
calendar_adjustment, summed from each forecast row's own model_params, and the error
card's adjusted / unadjusted runs, told apart by the run label's suffix. Pure: no DB."""
from datetime import date

from backend import marts
from backend.routers.dashboard import calendar_adjustment


def _row(key, value, factor=None, years=None, before=None):
    return {"product_key": key, "forecast_date": date(2026, 3, 1), "forecast_value": value,
            "calendar_factor": factor, "calendar_years": years, "value_before_calendar": before}


def test_adjusted_rows_report_the_factor_and_the_total_before_it():
    rows = [_row(1, 107.62, 1.0762, 2, 100.0), _row(2, 215.24, 1.0762, 2, 200.0)]
    out = calendar_adjustment(rows)
    assert out["applied"] is True
    assert out["products"] == out["of_products"] == 2
    assert out["factor"] == 1.0762 and out["years"] == 2
    assert out["forecast_period"] == "2026-03"
    assert out["forecast_pieces"] == 322.86
    assert out["before_pieces"] == 300.0


def test_a_row_without_a_factor_counts_at_its_own_value_before_and_after():
    rows = [_row(1, 107.62, 1.0762, 2, 100.0), _row(2, 50.0)]
    out = calendar_adjustment(rows)
    assert out["products"] == 1 and out["of_products"] == 2
    assert out["forecast_pieces"] == 157.62
    assert out["before_pieces"] == 150.0


def test_different_factors_give_a_range_not_one_factor():
    rows = [_row(1, 110.0, 1.1, 2, 100.0), _row(2, 95.0, 0.95, 1, 100.0)]
    out = calendar_adjustment(rows)
    assert out["factor"] is None and out["years"] is None
    assert (out["factor_min"], out["factor_max"]) == (0.95, 1.1)
    assert (out["years_min"], out["years_max"]) == (1, 2)


def test_no_factor_anywhere_is_not_applied_and_says_nothing_else():
    out = calendar_adjustment([_row(1, 100.0), _row(2, 50.0)])
    assert out["applied"] is False
    assert "factor" not in out and "forecast_pieces" not in out
    assert calendar_adjustment([])["applied"] is False


def test_the_sign_off_flag_comes_from_params():
    from analytics import params
    assert calendar_adjustment([])["signed_off"] is params.CALENDAR_FACTOR_SIGNED_OFF


def test_calendar_adjusted_state_reads_the_label_suffix():
    adjusted = "backtest 2023-10..2026-02, Tier A the month before each month, calendar-adjusted"
    published = "backtest 2023-10..2026-02, Tier A the month before each month"
    assert marts.calendar_adjusted_state([adjusted]) == "yes"
    assert marts.calendar_adjusted_state([published]) == "no"
    assert marts.calendar_adjusted_state([adjusted, published]) == "partly"
    assert marts.calendar_adjusted_state([]) is None


def test_the_unadjusted_twin_is_the_label_without_the_suffix():
    sql, params = marts.unadjusted_twin_query(marts.DEFAULT_BACKTEST_LABEL)
    # The default is the as-served run since 2026-10-21 (Kelvin); treated since 2026-11-10; with the calendar factor at product grain
    # since 2026-11-12 (scripts/apply_calendar_grain.py): its twin is the same series' run without the calendar factor, labelled
    # ", calendar factor not applied" since migration 0080 (2026-11-13), the bare label kept as the fallback (run 16's twin, run 15).
    base = "as-served backtest 2023-10..2026-02, Tier A the month before each month, succession + fading, product calendar"
    assert params == {"off": base + ", calendar factor not applied", "base": base}
    assert "mart.forecast_run" in sql and "ORDER BY (label = :off) DESC" in sql
    company = "as-served backtest 2023-10..2026-02, Tier A the month before each month, succession + fading"
    assert marts.unadjusted_twin_labels(company + ", calendar-adjusted") == (company + ", calendar factor not applied", company)


def test_no_comparison_unless_one_adjusted_run_is_behind_the_figures():
    published = {"run_labels": ["backtest 2023-10..2026-02, Tier A the month before each month"]}
    mixed = {"run_labels": [marts.DEFAULT_BACKTEST_LABEL, "forecast_result generated 2026-10-19"]}
    assert marts.accuracy_comparison(None, published) is None
    assert marts.accuracy_comparison(None, mixed) is None
    assert marts.accuracy_comparison(None, {"run_labels": []}) is None
