"""
scripts/chapter_figures.py - pin the figures Chapter 4 prints that come from the code or the running system, and fail
when one drifts (2026-11-02).

Pinned in docs/CHAPTER4_CODE_FIGURES.json, one entry per figure with its value and the command that produces it.
The accuracy figures are pinned separately (docs/PUBLISHED_FIGURES_SNAPSHOT_2026-10-24.json); these are the rest.

    python -m scripts.chapter_figures --measure [ID]      print the current value of one figure (or all)
    python -m scripts.chapter_figures --verify            measure the static and dependence figures, compare with the pin (scripts/check.sh --fast)
    python -m scripts.chapter_figures --verify-junit A.xml B.xml
                                                          compare the pytest totals of a whole run (invariants + suite) with the pin
                                                          (scripts/check.sh --full)
    python -m scripts.chapter_figures --write [--junit A.xml B.xml]
                                                          re-pin from the live measurement (a human act: say why in the commit)

The test totals: a run on a clean clone skips all of the opt-in list; a machine that holds SSM's real data/raw and the
per-product policy table runs REAL_DATA_TESTS and skips that many fewer. The check expects exactly
(opt-in list size) minus (REAL_DATA_TESTS that ran), so a partial environment is not a false alarm and a new unlisted
skip is still a failure (scripts/check_helpers.py already fails it).

The dependence figures (2026-11-03) read the live database, inside a READ ONLY transaction, for the plan they describe:
how far the 110 planned products of lp_run 9 (scripts/apply_final_bundle.py, 2026-11-11: safety stock following the level for
treated and zero-forecast products; lp_run 8 held 110 / 381,484, lp_run 7 110 / 419,344, lp_run 6 109) lean on the count of 2 March
2026. Pinned from the rehearsal copy (a restore of live's backup of 2026-11-11 plus the bundle), which the bundle proves equal to live. They are fixed to that run, so a later
plan does not move them; DEPENDENCE_SQL is written into the pin beside them.

The manuscript figures of 2026-11-03 read the same way, each query pinned beside its value, each fixed to a run, a period or
a window so that loading a new month does not move them: the single-delivery sensitivity (an alternative, computed read-only,
never adopted), the seasonality counts, the Critical split, and the gap between the category sum and the net sales total.

The collected total also depends on the machine: tests/etl/test_extract.py parametrizes its six raw-file tests over
"synthetic" and, only where data/raw exists, "real_corpus". The pin holds both totals (REAL_CORPUS_MARK counts the cases).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
PIN = REPO / "docs" / "CHAPTER4_CODE_FIGURES.json"
ROUTERS = REPO / "backend" / "routers"

# The tests that need SSM's real files (never committed); they are the only listed skips that can run on a machine that has them.
REAL_DATA_TESTS = (
    "tests.etl.test_layout_regression::test_content_identification_reproduces_todays_family_and_month_for_every_file",
    "tests.etl.test_extract::test_parse_unilever_sku_against_real_file",
    "tests.backend.test_policy_comparison::test_pesos_reproduce_the_lp_logic_check_totals",
)


def _permissions_module():
    """tests/backend/test_permissions.py walks the live FastAPI app the way ROUTE_COUNT does; reuse its walk."""
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")
    os.environ.setdefault("JWT_SECRET_KEY", "chapter-figures-measurement-only")   # the route walk never signs anything
    from tests.backend import test_permissions
    return test_permissions


def route_split() -> dict:
    tp = _permissions_module()
    seen = {}
    for method, path, keys, _calls in tp._routes():
        seen[(method, path)] = bool(keys)
    public = {r for r in seen if r in tp.PUBLIC}
    named = {r for r, k in seen.items() if k and r not in public}
    return {"routes_total": len(seen), "routes_public": len(public), "routes_require_sign_in": len(seen) - len(public),
            "routes_named_permission": len(named), "routes_sign_in_only": len(seen) - len(public) - len(named)}


def cached_get_routes() -> int:
    """@cached("GET /path") decorators on the routers; each is one cached GET route."""
    pat = re.compile(r'^@cached\(\s*"GET ', re.M)
    return sum(len(pat.findall(p.read_text(encoding="utf-8"))) for p in sorted(ROUTERS.glob("*.py")))


def opt_in_list_size() -> int:
    from scripts.check_helpers import load_allowed
    return len(load_allowed())


REAL_CORPUS_MARK = "[real_corpus]"


def collect_count() -> tuple[int, int]:
    """(tests collected, of which real_corpus cases) on this machine."""
    out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", "tests"],
                         cwd=REPO, capture_output=True, text=True).stdout
    m = re.search(r"(\d+) tests? collected", out)
    if not m:
        raise SystemExit("could not read the collected-test count from pytest --collect-only")
    return int(m.group(1)), sum(1 for line in out.splitlines() if "::" in line and REAL_CORPUS_MARK in line)


def read_junit(paths) -> dict:
    total = failed = skipped = real_cases = 0
    ran, skipped_ids = set(), set()
    for p in paths:
        for case in ET.parse(p).getroot().iter("testcase"):
            total += 1
            real_cases += REAL_CORPUS_MARK in (case.get("name") or "")
            tid = f"{case.get('classname')}::{case.get('name')}"
            if case.find("skipped") is not None:
                skipped += 1
                skipped_ids.add(tid)
            elif case.find("failure") is not None or case.find("error") is not None:
                failed += 1
            else:
                ran.add(tid)
    real_ran = sum(1 for t in REAL_DATA_TESTS if t in ran)
    return {"tests_collected": total, "tests_failed": failed, "tests_skipped": skipped, "tests_passed": total - skipped - failed,
            "real_data_tests_that_ran": real_ran, "real_corpus_cases": real_cases}


def measure_static() -> dict:
    return {**route_split(), "cached_get_routes": cached_get_routes(), "opt_in_list_size": opt_in_list_size()}


# For the 110 planned products (lp_run 9): stock in pieces at each count (a product the count omits is 0, as the LP reads it) and the
# requirement at that stock level, need = forecast + target stock - stock, floored at 0 (scripts/run_lp.py, before the allocation).
DEPENDENCE_SQL = """
WITH plan AS (
  SELECT lr.product_key, lr.rop_i, fr.forecast_value
  FROM lp_recommendation lr
  JOIN forecast_result fr ON fr.product_key = lr.product_key AND fr.forecast_date = lr.planning_cycle_date
  WHERE lr.planning_cycle_date = DATE '2026-03-01' AND lr.lp_run_key = 9
), stock AS (
  SELECT inv._period, inv.product_key,
         SUM(inv.quantity_on_hand) * pd.pack_size::numeric + COALESCE(SUM(inv.quantity_pieces), 0) AS pieces
  FROM inventory_fact_real inv
  JOIN plan ON plan.product_key = inv.product_key
  JOIN product_dimension pd ON pd.product_key = inv.product_key
  WHERE inv._period IN ('2026-01', '2026-02', '2026-03')
  GROUP BY inv._period, inv.product_key, pd.pack_size
), counts(period) AS (VALUES ('2026-01'), ('2026-02'), ('2026-03'))
SELECT counts.period, COUNT(*) AS products, SUM(COALESCE(stock.pieces, 0)) AS stock_pieces,
       SUM(GREATEST(0, plan.forecast_value + plan.rop_i - COALESCE(stock.pieces, 0))) AS requirement_pieces
