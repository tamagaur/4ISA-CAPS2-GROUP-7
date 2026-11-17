"""scripts/figure_provenance.py: what counts as a figure, and how each class of file is held (2026-11-17).

Synthetic inputs only; the committed ledger itself is checked by `python -m scripts.figure_provenance --verify`
(scripts/check.sh, both modes)."""
import pytest

from scripts import figure_provenance as fp

CURRENT = {"globs": ["x.md"], "class": "current"}
CODE = {"globs": ["x.py"], "class": "code"}


def run(monkeypatch, path, text, rule, checked=(), not_claims=(), dated=()):
    monkeypatch.setattr(fp, "_read", lambda p: text if p == path else None)
    return {(f.line, f.figure): f.status for f in fp.scan(path, rule, list(checked), list(not_claims), list(dated))}


def test_what_counts_as_a_figure():
    assert fp.figures_in("1,807 products; 32.4% MAPE; MASE 0.722; 12 months") == ["1,807", "32.4%", "0.722", "12"]
    # dates, years, versions, paths, line references, ids, migration numbers and small integers are not figures
    assert fp.figures_in("on 2026-11-17 (2026-03), v1.2.3, scripts/x.py:120, DEC-41, A12, 0081, rule 9, lp_run 10, 3 windows") == []
    assert fp.figures_in("Table 4.2.18 and Figure 4.2.26, Steps 10–11, port 55432 on 127.0.0.1") == []
    assert fp.figures_in("a 409 answer from the route") == []          # an HTTP status beside its context
    assert fp.figures_in("raising 413", code=True) == []                # in code, a bare status is always a status


def test_an_undated_figure_in_a_current_file_is_residue_and_a_date_clears_it(monkeypatch):
    text = "# Runbook\n\nThe plan has 115 rows.\n\nOn 2026-11-13 the plan had 115 rows.\n\n## Old (2026-10-01)\n\nIt had 109 rows.\n"
    got = run(monkeypatch, "x.md", text, CURRENT)
    assert got[(3, "115")] == "residue"
    assert got[(5, "115")] == "dated"          # a date on the line
    assert got[(9, "109")] == "dated"          # a date in a heading above it


def test_a_date_anywhere_in_the_paragraph_dates_it(monkeypatch):
    text = "The count was 8,224 rows\nwhen read on 2026-11-02.\n"
    assert run(monkeypatch, "x.md", text, CURRENT)[(1, "8,224")] == "dated"


def test_figures_as_of_in_the_head_dates_the_whole_file(monkeypatch):
    text = "# Runbook\n\n> Figures as of 2026-11-05: the seed backup.\n\nIt shows 435,988 pieces.\n"
    assert run(monkeypatch, "x.md", text, CURRENT)[(5, "435,988")] == "dated"


def test_untraceable_needs_the_settle_form(monkeypatch):
    ok = "within 72 hours UNTRACEABLE (settle: cite the issuance and section)\n"
    bare = "within 72 hours UNTRACEABLE\n"
    assert run(monkeypatch, "x.md", ok, CURRENT)[(1, "72")] == "untraceable"
    assert run(monkeypatch, "x.md", bare, CURRENT)[(1, "72")] == "residue"


def test_a_checked_entry_covers_only_the_figures_it_names(monkeypatch):
    text = "Salesman names (33 distinct): 30 of the 33 are people.\n"
    entry = {"file": "x.md", "pattern": r"Salesman names \(\d+ distinct\)", "figures": ["33"], "by": "t::x"}
    got = run(monkeypatch, "x.md", text, CURRENT, checked=[entry])
    assert got[(1, "33")] == "checked" and got[(1, "30")] == "residue"


def test_code_comments_definitions_examples_and_ledger_dates(monkeypatch):
    text = ('LIMIT = 250\n'
            '# at most 250 rows a page\n'
            '# e.g. 1,234,567 is shown as 1.2M\n'
            '# the count read 1,429 when 179 were stale\n'
            '# measured 4,473 gaps\n')
    got = run(monkeypatch, "x.py", text, CODE,
              not_claims=[{"file": "x.py", "pattern": r"read 1,429 when", "kind": "example", "note": "a sample message"}],
              dated=[{"file": "x.py", "pattern": r"measured [\d,]+ gaps", "date": "2026-10-15", "source": "git blame: abc"}])
    assert got[(2, "250")] == "definition"     # the same literal is in the code
    assert got[(3, "1,234,567")] == "example"  # an e.g. line
    assert got[(4, "1,429")] == "example"        # a ledger not_claims entry
    assert got[(5, "4,473")] == "dated"        # a ledger-side date (for files a comment edit must not touch)


def test_a_param_entry_fails_when_the_stated_value_is_not_the_constant():
    text = "weights w1=0.45 purchase cost, w2=0.35 need met, w3=0.25 storage"
    entry = {"file": "x.md", "pattern": r"w1=([\d.]+) purchase cost, w2=([\d.]+) need met, w3=([\d.]+) storage",
             "params": [{"name": "analytics.params.LP_WEIGHTS", "key": k} for k in ("cost", "service_level", "storage")]}
    problems = fp._param_problem(entry, text)
    assert len(problems) == 1 and "0.25" in problems[0]
    assert fp._param_problem(entry, text.replace("w3=0.25", "w3=0.20")) == []


@pytest.mark.parametrize("head, ok", [("> **Dated record (2026-09-14), not maintained.**", True),
                                      ("> **Dated record (2026-09; last edited 2026-11-13).**", True),
                                      ("# A report written in September", False)])
def test_the_dated_record_label(head, ok):
    assert bool(fp.BANNER.search(head)) is ok


def test_every_tracked_file_has_a_class():
    led = fp.load_ledger()
    assert [f for f in fp.tracked_files() if fp.classify(f, led["rules"]) is None] == []
