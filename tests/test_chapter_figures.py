"""The Chapter 4 code figures (docs/CHAPTER4_CODE_FIGURES.json) are pinned and drift fails (2026-11-02)."""
import json

import pytest

from scripts import chapter_figures as cf


def test_every_figure_has_a_value_and_a_command():
    pin = json.loads(cf.PIN.read_text(encoding="utf-8"))["figures"]
    assert [f["id"] for f in pin] == [i for i, _, _ in cf.FIGURES]
    assert all(f["command"] and isinstance(f["value"], (int, float)) for f in pin)
    assert all(f["query"] == " ".join(cf.DEPENDENCE_SQL.split()) for f in pin if f["id"] in cf.DEPENDENCE_IDS)


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
    rows = [("2026-01", 109, 599016, 1665182.21), ("2026-02", 109, 2232506, 431443.44), ("2026-03", 109, 737284, 1541823.73)]
    assert cf.dependence_figures(rows) == {"count_2mar_over_3feb": 3.7, "count_2mar_over_6apr": 3.0,
                                           "requirement_at_3feb_million_pieces": 1.67, "requirement_at_6apr_million_pieces": 1.54}


def test_a_dependence_read_of_the_wrong_products_is_refused():
    with pytest.raises(SystemExit):
        cf.dependence_figures([("2026-01", 108, 1, 1), ("2026-02", 108, 1, 1), ("2026-03", 108, 1, 1)])


def test_a_changed_cached_route_fails_the_check(monkeypatch, capsys):
    monkeypatch.setattr(cf, "cached_get_routes", lambda: 99)
    assert cf.cmd_verify(live=False) == 1
    assert "cached_get_routes" in capsys.readouterr().out


def test_the_cached_count_reads_the_decorators(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text('@cached("GET /a")\n@router.get("/a")\n@cached("POST /b")\n# @cached("GET /c")\n', encoding="utf-8")
    monkeypatch.setattr(cf, "ROUTERS", tmp_path)
    assert cf.cached_get_routes() == 1