FROM counts CROSS JOIN plan
LEFT JOIN stock ON stock._period = counts.period AND stock.product_key = plan.product_key
GROUP BY counts.period ORDER BY counts.period
"""
DEPENDENCE_PRODUCTS = 110


def dependence_figures(rows) -> dict:
    """The four published values, as the chapter rounds them, from DEPENDENCE_SQL's rows
    ((period, products, stock pieces, requirement pieces): the counts of 3 Feb, 2 Mar and 6 Apr 2026)."""
    by = {r[0]: r for r in rows}
    if {r[1] for r in rows} != {DEPENDENCE_PRODUCTS} or set(by) != {"2026-01", "2026-02", "2026-03"}:
        raise SystemExit(f"the dependence query did not read {DEPENDENCE_PRODUCTS} products at the three counts: {rows}")
    stock = {p: float(by[p][2]) for p in by}
    return {"count_2mar_over_3feb": round(stock["2026-02"] / stock["2026-01"], 1),
            "count_2mar_over_6apr": round(stock["2026-02"] / stock["2026-03"], 1),
            "requirement_at_3feb_million_pieces": round(float(by["2026-01"][3]) / 1e6, 2),
            "requirement_at_6apr_million_pieces": round(float(by["2026-03"][3]) / 1e6, 2)}


def read_dependence_rows() -> list[tuple]:
    from scripts.snapshot_published_figures import connect
    conn, cur = connect()          # BEGIN; SET TRANSACTION READ ONLY
    try:
        cur.execute(DEPENDENCE_SQL)
        return cur.fetchall()
    finally:
        conn.rollback()
        conn.close()


# The sensitivity: what the plan's own inputs would require if SSM takes one delivery a month, so the review period R falls
# inside the month's forecast F and only the lead time L is left to carry past it. Rounded up to whole case packs as the plan
# is. The live formula in the same query is the control: it must rebuild the plan, or the alternative beside it means nothing.
SINGLE_DELIVERY_SQL = """
WITH inp AS (
  SELECT lr.q_i, lr.rop_i, lr.ss_i, lr.pack_size::numeric AS pack, fr.forecast_value AS f,
         COALESCE(so.opening_pieces, 0) AS s,
         fr.forecast_value / (365.25 / 12 / 7) AS w,
         (run.inputs ->> 'lead_days')::numeric / 5 AS l_weeks
  FROM lp_recommendation lr
  JOIN lp_run run ON run.run_key = lr.lp_run_key
  JOIN forecast_result fr ON fr.product_key = lr.product_key AND fr.forecast_date = lr.planning_cycle_date
  LEFT JOIN stock_opening_v so ON so.product_key = lr.product_key AND so.cycle = lr.planning_cycle_date
  WHERE lr.planning_cycle_date = DATE '2026-03-01' AND lr.lp_run_key = 9
), need AS (
  SELECT q_i, pack, GREATEST(0, f + rop_i - s) AS live, GREATEST(0, f + w * l_weeks + ss_i - s) AS one_delivery FROM inp
)
SELECT COUNT(*) AS products, SUM(q_i) AS plan_pieces,
       SUM(CASE WHEN pack > 1 AND live > 0 THEN CEIL(live / pack - 1e-9) * pack ELSE live END) AS live_rounded,
       SUM(one_delivery) AS one_delivery_raw,
       SUM(CASE WHEN pack > 1 AND one_delivery > 0 THEN CEIL(one_delivery / pack - 1e-9) * pack ELSE one_delivery END) AS one_delivery_rounded
