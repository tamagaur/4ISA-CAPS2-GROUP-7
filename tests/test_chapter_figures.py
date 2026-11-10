"""The Chapter 4 code figures (docs/CHAPTER4_CODE_FIGURES.json) are pinned and drift fails (2026-11-02)."""
import json

import pytest

from scripts import chapter_figures as cf


def test_every_figure_has_a_value_and_a_command():
    pin = json.loads(cf.PIN.read_text(encoding="utf-8"))["figures"]
    assert [f["id"] for f in pin] == [i for i, _, _ in cf.FIGURES]
    assert all(f["command"] and isinstance(f["value"], (int, float)) for f in pin)
    assert all(f["query"] == " ".join(cf.DEPENDENCE_SQL.split()) for f in pin if f["id"] in cf.DEPENDENCE_IDS)
    # A figure read from the live database says how: the query beside the value, never a bare number.
    assert all(f["query"] == " ".join(cf.QUERY_OF[f["id"]].split()) for f in pin if f["id"] in cf.QUERY_OF)


def test_the_single_delivery_pin_states_its_formula_and_that_it_is_not_adopted():
    pin = {f["id"]: f for f in json.loads(cf.PIN.read_text(encoding="utf-8"))["figures"]}
    entry = pin["single_delivery_requirement_pieces"]
    assert "F + w*L + SS - S" in entry["formula"]
    assert "not adopted" in entry["note"] and "not written" in entry["note"]


def test_the_pinned_totals_add_up():
    v = {f["id"]: f["value"] for f in json.loads(cf.PIN.read_text(encoding="utf-8"))["figures"]}
    assert v["routes_total"] == v["routes_public"] + v["routes_require_sign_in"]
    assert v["routes_require_sign_in"] == v["routes_named_permission"] + v["routes_sign_in_only"]
    assert v["tests_passed_clean_clone"] + v["tests_skipped_clean_clone"] + v["tests_failed"] == v["tests_collected_clean_clone"]
    assert v["tests_passed_with_real_data"] + v["tests_skipped_with_real_data"] + v["tests_failed"] == v["tests_collected_with_real_data"]
    assert v["tests_collected_with_real_data"] - v["tests_collected_clean_clone"] == v["real_corpus_cases"]
    assert v["tests_skipped_clean_clone"] - v["tests_skipped_with_real_data"] == len(cf.REAL_DATA_TESTS)


def test_the_static_figures_match_the_pin():
    assert cf.cmd_verify(live=False) == 0


def test_the_dependence_figures_are_the_published_rounding_of_the_query():
    rows = [("2026-01", 110, 598943, 1628023.44), ("2026-02", 110, 2232032, 414820.41), ("2026-03", 110, 737235, 1519085.62)]   # lp_run 7
    assert cf.dependence_figures(rows) == {"count_2mar_over_3feb": 3.7, "count_2mar_over_6apr": 3.0,
                                           "requirement_at_3feb_million_pieces": 1.63, "requirement_at_6apr_million_pieces": 1.52}


def test_a_dependence_read_of_the_wrong_products_is_refused():
    with pytest.raises(SystemExit):
        cf.dependence_figures([("2026-01", 108, 1, 1), ("2026-02", 108, 1, 1), ("2026-03", 108, 1, 1)])


def test_the_single_delivery_figures_come_from_the_query_and_its_control_holds():
    # (products, plan total, live formula rounded, one delivery raw, one delivery rounded)
    assert cf.single_delivery_figures([(110, 419344, 419344, 277386.57, 280856)]) == {   # lp_run 7
        "single_delivery_requirement_pieces": 280856, "single_delivery_requirement_before_case_rounding_pieces": 277387}


def test_a_single_delivery_read_whose_control_misses_the_plan_is_refused():
    # The same query rebuilds the live plan; if it cannot, its alternative means nothing.
    with pytest.raises(SystemExit):
        cf.single_delivery_figures([(110, 419344, 419000, 277387, 280856)])
    with pytest.raises(SystemExit):
        cf.single_delivery_figures([(108, 419344, 419344, 277387, 280856)])


def _pattern(r, months=30, bound=0.358):
    """A yearly_pattern() result: repeats_yearly is the label, which fires only above the bound (decomposition.py)."""
    return {"months": months, "acf_lag12": r, "acf_bound": bound, "repeats_yearly": None if bound is None else bool(r is not None and r > bound)}


