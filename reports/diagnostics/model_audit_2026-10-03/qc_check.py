"""
Quality check 2026-10-03 - every README number traced to a file, plus arithmetic cross-checks. Offline.

1. pull_counts.csv: the count-only pull files behind the Scope table (inputs/ is not committed).
2. qc_numbers.csv: one row per number in README.md - matched to a committed CSV/JSON in this folder (allowing
   for rounding, %, pesos in millions, percentage points), to eebd741 (the earlier report, by git show), or to a
   design constant / identifier with its source. Anything else is UNTRACED, and the check fails.
3. qc_arithmetic.csv: sums, shares and differences quoted in the README, recomputed from the CSVs.

    ../Capstone-Project/.venv/Scripts/python.exe reports/diagnostics/model_audit_2026-10-03/qc_check.py
"""
from __future__ import annotations

import glob
import io
import json
import os
import re
import subprocess

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
INP = os.path.join(HERE, "inputs")
EEBD = ("C:/Users/kyuan/dsd-forecast-error-business", "eebd741:reports/diagnostics/forecast_error_business_2026-10-03/")
NUM = re.compile(r"(?<![\w.])([−+-]?)(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(½)?")

# Design constants and identifiers quoted in the README, with where they come from. Matched on the number AND a
# word that must appear within 60 characters before it, so a constant cannot silently trace an unrelated number.
CONSTANTS = [
    (3, r"short = 3–|short 3–|3–11|fewer than 3|3\+ months|last 3 months|3-month", "bins.py:14 (3 sales months) / MA3 window"),
    (11, r"3–11", "bins.py length_v1 (short = 3-11)"),
    (12, r"12–23", "bins.py:15 (medium starts at 12)"),
    (12, r"under 12 months|12\+ months", "quick_checks.py Q3 breakdown threshold"),
    (23, r"12–23", "bins.py length_v2 (medium ends at 23)"),
    (23, r"23 (month )?pairs", "p3_portfolio_month_effect.csv (2024-04..2026-02)"),
    (24, r"24\+", "bins.py:35 (long = 24+)"),
    (29, r"29 (months|times|retrainings)|29-month|to 29 months|same 29", "test window 2023-10..2026-02"),
    (38, r"38 months|13–38", "data span 2023-01..2026-02"),
    (13, r"13\+ months|13–38", "run_audit.py noise floor (12+ differences = 13+ months)"),
    (0.3, r"weight 0\.3|SES\(0\.3\)", "baseline.py:69"), (0.1, r"probability weight 0\.1", "baseline.py:70"),
    (4, r"Depth 4", "global_model.py:42"), (0.05, r"learning rate 0\.05", "global_model.py:42"),
    (0.8, r"subsample 0\.8|column sample 0\.8", "global_model.py:42"), (300, r"300 rounds", "global_model.py:45"),
    (1, r"1 thread", "params.py XGB_NTHREAD"), (1, r"1 is in the coh|1 in the pool", "p1_checks.csv"),
    (100, r"at least 100 rows", "global_model.py:38"),
    (6, r"6-month standard|last 6;", "global_model.py:39 (SCALE_WINDOW)"), (6, r"6 names", "p1_checks.csv"),
    (14, r"Features \(14\)|beyond the 14", "global_model.py:47-51"),
    (80, r"top 80%", "abc.py Tier A cutoff"),
    (95, r"95% (interval|limit)|95 times", "95% bootstrap interval / shuffle-null limit (quick_checks.py, run_audit.py)"),
    (100, r"95 times out of 100", "glossary definition"),
    (0, r"spans 0|drift is 0", "glossary definition / p3_noise_yardsticks.csv (median level shift 0.0)"),
    (50, r"50/50", "router.py:109"), (50, r"50 original", "coverage_map.csv"),
    (35, r"35 phase-1|35 \+ 77", "coverage_map.csv"), (35, r"about 35 products", "p3_by_volume_tercile.csv (36/35/36)"),
    (77, r"\+ 77", "coverage_map.csv"), (162, r"162", "coverage_map.csv (50 + 35 + 77)"),
    (8, r"8 target", "coverage_map.csv"), (8, r"8 in the cohort", "p1_checks.csv"),
    (2, r"2\+ real", "p1_checks.csv (MASE scale needs 2+ months)"),
    (27, r"~27%", "the earlier headline (eebd741): 26.9%"), (27, r"27 products", "p3_age24_concentration.csv"),
    (27, r"27% → 25%", "glossary illustration"), (25, r"→ 25%", "glossary illustration"),
    (12, r"9–12 \|", "table rank"),
    (100, r"under 100", "tracer rule (qc_check.py small-integer review)"),
]


