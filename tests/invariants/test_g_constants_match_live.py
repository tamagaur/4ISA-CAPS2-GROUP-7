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


# ---- figures stated in the rules and the docs that live reproduces (2026-11-17, the figure-provenance audit). Each is named
# ---- in docs/FIGURE_PROVENANCE.json `checked`, so scripts/figure_provenance.py --verify knows a live test reads it.
DEMO = (REPO / "docs" / "DEMO_DATA.md").read_text(encoding="utf-8")
GOVERNANCE = (REPO / "docs" / "DATA_GOVERNANCE.md").read_text(encoding="utf-8")

# A month with any row (a blank capture included) counts as present: the definition the 4,473 was stated on (2026-10-15).
GAP_SQL = """WITH m AS (SELECT product_key, left(calendar_month, 7) AS mo FROM unilever_sku_demand_fact_real GROUP BY 1, 2),
                  s AS (SELECT product_key, MIN(mo) AS lo, MAX(mo) AS hi, COUNT(*) AS n FROM m GROUP BY 1),
                  g AS (SELECT (left(hi, 4)::int * 12 + right(hi, 2)::int) - (left(lo, 4)::int * 12 + right(lo, 2)::int) + 1 - n AS gap FROM s)
             SELECT SUM(gap) AS gap_months, COUNT(*) FILTER (WHERE gap > 0) AS with_gap, COUNT(*) AS products FROM g"""


def test_unilever_gap_and_blank_capture_figures_are_live(sql):
    """CLAUDE.md ("Why data is missing") and docs/DEMO_DATA.md section 6: Unilever's in-span gap months; CLAUDE.md's blank captures."""
    g = sql(GAP_SQL)[0]
    live = (int(g["gap_months"]), int(g["with_gap"]), int(g["products"]))
    for where, text in (("CLAUDE.md", CLAUDE), ("docs/DEMO_DATA.md", DEMO)):
        m = _found(r"([\d,]+) in-span gap-months across (\d+) of\s+([\d,]+) products", text, where)
        assert (int(_num(m[1])), int(m[2]), int(_num(m[3]))) == live, f"{where} states {m[0]!r}; live gives {live}"
    b = sql("""SELECT COUNT(*) AS n, COUNT(DISTINCT product_key) AS skus FROM unilever_sku_demand_fact_real
               WHERE quantity_sold IS NULL""")[0]
    after = sql("""SELECT COUNT(DISTINCT d.product_key) AS n FROM unilever_sku_demand_fact_real d
                   JOIN (SELECT product_key, MIN(calendar_month) AS first FROM unilever_sku_demand_fact_real
                         WHERE quantity_sold > 0 GROUP BY 1) s ON s.product_key = d.product_key
                   WHERE d.quantity_sold IS NULL AND d.calendar_month > s.first""")[0]["n"]
    m = _found(r"never read as zero \((\d+) rows, (\d+) SKUs\)", CLAUDE, "CLAUDE.md's NULL QUANTITY note")
    assert (int(m[1]), int(m[2])) == (b["n"], b["skus"])
    m = _found(r"a blank after its first sale \((\d+) of the (\d+)\)", CLAUDE, "CLAUDE.md's NULL QUANTITY note")
    assert (int(m[1]), int(m[2])) == (after, b["skus"])


def test_data_governance_inventory_counts_are_live(sql):
    """docs/DATA_GOVERNANCE.md's data inventory: the counts of each personal or confidential column it names."""
    cases = [
        (r"`customer_dimension.customer_name` \(([\d,]+) distinct\)", "SELECT COUNT(DISTINCT customer_name) AS n FROM customer_dimension"),
        (r"`salesreturn_fact.customer_name` \(([\d,]+)\)", "SELECT COUNT(DISTINCT customer_name) AS n FROM salesreturn_fact"),
        (r"`salesman_dimension.salesman_name` \(([\d,]+) distinct\)", "SELECT COUNT(DISTINCT salesman_name) AS n FROM salesman_dimension"),
        (r"`etl_quarantine.raw_values` \(([\d,]+) rows", "SELECT COUNT(*) AS n FROM etl_quarantine"),
        (r"`invoice_num` on `sales_fact` \(([\d,]+) distinct\)", "SELECT COUNT(DISTINCT invoice_num) AS n FROM sales_fact"),
        (r"`salesreturn_fact` \(([\d,]+)\), `purchase_fact`", "SELECT COUNT(DISTINCT invoice_num) AS n FROM salesreturn_fact"),
        (r"`purchase_fact` \(([\d,]+)\) \| Confidential", "SELECT COUNT(DISTINCT invoice_num) AS n FROM purchase_fact"),
    ]
    for pattern, query in cases:
        m = _found(pattern, GOVERNANCE, "docs/DATA_GOVERNANCE.md")
        assert int(_num(m[1])) == sql(query)[0]["n"], f"docs/DATA_GOVERNANCE.md states {m[0]!r}; live differs"


