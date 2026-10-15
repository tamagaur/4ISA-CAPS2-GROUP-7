"""backend.series_gaps: the reason a chart point has no value (chart shaping only)."""
from backend.series_gaps import gap_note, month_range, unilever_points


def test_month_range_crosses_a_year_end():
    assert month_range("2025-11", "2026-02") == ["2025-11", "2025-12", "2026-01", "2026-02"]


def test_no_row_between_first_and_last_sale_is_zero_no_sale():
    pts = unilever_points({"2026-01": 5.0, "2026-04": 7.0})
    assert [(p["period"], p["quantity"], p["reason"]) for p in pts] == [
        ("2026-01", 5.0, None), ("2026-02", 0.0, "no_sale"), ("2026-03", 0.0, "no_sale"), ("2026-04", 7.0, None)]


def test_blank_quantity_is_null_never_zero():
    pts = {p["period"]: p for p in unilever_points({"2026-01": 5.0, "2026-02": None, "2026-03": 1.0})}
    assert pts["2026-02"]["quantity"] is None and pts["2026-02"]["reason"] == "blank_capture"


def test_outside_lifespan_is_null_and_a_real_zero_row_has_no_reason():
    pts = {p["period"]: p for p in unilever_points({"2026-02": 0.0, "2026-03": 4.0}, "2026-01", "2026-05")}
    assert (pts["2026-01"]["quantity"], pts["2026-01"]["reason"]) == (None, "outside_product_lifespan")
    assert (pts["2026-02"]["quantity"], pts["2026-02"]["reason"]) == (0.0, None)
    assert (pts["2026-05"]["quantity"], pts["2026-05"]["reason"]) == (None, "outside_product_lifespan")


def test_empty_series_and_note():
    assert unilever_points({}) == []
    assert gap_note([]) is None
    assert gap_note(["no_sale"]).startswith("[no_sale]")
