"""QA checks 1, 2 and 5 (2026-10-03) for this folder's README and CSVs.

1. NUMBERS: every number in README.md is located and matched, at the
   precision printed, against the CSV it comes from: the section's CSVs, the
   CSV rows of any SKU named on the same line, a value derived from the CSVs
   (DERIVED below), or a fixed rule of the method (CONSTANTS). Anything left
   over is reported with its line. Every SKU must follow its product name.
2. ARITHMETIC: covered + left out = total; A + B + C = products ranked;
   overlap is symmetric; entered - left = change in list size; safety stock
   sums by class; impact counts add up.
5. EDGE CASES (with --extract): returns >= sales, single sales month, codes
   and names, blank revenue - each against the raw extract.

    python qa_check.py [--extract <dir>]
"""
from __future__ import annotations

import argparse
import re
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
FAILS: list[str] = []
WEAK: list[str] = []  # matches by a fixed rule or a true/false column: listed for review


def csv(name: str) -> pd.DataFrame:
    """The full table from the git-ignored local/ folder when there is one (per-product revenue, cost and peso
    columns are not committed: run_tier_a_basis.py CLIENT_COLUMNS), otherwise the committed table."""
    full = HERE / "local" / name
    return pd.read_csv(full if full.exists() else HERE / name, dtype={"sku_code": str})


def fail(msg: str) -> None:
    FAILS.append(msg)
    print("  FAIL", msg)


def ok(cond: bool, msg: str) -> None:
    if not cond:
        fail(msg)


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #
T = {n: csv(n) for n in [
    "basis_summary.csv", "overlap_matrix.csv", "revenue_left_out.csv", "monthly_churn.csv",
    "monthly_churn_average.csv", "safety_stock_summary.csv", "rule1_revenue_left_out.csv",
    "impact_preview_summary.csv", "sensitivity.csv", "checks.csv", "extract_profile.csv",
    "reproduction_check.csv", "missing_from_current_tier_a.csv", "current_tier_a_not_in_12m_or_24m.csv",
    "calendar_2025_vs_2024.csv", "rule1_added_products.csv", "impact_preview_by_product.csv",
    "tiers_by_basis.csv", "safety_stock_by_sku.csv", "class_a_frequency_2025_01_to_2026_02.csv",
    "monthly_churn_members_1m.csv"]}
PRODUCT_CSVS = ["missing_from_current_tier_a.csv", "current_tier_a_not_in_12m_or_24m.csv",
                "calendar_2025_vs_2024.csv", "rule1_added_products.csv", "impact_preview_by_product.csv",
                "tiers_by_basis.csv", "safety_stock_by_sku.csv"]
tiers = T["tiers_by_basis.csv"].set_index("product_key")
prof = T["extract_profile.csv"].set_index("key")


def pnum(key: str) -> float:
    return float(prof.at[key, "value"])