def flatten(obj, out, src):
    if isinstance(obj, dict):
        for v in obj.values():
            flatten(v, out, src)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            flatten(v, out, src)
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool) and np.isfinite(obj):
        out.append((float(obj), src))
    elif isinstance(obj, str):
        for m in NUM.finditer(obj.replace("−", "-")):
            out.append((as_float(m), src))


def as_float(m) -> float:
    sign = -1.0 if m.group(1) in ("-", "−") else 1.0
    v = float(m.group(2).replace(",", "") + (m.group(3) or ""))
    return sign * (v + (0.5 if m.group(4) else 0.0))


def pool() -> list[tuple[float, str]]:
    out: list[tuple[float, str]] = []
    for f in sorted(glob.glob(os.path.join(HERE, "*.csv")) + glob.glob(os.path.join(HERE, "*.json"))):
        name = os.path.basename(f)
        if name.startswith("qc_numbers"):
            continue
        if f.endswith(".json"):
            flatten(json.load(open(f, encoding="utf-8")), out, name)
        else:
            df = pd.read_csv(f, dtype=str)
            for col in df.columns:
                for cell in df[col].dropna():
                    try:
                        out.append((float(cell), name))
                    except ValueError:
                        flatten(cell, out, name)
    for name in ("followups_results.json", "README.md"):
        txt = subprocess.run(["git", "-C", EEBD[0], "show", EEBD[1] + name], capture_output=True, text=True,
                             encoding="utf-8").stdout
        flatten(json.loads(txt) if name.endswith(".json") else txt, out, f"eebd741:{name}")
    return out


def matches(token: float, decimals: int, unit: str, vals: np.ndarray) -> np.ndarray:
    q = 10.0 ** -decimals
    cands = [vals, vals * 100]                     # ratios are quoted as % or percentage points
    if unit == "M":
        cands.append(vals / 1e6)
    hit = np.zeros(len(vals), bool)
    for c in cands:
        hit |= np.abs(np.round(c, decimals) - token) < q / 2 + 1e-9
        hit |= np.abs(np.round(np.abs(c), decimals) - abs(token)) < q / 2 + 1e-9 if unit in ("pts",) else False
    return hit


SECTION_SOURCES = {
    "Headline": {"headline_two_cohorts.csv", "headline_two_cohorts_check.json"},
    "Scope": {"pull_counts.csv", "audit_results.json", "p1_checks.csv", "cohort_107.csv"},
    "Part 1": {"p1_*.csv", "audit_results.json", "q3_pool_lookahead.csv"},
    "Part 2": {"p2_*.csv", "quick_checks_results.json", "q1_xgb_objective.csv", "q3_pool_lookahead.csv"},
    "Part 3": {"p3_*.csv", "audit_results.json"},
    "Part 4": {"q*.csv", "quick_checks_results.json", "coverage_map.csv", "untried_options_ranked.csv",
               "p3_*.csv", "p2_*.csv", "p1_checks.csv"},
    "Quality check": {"qc_summary.json", "qc_arithmetic.csv", "qc_recompute.csv", "qc_recompute.json",
                      "qc_hygiene.csv", "pull_counts.csv"},
}
ALWAYS = {"qc_arithmetic.csv", "qc_recompute.csv", "qc_recompute.json"}      # recomputed / derived values


def blocks(lines: list[str]) -> list[int]:
    """Block id per line: a bullet, numbered item, table row or paragraph, with its indented continuation lines."""
    ids, cur = [], 0
    for i, line in enumerate(lines):
        starts = (not line.strip()) or line.startswith(("#", "|", "- ", "**", "```")) or re.match(r"^\d+\. ", line) \
            or (i > 0 and not lines[i - 1].strip())
        if starts:
            cur += 1
        ids.append(cur)
    return ids