def test_the_label_is_one_sided_so_the_rate_beside_its_count_is_too():
    patterns = [_pattern(0.5), _pattern(-0.5), _pattern(0.1), _pattern(None, months=12, bound=None)]
    assert cf.seasonality_counts(patterns) == {
        "products": 4, "testable": 3, "significant": 1, "negative_hits": 1,
        "expected_by_chance_one_sided": 0.075, "expected_by_chance_two_sided": 0.15}


def test_a_constant_series_counts_as_tested_and_not_significant():
    counts = cf.seasonality_counts([_pattern(None)])
    assert (counts["testable"], counts["significant"], counts["negative_hits"]) == (1, 0, 0)


KEEP = {"products": 132, "testable": 72, "significant": 3, "negative_hits": 0, "expected_by_chance_one_sided": 1.8, "expected_by_chance_two_sided": 3.6}
CURRENT = {"products": 189, "testable": 110, "significant": 5, "negative_hits": 0, "expected_by_chance_one_sided": 2.75, "expected_by_chance_two_sided": 5.5}


def test_the_pin_records_both_tails_and_the_observed_counts():
    out = cf.seasonality_figures(KEEP, CURRENT)
    assert (out["seasonality_132_significant"], out["seasonality_132_expected_by_chance_one_sided"], out["seasonality_132_expected_by_chance_two_sided"]) == (3, 1.8, 3.6)
    assert (out["seasonality_189_significant"], out["seasonality_189_expected_by_chance_one_sided"], out["seasonality_189_expected_by_chance_two_sided"]) == (5, 2.75, 5.5)
    assert out["seasonality_132_negative_hits"] == out["seasonality_189_negative_hits"] == 0


def test_a_negative_seasonality_hit_fails_the_pin():
    with pytest.raises(SystemExit):
        cf.seasonality_figures({**KEEP, "negative_hits": 1}, CURRENT)
    with pytest.raises(SystemExit):
        cf.seasonality_figures(KEEP, {**CURRENT, "negative_hits": 1})


def test_the_pinned_seasonality_rates_are_the_one_sided_count_beside_both_tails():
    pin = {f["id"]: f for f in json.loads(cf.PIN.read_text(encoding="utf-8"))["figures"]}
    assert not {i for i in pin if i.endswith("_expected_by_chance")}, "a bare expected-by-chance figure loses which tail it is"
    assert "one-sided" in pin["seasonality_132_significant"]["note"] and "two-sided" in pin["seasonality_132_significant"]["note"]


def test_the_critical_split_separates_counted_from_absent():
    assert cf.critical_figures([(True, 10, 3189.0, 45600.0), (False, 8, 0.0, 73044.0)]) == {
        "critical_counted_products": 10, "critical_counted_stock_pieces": 3189, "critical_counted_order_pieces": 45600,
        "critical_absent_products": 8, "critical_absent_order_pieces": 73044, "critical_total_order_pieces": 118644}


def test_an_absent_product_holding_stock_in_the_critical_split_is_refused():
    # Absent from the count means read as 0; anything else and the published split no longer describes it.
    with pytest.raises(SystemExit):
        cf.critical_figures([(True, 10, 3189.0, 45600.0), (False, 8, 5.0, 73044.0)])


def test_the_category_gap_is_the_sum_over_categories_minus_the_net_total():
    assert cf.category_gap_figures([(392655664.45, 391113139.25)]) == {
        "category_sum_pesos": 392655664.45, "category_net_total_pesos": 391113139.25, "category_gap_pesos": 1542525.20}


def test_the_skip_list_comments_state_the_size_the_list_has():
    """29 non-empty lines were once read as a disagreement with the pinned 21: eight are comments, not tests."""
    lines = [l for l in (cf.REPO / "scripts" / "known_opt_in_skips.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
    comments = [l for l in lines if l.startswith("#")]
    assert len(lines) - len(comments) == cf.opt_in_list_size()
    assert f"The {cf.opt_in_list_size()} tests allowed" in comments[0]


def test_a_changed_cached_route_fails_the_check(monkeypatch, capsys):
    monkeypatch.setattr(cf, "cached_get_routes", lambda: 99)
    assert cf.cmd_verify(live=False) == 1
    assert "cached_get_routes" in capsys.readouterr().out


def test_the_cached_count_reads_the_decorators(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text('@cached("GET /a")\n@router.get("/a")\n@cached("POST /b")\n# @cached("GET /c")\n', encoding="utf-8")
    monkeypatch.setattr(cf, "ROUTERS", tmp_path)
    assert cf.cached_get_routes() == 1