# --------------------------------------------------------------------------- #
# DERIVED: README figures that are sums, counts or differences of CSV values
# --------------------------------------------------------------------------- #
def derived() -> dict[str, float]:
    D: dict[str, float] = {}
    miss = T["missing_from_current_tier_a.csv"]
    D["missing: products"] = len(miss)
    D["missing: in both"] = int((miss.in_12m_class_a & miss.in_24m_class_a).sum())
    D["missing: 12m only"] = int((miss.in_12m_class_a & ~miss.in_24m_class_a).sum())
    D["missing: 24m only"] = int((~miss.in_12m_class_a & miss.in_24m_class_a).sum())
    D["missing: 12m subset"] = int(miss.in_12m_class_a.sum())
    D["missing: 12m subset revenue"] = miss.loc[miss.in_12m_class_a, "revenue_php_12m"].sum()
    D["missing: 24m subset"] = int(miss.in_24m_class_a.sum())
    D["missing: 24m subset revenue"] = miss.loc[miss.in_24m_class_a, "revenue_php_24m"].sum()
    for k, v in miss.tier_2026_02.value_counts().items():
        D[f"missing: Feb 2026 status {k}"] = v
    D["missing: last sold before 2025-12"] = int((miss.last_month_with_sales < "2025-12").sum())
    D["missing: no sales last 12 months"] = int((miss.months_with_sales_last_12 == 0).sum())
    D["missing: 12m subset, no sale after 2025-11"] = int((miss.in_12m_class_a & (miss.last_month_with_sales < "2025-12")).sum())
    ex = T["current_tier_a_not_in_12m_or_24m.csv"]
    D["today-only: products"] = len(ex)
    D["today-only: Feb 2026 revenue"] = ex.revenue_php_1m.sum()
    total_1m = T["basis_summary.csv"].set_index("basis").at["1m", "total_revenue_php"]
    D["today-only: % of Feb 2026"] = 100 * ex.revenue_php_1m.sum() / total_1m
    D["today-only: first sold 2025-06 or later"] = int((ex.first_month_with_sales >= "2025-06").sum())
    lo = T["revenue_left_out.csv"].set_index(["planning_list", "revenue_measured_over"])
    D["12m list recovers vs today, PHP"] = lo.at[("1m", "12m"), "left_out_php"] - lo.at[("12m", "12m"), "left_out_php"]
    D["12m list recovers vs today, pp"] = lo.at[("1m", "12m"), "left_out_pct"] - lo.at[("12m", "12m"), "left_out_pct"]
    D["12m list costs on Feb 2026, pp"] = lo.at[("12m", "1m"), "left_out_pct"] - lo.at[("1m", "1m"), "left_out_pct"]
    ch = T["monthly_churn.csv"]
    for b, g in ch.groupby("basis"):
        for c in ("entered", "left"):
            D[f"churn {b}: min {c}"], D[f"churn {b}: max {c}"] = g[c].min(), g[c].max()
    D["churn: months in test"] = ch.month.nunique()
    avg = T["monthly_churn_average.csv"].set_index("basis")
    D["rule1 vs 12m: extra entered"] = avg.at["12m+new", "entered"] - avg.at["12m", "entered"]
    D["rule1 vs 12m: extra left"] = avg.at["12m+new", "left"] - avg.at["12m", "left"]
    fq = T["class_a_frequency_2025_01_to_2026_02.csv"]
    D["1m: ever Class A"] = int((fq.months_in_class_a_1m > 0).sum())
    D["1m: Class A all 14 months"] = int((fq.months_in_class_a_1m == ch.month.nunique()).sum())
    D["today's A: Class A in <= 3 months"] = int((fq.in_current_tier_a & (fq.months_in_class_a_1m <= 3)).sum())
    cal = T["calendar_2025_vs_2024.csv"]
    for chg, g in cal.groupby("change"):
        D[f"calendar {chg}: products"] = len(g)
        D[f"calendar {chg}: revenue 2024"] = g.revenue_php_2024.sum()
        D[f"calendar {chg}: revenue 2025"] = g.revenue_php_2025.sum()
    D["calendar: 2024 Class A"] = int((cal.change != "entered").sum())
    D["calendar: 2025 Class A"] = int((cal.change != "left").sum())
    ent, lef = cal[cal.change == "entered"], cal[cal.change == "left"]
    D["calendar entered: no 2024 sales"] = int((ent.tier_2024 == "no sales").sum())
    D["calendar entered: Class B in 2024"] = int((ent.tier_2024 == "B").sum())
    D["calendar left: no 2025 sales"] = int((lef.tier_2025 == "no sales").sum())
    ss = T["safety_stock_by_sku.csv"]
    D["SS: costed from 2026-03 stock file"] = int((ss.cost_period == "2026-03").sum())
    sss = T["safety_stock_summary.csv"].set_index("tier_12m")
    D["SS: z tiered A"] = ss.loc[ss.tier_12m == "A", "z_tiered"].iloc[0]
    D["SS: z tiered C"] = ss.loc[ss.tier_12m == "C", "z_tiered"].iloc[0]
    D["SS: A flat value"] = sss.at["A", "ss_flat_value_php"]
    D["SS: all flat value"] = sss.at["all", "ss_flat_value_php"]
    bs = T["basis_summary.csv"].set_index("basis")
    D["12m vs today: extra products"] = bs.at["12m", "class_a"] - bs.at["1m", "class_a"]
    D["12m vs today: extra products %"] = 100 * D["12m vs today: extra products"] / bs.at["1m", "class_a"]
    a12 = tiers[tiers.tier_12m == "A"]
    D["12m A: first sold after 2024-03"] = int((a12.first_month_with_sales > "2024-03").sum())
    r1 = T["rule1_added_products.csv"]
    D["rule1: added"] = len(r1)
    D["rule1: list"] = bs.at["12m", "class_a"] + len(r1)
    D["rule1: added in today's A"] = int(r1.in_current_tier_a.sum())
    D["rule1: 3m revenue"], D["rule1: 12m revenue"], D["rule1: Feb revenue"] = (
        r1.revenue_php_3m.sum(), r1.revenue_php_12m.sum(), r1.revenue_php_1m.sum())
    caught = set(r1.product_key) & set(ex.product_key)
    D["rule1: today-only caught"] = len(caught)
    unc = tiers.loc[sorted(set(ex.product_key) - caught)]
    D["rule1: today-only missed"] = len(unc)
    D["rule1: missed, min 3m rank"], D["rule1: missed, max 3m rank"] = unc.rank_3m.min(), unc.rank_3m.max()
    imp = T["impact_preview_by_product.csv"]
    i12 = imp[imp.in_12m]
    D["impact 12m: dead"] = int((i12.runner_status == "dead_sku").sum())
    D["impact 12m: insufficient, 2 sales months"] = int(((i12.runner_status == "insufficient_data") & (i12.sales_months_to_2026_02 == 2)).sum())
    D["impact 12m: not in stock file"] = int((~i12.in_stock_file_2026_03).sum())
    D["impact 12m: not in stock file, sold Feb 2026"] = int((~i12.in_stock_file_2026_03 & (i12.last_month_with_sales == "2026-02")).sum())
    others = [pnum(f"top10_share_pct_{m}") for m in ch.month.unique() if m != "2025-12"]
    D["top-10 share, other months min"], D["top-10 share, other months max"] = min(others), max(others)
    sens = T["sensitivity.csv"]
    D["sensitivity: max change"] = sens.products_that_change.max()
    D["sensitivity: max change, skip-month variant"] = sens.loc[sens.variant.str.contains("skip"), "products_that_change"].max()
    return D


