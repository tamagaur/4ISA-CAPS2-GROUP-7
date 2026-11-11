"""Every copy of the plan's rows and pieces outside the live database equals STATE.md's plan line, which
tests/invariants/test_a_plan_agreement.py holds equal to live (2026-11-11). Before this, three copies still read
lp_run 6's 109 / 435,988 after the plan moved twice: the month-load rehearsal, the manuscript tables' check, and
CLAUDE.md's numeric gate had to be found by hand."""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _state() -> tuple[int, int]:
    line = next(ln for ln in (REPO / "STATE.md").read_text(encoding="utf-8").splitlines() if ln.startswith("plan:"))
    got = dict(re.findall(r"(\w+)=(\S+)", line))
    return int(got["rows"]), int(got["pieces"])


def test_manuscript_plan_tables_expect_the_current_plan():
    from scripts import manuscript_figures as mf
    rows, pieces = _state()
    assert (mf.PLAN_TOTALS[0], mf.PLAN_TOTALS[2]) == (rows, pieces) == mf._state_plan()
    assert sum(v[0] for v in mf.TIER_B_URGENCY.values()) == rows
    assert sum(v[2] for v in mf.TIER_B_URGENCY.values()) == pieces
    assert sum(v[0] for v in mf.TIER_B_CATEGORY.values()) == rows
    assert sum(v[2] for v in mf.TIER_B_CATEGORY.values()) == pieces


def test_the_rehearsal_starts_from_the_current_plan():
    from scripts import month_load_rehearsal as mlr
    assert mlr.START_PLAN == _state()


def test_claude_md_numeric_gate_names_the_current_plan():
    rows, pieces = _state()
    gate = next(ln for ln in (REPO / "CLAUDE.md").read_text(encoding="utf-8").splitlines() if ln.startswith("NUMERIC GATE."))
    assert f"{rows} rows, {pieces:,} pieces" in gate
