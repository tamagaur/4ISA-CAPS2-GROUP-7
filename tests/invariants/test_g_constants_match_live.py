"""(g) The constants written down outside the database equal live.

Guards against: a figure that is checked only against another document. Until 2026-11-16 CLAUDE.md's numeric gate and
the manuscript's plan tables were compared with STATE.md's plan line (tests/test_plan_pins_follow_state.py, whole suite
only), and STATE.md with live, so the gate reached live through one document and only for rows and pieces; the other
constants (rows ordering, safety stock, forecast, the urgency and category tables, the migration ledger, the Tier A
count, the calendar factor's range) reached it only when someone ran scripts.manuscript_figures by hand, or never.
Each is read from live here, in scripts/check.sh --fast.

Every other manuscript statement is compared with live by `python -m scripts.manuscript_figures --verify`
(scripts/check.sh --full); the Chapter 4 code figures by scripts.chapter_figures --verify; the accuracy figures by
scripts.snapshot_published_figures --verify.
"""
import re
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[2]
CLAUDE = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
STATE = (REPO / "STATE.md").read_text(encoding="utf-8")


def _found(pattern: str, text: str, where: str) -> re.Match:
    m = re.search(pattern, text)
    assert m, f"{where} no longer states this in the form the check reads ({pattern!r}): restore the sentence or update the check"
    return m


def _num(s: str) -> float:
    return float(s.replace(",", ""))


@pytest.fixture(scope="module")
def live_plan(plan):
    it = pd.DataFrame(plan["items"])
    assert not it.outside_plan.astype(bool).any()
    return it


def test_claude_md_numeric_gate_is_the_live_plan(plan, live_plan):
    gate = next(ln for ln in CLAUDE.splitlines() if ln.startswith("NUMERIC GATE."))
    m = _found(r"Plan invariant: (\d+) rows, ([\d,]+) pieces, .*?\(lp_run (\d+),", gate, "CLAUDE.md's NUMERIC GATE")
    live = (plan["count"], round(float(live_plan.plan_q_i.sum())), plan["lp_model"]["run"]["run_key"])
    assert (int(m[1]), int(_num(m[2])), int(m[3])) == live, (
        f"CLAUDE.md's numeric gate says {m[1]} rows / {m[2]} pieces / lp_run {m[3]}; the live plan is "
        f"{live[0]} / {live[1]:,} / lp_run {live[2]}")


def test_manuscript_plan_tables_are_the_live_plan(plan, live_plan, sql):
    """scripts/manuscript_figures.PLAN_TOTALS, TIER_B_URGENCY and TIER_B_CATEGORY: Tables 4.2.19 and 4.2.20, every cell."""
    from scripts import manuscript_figures as mf
    cats = pd.DataFrame(sql("SELECT sku_code AS sku_id, category_path FROM product_dimension "
                            "WHERE principal = 'unilever' AND grain = 'sku'"))
    it = live_plan.merge(cats, on="sku_id", how="left")
    for col in ("plan_q_i", "ss_i", "forecast_units"):
        it[col] = it[col].astype(float)
    totals = (len(it), int((it.plan_q_i > 0).sum()), round(it.plan_q_i.sum()), round(it.ss_i.sum()), round(it.forecast_units.sum()))
    assert totals == mf.PLAN_TOTALS, f"manuscript_figures.PLAN_TOTALS {mf.PLAN_TOTALS} != live {totals}"
    u = mf.urgency_table(it)
    live_u = {k: (int(u.loc[k, "products"]), int(u.loc[k, "ordering"]), round(u.loc[k, "order"]),
                  round(float(u.loc[k, "ss"]), 2), round(float(u.loc[k, "forecast"]), 2)) for k in mf.TIER_B_URGENCY}
    for k, pinned in mf.TIER_B_URGENCY.items():
        assert live_u[k][:3] == pinned[:3] and live_u[k][3:] == pytest.approx(pinned[3:], abs=0.005), \
            f"TIER_B_URGENCY[{k}] {pinned} != live {live_u[k]}"
    c = mf.category_plan(it)
    live_c = {k: (int(r.products), int(r.ordering), round(r.order)) for k, r in c.iterrows()}
    assert live_c == mf.TIER_B_CATEGORY, f"TIER_B_CATEGORY != live: {live_c}"