# Fixed rules of the method, quoted in prose (source in brackets).
CONSTANTS = {
    80: "Class A cutoff (abc.py:56)", 95: "Class B cutoff (abc.py:57) / tiered A service level",
    90: "service level (params.py:109)", 85: "tiered C service level", 1.28: "Z at 90% (params.py:108)",
    25: "placeholder PHP/piece (params.py:173)", 5: "review days (params.py:164)", 3: "lead days / bin floor",
    8: "review + lead", 6: "dead-SKU months (params.py:66)", 12: "window / bin", 24: "window / bin",
    11: "bin bound", 23: "bin bound", 38: "real months", 14: "churn months", 2: "LP min months",
    15: "top 15 table", 10: "top 10 products", 1: "one-month basis", 4: "blank-row windows text",
}

SECTION_CSVS = {
    "": ["*"], "Data used": ["extract_profile.csv", "checks.csv"],
    "How each list is built": ["reproduction_check.csv", "checks.csv"],
    "1.": ["basis_summary.csv"],
    "2.": ["overlap_matrix.csv", "revenue_left_out.csv", "basis_summary.csv"],
    "3.": ["monthly_churn.csv", "monthly_churn_average.csv", "extract_profile.csv"],
    "4.": ["extract_profile.csv"], "5.": ["safety_stock_summary.csv", "checks.csv"],
    "6.": ["*"], "7.": ["rule1_revenue_left_out.csv", "monthly_churn_average.csv", "checks.csv", "basis_summary.csv"],
    "8.": ["impact_preview_summary.csv", "checks.csv", "extract_profile.csv"],
    "Caveats": ["sensitivity.csv", "basis_summary.csv", "extract_profile.csv"],
    "Files": ["reproduction_check.csv", "checks.csv"], "Reproduce": [],
}
SUMMARY_CSVS = [n for n in T if n not in PRODUCT_CSVS + ["class_a_frequency_2025_01_to_2026_02.csv", "monthly_churn_members_1m.csv"]]


