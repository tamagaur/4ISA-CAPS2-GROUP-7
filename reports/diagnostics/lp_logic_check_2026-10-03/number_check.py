"""
Number check for README.md (2026-10-03): every number in the text is traced
to a source, or labelled as a constant, a quote or an effort estimate. Anything
left over is listed as UNSOURCED. A number within one display unit of a source
value but outside its rounding is listed as ROUNDING.

Not checked here (by design): text inside `code spans` (file:line references
are checked by check_refs.py; the rest is code), dates and month labels,
times, commit hashes, SKU codes, DEC / migration ids, list and section
numbering, and digits inside product names.

Matching: a number shown with d decimals matches a source value v when
|x - v| <= 0.5 x 10^-d (absolute values: the text writes "28.1% less" for
-28.06). "M" means millions; "%" also tries v x 100. Writes number_check.csv.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PULL = ROOT / "scratch" / "lp_logic_check_2026-10-03" / "pull"
pool: list[tuple[float, str]] = []


def add(v, label: str) -> None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return
    if np.isfinite(f):
        pool.append((abs(f), label))


def add_csv(path: Path, label: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    for col in df.columns:
        for v in pd.to_numeric(df[col], errors="coerce").dropna().unique():
            add(v, f"{label}:{col}")
    return df


def add_json(obj, label: str) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            add_json(v, f"{label}.{k}")
    elif isinstance(obj, list):
        add(len(obj), f"{label} (count)")
        for i, v in enumerate(obj):
            add_json(v, f"{label}[{i}]")
    elif isinstance(obj, str) and re.fullmatch(r"\d+/\d+", obj):
        for part in obj.split("/"):
            add(part, f"{label} ('{obj}')")
    else:
        add(obj, label)


def full(name: str) -> Path:
    """A per-product table with its price and peso columns: the git-ignored local/ copy (analyse.py CLIENT_COLUMNS).
    Those columns are not committed; without local/, rerun analyse.py."""
    path = HERE / "local" / name
    return path if path.exists() else HERE / name


# ---- sources: the report's own outputs ------------------------------------------------------------
for csv in sorted(HERE.glob("*.csv")):
    if csv.name not in ("number_check.csv", "arithmetic_check.csv", "check_refs.csv"):
        add_csv(full(csv.name), csv.name)
for js in ("figures.json", "balance_figures.json", "independent_recompute.json"):
    add_json(json.loads((HERE / js).read_text(encoding="utf-8")), js)
for name in ("snapshot_meta.csv", "balance_sources.csv", "lp_counts.csv", "forecast_dates.csv"):
    add_csv(PULL / name, f"pull/{name}")
add_csv(ROOT / "reports" / "evidence" / "ch08_totals.csv", "reports/evidence/ch08_totals.csv")

# ---- derived aggregates (formula in the label) ------------------------------------------------------
p1 = pd.read_csv(full("issue1_stock_timing_per_product.csv"))
for col in p1.columns:
    if p1[col].dtype.kind in "fi":
        add(p1[col].sum(), f"derived: sum issue1_stock_timing_per_product.csv:{col}")
p4 = pd.read_csv(full("issue4_policy_card_per_product.csv"))
for col in p4.columns:
    if p4[col].dtype.kind in "fi":
        add(p4[col].sum(), f"derived: sum issue4_policy_card_per_product.csv:{col}")
fc = pd.read_csv(HERE / "flag_counts.csv")
for (t, fs), g in fc.groupby(["table_name", "fill_source"]):
    add(g["row_count"].sum(), f"derived: flag_counts.csv rows {t} fill_source={fs}")
add(fc.loc[fc["valuation_source"] == "derived_cost", "row_count"].sum(), "derived: flag_counts.csv derived_cost rows")
ss = pd.read_csv(HERE / "ssis_sales_monthly.csv")
for m, g in ss.groupby("month"):
    add(g["ul_gsv"].sum(), f"derived: ssis_sales_monthly.csv {m} net UL GSV")
    add(g["lines"].sum(), f"derived: ssis_sales_monthly.csv {m} register lines")
w = ss[(ss["month"] >= "2025-03") & (ss["month"] <= "2026-02")]
add(w["ul_gsv"].sum() / w["gsv"].sum() * 100, "derived: UL GSV / register GSV, 2025-03..2026-02, %")
soh = pd.read_csv(HERE / "ssis_soh_columns.csv")
add((soh["whse_retail_at_cost"] / soh["whse_retail_without_vat"]).mean() * 100, "derived: INVENTORY at cost / without VAT, %")
add(len(soh), "derived: SOH sheets read")
cov3 = pd.read_csv(HERE / "issue3_weeks_of_cover.csv")
add((1 / 1.12) / cov3.iloc[1]["ratio_sales_to_shown_basis"] * 100, "derived: ex-VAT net sales / GSV, % (0.8929 / 0.9158)")
add((1 - (1 / 1.12) / cov3.iloc[1]["ratio_sales_to_shown_basis"]) * 100, "derived: 100% - ex-VAT net sales / GSV")
cb = pd.read_csv(HERE / "cover_both_counts.csv")
lu = cb[(cb["count"] == "2026-04-06") & (cb["scope"] == "whole count")].set_index("sales_basis")["weeks"]
add(lu.iloc[0] / lu.iloc[1], "derived: La Union-based / Ilocos-based cover, 2026-04-06")
bal = pd.read_csv(HERE / "balance_monthly.csv").set_index("month")
bf = json.loads((HERE / "balance_figures.json").read_text(encoding="utf-8"))
med = bf["implied_over_sales_baseline"]["median"]
feb = bal.loc["2026-02"]
hyp = feb["opening_php"] + (med - 1) * feb["sales_ilocos_ul_gsv_php"]
add(hyp, "derived: hypothetical 2 Mar count at median ratio")
add(feb["closing_php"] - hyp, "derived: reported 2 Mar count - hypothetical")
add(bal["sales_la_union_gsv_php"].notna().sum(), "derived: balance months with La Union sales")
add(len(bal), "derived: balance months")
fl = pd.read_csv(PULL / "forecast_latest.csv")
ok = fl[fl["status"] == "ok"]
add(ok["holdout_months"].min(), "derived: shortest stored test window (months)")
add(ok["holdout_months"].max(), "derived: longest stored test window (months)")
add(len(ok), "derived: forecast rows status ok")
add(len(fl), "derived: forecast rows at 2026-03-01")
fit = pd.read_csv(ROOT / "reports" / "diagnostics" / "fit_diagnosis_2026-10" / "per_sku.csv")
for k, n in fit["verdict_source"].value_counts().items():
    add(n, f"derived: fit_diagnosis per_sku verdict_source={k}")
add(len(pd.read_csv(HERE / "check_refs.csv")), "derived: check_refs.csv references")
add(len(pd.read_csv(PULL / "lp_cycle.csv")), "derived: lp_cycle rows, cycle 2026-03")
lp = pd.read_csv(PULL / "lp_cycle.csv")
add(lp["lp_run_key"].isna().sum(), "derived: lp_cycle rows with lp_run_key NULL")
add(len(pd.read_csv(PULL / "lp_run.csv")) if (PULL / "lp_run.csv").stat().st_size > 2 else 0, "derived: lp_run rows")
ar = pd.read_csv(HERE / "arithmetic_check.csv")
add(len(ar), "derived: arithmetic checks")
add(int(ar["pass"].sum()), "derived: arithmetic checks passing")

# ---- constants, quotes and estimates (what each one is) --------------------------------------------
CONSTANTS = {
    12: "VAT rate % / months in a window / months per year", 1.12: "1 + VAT", 4.348: "weeks per month = 365.25 / 12 / 7 (params.py:113-114)",
    365.25: "days per year", 7: "days per week", 1.28: "Z for 90% service (params.py:108)", 90: "service level %",
    103: "allocation % (PLACEHOLDERS)", 105: "stored run's allocation %", 5: "review business days / business days per week",
    3: "lead business days / rule weeks (POLICY_COVER_WEEKS)", 1.6: "(R + L) / 5 = 8 / 5", 2: "half the cycle order (÷ 2)",
    20: "holdout % (HOLDOUT_FRACTION 0.20)", 1: "MASE gate", 0.1: "band around the MASE gate", 1.5: "jump threshold used in the analysis (×)",
    24: "long bin starts at 24 sales months", 11: "short bin ends at 11 months", 23: "medium bin ends at 23 months", 6: "common test window, months / DEC-20 maximum days",
    32: "next free DEC number (DEC-31 is the last at 953cda3)", 0: "zero", 13: "count of SOH workbooks / counts", 2006: "Hyndman & Koehler year",
}
QUOTES = {46.6: "data_notes.py:26-29 quote (₱46.6M)", 24.3: "data_notes.py:26-29 quote (₱24.3M)", 22.7: "data_notes.py:26-29 quote (₱22.7M)",
          27282: "ARCHITECTURE.md:90 DEC-20 quote (27,282/27,282)"}
ESTIMATE_CONTEXT = re.compile(r"(about \d+ day|under \d+ hour|\d+-\d+ hours|half a day)")

# ---- extract numbers from the README ----------------------------------------------------------------
NUM = re.compile(r"(?<![\w.,/])([+−-]?)(₱?)(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?\s?(M\b|%|×)?(?![\w])")
STRIP = [
    (re.compile(r"`[^`]*`\s+\d+(?:-\d+)?\b"), " "),                         # a code name followed by its lines
    (re.compile(r"\(\d+-\d+, unchanged\)"), " "), (re.compile(r"^\s*\d+-\d+\)"), " "),  # "(464-480, unchanged)", wrapped refs
    (re.compile(r"`[^`]*`"), " "),                                          # code spans
    # line references written in parentheses, e.g. "(503-539)", "(823+)", "(391, 492)", "(dicts at 1299-1313)",
    # "(exposure card, 520-528)", "(line 90)": file:line references, checked by check_refs.py
    (re.compile(r"\((?:[a-z ]+,? )?(?:dicts at |line )?\d+(?:-\d+)?\+?(?:,\s*\d+(?:-\d+)?\+?)*\)"), " "),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}\b"), " "), (re.compile(r"\b\d{4}-\d{2}(\.\.\d{4}-\d{2})?\b"), " "),
    (re.compile(r"\b\d{2}:\d{2}\b"), " "),                                  # times
    (re.compile(r"\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{7}\b"), " "),  # commit hashes
    (re.compile(r"\(\d{8}\)"), " "),                                        # SKU codes
    (re.compile(r"\bDEC-\d+\b"), " "), (re.compile(r"\b0\d{3}\b"), " "), (re.compile(r"\b4019\b"), " "),
    (re.compile(r"\b\d{1,2} (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b"), " "),
    (re.compile(r"\b(January|February|March|April|May|June|July|August|September|October|November|December) (19|20)\d{2}\b"), " "),
    (re.compile(r"\b(19|20)\d{2}\b"), " "),
    (re.compile(r"^\s*(#+\s*)?\d+\.\s"), " "), (re.compile(r"^\|\s*\d+\s*\|"), "|"),
    (re.compile(r"^\|\s*[A-Z][A-Z0-9'&+()./ -]*X[0-9A-Z()+./ -]*\s*\|"), "|"),  # product-name first cells
    (re.compile(r"\b[A-Z][A-Z0-9'&+.()/ -]*\d+X\d+[A-Z0-9()+./]*"), " "),       # names like 48X12X10G in text
    (re.compile(r"\bfile:line\b"), " "), (re.compile(r"\bM−1\b|\bM − 1\b|M − 1"), " "), (re.compile(r"\bS_i|w_i|F_i|T_i|SS_i|rule_i|need_i"), " "),
]

rows = []
for ln, raw in enumerate((HERE / "README.md").read_text(encoding="utf-8").splitlines(), 1):
    line = raw
    for rx, rep in STRIP:
        line = rx.sub(rep, line)
    for m in NUM.finditer(line):
        sign, peso, whole, dec, unit = m.groups()
        d = len(dec) if dec else 0
        x = float(whole.replace(",", "") + ("." + dec if dec else ""))
        tol = 0.5 * 10 ** -d + 1e-9
        cands = [(x, tol)]
        if unit == "M":
            cands = [(x * 1e6, tol * 1e6)]
        elif unit == "%":
            cands = [(x, tol), (x / 100, tol / 100)]
        token = m.group(0).strip()
        ctx = line[max(0, m.start() - 40): m.end() + 40].strip()
        hits = [lab for v, lab in pool for c, t in cands if abs(v - c) <= t]
        status, source = "", ""
        if ESTIMATE_CONTEXT.search(line[max(0, m.start() - 15): m.end() + 15]):
            status, source = "estimate", "effort estimate (judgement, not data)"
        elif hits:
            status, source = "sourced", "; ".join(sorted(set(hits))[:3])
        elif x in QUOTES and unit in (None, "M") or (x * (1e6 if unit == "M" else 1)) in QUOTES:
            status, source = "quote", QUOTES.get(x) or QUOTES.get(x * 1e6)
        elif x in CONSTANTS:
            status, source = "constant", CONSTANTS[x]
        else:
            near = [(abs(v - c), lab, v) for v, lab in pool for c, t in cands if abs(v - c) <= 2 * 10 ** -d * (1e6 if unit == "M" else 1)]
            status, source = ("ROUNDING", f"nearest {min(near)[2]} ({min(near)[1]})") if near else ("UNSOURCED", "")
        if status == "sourced" and x <= 31 and d == 0 and unit is None and x in CONSTANTS:
            status, source = "constant", CONSTANTS[x] + f" | also matches {source}"
        rows.append({"line": ln, "token": token, "status": status, "source": source, "context": ctx})

out = pd.DataFrame(rows)
out.to_csv(HERE / "number_check.csv", index=False)
print(out["status"].value_counts().to_string())
bad = out[out["status"].isin(["UNSOURCED", "ROUNDING"])]
print(bad.to_string(index=False) if len(bad) else "no unsourced or mis-rounded numbers")
sys.exit(1 if len(bad) else 0)