def test_state_md_plan_note_is_the_live_plan(live_plan):
    m = _found(r"(\d+) rows order >0; safety stock ([\d,]+\.\d+);", STATE, "STATE.md's plan note")
    assert int(m[1]) == int((live_plan.plan_q_i.astype(float) > 0).sum())
    assert _num(m[2]) == pytest.approx(float(live_plan.ss_i.astype(float).sum()), abs=0.005)


def test_state_md_next_migration_follows_the_live_ledger_and_the_files(sql):
    """CLAUDE.md sends every session to STATE.md for the next free migration number; a wrong one collides."""
    m = _found(r"Next migration: (\d{4}) \(ledger ends at (\d{4}), (\d+) rows", STATE, "STATE.md")
    ledger = sql("SELECT COUNT(*) AS n, MAX(filename) AS last FROM schema_migrations")[0]
    files = sorted(p.name for p in (REPO / "analytics" / "db" / "migrations").glob("[0-9][0-9][0-9][0-9]_*.sql"))
    assert (m[2], int(m[3])) == (ledger["last"][:4], ledger["n"]), f"STATE.md's ledger {m[2]} / {m[3]} rows != live {ledger}"
    assert files[-1] == ledger["last"], f"the newest migration file {files[-1]} is not the last applied on live ({ledger['last']})"
    assert int(m[1]) == int(files[-1][:4]) + 1


def test_state_md_forecast_figures_are_the_live_forecast(plan, sql):
    cycle = plan["planning_cycle_date"]
    m = _found(r"March forecast ([\d,]+\.\d+) over (\d+) 'ok' \(factor ([\d.]+) to ([\d.]+) per product", STATE, "STATE.md")
    mase = _found(r"MASE < 1 (\d+) of (\d+)", STATE, "STATE.md")
    flags = _found(r"review flags (\d+) of (\d+)", STATE, "STATE.md")
    fr = sql("""SELECT COUNT(*) AS ok, SUM(forecast_value) AS total, COUNT(*) FILTER (WHERE mase < 1) AS passed,
                       MIN((model_params ->> 'calendar_factor')::numeric) AS lo,
                       MAX((model_params ->> 'calendar_factor')::numeric) AS hi
                FROM forecast_result WHERE forecast_date = :c AND status = 'ok'""", c=cycle)[0]
    rf = sql("SELECT COUNT(*) AS n, COUNT(*) FILTER (WHERE needs_review) AS flagged FROM review_flag "
             "WHERE planning_cycle_date = :c", c=cycle)[0]
    assert (int(m[2]), _num(m[1])) == (fr["ok"], pytest.approx(float(fr["total"]), abs=0.005))
    assert (float(m[3]), float(m[4])) == (pytest.approx(float(fr["lo"]), abs=5e-5), pytest.approx(float(fr["hi"]), abs=5e-5))
    assert (int(mase[1]), int(mase[2])) == (fr["passed"], fr["ok"])
    assert (int(flags[1]), int(flags[2])) == (rf["flagged"], rf["n"])


def test_claude_md_tier_a_count_and_calendar_range_are_live(plan, sql):
    tier = _found(r"ABC method `t12m_new`; (\d+) products as of (\d{4}-\d{2})\)", CLAUDE, "CLAUDE.md's Tier A basis")
    n = sql("""SELECT COUNT(*) AS n FROM abc_classification WHERE principal = 'unilever' AND method = 't12m_new'
               AND tier = 'A' AND classification_period = :p""", p=tier[2])[0]["n"]
    assert int(tier[1]) == n, f"CLAUDE.md says {tier[1]} Tier A products as of {tier[2]}; live has {n}"
    cal = _found(r"all (\d+) `ok` `Forecast_Result` rows for March 2026 carry each product's own `calendar_factor` "
                 r"\(([\d.]+) to ([\d.]+);", CLAUDE, "CLAUDE.md's calendar factor note")
    fr = sql("""SELECT COUNT(*) AS ok, MIN((model_params ->> 'calendar_factor')::numeric) AS lo,
                       MAX((model_params ->> 'calendar_factor')::numeric) AS hi
                FROM forecast_result WHERE forecast_date = '2026-03-01' AND status = 'ok'""")[0]
    assert int(cal[1]) == fr["ok"]
    assert (float(cal[2]), float(cal[3])) == (pytest.approx(float(fr["lo"]), abs=5e-5), pytest.approx(float(fr["hi"]), abs=5e-5))