def values_of(df: pd.DataFrame) -> list[tuple[float, str]]:
    out = []
    for col in df.columns:
        if df[col].dtype == bool:  # a True would "match" 1 or 100%
            continue
        for i, v in df[col].items():
            try:
                f = float(v)
            except (TypeError, ValueError):
                continue
            if f == f:
                out.append((f, f"{col}[{i}]"))
    return out


NUM = re.compile(r"(?P<sign>[+−-])?(?P<php>₱)?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?P<m>M)?(?P<pct>%)?")
MONTHS = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"


def half_up(v: float, dec: int) -> Decimal:
    return Decimal(repr(v)).quantize(Decimal(1).scaleb(-dec), rounding=ROUND_HALF_UP)


BOUNDARY: list[str] = []  # source values exactly half-way at the printed precision


def token_matches(tok: dict, v: float) -> bool:
    for c in (v, v * 100) if tok["pct"] else (v,):
        c = abs(c) / (1e6 if tok["m"] else 1)
        if half_up(c, tok["dec"]) == tok["value"]:
            frac = Decimal(repr(c)).scaleb(tok["dec"]) % 1
            if frac == Decimal("0.5"):
                tok["boundary"] = True
            return True
    return False


def check_numbers(D: dict[str, float]) -> None:
    print("\n[1] NUMBER CHECK")
    text = (HERE / "README.md").read_text(encoding="utf-8")
    names = set()
    sku_name = {}
    for n in PRODUCT_CSVS:
        df = T[n]
        names |= set(df.product_name.dropna())
        sku_name.update(dict(zip(df.sku_code, df.product_name)))
    names |= {s.split(": ", 1)[1] for s in prof.source if s.startswith("demand_real: ")}
    sku_name.update({k.rsplit("_", 1)[1]: s.split(": ", 1)[1] for k, s in prof.source.items() if k.startswith("blank_net_amount_")})
    names_by_len = sorted(names, key=len, reverse=True)

    section, n_tokens, n_unmatched, n_sku = "", 0, 0, 0
    by_source: dict[str, int] = {}
    pools = {n: values_of(T[n]) for n in T}
    dpool = [(float(v), f"DERIVED {k}") for k, v in D.items()]
    cpool = [(float(k), f"CONSTANT {v}") for k, v in CONSTANTS.items()]
    for lineno, raw in enumerate(text.splitlines(), 1):
        if raw.startswith("## "):
            head = raw[3:]
            section = next((k for k in SECTION_CSVS if k and head.startswith(k)), head)
        if raw.startswith("```") or raw.startswith("python ") or raw.startswith("D=") or raw.startswith("X="):
            continue
        line = re.sub(r"`[^`]*`", " ", raw)
        # SKU check: each 8-digit code follows the name it belongs to
        for m in re.finditer(r"(?<![\d.])(\d{8})(?![\d.])", line):
            n_sku += 1
            sku = m.group(1)
            before = line[:m.start()]
            name = next((nm for nm in names_by_len if nm in before), None)
            last_name = max(((before.rfind(nm), nm) for nm in names_by_len if nm in before), default=(-1, None))[1]
            if sku not in sku_name:
                fail(f"line {lineno}: SKU {sku} not found in any CSV")
            elif name is None or sku_name[sku] != last_name:
                fail(f"line {lineno}: SKU {sku} is not preceded by its name ({sku_name[sku]})")
        line = re.sub(r"(?<![\d.])\d{8}(?![\d.])", " ", line)
        for nm in names_by_len:
            line = line.replace(nm, " ")
        line = re.sub(r"\d{4}-\d{2}-\d{2}(T[\d:.+]+)?|\d{4}-\d{2}|\d{2}:\d{2}", " ", line)
        line = re.sub(rf"{MONTHS}[a-z]*\.? \d{{4}}|\b20\d\d\b|§\d+|^#+ \d+\.|^\d+\. |^\s*\d+\. |lines \d+-\d+|item \d", " ", line)
        line = re.sub(r"\b[a-z_]+\d[\w.]*\b", " ", line)  # identifiers like 12m, t3m, 1m
        skus_here = re.findall(r"(?<![\d.])(\d{8})(?![\d.])", re.sub(r"`[^`]*`", " ", raw))
        row_pool = []
        for n in PRODUCT_CSVS:
            df = T[n]
            for s in skus_here:
                row_pool += values_of(df[df.sku_code == s])
        scope = SECTION_CSVS.get(section, ["*"])
        names_scope = SUMMARY_CSVS if "*" in scope else scope
        sec_pool = [vv for n in names_scope for vv in [(v, f"{n}:{s}") for v, s in pools[n]]]
        for m in NUM.finditer(line):
            num = m.group("num").replace(",", "")
            tok = {"value": Decimal(num), "dec": len(num.split(".")[1]) if "." in num else 0,
                   "m": bool(m.group("m")), "pct": bool(m.group("pct"))}
            n_tokens += 1
            src = next((s for v, s in row_pool + sec_pool + dpool + cpool if token_matches(tok, v)), None)
            if src is None:
                n_unmatched += 1
                fail(f"line {lineno} [{section or 'top'}]: '{m.group(0)}' matches no source")
            else:
                kind = src.split(":")[0].split(" ")[0] if "[" not in src.split(":")[0] else "row of named SKU"
                by_source[kind] = by_source.get(kind, 0) + 1
                weak = src.startswith("CONSTANT") or re.search(r"in_\w+_class_a\[|in_current", src)
                if weak:
                    WEAK.append(f"line {lineno}: '{m.group(0)}' <- {src}")
                if tok.get("boundary"):
                    BOUNDARY.append(f"line {lineno}: '{m.group(0)}' <- {src}")
    print(f"  {n_tokens} numbers checked, {n_unmatched} unmatched; {n_sku} SKU codes checked against their names")
    print("  matched by source:", dict(sorted(by_source.items(), key=lambda kv: -kv[1])))
    print(f"  rounding: values exactly half-way at the printed precision ({len(BOUNDARY)}):")
    for b in BOUNDARY:
        print("   ", b)
    print(f"  weak matches for review ({len(WEAK)}):")
    for w in WEAK:
        print("   ", w)
    words = re.findall(r"\b(one|two|three|four|five|six|seven|eight|nine|ten|twenty|thirty|half|third|quarter)\b",
                       text, flags=re.I)
    print(f"  number words left for review: {sorted(set(w.lower() for w in words))}")