FROM need
"""
SINGLE_DELIVERY_FORMULA = ("need_i = max(0, F + w*L + SS - S), the live F + T - S with T's review period dropped: F the month's forecast, "
                           "w = F / (365.25 / 12 / 7) the weekly rate, L = lead_days / 5 weeks (lp_run 9: 3 days), SS the stored safety stock, "
                           "S the opening stock; the figure sums it over the 110 products of lp_run 9, each rounded up to whole case packs")
SINGLE_DELIVERY_NOTE = ("An alternative, not adopted and not written anywhere: the plan stays 110 rows and 378,700 pieces. SS is kept as stored, sized on "
                        "the 8-business-day window, although a monthly review period would widen it; so the figure is the formula's, not a re-derived "
                        "monthly policy. Supplier allocation and warehouse ceilings are not applied. Which formula applies depends on whether SSM takes "
                        "weekly deliveries or one a month, which only SSM can answer.")


def single_delivery_figures(rows) -> dict:
    products, plan, live, raw, rounded = rows[0]
    if products != DEPENDENCE_PRODUCTS or round(float(live)) != round(float(plan)):
        raise SystemExit(f"the single-delivery query does not rebuild the plan: {products} products, live formula {live}, plan {plan}")
    return {"single_delivery_requirement_pieces": round(float(rounded)),
            "single_delivery_requirement_before_case_rounding_pieces": round(float(raw))}


# lag-12 autocorrelation (analytics/forecasting/decomposition.yearly_pattern) on each product's zero-filled series to 2026-02.
# Python only because the test is the code's own (build_series, then yearly_pattern); the rows are one cohort's, nothing is moved.
SEASONALITY_SQL = """
SELECT ac.method, ac.product_key, d.calendar_month, d.quantity_sold::float AS quantity
FROM abc_classification ac
LEFT JOIN unilever_sku_demand_fact_real d ON d.product_key = ac.product_key AND d.calendar_month <= '2026-02'
WHERE ac.principal = 'unilever' AND ac.classification_period = '2026-02' AND ac.tier = 'A' AND ac.method IN ('single', 't12m_new')
"""
SEASONALITY_KEYS = ("products", "testable", "significant", "negative_hits", "expected_by_chance_one_sided", "expected_by_chance_two_sided")
SEASONALITY_ONE_TAIL = 0.025   # analytics.params.YEARLY_ACF_Z = 1.96: the label fires only above +1.96 / sqrt(n)
SEASONALITY_NOTE = ("Lag-12 autocorrelation of each product's monthly series against 1.96 / sqrt(n), for products with 24 or more months, no multiple-comparison "
                    "correction. 'Significant' is what the 'Repeats yearly' label counts: above the bound only, a one-sided test "
                    "(analytics/forecasting/decomposition.yearly_pattern), so its chance rate is the ONE-SIDED one, testable x 0.025. The two-sided rate, testable x 0.05, "
                    "is recorded so the two cannot be confused; it would apply only to a count of hits in either direction. Every hit is positive (negative_hits, pinned at 0), "
                    "so both counts are the same products, and the pin fails if a negative hit appears. "
                    "The 132 is Tier A as of 2026-02 on method 'single', the 189 Tier A as of 2026-02 on method 't12m_new'.")


def seasonality_counts(patterns) -> dict:
    """Counts over yearly_pattern() results. A series that never varies has no ACF: it was tested and is not significant.
    'significant' is the label itself, so the count and its one-sided rate cannot come apart."""
    tested = [p for p in patterns if p["acf_bound"] is not None]
    return {"products": len(patterns), "testable": len(tested),
            "significant": sum(1 for p in tested if p["repeats_yearly"]),
            "negative_hits": sum(1 for p in tested if p["acf_lag12"] is not None and p["acf_lag12"] < -p["acf_bound"]),
            "expected_by_chance_one_sided": round(len(tested) * SEASONALITY_ONE_TAIL, 3),
            "expected_by_chance_two_sided": round(len(tested) * SEASONALITY_ONE_TAIL * 2, 3)}


def seasonality_figures(cohort_132: dict, current_189: dict) -> dict:
    out = {}
    for name, c in (("132", cohort_132), ("189", current_189)):
        if c["negative_hits"]:
            raise SystemExit(f"a seasonality hit in the {name} cohort is negative, so the one-sided and two-sided counts now differ: {c}")
        out.update({f"seasonality_{name}_{k}": c[k] for k in SEASONALITY_KEYS})
    return out


def read_seasonality(rows) -> dict:
    import pandas as pd
    from analytics.forecasting.decomposition import yearly_pattern
    from scripts.run_baseline_forecast import build_series
    df = pd.DataFrame(rows, columns=["method", "product_key", "calendar_month", "quantity"])
    counts = {}
    for method, cohort in df.groupby("method"):
        patterns = []
        for _, g in cohort.groupby("product_key"):
            sold = g.dropna(subset=["calendar_month"]).assign(is_demo=False)
            values = build_series(sold, "2026-02").to_numpy() if len(sold) else []
            patterns.append(yearly_pattern([float(v) for v in values]))
        counts[method] = seasonality_counts(patterns)
    return seasonality_figures(counts["single"], counts["t12m_new"])


# Critical = stock below safety stock, on the plan's own opening stock from the 2 March 2026 count. A product absent from the
# count has no row in that count and is read as 0, which is the assumption the split exposes.
CRITICAL_SQL = """
SELECT COALESCE(so.in_stock_file, FALSE) AS in_the_count, COUNT(*) AS products,
       SUM(COALESCE(so.opening_pieces, 0)) AS stock_pieces, SUM(lr.q_i) AS order_pieces