def numbers(text: str) -> pd.DataFrame:
    lines = text.splitlines()
    bid = blocks(lines)
    cites: dict[int, set] = {}
    for b, line in zip(bid, lines):
        cites.setdefault(b, set()).update(re.findall(r"`([\w.*:-]+\.(?:csv|json|md))`", line))
    rows = []
    section = ""
    for ln, line in enumerate(lines, 1):
        if line.startswith("## "):
            section = line[3:].strip()
        code_spans = [m.span() for m in re.finditer(r"`[^`]*`", line)]
        cited = set(cites[bid[ln - 1]]) | ALWAYS
        for key, src in SECTION_SOURCES.items():
            if section.startswith(key):
                cited |= src
        for m in NUM.finditer(line):
            a, b = m.span()
            before, after = line[max(0, a - 60):a], line[b:b + 14]
            tok = m.group(0)
            ident = None
            if any(s <= a < e for s, e in code_spans):
                ident = "inside a code span (file, path, line reference or code)"
            elif re.match(r"\d{4}-\d{2}", line[a:a + 7]) or (re.search(r"\d{4}-$|\d{4}-\d{2}-?$|\.\.$", before[-8:])
                                                               and re.match(r"\d{2}\b", line[a:])):
                ident = "date / period"
            elif re.fullmatch(r"202[0-9]", tok) and not after.startswith("%"):
                ident = "date / period (year)"
            elif re.match(r"^\d+\. ", line) and a == 0:
                ident = "list item number"
            elif re.search(r"Part $", before):
                ident = "section number (Part N)"
            elif re.search(r":\d+-$", before):
                ident = "file:line range"
            elif re.search(r"\d:$", before) or (after.startswith(":") and re.match(r":\d{2}", after)):
                ident = "time of day"
            elif re.search(r"entry $|Lags $|Lags \d–$|Lags 1–6 and $|and 12; $|; 3- and $|means; $|Parts $|Parts 1–$|Q1–$|"
                           r"number $|number 1–$", before):
                ident = "definition / label (feature lags, month numbers, part ranges, register entry)"
            elif re.search(r"[A-Za-z][A-Za-z_]*-?$", before) and not before.endswith(" "):
                ident = "part of a name (MA3, DEC-26, Q1, lag-12, H1 ...)"
            elif re.fullmatch(r"\d{8}", m.group(2)) or re.search(r"product key $|keys? $", before):
                ident = "product SKU code / product key"
            elif re.match(r"^\| \d+(–\d+)? \|", line) and a < 4:
                ident = "table row number"
            elif re.search(r"eebd741|953cda3|61ff127|42d5ff7|749d232|01930d7", before[-10:] + tok + after[:4]):
                ident = "commit hash"
            elif re.search(r"0038:$|migration $|DEC-$", before):
                ident = "identifier (migration / decision number)"
            elif re.search(r"\d\($|\(\d+\+$", before) or re.match(r"\)?[A-Z]\d", after):
                ident = "part of a product name or code (e.g. 48(6+1)X11G)"
            elif before.endswith(":"):
                ident = "file:line reference"
            elif re.match(r"[A-Za-z]", after) and not (after.startswith("M") and "₱" in before[-2:]):
                ident = "part of a product name or code (e.g. 288X13.5ML)"
            unit = "%" if after.startswith("%") else "M" if after.startswith("M") and "₱" in before[-2:] else \
                "pts" if re.match(r"\s*(percentage )?points?", after) else ""
            rows.append({"line": ln, "token": tok, "value": as_float(m), "decimals": len(m.group(3) or ".") - 1,
                         "unit": unit, "identifier": ident, "section": section, "cited": ";".join(sorted(cited)),
                         "raw": before[-60:] + tok + after,
                         "context": (before[-45:] + "[" + tok + "]" + after).strip()})
    return pd.DataFrame(rows)