# --------------------------------------------------------------------------- #
# 2. Arithmetic
# --------------------------------------------------------------------------- #
def check_arithmetic() -> None:
    print("\n[2] ARITHMETIC CHECK")
    bs = T["basis_summary.csv"].set_index("basis")
    for b, r in bs.iterrows():
        ok(r.class_a + r.class_b + r.class_c == r.products_ranked, f"{b}: A+B+C != products ranked")
        ok((tiers[f"tier_{b}"] == "A").sum() == r.class_a, f"{b}: tiers_by_basis Class A count != basis_summary")
        ok(abs(tiers[f"revenue_php_{b}"].sum() - r.total_revenue_php) < 0.05, f"{b}: tiers_by_basis revenue != total")
    print(f"  A+B+C = products ranked, and per-product totals = basis totals: {len(bs)} bases")

    lo = T["revenue_left_out.csv"]
    for _, r in lo.iterrows():
        ok(abs(r.covered_php + r.left_out_php - r.total_revenue_php) < 0.02, f"left out + covered != total ({r.planning_list}/{r.revenue_measured_over})")
        members = tiers[f"tier_{r.planning_list}"] == "A"
        ok(abs(tiers.loc[members, f"revenue_php_{r.revenue_measured_over}"].sum() - r.covered_php) < 0.05,
           f"covered != sum of list members' revenue ({r.planning_list}/{r.revenue_measured_over})")
    r1 = T["rule1_revenue_left_out.csv"]
    added = set(T["rule1_added_products.csv"].product_key)
    lists = {"latest month (today)": tiers.tier_1m == "A", "12m": tiers.tier_12m == "A",
             "12m+new": (tiers.tier_12m == "A") | tiers.index.isin(added)}
    for _, r in r1.iterrows():
        covered = tiers.loc[lists[r.planning_list], f"revenue_php_{r.revenue_measured_over}"].sum()
        ok(abs(covered + r.left_out_php - r.total_revenue_php) < 0.05, f"rule1 left out + covered != total ({r.planning_list}/{r.revenue_measured_over})")
        ok(int(lists[r.planning_list].sum()) == r.list_size, f"rule1 list size ({r.planning_list})")
    print(f"  covered + left out = total, covered recomputed from members: {len(lo)} + {len(r1)} list x window pairs")

    ov = T["overlap_matrix.csv"].set_index(["basis_x", "basis_y"])
    for (x, y), r in ov.iterrows():
        ok(r.in_both == ov.at[(y, x), "in_both"] and r.jaccard_pct == ov.at[(y, x), "jaccard_pct"], f"overlap not symmetric {x}/{y}")
        ok(r.in_both == ((tiers[f"tier_{x}"] == "A") & (tiers[f"tier_{y}"] == "A")).sum(), f"overlap count wrong {x}/{y}")
        if x == y:
            ok(r.in_both == r.class_a_x, f"overlap diagonal {x}")
    print(f"  overlap symmetric and recounted from tiers_by_basis: {len(ov)} pairs")

    ch = T["monthly_churn.csv"]
    for b, g in ch.groupby("basis"):
        g = g.sort_values("month").reset_index(drop=True)
        for i, r in g.iterrows():
            ok(r.entered - r.left == r.class_a - r.previous_class_a, f"churn {b} {r.month}: entered - left != change")
            ok(r.stayed + r.entered == r.class_a and r.stayed + r.left == r.previous_class_a, f"churn {b} {r.month}: stayed")
            if i:
                ok(r.previous_class_a == g.at[i - 1, "class_a"], f"churn {b} {r.month}: previous != last month's size")
    avg = T["monthly_churn_average.csv"].set_index("basis")
    for b, g in ch.groupby("basis"):
        for c in ("class_a", "entered", "left", "entered_pct_of_list"):
            ok(abs(g[c].mean() - avg.at[b, c]) < 0.006, f"churn average {b} {c}")
    mem = T["monthly_churn_members_1m.csv"].groupby(["month", "change"]).size()
    for _, r in ch[ch.basis == "1m"].iterrows():
        ok(mem.get((r.month, "entered"), 0) == r.entered and mem.get((r.month, "left"), 0) == r.left, f"members list {r.month}")
    print(f"  entered - left = change in size, averages, member lists: {len(ch)} basis x month rows")

    cal = T["calendar_2025_vs_2024.csv"]
    ok(((cal.revenue_php_2025 - cal.revenue_php_2024 - cal.change_php).abs() < 0.02).all(), "calendar change_php")
    ok((cal.loc[cal.change == "entered", "tier_2025"] == "A").all() and (cal.loc[cal.change == "entered", "tier_2024"] != "A").all(), "calendar entered tiers")
    ok((cal.loc[cal.change == "left", "tier_2024"] == "A").all() and (cal.loc[cal.change == "left", "tier_2025"] != "A").all(), "calendar left tiers")
    print("  calendar: change = 2025 - 2024 for every row; entered/left tiers consistent")

    sss = T["safety_stock_summary.csv"].set_index("tier_12m")
    by = T["safety_stock_by_sku.csv"]
    for col in ("products", "products_insufficient_data", "products_with_stock_file_cost", "products_without_cost",
                "ss_flat_pieces", "ss_tiered_pieces", "ss_flat_value_php", "ss_tiered_value_php", "difference_value_php"):
        ok(abs(sss.loc[["A", "B", "C"], col].sum() - sss.at["all", col]) <= 2, f"safety stock: A+B+C != all ({col})")
    for t, r in sss.iterrows():
        ok(abs(r.ss_tiered_value_php - r.ss_flat_value_php - r.difference_value_php) <= 1, f"safety stock difference ({t})")
        g = by if t == "all" else by[by.tier_12m == t]
        okg = g[g.status == "ok"]
        ok(abs(okg.ss_flat_pieces.sum() - r.ss_flat_pieces) <= 1 and abs(okg.ss_tiered_pieces.sum() - r.ss_tiered_pieces) <= 1,
           f"safety stock pieces by SKU != summary ({t})")
        ok(abs(okg.ss_flat_value_php.sum() - r.ss_flat_value_php) <= 1, f"safety stock value by SKU != summary ({t})")
    ok(sss.at["B", "difference_value_php"] == 0, "class B difference should be 0 (90% both ways)")
    print("  safety stock: classes add to 'all', tiered - flat = difference, per-SKU sums = summary")

    imp, imps = T["impact_preview_by_product.csv"], T["impact_preview_summary.csv"].set_index("list")
    for lst, r in imps.iterrows():
        ok(r.history_under_3_months + r.history_3_11_months + r.history_12_23_months + r.history_24_plus_months == r.products, f"impact bins ({lst})")
        ok(r.runner_insufficient_data + r.runner_dead_sku + r.runner_ok_short_ma3 + r.runner_ok_medium_tsb + r.runner_ok_long_xgb_ma3 == r.products, f"impact runner ({lst})")
        ok(r.of_which_no_forecast_row + r.of_which_forecast_not_ok == r.in_stock_file_no_forecast_today, f"impact no-forecast split ({lst})")
        g = imp[imp[f"in_{lst}"]]
        ok(len(g) == r.products and int(g.in_stock_file_2026_03.sum()) == r.in_stock_file_2026_03, f"impact recount ({lst})")
    print(f"  impact: bins and runner outcomes add to list size, no-forecast split adds up: {len(imps)} lists")

    miss = T["missing_from_current_tier_a.csv"]
    expect = set(tiers.index[(tiers.tier_12m == "A") | (tiers.tier_24m == "A")]) - set(tiers.index[tiers.tier_1m == "A"])
    ok(set(miss.product_key) == expect, "missing list != (12m A | 24m A) - today's A")
    # Committed copies of the per-product tables: same rows as local/, no client column (revenue, cost, peso value).
    client = re.compile(r"^(revenue_php_.*|change_php|cost_per_piece_php|.*_value_php)$")
    n_local = 0
    for full in sorted((HERE / "local").glob("*.csv")):
        pub = pd.read_csv(HERE / full.name, dtype={"sku_code": str})
        ok(not [c for c in pub.columns if client.search(c)], f"{full.name}: a client column is in the committed copy")
        ok(pub.equals(T[full.name][pub.columns]), f"{full.name}: committed copy != local/ copy minus client columns")
        n_local += 1
    print(f"  committed per-product tables = local/ copies minus client columns: {n_local} tables")
    ok(set(T["sensitivity.csv"].query("not basis.str.startswith('calendar')", engine="python").groupby("basis").class_a_primary.first().items())
       == set(bs.class_a.items()), "sensitivity primary counts != basis_summary")
    print("  missing list = (12m A or 24m A) minus today's A; sensitivity primaries = basis_summary")