def test_demo_data_doc_counts_are_live(sql):
    """docs/DEMO_DATA.md: the rows per origin of each demonstration run, Del Monte's generated stock, its demo order plan."""
    origins = ("real_copy", "interpolated", "bridged", "forward_filled", "backcast")
    dm = {r["origin"]: r["n"] for r in sql("SELECT origin, COUNT(*) AS n FROM demo.dm_category_sales WHERE run_id = 7 GROUP BY 1")}
    m = _found(r"\| 7 `demonstration` \| Del Monte \| category \| ([\d,]+) \| ([\d,]+) \| ([\d,]+) \| ([\d,]+) \| ([\d,]+) \|", DEMO,
               "docs/DEMO_DATA.md section 1")
    assert tuple(int(_num(x)) for x in m.groups()) == tuple(dm.get(o, 0) for o in origins)
    un = sql("SELECT run_id, origin, COUNT(*) AS n FROM demo.unilever_sku_sales GROUP BY 1, 2")
    runs = sorted({r["run_id"] for r in un})
    m = _found(r"\| ([\d, ]+) `demonstration_unilever` \(each\) \| Unilever \| SKU \| ([\d,]+) \| 0 \| 0 \| 0 \| ([\d,]+) \|", DEMO,
               "docs/DEMO_DATA.md section 1")
    assert [int(x) for x in m[1].split(",")] == runs
    for run in runs:
        got = {r["origin"]: r["n"] for r in un if r["run_id"] == run}
        assert (got.get("real_copy", 0), got.get("backcast", 0)) == (int(_num(m[2])), int(_num(m[3]))), f"run {run}: {got}"
    st = sql("SELECT COUNT(*) AS n, COUNT(DISTINCT category_path) AS cats, MIN(run_id) AS lo, MAX(run_id) AS hi FROM demo.dm_category_stock")[0]
    m = _found(r"Live: ([\d,]+) rows, (\d+) categories, run_id (\d+)", DEMO, "docs/DEMO_DATA.md section 8")
    assert (int(_num(m[1])), int(m[2]), int(m[3]), int(m[3])) == (st["n"], st["cats"], st["lo"], st["hi"])
    lp = {r["category_path"]: float(r["q"]) for r in sql("SELECT category_path, ROUND(order_qty::numeric, 2) AS q FROM demo.dm_category_lp WHERE run_id = 7")}
    m = _found(r"BEVERAGE ([\d,.]+),\s+CULINARY ([\d,.]+), DAIRY ([\d,.]+), FRUITS ([\d,.]+), INNOVATION ([\d,.]+) \(before", DEMO,
               "docs/DEMO_DATA.md section 10")
    stated = dict(zip(("BEVERAGE", "CULINARY", "DAIRY", "FRUITS", "INNOVATION"), (_num(x) for x in m.groups())))
    assert stated == lp, f"docs/DEMO_DATA.md states {stated}; live demo.dm_category_lp run 7 is {lp}"


def test_pinned_figure_count_stated_in_the_runbooks_is_the_pin():
    """The runbooks' "51 pinned figures" is the count of figures in the published snapshot pin (static, no database)."""
    import json
    pin = json.loads((REPO / "docs" / "PUBLISHED_FIGURES_SNAPSHOT_2026-10-24.json").read_text(encoding="utf-8"))["figures"]

    def leaves(d):
        return sum(leaves(v) if isinstance(v, dict) else 1 for v in d.values())
    n = leaves(pin)
    for doc, pattern in (("docs/MONTHLY_LOAD_PROCEDURE.md", r"The (\d+) pinned figures \(docs/PUBLISHED_FIGURES_SNAPSHOT"),
                         ("docs/MONTH_LOAD_RUNBOOK.md", r"runs the (\d+) pinned figures")):
        m = _found(pattern, (REPO / doc).read_text(encoding="utf-8"), doc)
        assert int(m[1]) == n, f"{doc} says {m[1]} pinned figures; the pin holds {n}"


def test_chapter_figures_pre_rounding_plan_label_is_live(db):
    """scripts/chapter_figures.py labels a pinned measure "against the live plan's N before rounding": N is the plan's need
    before case-pack rounding, the `live` column of the measure's own SQL summed (lp_run 10: 326,491.32)."""
    from sqlalchemy import text

    from scripts import chapter_figures as cf
    src = (REPO / "scripts" / "chapter_figures.py").read_text(encoding="utf-8")
    m = _found(r"against the live plan's ([\d,]+) before rounding", src, "scripts/chapter_figures.py")
    q = cf.SINGLE_DELIVERY_SQL.replace("SELECT COUNT(*) AS products, SUM(q_i) AS plan_pieces,",
                                       "SELECT COUNT(*) AS products, SUM(q_i) AS plan_pieces, SUM(live) AS live_raw,")
    assert "live_raw" in q, "the measure's SQL no longer has the shape this test reads"
    live_raw = float(db.execute(text(q)).mappings().one()["live_raw"])
    assert int(_num(m[1])) == round(live_raw), f"chapter_figures says {m[1]}; live gives {live_raw:,.2f}"


def test_accuracy_as_served_quotes_stored_run_5(db):
    """scripts/accuracy_as_served.py writes "Run 5 reproduces the N% median quoted before" into docs/ACCURACY_AS_SERVED.md:
    N is stored mart.forecast_run 5's median product WAPE, scored by the generator's own stored_run_headline."""
    from analytics.config import long_read_db_url
    from scripts.accuracy_as_served import stored_run_headline
    from scripts.snapshot_published_figures import live_money
    src = (REPO / "scripts" / "accuracy_as_served.py").read_text(encoding="utf-8")
    m = _found(r"Run 5 reproduces the ([\d.]+)% median quoted before", src, "scripts/accuracy_as_served.py")
    cur = db.connection().connection.cursor()
    s5 = stored_run_headline(long_read_db_url(), 5, live_money(cur))
    assert float(m[1]) == pytest.approx(100 * s5["median_product_wape_served"], abs=0.005), \
        f"accuracy_as_served says run 5's median is {m[1]}%; live run 5 gives {100 * s5['median_product_wape_served']:.4f}%"