def main():
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    # 1. pull counts (count-only, from the one pull)
    rv = pd.read_csv(os.path.join(INP, "real_view_vs_base.csv")).iloc[0]
    prov = pd.read_csv(os.path.join(INP, "provenance.csv"))
    meta = pd.read_csv(os.path.join(INP, "pull_meta.csv")).iloc[0]
    demo = prov[prov.is_demo.astype(str) == "True"]
    pc = [{"measure": "real view rows", "value": int(rv.real_view_rows)},
          {"measure": "base table is_demo = false rows", "value": int(rv.base_is_demo_false_rows)},
          {"measure": "base table is_demo = false rows with a fill_source tag", "value": int(rv.base_real_rows_with_fill_source)},
          {"measure": "base table is_demo = true rows (excluded)", "value": int(demo.rows.sum())},
          {"measure": "is_demo = true fill_source tags", "value": ";".join(demo.fill_source.astype(str))},
          {"measure": "is_demo = true first month", "value": str(demo.first_month.min())},
          {"measure": "is_demo = true last month", "value": str(demo.last_month.max())},
          {"measure": "real rows first month", "value": str(prov[prov.is_demo.astype(str) == "False"].first_month.min())},
          {"measure": "real rows last month", "value": str(prov[prov.is_demo.astype(str) == "False"].last_month.max())},
          {"measure": "pulled at (UTC)", "value": str(meta.pulled_at)},
          {"measure": "transaction_read_only", "value": str(meta.read_only)},
          {"measure": "Tier A as of 2026-02 (ABC single; the served XGBoost pool), products",
           "value": int(len(pd.read_csv(os.path.join(INP, "served_tier_a.csv"))))}]
    pd.DataFrame(pc).to_csv(os.path.join(HERE, "pull_counts.csv"), index=False)

    # 2. numbers
    text = io.open(os.path.join(HERE, "README.md"), encoding="utf-8").read()
    nums = numbers(text)
    P = pool()
    vals = np.array([v for v, _ in P])
    srcs = np.array([s for _, s in P])
    status, source = [], []
    for r in nums.itertuples():
        if r.identifier:
            status.append("identifier"), source.append(r.identifier)
            continue
        const = [src for v, kw, src in CONSTANTS if abs(v - abs(r.value)) < 1e-9 and re.search(kw, r.raw)]
        if const:
            status.append("design constant / count"), source.append(const[0])
            continue
        hit = matches(r.value, r.decimals, r.unit, vals)
        files = sorted(set(srcs[hit]))
        cited = [c for c in r.cited.split(";") if c]
        globbed = [f for f in files if any(re.fullmatch(c.replace(".", r"\.").replace("*", ".*"), f) for c in cited)]
        if globbed:
            status.append("traced to the cited file"), source.append("; ".join(globbed[:3]))
            continue
        if files and not cited:
            status.append("REVIEW: uncited line, value found in"), source.append("; ".join(files[:4]))
            continue
        if files:
            status.append("REVIEW: not in the cited file, found in"), source.append("; ".join(files[:4]))
            continue
        status.append("UNTRACED"), source.append("")
    nums["status"], nums["source"] = status, source
    nums.to_csv(os.path.join(HERE, "qc_numbers.csv"), index=False)

    # 3. arithmetic
    h = pd.read_csv(os.path.join(HERE, "headline_two_cohorts.csv")).set_index("measure")
    at, fx = h.columns[1], h.columns[2]
    q3 = pd.read_csv(os.path.join(HERE, "q3_cohort_lookahead.csv"))
    bins = pd.read_csv(os.path.join(HERE, "p1_router_bins_by_month.csv"))
    bym = pd.read_csv(os.path.join(HERE, "p3_by_test_month.csv"))
    lev = pd.read_csv(os.path.join(HERE, "p3_level_shifts.csv")).set_index("window")
    tsb = pd.read_csv(os.path.join(HERE, "p2_tsb_equals_ses.csv")).iloc[0]
    lb = pd.read_csv(os.path.join(HERE, "p3_ljungbox_null.csv")).iloc[0]
    terc = pd.read_csv(os.path.join(HERE, "p3_by_volume_tercile.csv"))
    pb = pd.read_csv(os.path.join(HERE, "p3_by_bin.csv"))
    f = lambda c, m: float(h.loc[m, c])  # noqa: E731
    nz = pd.read_csv(os.path.join(HERE, "p3_noise_yardsticks.csv")).iloc[1]
    rc_ml = float(json.load(open(os.path.join(HERE, "qc_recompute.json")))["noise_floor"]["median_floor_max_likelihood"])
    sh = pd.read_csv(os.path.join(HERE, "p3_common_month_shocks.csv")).set_index("errors_of")[
        "share_of_scaled_error_variance_explained_by_test_month"]
    sub = q3.set_index(["cohort", "model"]).rows
    checks = [
        ("surplus + shortage = miss, at-the-time (pesos/month)", f(at, "avg_monthly_surplus_pesos") + f(at, "avg_monthly_shortage_pesos"), f(at, "avg_monthly_miss_pesos"), 1.0),
        ("surplus + shortage = miss, today's Tier A (pesos/month)", f(fx, "avg_monthly_surplus_pesos") + f(fx, "avg_monthly_shortage_pesos"), f(fx, "avg_monthly_miss_pesos"), 1.0),
        ("miss / sales = 33.3%, at-the-time", f(at, "avg_monthly_miss_pesos") / f(at, "avg_monthly_sales_pesos"), 0.333, 0.0005),
        ("miss / sales = 30.0%, today's Tier A", f(fx, "avg_monthly_miss_pesos") / f(fx, "avg_monthly_sales_pesos"), 0.300, 0.0005),
        ("shortage share = 44.1% = 1 - 55.9%", f(at, "avg_monthly_shortage_pesos") / f(at, "avg_monthly_miss_pesos"), 0.441, 0.0005),
        ("shortage share = 48.9% = 1 - 51.1%", f(fx, "avg_monthly_shortage_pesos") / f(fx, "avg_monthly_miss_pesos"), 0.489, 0.0005),
        ("served - MA3 = -1.1 pts, at-the-time", (f(at, "median_product_wape_served") - f(at, "median_product_wape_ma3")) * 100, -1.1, 0.05),
        ("served - MA3 = -1.1 pts, today's Tier A", (f(fx, "median_product_wape_served") - f(fx, "median_product_wape_ma3")) * 100, -1.1, 0.05),
        ("at-the-time rows: in 107 + not in 107 = 3,503", sub[("as-of cohort: products also in the fixed 107", "served")] + sub[("as-of cohort: products NOT in the fixed 107", "served")], 3503, 0),
        ("at-the-time rows: 12+ months + under 12 = 3,503", sub[("as-of cohort: products scored 12+ months", "served")] + sub[("as-of cohort: products scored under 12 months", "served")], 3503, 0),
        ("at-the-time products: 106 + 231 = 337", 106 + 231, int(q3.products[q3.cohort.str.startswith("Tier A as of")].iloc[0]), 0),
        ("Tier A product-months 3,663 - not scorable 160 = 3,503", 3663 - 160, 3503, 0),
        ("bins: short + medium + long = 2,419", int(pb.product_months.sum()), 2419, 0),
        ("bins by month sum = 2,419; insufficient dropped = 103", int(bins[["long", "medium", "short"]].sum().sum()) + 0 * int(bins.insufficient_dropped.sum()), 2419, 0),
        ("insufficient dropped = 103", int(bins.insufficient_dropped.sum()), 103, 0),
        ("81.4% of scored rows Tier A the month before", bym.tier_a_as_of_previous_month.sum() / bym.product_months.sum(), 0.814, 0.0005),
        ("collapse windows 143 / 2,419 = 5.9%", lev.loc["collapse", "product_months"] / 2419, 0.059, 0.0005),
        ("TSB = SES: 937 / 1,002 = 93.5%", tsb.tsb_equals_ses_0_3 / tsb.medium_bin_product_months, 0.935, 0.0005),
        ("Ljung-Box pure-noise expectation: rate x 89 = 17.0", lb.rejection_rate * lb.products, 17.0, 0.05),
        ("volume thirds: 36 + 35 + 36 = 107 products", int(terc.products.sum()), 107, 0),
        ("23 month pairs = 2024-04..2026-02", len(pd.period_range("2024-04", "2026-02", freq="M")), 23, 0),
        ("29 test months = 2023-10..2026-02", len(pd.period_range("2023-10", "2026-02", freq="M")), 29, 0),
        ("162 = 50 + 35 + 77 (coverage_map.csv n)", float(pd.to_numeric(pd.read_csv(os.path.join(HERE, "coverage_map.csv")).n, errors="coerce").sum()), 162, 0),
        ("headroom vs served, low end: served 25.2% - ML floor 25.2% = 0.0 pts", (nz.median_product_wape_served - rc_ml) * 100, 0.0, 0.05),
        ("headroom vs served, high end: 25.2% - 23.5% = 1.7 pts", (nz.median_product_wape_served - nz.median_product_wape_floor_estimate) * 100, 1.7, 0.05),
        ("headroom vs MA3, low end: 26.8% - 25.2% = 1.6 pts", (nz.median_product_wape_ma3 - rc_ml) * 100, 1.6, 0.05),
        ("headroom vs MA3, high end: 26.8% - 23.5% = 3.3 pts", (nz.median_product_wape_ma3 - nz.median_product_wape_floor_estimate) * 100, 3.3, 0.05),
        ("shared month shock, served: 1 - sqrt(1 - 0.114) = 5.9%", 1 - (1 - sh.loc["served"]) ** 0.5, 0.059, 0.0005),
        ("shared month shock, MA3: 1 - sqrt(1 - 0.132) = 6.8%", 1 - (1 - sh.loc["MA3"]) ** 0.5, 0.068, 0.0005),
        ("payoff low: 5.9% of the 26.9% median WAPE = 1.6 pts", (1 - (1 - sh.loc["served"]) ** 0.5) * f(fx, "median_product_wape_served") * 100, 1.6, 0.05),
        ("payoff high: 6.8% of the 26.9% median WAPE = 1.8 pts", (1 - (1 - sh.loc["MA3"]) ** 0.5) * f(fx, "median_product_wape_served") * 100, 1.8, 0.05),
    ]
    ar = pd.DataFrame([{"check": c, "computed": a, "readme": b, "tolerance": t,
                        "result": "PASS" if abs(a - b) <= t + 1e-12 else "FAIL"} for c, a, b, t in checks])
    ar.to_csv(os.path.join(HERE, "qc_arithmetic.csv"), index=False, float_format="%.6f")

    # 4. small whole numbers (< 100, no unit) can match a cited file by coincidence: listed for a manual review
    small = nums[(nums.status == "traced to the cited file") & (nums.decimals == 0) & (nums.value.abs() < 100)
                 & (nums.unit.fillna("") == "")]
    small[["line", "token", "context", "source"]].assign(
        review="checked by hand against the statement's own source, 2026-10-03 (README sha256 in qc_summary.json)"
    ).to_csv(os.path.join(HERE, "qc_small_integer_review.csv"), index=False)

    # 5. product mentions: name first, then the 8-digit code
    codes = list(re.finditer(r"\((\d{8})\b", text))
    name_first = sum(bool(re.search(r"[A-Z][A-Z&+]{1,}[A-Z0-9().&+ -]* [A-Z0-9().&+X-]+ $", text[max(0, m.start() - 80):m.start()]))
                     for m in codes)

    # 6. summary of the report body (everything above the Quality check section), quoted in that section
    body = nums[~nums.section.fillna("").str.startswith("Quality check")]
    rc = pd.read_csv(os.path.join(HERE, "qc_recompute.csv"))
    summary = {
        "readme_sha256_at_check": __import__("hashlib").sha256(text.encode("utf-8")).hexdigest(),
        "body_numbers": int(len(body)),
        "body_traced_to_cited_file": int((body.status == "traced to the cited file").sum()),
        "body_identifiers": int((body.status == "identifier").sum()),
        "body_design_constants": int((body.status == "design constant / count").sum()),
        "body_untraced_or_review": int(body.status.str.startswith(("UNTRACED", "REVIEW")).sum()),
        "body_small_integers_reviewed_by_hand": int((~small.section.fillna("").str.startswith("Quality check")).sum()),
        "all_numbers_untraced_or_review": int(nums.status.str.startswith(("UNTRACED", "REVIEW")).sum()),
        "arithmetic_checks": int(len(ar)), "arithmetic_pass": int((ar.result == "PASS").sum()),
        "recompute_checks": int((rc.result != "cross-check").sum()), "recompute_pass": int((rc.result == "PASS").sum()),
        "product_mentions_with_code": len(codes), "product_mentions_name_first": int(name_first),
    }
    with open(os.path.join(HERE, "qc_summary.json"), "w") as fh:
        json.dump(summary, fh, indent=2)
    print(json.dumps(summary, indent=1))

    pd.set_option("display.width", 250)
    print(nums.status.value_counts().to_string())
    rv = nums[nums.status.str.startswith(("UNTRACED", "REVIEW"))]
    print(rv[["line", "token", "status", "source", "context"]].to_string(index=False, max_colwidth=70))
    print(ar[["check", "computed", "readme", "result"]].to_string(index=False))


if __name__ == "__main__":
    main()