FROM lp_recommendation lr
LEFT JOIN stock_opening_v so ON so.product_key = lr.product_key AND so.cycle = lr.planning_cycle_date
WHERE lr.planning_cycle_date = DATE '2026-03-01' AND lr.lp_run_key = 9
  AND COALESCE(so.opening_pieces, 0) < lr.ss_i
GROUP BY 1 ORDER BY 1 DESC
"""


def critical_figures(rows) -> dict:
    by = {bool(r[0]): r for r in rows}
    if set(by) != {True, False} or float(by[False][2]) != 0:
        raise SystemExit(f"the Critical query did not split into counted products and absent products read as 0: {rows}")
    counted, absent = by[True], by[False]
    return {"critical_counted_products": int(counted[1]), "critical_counted_stock_pieces": round(float(counted[2])),
            "critical_counted_order_pieces": round(float(counted[3])), "critical_absent_products": int(absent[1]),
            "critical_absent_order_pieces": round(float(absent[3])), "critical_total_order_pieces": round(float(counted[3]) + float(absent[3]))}


# March 2025 to February 2026. GET /category-trends floors each product-month row at 0 (a month whose returns exceed its sales
# counts as 0), so the sum over its categories is above the net total of the same rows by exactly the rows it floored.
CATEGORY_GAP_SQL = """
WITH by_category AS (
  SELECT COALESCE(pd.category_path, 'UNCLASSIFIED') AS category,
         SUM(GREATEST(d.net_amount, 0)) AS floored, SUM(d.net_amount) AS net
  FROM unilever_sku_demand_fact_real d JOIN product_dimension pd ON pd.product_key = d.product_key
  WHERE d.calendar_month BETWEEN '2025-03' AND '2026-02'
  GROUP BY 1
)
SELECT SUM(floored) AS sum_over_categories, SUM(net) AS net_total FROM by_category
"""


def category_gap_figures(rows) -> dict:
    floored, net = float(rows[0][0]), float(rows[0][1])
    return {"category_sum_pesos": round(floored, 2), "category_net_total_pesos": round(net, 2), "category_gap_pesos": round(floored - net, 2)}


def read_manuscript_rows() -> dict:
    from scripts.snapshot_published_figures import connect
    conn, cur = connect()          # BEGIN; SET TRANSACTION READ ONLY
    try:
        out = {}
        for name, sql in (("single_delivery", SINGLE_DELIVERY_SQL), ("seasonality", SEASONALITY_SQL),
                          ("critical", CRITICAL_SQL), ("category_gap", CATEGORY_GAP_SQL)):
            cur.execute(sql)
            out[name] = cur.fetchall()
        return out
    finally:
        conn.rollback()
        conn.close()


def manuscript_figures() -> dict:
    rows = read_manuscript_rows()
    return {**single_delivery_figures(rows["single_delivery"]), **read_seasonality(rows["seasonality"]),
            **critical_figures(rows["critical"]), **category_gap_figures(rows["category_gap"])}


def measure_all() -> dict:
    return {**measure_static(), **dependence_figures(read_dependence_rows()), **manuscript_figures()}


FIGURES = [  # id, what the chapter says, equivalent plain command
    ("routes_total", "Method/path pairs the API serves", "python -m scripts.chapter_figures --measure routes_total  (= tests/backend/test_permissions.py ROUTE_COUNT)"),
    ("routes_require_sign_in", "Routes that need a signed-in user (every route but the public ones)", "python -m scripts.chapter_figures --measure routes_require_sign_in"),
    ("routes_named_permission", "...of which gated by a named permission key", "python -m scripts.chapter_figures --measure routes_named_permission"),
    ("routes_sign_in_only", "...of which sign-in only, no permission key", "python -m scripts.chapter_figures --measure routes_sign_in_only"),
    ("routes_public", "Routes that need no sign-in (test_permissions.PUBLIC)", "python -m scripts.chapter_figures --measure routes_public"),
    ("cached_get_routes", "GET routes behind the response cache", "grep -rhE '^@cached\\(\"GET ' backend/routers | wc -l"),
    ("opt_in_list_size", "Tests allowed to skip in the whole suite (scripts/known_opt_in_skips.txt)", "grep -vc '^#' scripts/known_opt_in_skips.txt"),
    ("tests_collected_clean_clone", "Tests in the whole run on a clean clone (invariants plus suite)", "DERIVED, not run: tests_collected_with_real_data minus real_corpus_cases (scripts/chapter_figures.derived). Confirmed by a run of scripts/check.sh --full on a clean clone at fb2ff86 (STATE.md); no step of check.sh re-confirms it"),
    ("tests_collected_with_real_data", "Tests in the whole run where data/raw exists (adds the real_corpus cases)", "python -m pytest --collect-only -q tests | tail -1  (where data/raw exists)"),
    ("real_corpus_cases", "Extract test cases that exist only where data/raw exists", "python -m pytest --collect-only -q tests | grep -c 'real_corpus]'  (where data/raw exists)"),
    ("tests_failed", "Failed tests in a full run", "pinned as 0 at --write; every scripts/check.sh --full on a machine compares the run's failures with it (--verify-junit)"),
    ("tests_skipped_clean_clone", "Skipped tests on a clean clone (the whole opt-in list)", "DERIVED, not run: the length of scripts/known_opt_in_skips.txt (a clean clone skips the whole list). Confirmed by a run of scripts/check.sh --full on a clean clone at fb2ff86 (STATE.md); no step of check.sh re-confirms it"),
    ("tests_skipped_with_real_data", "Skipped tests on a machine with SSM's data/raw and the per-product policy table", "scripts/check.sh --full there"),
    ("tests_passed_clean_clone", "Passed tests on a clean clone (collected minus skipped)", "DERIVED, not run: tests_collected_clean_clone minus tests_skipped_clean_clone minus tests_failed (scripts/chapter_figures.derived). Confirmed by a run of scripts/check.sh --full on a clean clone at fb2ff86 (STATE.md); no step of check.sh re-confirms it"),
    ("tests_passed_with_real_data", "Passed tests with SSM's real files present (collected minus skipped)", "scripts/check.sh --full there"),
    ("count_2mar_over_3feb", "The 110 planned products (lp_run 9): stock at the 2 March 2026 count over the 3 February count, times", "python -m scripts.chapter_figures --measure count_2mar_over_3feb"),
    ("count_2mar_over_6apr", "The 110 planned products (lp_run 9): stock at the 2 March 2026 count over the 6 April count, times", "python -m scripts.chapter_figures --measure count_2mar_over_6apr"),
    ("requirement_at_3feb_million_pieces", "Requirement for those products at the 3 February stock level, million pieces", "python -m scripts.chapter_figures --measure requirement_at_3feb_million_pieces"),
    ("requirement_at_6apr_million_pieces", "Requirement for those products at the 6 April stock level, million pieces", "python -m scripts.chapter_figures --measure requirement_at_6apr_million_pieces"),
    ("single_delivery_requirement_pieces", "Sensitivity: requirement under one delivery a month, whole case packs, against the live plan's 378,700 (not adopted)", "python -m scripts.chapter_figures --measure single_delivery_requirement_pieces"),
    ("single_delivery_requirement_before_case_rounding_pieces", "The same before case-pack rounding, against the live plan's 374,794 before rounding (not adopted)", "python -m scripts.chapter_figures --measure single_delivery_requirement_before_case_rounding_pieces"),
    ("seasonality_132_products", "Seasonality: the 132-product cohort (Tier A as of 2026-02, method single)", "python -m scripts.chapter_figures --measure seasonality_132_products"),
    ("seasonality_132_testable", "...with 24 or more months, so testable", "python -m scripts.chapter_figures --measure seasonality_132_testable"),
    ("seasonality_132_significant", "...above the bound at lag 12, what the 'Repeats yearly' label counts", "python -m scripts.chapter_figures --measure seasonality_132_significant"),
    ("seasonality_132_negative_hits", "...below the negative bound (the pin fails if this is not 0)", "python -m scripts.chapter_figures --measure seasonality_132_negative_hits"),
    ("seasonality_132_expected_by_chance_one_sided", "...expected by chance on the label's own test, one-sided, 2.5%", "python -m scripts.chapter_figures --measure seasonality_132_expected_by_chance_one_sided"),
    ("seasonality_132_expected_by_chance_two_sided", "...expected by chance on a two-sided 5% test, which is NOT the label's", "python -m scripts.chapter_figures --measure seasonality_132_expected_by_chance_two_sided"),
    ("seasonality_189_products", "Seasonality: the current cohort (Tier A as of 2026-02, method t12m_new)", "python -m scripts.chapter_figures --measure seasonality_189_products"),
    ("seasonality_189_testable", "...with 24 or more months, so testable", "python -m scripts.chapter_figures --measure seasonality_189_testable"),
    ("seasonality_189_significant", "...above the bound at lag 12, what the 'Repeats yearly' label counts", "python -m scripts.chapter_figures --measure seasonality_189_significant"),
    ("seasonality_189_negative_hits", "...below the negative bound (the pin fails if this is not 0)", "python -m scripts.chapter_figures --measure seasonality_189_negative_hits"),
    ("seasonality_189_expected_by_chance_one_sided", "...expected by chance on the label's own test, one-sided, 2.5%", "python -m scripts.chapter_figures --measure seasonality_189_expected_by_chance_one_sided"),
    ("seasonality_189_expected_by_chance_two_sided", "...expected by chance on a two-sided 5% test, which is NOT the label's", "python -m scripts.chapter_figures --measure seasonality_189_expected_by_chance_two_sided"),
    ("critical_counted_products", "Critical (lp_run 9, count of 2 March 2026): products in the count below safety stock", "python -m scripts.chapter_figures --measure critical_counted_products"),
    ("critical_counted_stock_pieces", "...the stock they hold, pieces", "python -m scripts.chapter_figures --measure critical_counted_stock_pieces"),
    ("critical_counted_order_pieces", "...the order they carry, pieces", "python -m scripts.chapter_figures --measure critical_counted_order_pieces"),
    ("critical_absent_products", "Critical: products absent from the count, read as 0", "python -m scripts.chapter_figures --measure critical_absent_products"),
    ("critical_absent_order_pieces", "...the order they carry, pieces", "python -m scripts.chapter_figures --measure critical_absent_order_pieces"),
    ("critical_total_order_pieces", "Critical: total order, pieces", "python -m scripts.chapter_figures --measure critical_total_order_pieces"),
    ("category_sum_pesos", "Unilever sales March 2025 to February 2026, sum over categories (each row floored at 0, as GET /category-trends), PHP", "python -m scripts.chapter_figures --measure category_sum_pesos"),
    ("category_net_total_pesos", "The net twelve-month total of the same rows, PHP", "python -m scripts.chapter_figures --measure category_net_total_pesos"),
    ("category_gap_pesos", "The difference, PHP", "python -m scripts.chapter_figures --measure category_gap_pesos"),
]
DEPENDENCE_IDS = ("count_2mar_over_3feb", "count_2mar_over_6apr", "requirement_at_3feb_million_pieces", "requirement_at_6apr_million_pieces")
QUERY_OF = {
    **{i: DEPENDENCE_SQL for i in DEPENDENCE_IDS},
    **{i: SINGLE_DELIVERY_SQL for i in ("single_delivery_requirement_pieces", "single_delivery_requirement_before_case_rounding_pieces")},
    **{f"seasonality_{c}_{k}": SEASONALITY_SQL for c in ("132", "189") for k in SEASONALITY_KEYS},
    **{f"critical_{k}": CRITICAL_SQL for k in ("counted_products", "counted_stock_pieces", "counted_order_pieces",
                                               "absent_products", "absent_order_pieces", "total_order_pieces")},
    **{i: CATEGORY_GAP_SQL for i in ("category_sum_pesos", "category_net_total_pesos", "category_gap_pesos")},
}
EXTRA_OF = {  # written into the pin beside the value
    "single_delivery_requirement_pieces": {"formula": SINGLE_DELIVERY_FORMULA, "note": SINGLE_DELIVERY_NOTE},
    "single_delivery_requirement_before_case_rounding_pieces": {"formula": SINGLE_DELIVERY_FORMULA, "note": SINGLE_DELIVERY_NOTE},
    **{f"seasonality_{c}_{k}": {"note": SEASONALITY_NOTE} for c in ("132", "189") for k in SEASONALITY_KEYS if k != "products"},
}


def derived(static: dict, collected: int, real_cases: int, failed: int = 0) -> dict:
    """collected and real_cases are as measured on the machine that writes the pin; the clean-clone total is collected minus real_cases."""
    n = static["opt_in_list_size"]
    r = len(REAL_DATA_TESTS)
    clean, withdata = collected - real_cases, collected
    return {**static, "tests_collected_clean_clone": clean, "tests_collected_with_real_data": withdata, "real_corpus_cases": real_cases,
            "tests_failed": failed, "tests_skipped_clean_clone": n, "tests_skipped_with_real_data": n - r,
            "tests_passed_clean_clone": clean - n - failed, "tests_passed_with_real_data": withdata - (n - r) - failed}


def cmd_write(junit) -> int:
    static = measure_all()
    if junit:
        j = read_junit(junit)
        collected, real_cases = j["tests_collected"], j["real_corpus_cases"]
    else:
        collected, real_cases = collect_count()
    if not real_cases:
        raise SystemExit("this machine has no data/raw, so the real_corpus cases cannot be counted: re-pin on the machine that has it")
    vals = derived(static, collected, real_cases)
    out = {"pinned_on": "2026-11-03",
           "rule": "Chapter 4 prints these from the code or the live system. Re-pin only on purpose, in the commit that changes the code; "
                   "the chapter must take every figure from one commit. scripts/check.sh fails on drift.",
           "figures": [{"id": i, "what": w, "value": vals[i], "command": c,
                        **({"query": " ".join(QUERY_OF[i].split())} if i in QUERY_OF else {}), **EXTRA_OF.get(i, {})}
                       for i, w, c in FIGURES]}
    PIN.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {PIN.relative_to(REPO)}: " + ", ".join(f"{i}={vals[i]}" for i, _, _ in FIGURES))
    return 0


def _pinned() -> dict:
    return {f["id"]: f["value"] for f in json.loads(PIN.read_text(encoding="utf-8"))["figures"]}


def cmd_verify(live: bool = True) -> int:
    """`live`: also read the dependence figures from the database (check.sh, which fails first when it has none). The
    test suite passes False: it also runs on a clean clone, and tests/test_chapter_figures.py tests their arithmetic."""
    pin = _pinned()
    now = measure_all() if live else measure_static()
    bad = [f"{k}: pinned {pin.get(k)!r}, measured {v!r}" for k, v in now.items() if pin.get(k) != v]
    bad += [f"{i}: not in {PIN.name}" for i, _, _ in FIGURES if i not in pin]
    if now["opt_in_list_size"] != pin.get("tests_skipped_clean_clone"):
        bad.append(f"tests_skipped_clean_clone: pinned {pin.get('tests_skipped_clean_clone')!r}, opt-in list has {now['opt_in_list_size']}")
    for b in bad:
        print("FAIL", b)
    if bad:
        print(f"FAIL: {len(bad)} Chapter 4 code figure(s) drifted. If the change is intended, re-pin: "
              "python -m scripts.chapter_figures --write   (and update the chapter from the same commit)")
        return 1
    print("OK: " + ", ".join(f"{k}={v}" for k, v in now.items()))
    return 0


def cmd_verify_junit(paths) -> int:
    pin = _pinned()
    got = read_junit(paths)
    n_ran = got["real_data_tests_that_ran"]
    want_skipped = pin["tests_skipped_clean_clone"] - n_ran
    bad = []
    real = got["real_corpus_cases"]
    if real not in (0, pin["real_corpus_cases"]):
        bad.append(f"real_corpus_cases: pinned {pin['real_corpus_cases']} (or 0 without data/raw), ran {real}")
    want_collected = pin["tests_collected_with_real_data"] if real else pin["tests_collected_clean_clone"]
    if got["tests_collected"] != want_collected:
        bad.append(f"tests_collected: pinned {want_collected} ({'with' if real else 'without'} data/raw), ran {got['tests_collected']}")
    if got["tests_failed"] != pin["tests_failed"]:
        bad.append(f"tests_failed: pinned {pin['tests_failed']}, ran {got['tests_failed']}")
    if got["tests_skipped"] != want_skipped:
        bad.append(f"tests_skipped: expected {want_skipped} (opt-in list {pin['tests_skipped_clean_clone']} minus {n_ran} real-data test(s) that ran), got {got['tests_skipped']}")
    for b in bad:
        print("FAIL", b)
    if bad:
        print("FAIL: the pytest totals drifted from docs/CHAPTER4_CODE_FIGURES.json. If intended: python -m scripts.chapter_figures --write --junit <invariants.xml> <full.xml>")
        return 1
    print(f"OK: {got['tests_passed']} passed, {got['tests_skipped']} skipped, {got['tests_failed']} failed of {got['tests_collected']} "
          f"({n_ran} of {len(REAL_DATA_TESTS)} real-data tests ran here; {real} real_corpus cases)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--measure", nargs="?", const="all", metavar="ID")
    g.add_argument("--verify", action="store_true")
    g.add_argument("--verify-junit", nargs="+", metavar="XML")
    g.add_argument("--write", action="store_true")
    ap.add_argument("--junit", nargs="+", metavar="XML", help="with --write: take the collected total from these junit files")
    a = ap.parse_args()
    if a.measure:
        now = measure_all()
        if a.measure == "all":
            print(json.dumps(now, indent=1))
        elif a.measure in now:
            print(now[a.measure])
        elif a.measure == "tests_collected":
            print(collect_count()[0])
        else:
            raise SystemExit(f"{a.measure} is a test-run figure: scripts/check.sh --full measures it")
        return 0
    if a.verify:
        return cmd_verify()
    if a.verify_junit:
        return cmd_verify_junit(a.verify_junit)
    return cmd_write(a.junit)


if __name__ == "__main__":
    sys.exit(main())