# --------------------------------------------------------------------------- #
# 5. Edge cases, against the raw extract
# --------------------------------------------------------------------------- #
def check_edge_cases(x: Path) -> None:
    print("\n[5] EDGE CASES (raw extract)")
    d = pd.read_csv(x / "demand_real.csv", dtype={"sku_code": str})
    pdim = pd.read_csv(x / "product_dim.csv", dtype={"sku_code": str})
    feb = d[d.calendar_month == "2026-02"].set_index("product_key")
    miss = T["missing_from_current_tier_a.csv"]
    ret = miss[miss.tier_2026_02 == "returns >= sales"]
    ok(all(pk in feb.index and feb.at[pk, "net_amount"] <= 0 for pk in ret.product_key), "'returns >= sales' products do not have net <= 0 in Feb 2026")
    nonpos = set(feb.index[feb.net_amount <= 0])
    ok(not (nonpos & set(tiers.index[tiers.tier_1m != "-"])), "a product with net <= 0 in Feb 2026 got a Feb 2026 class")
    w12 = d[(d.calendar_month >= "2025-03") & (d.calendar_month <= "2026-02")]
    clamp = w12.assign(v=w12.net_amount.clip(lower=0)).groupby("product_key").v.sum()
    clamp = clamp[clamp > 0]
    neg_pks = set(w12.loc[w12.net_amount < 0, "product_key"]) & set(clamp.index)
    diff = (tiers.revenue_php_12m.reindex(clamp.index) - clamp).abs().max()
    ok(diff < 0.01, f"12-month revenue != per-month-clamped raw sum (max diff {diff})")
    print(f"  returns >= sales: {len(ret)} listed products have Feb 2026 net <= 0; {len(nonpos)} Feb 2026 products with net <= 0 got no class; "
          f"{len(neg_pks)} products with a negative month in Mar 2025-Feb 2026 carry only their positive months (max diff PHP {diff:.4f})")
    sales_months = d[d.net_amount > 0].groupby("product_key").calendar_month.nunique()
    one = set(sales_months.index[sales_months == 1])
    ss = T["safety_stock_by_sku.csv"].set_index("product_key")
    ok(((ss.months_used < 2) == (ss.status != "ok")).all(), "safety stock: status not 'insufficient' exactly when fewer than 2 months")
    imp = T["impact_preview_by_product.csv"].set_index("product_key")
    ok(((imp.sales_months_to_2026_02 < 3) == (imp.runner_status == "insufficient_data")).all(), "runner: insufficient_data not exactly < 3 sales months")
    ok(tiers.at[pdim.set_index("sku_code").at["65455331", "product_key"], "tier_1m"] == "A", "65455331 (1 sales month) should be Class A in Feb 2026")
    print(f"  single sales month: {len(one)} products in the extract; ranked like any other (e.g. 65455331, Class A Feb 2026); "
          f"SS 'insufficient' exactly when < 2 months ({int((ss.months_used < 2).sum())}); runner insufficient exactly when < 3 sales months")
    ok(pdim.sku_code.is_unique and pdim.product_key.is_unique, "product master: a SKU code with two product keys")
    joined = d[["product_key", "sku_code"]].drop_duplicates().merge(pdim[["product_key", "sku_code"]], on="product_key", suffixes=("_sales", "_master"))
    ok((joined.sku_code_sales == joined.sku_code_master).all(), "sales sku_code disagrees with the product master")
    ok(d.groupby("product_key").sku_code.nunique().max() == 1, "a product key appears under two SKU codes in sales")
    sold = pdim[pdim.product_key.isin(d.product_key)].copy()
    sold["n"] = sold.product_name.str.upper().str.split().str.join(" ")
    shared = sold.groupby("n").filter(lambda g: len(g) > 1)
    ok(shared.n.nunique() == pnum("names_with_more_than_one_code") and len(shared) == pnum("codes_under_shared_names"), "shared-name counts")
    ranked_both = sum(1 for _, g in shared.groupby("n") if g.product_key.isin(tiers.index).sum() == len(g))
    print(f"  codes and names: every SKU code has one product key and one name, sales and master agree; "
          f"{shared.n.nunique()} names carry {len(shared)} codes, each code ranked as its own product "
          f"({ranked_both} of {shared.n.nunique()} names have every code ranked somewhere)")
    blank = d[d.net_amount.isna()]
    for _, r in blank.iterrows():
        pk, m = r.product_key, r.calendar_month
        windows = {"24m": ("2024-03", "2026-02"), "full": ("2023-01", "2026-02"), "12m": ("2025-03", "2026-02"),
                   "3m": ("2025-12", "2026-02"), "1m": ("2026-02", "2026-02")}
        for b, (s, e) in windows.items():
            if s <= m <= e:
                ok(pk not in tiers.index or tiers.at[pk, f"tier_{b}"] == "-", f"blank {pk} {m}: should be out of {b}")
        cal = T["calendar_2025_vs_2024.csv"]
        if m.startswith("2024"):
            ok(pk not in set(cal.product_key), f"blank {pk}: should be out of calendar 2024")
    ok(tiers.at[108, "tier_12m"] != "-" if 108 in tiers.index else False, "64369313 should be ranked on 12 months (no blank month there)")
    print(f"  blank revenue: {len(blank)} rows; each product is out of every window containing its blank month and ranked elsewhere")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--extract", type=Path)
    args = ap.parse_args()
    check_numbers(derived())
    check_arithmetic()
    if args.extract:
        check_edge_cases(args.extract)
    print(f"\n{'ALL CHECKS PASS' if not FAILS else f'{len(FAILS)} FAILURE(S)'}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
