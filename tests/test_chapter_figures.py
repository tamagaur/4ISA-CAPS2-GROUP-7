"""The Chapter 4 code figures (docs/CHAPTER4_CODE_FIGURES.json) are pinned and drift fails (2026-11-02)."""
import json

from scripts import chapter_figures as cf


def test_every_figure_has_a_value_and_a_command():
    pin = json.loads(cf.PIN.read_text(encoding="utf-8"))["figures"]
    assert [f["id"] for f in pin] == [i for i, _, _ in cf.FIGURES]
    assert all(f["command"] and isinstance(f["value"], int) for f in pin)


def test_the_pinned_totals_add_up():
    v = {f["id"]: f["value"] for f in json.loads(cf.PIN.read_text(encoding="utf-8"))["figures"]}
    assert v["routes_total"] == v["routes_public"] + v["routes_require_sign_in"]
    assert v["routes_require_sign_in"] == v["routes_named_permission"] + v["routes_sign_in_only"]
    assert v["tests_passed_clean_clone"] + v["tests_skipped_clean_clone"] + v["tests_failed"] == v["tests_collected_clean_clone"]
    assert v["tests_passed_with_real_data"] + v["tests_skipped_with_real_data"] + v["tests_failed"] == v["tests_collected_with_real_data"]
    assert v["tests_collected_with_real_data"] - v["tests_collected_clean_clone"] == v["real_corpus_cases"]
    assert v["tests_skipped_clean_clone"] - v["tests_skipped_with_real_data"] == len(cf.REAL_DATA_TESTS)


def test_the_static_figures_match_the_pin():
    assert cf.cmd_verify() == 0


def test_a_changed_cached_route_fails_the_check(monkeypatch, capsys):
    monkeypatch.setattr(cf, "cached_get_routes", lambda: 99)
    assert cf.cmd_verify() == 1
    assert "cached_get_routes" in capsys.readouterr().out


def test_the_cached_count_reads_the_decorators(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text('@cached("GET /a")\n@router.get("/a")\n@cached("POST /b")\n# @cached("GET /c")\n', encoding="utf-8")
    monkeypatch.setattr(cf, "ROUTERS", tmp_path)
    assert cf.cached_get_routes() == 1
