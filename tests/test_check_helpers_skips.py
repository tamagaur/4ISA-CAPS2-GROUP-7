"""The skip check's allow-list (2026-10-30): exactly the known opt-in skips pass; anything else still fails."""
import xml.etree.ElementTree as ET

from scripts import check_helpers as ch

REASON = "needs FILLS_SCRATCH_SCHEMA (a filled rehearsal schema)"


def _xml(tmp_path, cases):
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite")
    for classname, name, skip in cases:
        tc = ET.SubElement(suite, "testcase", classname=classname, name=name)
        if skip is not None:
            ET.SubElement(tc, "skipped", message=skip)
    p = tmp_path / "r.xml"
    ET.ElementTree(root).write(p)
    return str(p)


ALLOWED = {"t.mod::test_known": REASON}


def test_the_allow_listed_skip_passes(tmp_path):
    assert ch.cmd_junit(_xml(tmp_path, [("t.mod", "test_known", REASON), ("t.mod", "test_ok", None)]), ALLOWED) == 0


def test_a_new_skip_outside_the_list_fails(tmp_path):
    assert ch.cmd_junit(_xml(tmp_path, [("t.mod", "test_known", REASON), ("t.mod", "test_new", "needs X_Y")]), ALLOWED) == 1


def test_the_same_test_skipping_for_another_reason_fails(tmp_path):
    assert ch.cmd_junit(_xml(tmp_path, [("t.mod", "test_known", "needs SOMETHING_ELSE")]), ALLOWED) == 1


def test_a_stale_allow_list_entry_fails(tmp_path):
    assert ch.cmd_junit(_xml(tmp_path, [("t.mod", "test_ok", None)]), ALLOWED) == 1


def test_the_committed_list_is_exactly_the_twenty_one():
    """18 decided 2026-10-30; 3 added 2026-11-02 for tests that pin SSM's real files, which are never committed."""
    allowed = ch.load_allowed()
    assert len(allowed) == 21
    assert sum(n.startswith("tests.etl.test_fills_db::") for n in allowed) == 17
    assert "tests.etl.test_rollover_scratch::test_rollover_on_a_scratch_schema_with_a_synthetic_march" in allowed
    assert {n for n in allowed if "real" in allowed[n] or "issue4" in allowed[n]} == {
        "tests.etl.test_layout_regression::test_content_identification_reproduces_todays_family_and_month_for_every_file",
        "tests.etl.test_extract::test_parse_unilever_sku_against_real_file",
        "tests.backend.test_policy_comparison::test_pesos_reproduce_the_lp_logic_check_totals"}


def test_no_allow_list_means_no_skip_is_allowed(tmp_path):
    """Every run except the whole suite (e.g. the invariants) calls cmd_junit with no list: any skip fails."""
    assert ch.cmd_junit(_xml(tmp_path, [("t.mod", "test_known", REASON)])) == 1
