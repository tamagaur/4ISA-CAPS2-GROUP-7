"""(c) /abc and /dashboard each state their ABC basis, and each count is reproducible from the basis it states.

Guards against: audit 2026-10-23 finding 1 - Tier A was 189 on the ABC page and 175 on the Dashboard's tier cards
with neither saying which basis it used (t12m_new vs a plain range Pareto), so a panel saw two Tier A counts for
one cohort. Both are defensible; an unlabelled number is not. Also guards a basis label that no longer matches the
rows (a label that says t12m_new over rows computed on 'single').
"""
from backend import marts


def test_abc_page_states_its_basis_and_its_tier_counts_reproduce(get, sql):
    abc = get("/abc?principal=unilever")
    basis = abc["basis"]["by_principal"]["unilever"]
    assert basis["method"] and basis["label"], "/abc does not state its ABC basis"
    period = abc["classification_period"]
    stored = sql("""SELECT tier, COUNT(*) AS n FROM abc_classification
                    WHERE principal = 'unilever' AND classification_period = :p AND method = :m GROUP BY tier""",
                 p=period, m=basis["method"])
    by_tier = {r["tier"]: int(r["n"]) for r in stored}
    summary = {t["tier"]: t["sku_count"] for t in abc["tier_summary"]}
    assert by_tier, f"no abc_classification rows for {period} / {basis['method']}: the stated basis is not in the data"
    assert summary == by_tier, f"/abc says {summary}; abc_classification ({basis['method']}, {period}) has {by_tier}"


def test_dashboard_states_its_basis_and_its_abc_mix_reproduces(get, db):
    dash = get("/dashboard?principal=unilever")
    basis = dash["abc_basis"]
    assert basis["method"] and basis["label"], "/dashboard does not state its ABC basis"
    assert basis["method"] == "range_pareto", f"unexpected dashboard basis {basis['method']!r}: extend this test"
    rev = dash["abc_revenue"]
    ranked = marts.pareto(db, rev["start_period"], rev["end_period"], "unilever")
    expected: dict[str, int] = {}
    for r in ranked:
        expected[r["class"]] = expected.get(r["class"], 0) + 1
    shown = {m["tier"]: m["count"] for m in dash["abc_mix"]}
    assert shown == expected, f"Dashboard abc_mix {shown}; pareto {rev['start_period']}..{rev['end_period']} gives {expected}"


def test_the_dashboard_names_the_planning_basis_the_abc_page_uses(get):
    """If the counts differ the Dashboard must say so (differs_from_planning_basis) instead of leaving two Tier A numbers."""
    abc, dash = get("/abc?principal=unilever"), get("/dashboard?principal=unilever")
    a_page = abc["basis"]["by_principal"]["unilever"]["method"]
    planning = dash["abc_basis"]["planning_basis"]["unilever"]["method"]
    assert planning == a_page, f"Dashboard says the planning basis is {planning}; /abc uses {a_page}"
    assert dash["abc_basis"]["differs_from_planning_basis"] == (dash["abc_basis"]["method"] != planning)
