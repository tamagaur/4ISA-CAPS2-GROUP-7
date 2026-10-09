"""
Final quality check, surplus-bias experiment (2026-10-03). Read-only and offline: reads README.md, the
outputs in six_months/ and long_window/, inputs/ (local only, never committed) and git objects. Writes
quality_check/ beside this file. Nothing touches the database.

  1 NUMBER CHECK  every number in README.md traced to a committed CSV/JSON value, a value derived here
                  from those files (formula in `DERIVED`), a rule constant of run_experiment.py, or a
                  cited figure from another commit; the main tables are also checked cell by cell, and
                  derived claims are checked against their formula.
  2 ARITHMETIC    surplus + shortage = total miss; over + under + exact = scored; per-product sums, bins
                  and halves add up to the candidate totals; D rows add up.
  3 INDEPENDENT   fresh code (no import of run_experiment): the 29-month share over-forecast (as measured
                  and possibly stock-limited excluded) and candidate A's surplus removed / shortage added.
  4 DATA RULES    generated rows excluded, stock counts real only, opening count = period M-1.
  5 WORDING       price basis and period on every peso / result line, product name before SKU, jargon
                  spelled out, decisions recorded, "approximation from monthly counts".
  6 REPO HYGIENE  no client data in any commit on the branch (git log -p) or in the files to commit.

    ../Capstone-Project/.venv/Scripts/python.exe reports/diagnostics/surplus_bias_experiment_2026-10-03/quality_check.py
"""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
OUT = os.path.join(HERE, "quality_check")
WINDOWS = ("six_months", "long_window")
SOURCE_COMMIT, SOURCE_PATH = "b4f6b77", "reports/diagnostics/forecast_error_business_2026-10-03"
# b4f6b77 no longer commits the per-row long-window table; the diagnostic's own copy is in its git-ignored local/
SOURCE_LOCAL_FULL = os.path.join("C:/Users/kyuan/dsd-forecast-error-business", SOURCE_PATH, "local",
                                 "longwindow_per_product_month.csv")
LP_COMMIT, LP_README = "65ed2cc", "reports/diagnostics/lp_logic_check_2026-10-03/README.md"
BASE = "kelvin-etl"
SUMMARY_FILES = ("candidates_summary.csv", "candidate_D_review_flag.csv", "part0_recount.csv", "part0_coverage.csv",
                 "part0_stock_limited_by_side.csv", "part0_overrun_products.csv", "part0_carryover_next_month.csv",
                 "part0_labels_by_month.csv", "part0_count_completeness.csv")
RAW_STOCK_FIELDS = {"cases", "loose_pieces", "stock_value", "unit_cost_per_case", "blocked_cases", "blocked_pieces",
                    "_src_file", "_src_sheet", "valuation", "quantity_on_hand", "quantity_pieces", "customer_name",
                    "salesman_name", "net_amount", "gsv"}

CLIENT_COLUMNS = {"actual", "price_per_piece_sell_vat_inc", "price_sell_vat_inc", "naive", "ma3", "mean_actual",
                  "last3_mean", "last12_mean", "last3_before", "avg_monthly_pcs", "opening_pcs", "closing_pcs",
                  "cost_per_piece", "net_amount", "gsv", "quantity"}  # per-product sales / prices (Yuan, 2026-10-03)
CHECKS: list[dict] = []

# What this quality pass changed (2026-10-03), with the evidence; written to quality_check/fixes.csv.
FIXES = [
    ("2 arithmetic", "29-month per-bin pesos per month were averaged over the months each bin exists, so the three bins did not add up "
     "to the overall row", "run_experiment.score() now divides by the window's (or half's) months. Only 29-month bin rows moved, "
     "e.g. E1 24+ month bin -₱31,396 -> -₱15,157 per month (= E1 overall); every overall row and the whole 6-month window unchanged"),
    ("1 number", "A's six-month total removed read ₱536,466 (6 x the rounded ₱89,411)", "now ₱536,467 = 6 x ₱89,411.1745 "
     "(candidates_summary.csv); CHERRY BLOSSOM's part ₱381,388 -> ₱381,390 with exact prices (the CSV price is rounded to 4 decimals)"),
    ("1 number", "'share over' did not say how the 1 exactly-right product-month (29 months) is counted",
     "defined as over / (over + under); over / all scored = 51.6% is shown by the independent check"),
    ("1 number", "Limits said 'about 4 in 10' (no source)", "now 39% (6 months) to 47% (29 months), from results.json label counts"),
    ("5 wording", "price basis missing on the side-table headers and two bin bullets; no period on the territory scale line; "
     "Tier A used before it was defined", "added; Tier A defined in the first sentence after the title"),
    ("1 number", "29-month rebuild imported the source branch's working folder, which had uncommitted edits during this check",
     "run_experiment.py now reads its source files from a pinned commit (git show): b4f6b77, which replaced eebd741 when "
     "client data was stripped; per-row check against the source's git-ignored local/ table (2,419 of 2,419), per-product "
     "and window totals against b4f6b77's committed files"),
    ("6 hygiene", "per-product monthly sales and prices (both per_product_month.csv) and one product's monthly sales figure in the "
     "README were committed; Yuan's rule (2026-10-03) makes them client data",
     "per-month tables now written to the git-ignored local/<window>/; README describes the DOVE SH KERATIN month without the "
     "figure; the branch's 4 unpushed commits rewritten into one clean commit on 97a0236"),
    ("decisions", "threshold, 2026-02 acceptance, 2025-05 label and territory status were not recorded",
     "README 'Decisions recorded'; columns meets_recorded_threshold, shortage_added_not_above_surplus_removed, months_exact, "
     "count_note; results.json recorded_decisions and data_facts"),
]


def check(section: str, name: str, ok: bool, evidence: str):
    CHECKS.append({"section": section, "check": name, "status": "PASS" if ok else "FAIL", "evidence": evidence})


def git(*args, binary=False):
    r = subprocess.run(["git", "-C", REPO, *args], capture_output=True, check=True)
    return r.stdout if binary else r.stdout.decode("utf-8", "replace")


def local_csv(w, name):
    """The git-ignored local/<window>/ tables (per-product monthly sales and prices: client data, never committed)."""
    return pd.read_csv(os.path.join(HERE, "local", w, name), dtype={"sku_code": str})


def out_csv(w, name):
    return pd.read_csv(os.path.join(HERE, w, name), dtype={"sku_code": str})


def results(w):
    with open(os.path.join(HERE, w, "results.json")) as fh:
        return json.load(fh)


def inp(name, **kw):
    return pd.read_csv(os.path.join(HERE, "inputs", name), **kw)


def exact_prices(p: pd.DataFrame) -> pd.Series:
    """Selling price per piece, VAT-inclusive, recomputed from inputs/ without the CSVs' 4-decimal rounding:
    sum(net_amount) / sum(pieces) over each product's own months in `p`."""
    money = inp("demand_money_tierA.csv", dtype={"calendar_month": str}).rename(columns={"calendar_month": "month"})
    g = p[["product_key", "month"]].merge(money, on=["product_key", "month"], how="left").groupby("product_key")[["quantity", "net_amount"]].sum()
    return p.product_key.map(g.net_amount / g.quantity)


def fmt(v, d):
    return f"{abs(float(v)):.{d}f}"


# =========================================================================== #
# README parsing
# =========================================================================== #
def readme_lines() -> list[str]:
    with open(os.path.join(HERE, "README.md"), encoding="utf-8") as fh:
        return fh.read().split("\n")


def product_names() -> dict:
    names = {}
    for w in WINDOWS:
        p = local_csv(w, "per_product_month.csv")
        names.update(dict(zip(p.product_name, p.sku_code)))
    return names


TOKEN = re.compile(r"(?P<sign>[−+±])?(?P<peso>₱)?(?P<int>\d{1,3}(?:,\d{3})+|\d+)(?P<dec>\.\d+)?(?P<unit>%|×)?")


def clean(line: str, names: dict) -> str:
    """Remove what is not a reported number: code spans, product names and their SKU, dates, commit
    hashes, bin labels, month indices, ordinals, section and decision numbers, model labels."""
    s = re.sub(r"`[^`]*`", " ", line)
    for n in sorted(names, key=len, reverse=True):
        s = s.replace(n, " <P> ")
    s = re.sub(r"<P>\s*\(\d{8}\)", " <P> ", s)
    s = re.sub(r"\b\d{4}-\d{2}(?:-\d{2})?\b", " ", s)
    s = re.sub(r"\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{7}\b", " ", s)
    s = re.sub(r"\b3-11\b|\b12-23\b|\b24\+", " ", s)
    s = re.sub(r"M[−+\-]1", " ", s)
    s = re.sub(r"\b\d+(?:st|nd|rd|th)\b", " ", s)
    s = re.sub(r"\bMA3\b|\bE[12]\b", " ", s)
    s = re.sub(r"\bdecisions? \d\b", " ", s)
    s = re.sub(r"^\| \d \|", "|", s)
    if s.lstrip().startswith("#"):
        s = re.sub(r"\bPart 0\b|\b0\.\d\b", " ", s)
    s = re.sub(r"\b(?:see|in|Part) 0(?:\.\d)?\b", " ", s)
    return s


def tokens(text: str):
    for m in TOKEN.finditer(text):
        raw = m.group(0)
        num = (m.group("int") or "").replace(",", "") + (m.group("dec") or "")
        d = len(m.group("dec")) - 1 if m.group("dec") else 0
        sign = -1.0 if m.group("sign") == "−" else 1.0
        yield {"raw": raw, "text": num, "value": sign * float(num), "dec": d, "unit": m.group("unit") or "",
               "peso": bool(m.group("peso"))}


def readme_tables(lines: list[str]) -> list[dict]:
    tabs, i = [], 0
    while i < len(lines):
        if lines[i].startswith("|") and i + 1 < len(lines) and re.match(r"^\|[-:| ]+\|$", lines[i + 1]):
            head = [c.strip() for c in lines[i].strip("|").split("|")]
            rows, j = [], i + 2
            while j < len(lines) and lines[j].startswith("|"):
                rows.append((j + 1, [c.strip() for c in lines[j].strip("|").split("|")]))
                j += 1
            tabs.append({"line": i + 1, "head": head, "rows": rows, "caption": " ".join(lines[max(0, i - 4):i])})
            i = j
        else:
            i += 1
    return tabs


def cell_numbers(cells: list[str], names: dict) -> list[dict]:
    out = []
    for c in cells:
        out += list(tokens(clean(c, names)))
    return out


# =========================================================================== #
# 1. Number check
# =========================================================================== #
def pools(names: dict):
    committed = {}

    def add(pool, v, label):
        if v is None or isinstance(v, bool):
            return
        try:
            v = float(v)
        except (TypeError, ValueError):
            return
        if not np.isfinite(v):
            return
        for d in range(0, 8):
            pool.setdefault(("n", d, fmt(v, d)), label)
            pool.setdefault(("p", d, fmt(v * 100, d)), label + " (x100)")

    for w in WINDOWS:
        for f in SUMMARY_FILES:
            df = out_csv(w, f)
            for col in df.select_dtypes("number").columns:
                for v in df[col].dropna().unique():
                    add(committed, v, f"{w}/{f}:{col}")

        def walk(o, path):
            if isinstance(o, dict):
                for k, v in o.items():
                    walk(v, f"{path}.{k}")
            elif isinstance(o, list):
                for i, v in enumerate(o):
                    walk(v, f"{path}[{i}]")
            else:
                add(committed, o, f"{w}/results.json{path}")
        walk(results(w), "")

    derived_vals, derived_claims = derived(names)
    derived_pool = {}
    for label, v in derived_vals.items():
        for x in (v if isinstance(v, (list, tuple)) else [v]):
            add(derived_pool, x, f"derived: {label}")

    constants = {}
    sys.path.insert(0, HERE)
    import run_experiment as R   # constants only; nothing in section 3 uses this module
    for label, v in {"AVG_MONTHS": R.AVG_MONTHS, "AVG_MIN_MONTHS": R.AVG_MIN_MONTHS, "weeks per year": 52,
                     "months per year": 12, "LOW_WEEKS": R.LOW_WEEKS, "HIGH_WEEKS": R.HIGH_WEEKS,
                     "LOW_WEEKS_SENSITIVITY": R.LOW_WEEKS_SENSITIVITY, "COLLAPSE_RATIO": R.COLLAPSE_RATIO,
                     "COLLAPSE_RATIO %": R.COLLAPSE_RATIO * 100, "KS": R.KS, "WINDOWS": R.WINDOWS,
                     "CAP %": R.CAP * 100, "SAME_SIGN_MIN": R.SAME_SIGN_MIN, "RUN_MIN": R.RUN_MIN,
                     "WAPE_TOL_PTS": R.WAPE_TOL_PTS, "SURPLUS_CUT_MIN_PCT": R.SURPLUS_CUT_MIN_PCT,
                     "carryover dip line % (part0_carryover_next_month.csv)": 70,
                     "months in each window": [len(R.WINDOW_SPEC[w]["test"]) for w in WINDOWS],
                     "bin edge (router: 24+ sales months)": 24, "exact zero": 0,
                     "decision count": 4, "candidate bins": 3}.items():
        for x in (v if isinstance(v, (list, tuple)) else [v]):
            add(constants, x, f"constant: {label}")

    external_vals = external()
    external_pool = {}
    for label, v in external_vals.items():
        for x in (v if isinstance(v, (list, tuple)) else [v]):
            add(external_pool, x, f"external: {label}")
    return committed, derived_pool, constants, external_pool, derived_claims


def external() -> dict:
    lp = git("show", f"{LP_COMMIT}:{LP_README}")
    m = re.search(r"La Union sales are (\d+)%–(\d+)% \(median (\d+)%\)", lp)
    check("1 number", "LP check figure 57%-76% (median 62%) present at 65ed2cc", bool(m), m.group(0) if m else "not found")
    src = json.loads(git("show", f"{SOURCE_COMMIT}:{SOURCE_PATH}/results.json"))
    decs = max(len(x.split(".")[1]) for x in pd.read_csv(SOURCE_LOCAL_FULL, dtype=str).forecast.dropna() if "." in x)
    return {"LP check La Union share of Ilocos register %": [int(m.group(1)), int(m.group(2)), int(m.group(3))] if m else [],
            f"{SOURCE_COMMIT} results.json counts.scored_one_month / not_scored / scored_common":
                [src["counts"]["scored_one_month"], src["counts"]["not_scored"], src["counts"]["scored_common"]],
            "decimals of the source's per-row long-window table (local/)": decs}


def derived(names: dict):
    v, claims = {}, []
    six, lng = {w: results(w) for w in WINDOWS}.values()
    d6, dl = out_csv("six_months", "candidate_D_review_flag.csv"), out_csv("long_window", "candidate_D_review_flag.csv")
    m6, ml = d6.iloc[:-1], dl.iloc[:-1]
    v["D flagged per month min/max, 6 months"] = [m6.flagged.min(), m6.flagged.max()]
    v["D flagged per month min/max/median, 29 months"] = [ml.flagged.min(), ml.flagged.max(), ml.flagged.median()]
    v["D surplus share / sales share"] = [d6.iloc[-1].flagged_share_of_surplus_pesos_pct / d6.iloc[-1].flagged_share_of_sales_pesos_pct,
                                          dl.iloc[-1].flagged_share_of_surplus_pesos_pct / dl.iloc[-1].flagged_share_of_sales_pesos_pct]
    for w, lab in (("six_months", "6 months"), ("long_window", "29 months")):
        l = out_csv(w, "part0_labels_by_month.csv")
        pct = l.stock_limited / l.product_months * 100
        v[f"stock-limited % by month min/max, {lab}"] = [pct.min(), pct.max()]
        r = results(w)
        o = r["overrun_3plus"]
        v[f"run months stock-limited %, {lab}"] = o["run_months_stock_limited"] / o["run_months"] * 100
        v[f"all months stock-limited %, {lab}"] = r["labels_test"]["stock_limited"] / r["test_product_months"] * 100
        rc = out_csv(w, "part0_recount.csv")
        b = rc[rc.view.str.startswith("(b)")]
        v[f"(b) share over min/max across settings, {lab}"] = [b.over_share_pct.min(), b.over_share_pct.max()]
        v[f"settings per window, {lab}"] = len(rc) / 3
        v[f"count periods in completeness, {lab}"] = len(out_csv(w, "part0_count_completeness.csv"))
    ov = out_csv("six_months", "part0_overrun_products.csv")
    op = ov[ov.run_still_open_at_end]
    v["open runs at 2026-02: products / run months / stock-limited"] = [len(op), op.run_months.sum(), op.run_months_stock_limited.sum()]
    e = six["E"]
    dr, kp = e["training_rows_dropped"].values(), e["training_rows_kept"].values()
    v["E1 rows dropped share %, 6 months"] = sum(dr) / (sum(dr) + sum(kp)) * 100
    # A's 6-month concentration
    p = local_csv("six_months", "per_product_month.csv")
    price = exact_prices(p)
    sur = lambda f: (f - p.actual).clip(lower=0) * price
    p["d_sur"] = sur(p.fA) - sur(p.baseline)
    by = p.groupby(["product_name", "sku_code"]).d_sur.sum()
    cb = -by.loc[("SURF POWDER CHERRY BLOSSOM L 288X65G", "69668140")]
    c6a = out_csv("six_months", "candidates_summary.csv").query("candidate == 'A collapse cap' and scope == 'all'").iloc[0]
    tot = -c6a.surplus_pesos_per_month_change * 6          # the committed total, not the rounded per-product file
    v["A 6-month removal: CHERRY BLOSSOM / total / share %"] = [cb, tot, cb / tot * 100]
    dove = p[(p.sku_code == "64314335") & (p.month == "2025-12")].actual.iloc[0]
    v["DOVE SH KERATIN STRT&SILKY 288X13.5ML (64314335): 2025-12 sales negative"] = float(dove < 0)
    # territory arithmetic from the LP check's 57% / 62% / 76%
    v["territory: 1 La Union week in warehouse weeks (median)"] = 0.62
    v["territory: 2 La Union weeks in warehouse weeks"] = [2 * 0.57, 2 * 0.76]
    v["territory: cover overstated by"] = [1 / 0.76, 1 / 0.57]
    c6 = out_csv("six_months", "candidates_summary.csv")
    small = c6[c6.candidate.isin(["B k=0.25, 3-month bias", "C = A + B k=0.25, 3-month bias"]) & c6.scope.isin(["3-11 months", "12-23 months"])]
    v["B/C median WAPE change in 3-11 and 12-23 bins, 6 months"] = [small.median_product_wape_pct_change.min(), small.median_product_wape_pct_change.max()]
    cl = out_csv("long_window", "candidates_summary.csv")
    abc = cl[(cl.scope == "all") & cl.candidate.isin(["A collapse cap", "B k=0.25, 3-month bias", "C = A + B k=0.25, 3-month bias"])]
    v["max surplus cut of A, B, C over 29 months, % (claim: under 1%)"] = abc.surplus_cut_pct.max()

    # claims: README text -> computed values (checked in section 1b)
    claims += [
        ("A concentration (6 months)", r"accounts for\s+₱([\d,]+) of the ₱([\d,]+) of surplus removed.*?\((\d+)%\)",
         [f"{cb:,.0f}", f"{tot:,.0f}", f"{cb / tot * 100:.0f}"]),
        ("D range 6 months", r"marks (\d+) to (\d+) of the 107 products a month over", [f"{m6.flagged.min()}", f"{m6.flagged.max()}"]),
        ("D range 29 months", r"and (\d+) to (\d+) a month over", [f"{ml.flagged.min()}", f"{ml.flagged.max()}"]),
        ("D median 29 months", r"\((\d+) to (\d+) products a month, median (\d+)\)",
         [f"{ml.flagged.min()}", f"{ml.flagged.max()}", f"{ml.flagged.median():.0f}"]),
        ("D surplus vs sales share", r"share of sales pesos: ([\d.]+)× over .*? and ([\d.]+)× over",
         [f"{v['D surplus share / sales share'][0]:.1f}", f"{v['D surplus share / sales share'][1]:.1f}"]),
        ("labels by month 6 months", r"tags (\d+)% to (\d+)% of products each month over",
         [f"{x:.0f}" for x in v["stock-limited % by month min/max, 6 months"]]),
        ("labels by month 29 months", r"and (\d+)% to (\d+)% over 2023-10 to 2026-02 \(",
         [f"{x:.0f}" for x in v["stock-limited % by month min/max, 29 months"]]),
        ("run months stock-limited", r"\*\*(\d+) \(([\d.]+)%\)\*\* \| \*\*(\d+) \(([\d.]+)%\)\*\*",
         [str(six["overrun_3plus"]["run_months_stock_limited"]), f"{v['run months stock-limited %, 6 months']:.1f}",
          str(lng["overrun_3plus"]["run_months_stock_limited"]), f"{v['run months stock-limited %, 29 months']:.1f}"]),
        ("all months stock-limited", r"\| ([\d.]+)% \((\d+) of (\d+)\) \| ([\d.]+)% \(([\d,]+) of ([\d,]+)\) \|",
         [f"{v['all months stock-limited %, 6 months']:.1f}", "250", "642", f"{v['all months stock-limited %, 29 months']:.1f}", "1,142", "2,419"]),
        ("open runs", r"The (\d+) products still in a run at 2026-02 have (\d+) possibly stock-limited months among their (\d+) run months",
         [str(len(op)), str(int(op.run_months_stock_limited.sum())), str(int(op.run_months.sum()))]),
        ("sensitivity ranges", r"between ([\d.]+)% and ([\d.]+)% over in the 6-month window, and between ([\d.]+)% and ([\d.]+)%",
         [f"{x:.1f}" for x in v["(b) share over min/max across settings, 6 months"] + v["(b) share over min/max across settings, 29 months"]]),
        ("settings count", r"has all (\d+) settings per window", [f"{v['settings per window, 6 months']:.0f}"]),
        ("E1 rows dropped", r"about (\d+)% of rows", [f"{v['E1 rows dropped share %, 6 months']:.0f}"]),
        ("E1 rows dropped range", r"(\d[\d,]*) to (\d[\d,]*) rows dropped and (\d[\d,]*) to (\d[\d,]*) kept",
         [f"{min(dr):,}", f"{max(dr):,}", f"{min(kp):,}", f"{max(kp):,}"]),
        ("DOVE negative month, described without the figure", r"64314335\), whose 2025-12 net sales were (negative)",
         ["negative" if dove < 0 else "not negative"]),
        ("labels 39% to 47%", r"It tags (\d+)% \(2025-09 to 2026-02\) to (\d+)% \(2023-10 to 2026-02\) of product-months",
         [f"{v['all months stock-limited %, 6 months']:.0f}", f"{v['all months stock-limited %, 29 months']:.0f}"]),
        ("territory weeks", r"about ([\d.]+) weeks of the warehouse's own sales", ["0.6"]),
        ("territory 2-week", r"about ([\d.]+) to ([\d.]+) weeks of warehouse sales", [f"{2 * 0.57:.1f}", f"{2 * 0.76:.1f}"]),
        ("territory overstated", r"overstated by about ([\d.]+)× to ([\d.]+)×", [f"{1 / 0.76:.1f}", f"{1 / 0.57:.2f}"]),
        ("B/C small bins", r"B and C raise median WAPE by ([\d.]+) to ([\d.]+) points",
         [f"{x:.1f}" for x in v["B/C median WAPE change in 3-11 and 12-23 bins, 6 months"]]),
        ("under 1%", r"each removes under (\d)% of surplus pesos", ["1"] if abc.surplus_cut_pct.max() < 1 else ["claim false"]),
        ("largest cut 29 months", r"the largest surplus cut is ([\d.]+)% \(E1\)",
         [f"{cl[(cl.scope == 'all') & (cl.candidate != 'baseline')].surplus_cut_pct.max():.1f}"]),
        ("all 38 periods", r"all (\d+) periods 2023-01 to 2026-02", [str(v["count periods in completeness, 6 months"])]),
    ]
    claims += prose_claims()
    best = cl[(cl.scope == "all") & (cl.candidate != "baseline")].sort_values("surplus_cut_pct").iloc[-1].candidate
    check("1 number", "largest 29-month surplus cut belongs to E1", best.startswith("E1"), f"largest cut: {best}")
    return v, claims


def prose_claims() -> list:
    """The prose numbers people read first, each tied to the cell it restates."""
    P = lambda v: f"{abs(v):,.0f}"
    one = lambda v: f"{abs(v):.1f}"
    two = lambda v: f"{abs(v):.2f}"
    out = []
    for w, anchor in (("six_months", r"6 months, 2025-09 to 2026-02\*\* \(642 product-months\): "),
                      ("long_window", r"29 months, 2023-10 to 2026-02\*\* \(2,419 product-months\): ")):
        r = out_csv(w, "part0_recount.csv")
        r = r[r.setting == "low stock < 1 wk; counts as recorded"].set_index("view")
        a, b = r.loc["(a) as measured"], r.loc["(b) stock-limited months excluded"]
        exact = r", (\d+) exactly right " if w == "long_window" else " "
        pat = (anchor + r"- As measured: ([\d,]+) over(?:-forecast)?, ([\d,]+) under(?:-forecast)?" + exact
               + r"\(([\d.]+)% over\)\. Surplus ₱([\d,]+) per month against shortage ₱([\d,]+) per month.*?"
               r"- With the ([\d,]+) possibly stock-limited product-months left out: ([\d,]+) over, ([\d,]+) under "
               r"\(([\d.]+)% over\)\. Surplus ₱([\d,]+) per month against shortage ₱([\d,]+) per month")
        want = [P(a.over), P(a.under)] + ([P(a.exact)] if w == "long_window" else []) + \
               [one(a.over_share_pct), P(a.surplus_pesos_per_month), P(a.shortage_pesos_per_month), P(b.stock_limited_months),
                P(b.over), P(b.under), one(b.over_share_pct), P(b.surplus_pesos_per_month), P(b.shortage_pesos_per_month)]
        out.append((f"plain-language bullets, {w}", pat, want))
    sd = out_csv("six_months", "part0_stock_limited_by_side.csv").set_index("group")
    lim = sd.loc[["opening count low only", "closing count low only", "both counts low"]]
    out.append(("evidence bullet", r"those months sold ([\d.]+)× to ([\d.]+)× of their own 12-month average pieces, against "
                r"([\d.]+)× for the other months\. They were also over-forecast in ([\d.]+)% to ([\d.]+)% of cases, against ([\d.]+)%",
                [two(lim.median_sales_vs_12m_avg.min()), two(lim.median_sales_vs_12m_avg.max()),
                 two(sd.loc["not stock-limited"].median_sales_vs_12m_avg), one(lim.over_forecast_pct.min()),
                 one(lim.over_forecast_pct.max()), one(sd.loc["not stock-limited"].over_forecast_pct)]))
    d6, dl = out_csv("six_months", "candidate_D_review_flag.csv").iloc[-1], out_csv("long_window", "candidate_D_review_flag.csv").iloc[-1]
    out.append(("D bullets", r"carry ([\d.]+)% of surplus pesos with ([\d.]+)% of sales pesos over the 6 months, and ([\d.]+)% with "
                r"([\d.]+)% over the 29 months.*?over-forecast: ([\d.]+)% against ([\d.]+)% \(6 months\), and ([\d.]+)% against ([\d.]+)%",
                [one(d6.flagged_share_of_surplus_pesos_pct), one(d6.flagged_share_of_sales_pesos_pct),
                 one(dl.flagged_share_of_surplus_pesos_pct), one(dl.flagged_share_of_sales_pesos_pct),
                 one(d6.flagged_over_forecast_pct), one(d6.unflagged_over_forecast_pct),
                 one(dl.flagged_over_forecast_pct), one(dl.unflagged_over_forecast_pct)]))
    r6, rl = out_csv("six_months", "part0_recount.csv"), out_csv("long_window", "part0_recount.csv")
    t6 = r6[(r6.setting == "low stock < 2 wk; counts as recorded") & r6.view.str.startswith("(b)")].iloc[0]
    tl = rl[(rl.setting == "low stock < 2 wk; counts as recorded") & rl.view.str.startswith("(b)")].iloc[0]
    out.append(("territory 2-week fallback", r"([\d.]+)% of misses are over-forecast over 2025-09 to 2026-02, with surplus ₱([\d,]+) per "
                r"month above shortage\. Over 2023-10 to 2026-02 the figures are ([\d.]+)% and ₱([\d,]+) per month",
                [one(t6.over_share_pct), P(t6.surplus_minus_shortage_pesos_per_month), one(tl.over_share_pct),
                 P(tl.surplus_minus_shortage_pesos_per_month)]))
    cs6, csl = out_csv("six_months", "candidates_summary.csv"), out_csv("long_window", "candidates_summary.csv")
    g = lambda c, name, scope="all", rows="all test months": c[(c.candidate == name) & (c.scope == scope) & (c.rows == rows)].iloc[0]
    nsl = "non-stock-limited test months only"
    e1l = g(csl, "E1 XGBoost rows excluded", rows=nsl)
    out.append(("E misses", r"\(E1\) removes ([\d.]+)% of surplus over 29 months, on the ([\d,]+) product-months",
                [one(e1l.surplus_cut_pct), P(e1l.product_months)]))
    abc = ["A collapse cap", "B k=0.25, 3-month bias", "C = A + B k=0.25, 3-month bias"]
    for c, lab, per in ((cs6, "6 months", "2025-09 to 2026-02"), (csl, "29 months", "2023-10 to 2026-02")):
        out.append((f"A/B/C stock-limited excluded, {lab}", r"cut surplus by ₱([\d,]+), ₱([\d,]+)\s+and ₱([\d,]+) per month over " + per,
                    [P(g(c, n).surplus_pesos_per_month_excl_stock_limited_change) for n in abc]))
    out.append(("bins: A/B/C in 24+ months, 6 months", r"cut that bin's surplus by ([\d.]+)%, ([\d.]+)% and ([\d.]+)% \(₱([\d,]+), ₱([\d,]+) and ₱([\d,]+) per month",
                [one(g(cs6, n, "24+ months").surplus_cut_pct) for n in abc] + [P(g(cs6, n, "24+ months").surplus_pesos_per_month_change) for n in abc]))
    e16 = g(cs6, "E1 XGBoost rows excluded", "24+ months", nsl)
    e1all6 = g(cs6, "E1 XGBoost rows excluded", rows=nsl)
    out.append(("bins: E1 6 months", r"Median WAPE falls ([\d.]+) points, and surplus falls ₱([\d,]+) per month at selling price, VAT-inclusive "
                r"\(([\d.]+)%\), with (\d+) products better and (\d+) worse\. - It fails overall only because the first-half median across all products rose ([\d.]+) points",
                [two(e16.median_product_wape_pct_change), P(e16.surplus_pesos_per_month_change), one(e16.surplus_cut_pct),
                 str(int(e16.products_better)), str(int(e16.products_worse)), two(e1all6.h1_median_wape_change_pts)]))
    e1b = g(csl, "E1 XGBoost rows excluded", "24+ months", nsl)
    out.append(("bins: E1 29 months", r"the same bin cuts ₱([\d,]+) per month at selling price, VAT-inclusive, averaged over all 29 months "
                r"\(([\d.]+)% of that bin's surplus\), with median WAPE up ([\d.]+) points",
                [P(e1b.surplus_pesos_per_month_change), one(e1b.surplus_cut_pct), two(e1b.median_product_wape_pct_change)]))
    e26, e2l = g(cs6, "E2 + MA3/TSB on cleaned history", "12-23 months", nsl), g(csl, "E2 + MA3/TSB on cleaned history", "12-23 months", nsl)
    out.append(("bins: E2", r"it cuts ₱([\d,]+) per month at selling price, VAT-inclusive, with median WAPE down ([\d.]+) points, but that rests on "
                r"(\d+) products and (\d+) product-months\. Over 2023-10 to 2026-02 it reverses: surplus up ₱([\d,]+) per month \(same basis, "
                r"averaged over all 29 months\) and median WAPE up ([\d.]+) points",
                [P(e26.surplus_pesos_per_month_change), two(e26.median_product_wape_pct_change), str(int(e26.products)),
                 str(int(e26.product_months)), P(e2l.surplus_pesos_per_month_change), two(e2l.median_product_wape_pct_change)]))
    o6, ol = results("six_months")["overrun_3plus"], results("long_window")["overrun_3plus"]
    for lab, key in ((r"Products with a run of 3\+ over-forecast months", "products"), ("Product-months inside those runs", "run_months"),
                     ("Products with at least one possibly stock-limited run month", "products_with_any_stock_limited_run_month"),
                     (r"Products whose run months were \*all\* possibly stock-limited", "products_all_run_months_stock_limited"),
                     ("Run product-months with high carryover", "run_months_high_carryover")):
        out.append((f"run table: {key}", rf"\| {lab} \| (\d+) \| (\d+) \|", [str(o6[key]), str(ol[key])]))
    cv = {w: out_csv(w, "part0_coverage.csv") for w in WINDOWS}
    cvv = lambda w, setting, item: int(cv[w][(cv[w].setting == setting) & (cv[w].item == item)].product_months.iloc[0])
    rec, m26, m25 = "counts as recorded", "2026-02 count treated as missing", "2025-05 count treated as missing"
    out.append(("coverage: both sides", r"\| Usable count on both sides \| (\d+) of (\d+) \| (\d+) \| ([\d,]+) of ([\d,]+) \| ([\d,]+) \|",
                [str(cvv("six_months", rec, "both sides")), "642", str(cvv("six_months", m26, "both sides")),
                 f"{cvv('long_window', rec, 'both sides'):,}", "2,419", f"{cvv('long_window', m25, 'both sides'):,}"]))
    for lab, item in (("A side rests on \"missing from the count = 0\"", "a side rests on stock_not_in_count (missing from the count = 0)"),
                      (r"Possibly stock-limited \*\*only\*\* because a product was missing from the count",
                       "stock-limited only because a product was missing from the count")):
        out.append((f"coverage: {item[:30]}", rf"\| {lab} \| (\d+) \| (\d+) \| (\d+) \| (\d+) \|",
                    [str(cvv("six_months", rec, item)), str(cvv("six_months", m26, item)), str(cvv("long_window", rec, item)),
                     str(cvv("long_window", m25, item))]))
    lp = git("show", f"{LP_COMMIT}:{LP_README}")
    m = re.search(r"La Union sales are (\d+)%–(\d+)% \(median (\d+)%\)", lp)
    out.append(("territory figures equal the LP check at 65ed2cc", r"La Union sales run (\d+)% to (\d+)% \(median (\d+)%\)",
                list(m.groups()) if m else ["not found in the LP check"]))
    return out


def number_check(lines, names):
    committed, derived_pool, constants, external_pool, claims = pools(names)
    rows, in_code = [], False
    for i, line in enumerate(lines, 1):
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        for t in tokens(clean(line, names)):
            hit = None
            keys = [("n", t["dec"], t["text"])] + ([("p", t["dec"], t["text"])] if t["unit"] == "%" else [])
            sig = len(t["text"].replace(".", "").lstrip("0"))
            order = (("committed file", committed), ("derived", derived_pool), ("rule constant", constants), ("external commit", external_pool))
            if sig < 3:
                order = (order[2], order[1], order[3], order[0])
            for kind, pool in order:
                for k in keys:
                    if k in pool:
                        hit = (kind, pool[k])
                        break
                if hit:
                    break
            sig = len(t["text"].replace(".", "").lstrip("0"))
            rows.append({"line": i, "token": t["raw"], "value": t["value"], "status": hit[0] if hit else "UNSOURCED",
                         "source": hit[1] if hit else "", "strength": "strong (3+ significant digits)" if sig >= 3 else "weak (1-2 digits)"})
    nc = pd.DataFrame(rows)
    uns = nc[nc.status == "UNSOURCED"]
    check("1 number", "every README number traced to a source", uns.empty,
          f"{len(nc)} numbers: " + ", ".join(f"{k} {v}" for k, v in nc.status.value_counts().items())
          + ("" if uns.empty else f"; UNSOURCED: {uns[['line', 'token']].values.tolist()}"))
    # 1b derived claims
    text = re.sub(r"\s+", " ", "\n".join(lines))
    bad = []
    for label, pat, want in claims:
        m = re.search(pat, text)
        got = list(m.groups()) if m else None
        if got != want:
            bad.append(f"{label}: README {got} vs computed {want}")
    check("1 number", f"derived claims match their formula ({len(claims)} claims)", not bad, "; ".join(bad) if bad else "all match")
    return nc


# ---- cell-by-cell table checks -------------------------------------------------- #
CAND_NAME = {"A. Collapse cap": "A collapse cap", "B k=0.25, 3-month": "B k=0.25, 3-month bias",
             "B k=0.5, 3-month": "B k=0.5, 3-month bias", "B k=1, 3-month": "B k=1, 3-month bias",
             "B k=0.25, 6-month": "B k=0.25, 6-month bias", "B k=0.5, 6-month": "B k=0.5, 6-month bias",
             "B k=1, 6-month": "B k=1, 6-month bias", "C. A + B k=0.25, 3-month": "C = A + B k=0.25, 3-month bias",
             "E1. XGBoost rows excluded": "E1 XGBoost rows excluded", "E2. + MA3/TSB on cleaned history": "E2 + MA3/TSB on cleaned history"}
CHANGED_KEY = {"E1 XGBoost rows excluded": "E1", "E2 + MA3/TSB on cleaned history": "E2"}


def compare_row(label, got: list[dict], want: list[tuple], issues: list, where: str):
    gv = [(t["value"], t["dec"]) for t in got]
    if len(gv) != len(want):
        issues.append(f"{where} {label}: {len(gv)} numbers in README, {len(want)} expected")
        return 0
    n = 0
    for (g, gd), (w, wd) in zip(gv, want):
        w_r = float(f"{w:.{wd}f}")
        if gd != wd or abs(g) != abs(w_r) or (w_r != 0 and np.sign(g) != np.sign(w_r)):
            issues.append(f"{where} {label}: README {g} vs expected {w_r}")
        n += 1
    return n


def table_checks(lines, names):
    tabs = readme_tables(lines)
    issues, cells = [], 0
    rc = {w: out_csv(w, "part0_recount.csv") for w in WINDOWS}
    cs = {w: out_csv(w, "candidates_summary.csv") for w in WINDOWS}
    rs = {w: results(w) for w in WINDOWS}
    side = {w: out_csv(w, "part0_stock_limited_by_side.csv").set_index("group") for w in WINDOWS}
    recount_tabs = [t for t in tabs if t["head"][0] == "View"]
    cand_tabs = [t for t in tabs if t["head"][0] == "Candidate" and t["head"][1].startswith("Product-months changed")]
    for w, t in zip(WINDOWS, recount_tabs):
        r = rc[w][rc[w].setting == "low stock < 1 wk; counts as recorded"].set_index("view")
        for ln, row in t["rows"]:
            x = r.loc[row[0]]
            want = [(x.over, 0), (x.under, 0), (x.exact, 0), (x.over_share_pct, 1), (x.surplus_pesos_per_month, 0),
                    (x.shortage_pesos_per_month, 0), (x.surplus_minus_shortage_pesos_per_month, 0)]
            cells += compare_row(row[0], cell_numbers(row[1:], names), want, issues, f"recount {w} line {ln}")
    for w, key in (("six_months", "Group, 6 months"), ("long_window", "Group, 29 months")):
        t = next(t for t in tabs if t["head"][0].startswith(key))
        for ln, row in t["rows"]:
            g = "can't tell (no label)" if row[0].startswith("no label") else row[0]
            x = side[w].loc[g]
            want = [(x.product_months, 0), (x.over_forecast_pct, 1)] + \
                   ([] if pd.isna(x.median_sales_vs_12m_avg) else [(x.median_sales_vs_12m_avg, 2)]) + \
                   [(x.surplus_pesos_per_month, 0), (x.shortage_pesos_per_month, 0)]
            cells += compare_row(row[0], cell_numbers(row[1:], names), want, issues, f"side {w} line {ln}")
    for w, t in zip(WINDOWS, cand_tabs):
        c = cs[w][cs[w].scope == "all"]
        for ln, row in t["rows"]:
            lab = row[0].strip("*")
            if lab.startswith("Baseline"):
                rows = "all test months" if "all" in lab else "non-stock-limited test months only"
                x = c[(c.candidate == "baseline") & (c.rows == rows)].iloc[0]
                want = [(x.median_product_wape_pct, 1), (x.total_wape_pct, 1), (x.signed_bias_pct, 1),
                        (x.surplus_pesos_per_month, 0), (x.shortage_pesos_per_month, 0)]
                cells += compare_row(lab, cell_numbers(row[1:], names), want, issues, f"candidates {w} line {ln}")
                continue
            name = CAND_NAME[lab]
            x = c[c.candidate == name].iloc[0]
            ch = rs[w]["rows_changed"][CHANGED_KEY.get(name, name)]
            want = [(ch["product_months"], 0), (ch["products"], 0), (x.median_product_wape_pct, 1),
                    (x.median_product_wape_pct_change, 2), (x.total_wape_pct, 1), (x.signed_bias_pct, 1),
                    (x.surplus_pesos_per_month_change, 0), (-x.surplus_cut_pct, 1), (x.shortage_pesos_per_month_change, 0),
                    (x.products_better, 0), (x.products_worse, 0), (x.h1_surplus_change_pesos_per_month, 0),
                    (x.h2_surplus_change_pesos_per_month, 0)]
            if w == "six_months" and name.startswith("E1"):
                want.append((x.h1_median_wape_change_pts, 2))
            cells += compare_row(lab, cell_numbers(row[1:], names), want, issues, f"candidates {w} line {ln}")
            yn = [cc for cc in row if cc in ("yes", "no") or cc.startswith("no:")]
            exp = ["yes" if x.meets_decision_rule else "no"] + (["yes" if x.meets_recorded_threshold else "no"] if w == "long_window" else [])
            if [y[:3].rstrip(":") for y in yn] != exp:
                issues.append(f"candidates {w} line {ln} {lab}: rule cells {yn} vs expected {exp}")
            cells += len(exp)
    # D table
    t = next(t for t in tabs if t["head"][0] == "Month")
    d = {w: out_csv(w, "candidate_D_review_flag.csv") for w in WINDOWS}
    for ln, row in t["rows"]:
        lab = row[0].strip("*")
        if lab.startswith("2025-09 to"):
            x = d["six_months"].iloc[-1]
        elif lab.startswith("2023-10 to"):
            x = d["long_window"].iloc[-1]
        else:
            x = d["six_months"].set_index("month").loc[lab]
        want = [(x.flagged, 0), (x.flagged_by_run, 0), (x.flagged_by_collapse, 0), (x.flagged_over_forecast_pct, 1),
                (x.unflagged_over_forecast_pct, 1), (x.flagged_share_of_surplus_pesos_pct, 1),
                (x.flagged_share_of_shortage_pesos_pct, 1), (x.flagged_share_of_sales_pesos_pct, 1)]
        cells += compare_row(lab, cell_numbers(row[1:], names), want, issues, f"D line {ln}")
    # carryover table
    t = next(t for t in tabs if t["head"][0] == "Months compared")
    cs6, csl = out_csv("six_months", "part0_carryover_next_month.csv"), out_csv("long_window", "part0_carryover_next_month.csv")
    order = [(cs6, "all months", "high carryover"), (cs6, "all months", "neither"), (cs6, "all months", "stock-limited"),
             (cs6, "test window", "high carryover"), (cs6, "test window", "neither"),
             (csl, "test window", "high carryover"), (csl, "test window", "neither")]
    for (ln, row), (src, wn, grp) in zip(t["rows"], order):
        x = src[src.window.str.startswith(wn) & src.group.str.startswith(grp)].iloc[0]
        want = [(x.product_months, 0), (x.median_this_month_vs_avg, 2), (x.median_next_month_vs_avg, 2),
                (x.share_next_month_below_avg_pct, 1), (x.share_next_month_below_70pct_of_avg, 1)]
        cells += compare_row(f"{row[0]} / {row[1]}", cell_numbers(row[2:], names), want, issues, f"carryover line {ln}")
    # headline table
    t = next(t for t in tabs if t["head"][0] == "Candidate" and t["head"][1].startswith("Surplus removed, 6 months"))
    for ln, row in t["rows"]:
        name = {"A. Collapse cap": "A collapse cap", "B. Bias correction, k = 0.25, 3-month bias": "B k=0.25, 3-month bias",
                "C. A + B": "C = A + B k=0.25, 3-month bias"}[row[0]]
        a = cs["six_months"].query("scope == 'all' and candidate == @name").iloc[0]
        b = cs["long_window"].query("scope == 'all' and candidate == @name").iloc[0]
        want = [(-a.surplus_pesos_per_month_change, 0), (a.surplus_cut_pct, 1), (a.shortage_pesos_per_month_change, 0),
                (-b.surplus_pesos_per_month_change, 0), (b.surplus_cut_pct, 1), (b.shortage_pesos_per_month_change, 0),
                (b.products_better, 0), (b.products_worse, 0)]
        cells += compare_row(row[0], cell_numbers(row[1:], names), want, issues, f"headline line {ln}")
    check("1 number", f"main tables checked cell by cell ({cells} cells in {len(recount_tabs) + 2 + len(cand_tabs) + 3} tables)",
          not issues, "; ".join(issues) if issues else "every cell equals its CSV value at the shown rounding")


MUTATIONS = [
    ("table cell: A's 29-month products changed 13 -> 14", "| A. Collapse cap | 23 (13) |", "| A. Collapse cap | 23 (14) |"),
    ("prose: 6-month share over 56.2% -> 56.3%", "(56.2% over). Surplus", "(56.3% over). Surplus"),
    ("prose peso: E1 bin cut ₱86,465 -> ₱86,466", "surplus falls ₱86,465 per month", "surplus falls ₱86,466 per month"),
    ("range: D 12 to 26 -> 12 to 27", "It marks 12 to 26 of the 107", "It marks 12 to 27 of the 107"),
    ("new unsourced number", "which is short of 5%.", "which is short of 5% (₱4,321 short)."),
    ("missing price basis", "₱381,390 of the ₱536,467 of surplus removed over 2025-09 to 2026-02, at selling price, VAT-inclusive (71%).",
     "₱381,390 of the ₱536,467 of surplus removed over 2025-09 to 2026-02 (71%)."),
    ("missing period", "12.3% with 9.8% over the 29 months, at selling price", "12.3% with 9.8% in the other window, at selling price"),
    ("SKU before product name", "SURF POWDER TAWAS L 40(6+1)57G (64861490)", "64861490 SURF POWDER TAWAS L 40(6+1)57G"),
]


def self_test(lines, names):
    """Each deliberate README error must turn at least one check FAIL; the real README is never changed."""
    global CHECKS
    saved, rows = CHECKS, []
    for desc, old, new in MUTATIONS:
        hit = [k for k, l in enumerate(lines) if old in l]
        if not hit:
            joined = "\n".join(lines)
            if old not in joined:
                rows.append((desc, False, ["mutation text not found"]))
                continue
            mut = joined.replace(old, new, 1).split("\n")
        else:
            mut = list(lines)
            mut[hit[0]] = mut[hit[0]].replace(old, new, 1)
        CHECKS = []
        number_check(mut, names)
        table_checks(mut, names)
        wording(mut, names)
        rows.append((desc, any(c["status"] == "FAIL" for c in CHECKS), [c["check"] for c in CHECKS if c["status"] == "FAIL"]))
    CHECKS = saved
    check("1 number", f"self-test: {len(rows)} deliberate README errors are each caught", all(c for _, c, _ in rows),
          "; ".join(f"{d} -> {'caught by: ' + ' + '.join(x[:45] for x in f) if c else 'MISSED'}" for d, c, f in rows))


# =========================================================================== #
# 2. Arithmetic
# =========================================================================== #
def arithmetic():
    cand_cols = {"baseline": "baseline", "A collapse cap": "fA", "B k=0.25, 3-month bias": "fB_k0.25_w3",
                 "B k=0.5, 3-month bias": "fB_k0.5_w3", "B k=1, 3-month bias": "fB_k1_w3",
                 "B k=0.25, 6-month bias": "fB_k0.25_w6", "B k=0.5, 6-month bias": "fB_k0.5_w6",
                 "B k=1, 6-month bias": "fB_k1_w6", "C = A + B k=0.25, 3-month bias": "fC",
                 "E1 XGBoost rows excluded": "fE1", "E2 + MA3/TSB on cleaned history": "fE2"}
    src_cmp = pd.read_csv(io.StringIO(git("show", f"{SOURCE_COMMIT}:{SOURCE_PATH}/window_comparison.csv")), index_col=0)
    src_col = {"six_months": "A: 6 months, bin fixed", "long_window": "C: 29 months, bin re-worked"}
    for w in WINDOWS:
        p = local_csv(w, "per_product_month.csv")
        r, cs = results(w), out_csv(w, "candidates_summary.csv")
        n = r["test_months"][2]
        months = sorted(p.month.unique())
        half = (n + 1) // 2
        halves = (months[:half], months[half:])
        price = exact_prices(p)
        p["price_exact"] = price
        gap_price = float((price - p.price_per_piece_sell_vat_inc).abs().max())
        # forecasts in the CSV are rounded to 4 decimals (actuals are whole pieces): a peso total can move by at
        # most sum(price x 0.00005) / months
        tol = float((price * 0.00005).sum() / n) + 0.01
        sl = p.stock_limited.astype(str).str.lower().eq("true")
        known = p.stock_limited.notna() & (p.stock_limited.astype(str) != "")
        # 2a surplus + shortage = total miss, and = the source diagnostic's average monthly miss
        e = p.baseline - p.actual
        miss = (e.abs() * price).sum() / n
        b = cs[(cs.candidate == "baseline") & (cs.scope == "all") & (cs.rows == "all test months")].iloc[0]
        src_miss = float(src_cmp.loc["avg_monthly_miss_pesos_sell", src_col[w]])
        ok = abs(b.surplus_pesos_per_month + b.shortage_pesos_per_month - miss) < tol and \
            abs(b.surplus_pesos_per_month + b.shortage_pesos_per_month - src_miss) < 0.01
        check("2 arithmetic", f"{w}: surplus + shortage = total miss = source diagnostic's miss", ok,
              f"₱{b.surplus_pesos_per_month:,.2f} + ₱{b.shortage_pesos_per_month:,.2f} = ₱{b.surplus_pesos_per_month + b.shortage_pesos_per_month:,.2f}; "
              f"Σ|error|×price/{n} from the per-product file = ₱{miss:,.2f} (rounding bound ₱{tol:.2f}); "
              f"{SOURCE_COMMIT} window_comparison.csv = ₱{src_miss:,.2f}; recomputed price vs file price: largest gap ₱{gap_price:.6f}")
        # 2b over + under + exact = scored, every candidates row and every recount row
        bad = cs[(cs.months_over + cs.months_under + cs.months_exact) != cs.product_months]
        rc = out_csv(w, "part0_recount.csv")
        scored = np.where(rc.view.str.startswith("(b)"), rc.product_months - rc.stock_limited_months, rc.product_months)
        bad_rc = rc[(rc.over + rc.under + rc.exact) != scored]
        check("2 arithmetic", f"{w}: over + under + exact = scored product-months ({len(cs)} candidate rows, {len(rc)} recount rows)",
              bad.empty and bad_rc.empty, f"mismatches: candidates {len(bad)}, recount {len(bad_rc)}")
        # 2c per-product sums = candidate totals; surplus + shortage = miss for every candidate; bins add up; halves add up
        worst, worst_bin, worst_half = 0.0, 0.0, 0.0
        for name, col in cand_cols.items():
            rows_lab = "non-stock-limited test months only" if col in ("fE1", "fE2") else "all test months"
            sub = p[known & ~sl] if col in ("fE1", "fE2") else p
            pr = sub.price_exact
            ec = sub[col] - sub.actual
            per_prod = pd.DataFrame({"k": sub.product_key, "s": ec.clip(lower=0) * pr, "h": (-ec).clip(lower=0) * pr}).groupby("k").sum()
            row = cs[(cs.candidate == name) & (cs.scope == "all") & (cs.rows == rows_lab)].iloc[0]
            worst = max(worst, abs(per_prod.s.sum() / n - row.surplus_pesos_per_month),
                        abs(per_prod.h.sum() / n - row.shortage_pesos_per_month),
                        abs((ec.abs() * pr).sum() / n - row.surplus_pesos_per_month - row.shortage_pesos_per_month))
            bins = cs[(cs.candidate == name) & (cs.scope != "all") & (cs.rows == rows_lab)]
            worst_bin = max(worst_bin, abs(bins.surplus_pesos_per_month.sum() - row.surplus_pesos_per_month),
                            abs(bins.shortage_pesos_per_month.sum() - row.shortage_pesos_per_month))
            if name != "baseline":
                for _, rr in cs[(cs.candidate == name) & (cs.rows == rows_lab)].iterrows():
                    h = (rr.h1_surplus_change_pesos_per_month if pd.notna(rr.h1_surplus_change_pesos_per_month) else 0) * len(halves[0]) + \
                        (rr.h2_surplus_change_pesos_per_month if pd.notna(rr.h2_surplus_change_pesos_per_month) else 0) * len(halves[1])
                    worst_half = max(worst_half, abs(h / n - rr.surplus_pesos_per_month_change))
        check("2 arithmetic", f"{w}: per-product surplus and shortage sum to each candidate's total, and surplus + shortage = miss",
              worst < tol, f"largest gap ₱{worst:.4f} per month over {len(cand_cols)} candidates (rounding bound ₱{tol:.2f})")
        check("2 arithmetic", f"{w}: the three history bins add up to the overall row", worst_bin < 0.01,
              f"largest gap ₱{worst_bin:.6f} per month")
        check("2 arithmetic", f"{w}: the two halves add up to the whole-window change", worst_half < 0.01,
              f"largest gap ₱{worst_half:.6f} per month (halves of {len(halves[0])} and {len(halves[1])} months)")
        # 2d side table and recount
        sd = out_csv(w, "part0_stock_limited_by_side.csv")
        ok = (sd.product_months.sum() == len(p) and abs(sd.surplus_pesos_per_month.sum() - b.surplus_pesos_per_month) < 0.01
              and abs(sd.shortage_pesos_per_month.sum() - b.shortage_pesos_per_month) < 0.01)
        check("2 arithmetic", f"{w}: side-split groups add up to the whole window", ok,
              f"product-months {sd.product_months.sum()} of {len(p)}; surplus ₱{sd.surplus_pesos_per_month.sum():,.2f} vs ₱{b.surplus_pesos_per_month:,.2f}")
        r1 = rc[rc.setting == "low stock < 1 wk; counts as recorded"].set_index("view")
        rb = r1.loc["(b) stock-limited months excluded"]
        s_b = (e[~sl].clip(lower=0) * price[~sl]).sum() / n
        h_b = ((-e[~sl]).clip(lower=0) * price[~sl]).sum() / n
        ok = abs(rb.surplus_pesos_per_month - s_b) < tol and abs(rb.shortage_pesos_per_month - h_b) < tol
        check("2 arithmetic", f"{w}: recount (b) = surplus and shortage of the months not possibly stock-limited", ok,
              f"₱{rb.surplus_pesos_per_month:,.2f} / ₱{rb.shortage_pesos_per_month:,.2f} vs recomputed ₱{s_b:,.2f} / ₱{h_b:,.2f} "
              f"({int((~sl).sum())} product-months incl. {int((~known).sum())} without a label; rounding bound ₱{tol:.2f})")
        # 2e D rows add up
        dd = out_csv(w, "candidate_D_review_flag.csv")
        mo, al = dd.iloc[:-1], dd.iloc[-1]
        fl = p[p.flag_D.astype(str).str.lower() == "true"]
        e_fl = fl.baseline - fl.actual
        share = (e_fl.clip(lower=0) * fl.price_exact).sum() / (e.clip(lower=0) * price).sum() * 100
        ok = (mo.flagged.sum() == al.flagged and mo.flagged_by_run.sum() == al.flagged_by_run
              and mo.flagged_by_collapse.sum() == al.flagged_by_collapse and len(fl) == al.flagged
              and abs(share - al.flagged_share_of_surplus_pesos_pct) < 1e-3)
        check("2 arithmetic", f"{w}: D monthly rows add up to the window row", ok,
              f"flagged {mo.flagged.sum()} = {al.flagged}; surplus share recomputed {share:.4f}% vs {al.flagged_share_of_surplus_pesos_pct:.4f}%")
        # 2f 3+ run table consistency
        ov = out_csv(w, "part0_overrun_products.csv")
        o = r["overrun_3plus"]
        ok = (len(ov) == o["products"] and ov.run_months.sum() == o["run_months"]
              and ov.run_months_stock_limited.sum() == o["run_months_stock_limited"]
              and (ov.run_months_stock_limited <= ov.run_months).all())
        check("2 arithmetic", f"{w}: over-run table adds up", ok,
              f"{len(ov)} products, {ov.run_months.sum()} run months, {ov.run_months_stock_limited.sum()} possibly stock-limited")


# =========================================================================== #
# 3. Independent recompute (fresh code; reads inputs/ and the source commit's CSV only)
# =========================================================================== #
def independent():
    # forecasts from the diagnostic's own per-row table (its code, not this experiment's), git-ignored local/ copy
    lw = pd.read_csv(SOURCE_LOCAL_FULL)[["product_key", "month", "actual", "forecast"]].copy()
    money = inp("demand_money_tierA.csv", dtype={"calendar_month": str})
    dem = inp("demand_real_tierA.csv", dtype={"calendar_month": str})
    dims = inp("product_dimension_tierA.csv", dtype={"sku_code": str})
    snaps = inp("stock_snapshots_unilever.csv", dtype={"_period": str})
    stock = inp("stock_real_tierA_by_period.csv", dtype={"_period": str})

    # price per piece over each product's own scored months
    mm = lw[["product_key", "month"]].merge(money.rename(columns={"calendar_month": "month"}), on=["product_key", "month"], how="left")
    agg = mm.groupby("product_key")[["quantity", "net_amount"]].sum()
    lw["price"] = lw.product_key.map(agg.net_amount / agg.quantity)

    # monthly pieces per product, zero-filled from the first month with a sale
    q = dem.assign(quantity=pd.to_numeric(dem.quantity, errors="coerce").fillna(0)).groupby(["product_key", "calendar_month"]).quantity.sum()
    hist = {}
    for k, g in q.groupby(level=0):
        g = g.droplevel(0)
        g.index = pd.PeriodIndex(g.index, freq="M")
        full = g.reindex(pd.period_range(g.index.min(), g.index.max(), freq="M"), fill_value=0.0)
        pos = full[full > 0]
        hist[k] = full.loc[pos.index[0]:] if len(pos) else full.iloc[0:0]

    # stock in pieces per (product, period); real periods only
    real = set(snaps.loc[(snaps.is_demo.astype(str) == "False") & snaps.fill_source.isna(), "_period"])
    pack = pd.to_numeric(dims.set_index("product_key").pack_size, errors="coerce")
    stock["pcs"] = stock.cases * stock.product_key.map(pack) + stock.loose_pieces.fillna(0)
    on_hand = stock.set_index(["product_key", "_period"]).pcs.to_dict()

    def count_at(k, per):
        if str(per) not in real:
            return np.nan
        return on_hand.get((k, str(per)), 0.0)

    lab, ratio, last3, open_w, close_w, wks = [], [], [], [], [], []
    for k, m in zip(lw.product_key, lw.month):
        M = pd.Period(m, freq="M")
        h = hist[k]
        before = h[h.index < M]
        prior12 = before.iloc[-12:]
        avg = prior12.mean() if len(prior12) >= 3 else np.nan
        wk = avg * 12 / 52 if avg == avg and avg > 0 else np.nan
        o, c = count_at(k, M - 1), count_at(k, M)
        sides = [x for x in (o, c) if x == x]
        lim = None
        if sides:
            if any(x <= 0 for x in sides) or (wk == wk and any(x < wk for x in sides)):
                lim = True
            elif wk == wk:
                lim = False
        lab.append(lim)
        wks.append(wk)
        open_w.append(o / wk if wk == wk and o == o else np.nan)
        close_w.append(c / wk if wk == wk and c == c else np.nan)
        ok12 = len(before) >= 12 and before.iloc[-12:].mean() > 0
        ratio.append(before.iloc[-3:].mean() / before.iloc[-12:].mean() if ok12 else np.nan)
        last3.append(before.iloc[-3:].mean() if len(before) else np.nan)
    lw["limited"], lw["ratio"], lw["last3"] = lab, ratio, last3
    lw["open_w"], lw["close_w"], lw["wk"] = open_w, close_w, wks

    err = lw.forecast - lw.actual
    over, under = int((err > 0).sum()), int((err < 0).sum())
    keep = lw.limited != True  # noqa: E712  (unlabelled months stay in, as in the report)
    over_b, under_b = int((err[keep] > 0).sum()), int((err[keep] < 0).sum())
    share_a, share_b = over / (over + under) * 100, over_b / (over_b + under_b) * 100
    fA = np.where(lw.ratio < 0.5, np.maximum(0, np.minimum(lw.forecast, lw.last3)), lw.forecast)
    eA = fA - lw.actual
    removed = ((err.clip(lower=0) - eA.clip(lower=0)) * lw.price).sum() / 29
    added = (((-eA).clip(lower=0) - (-err).clip(lower=0)) * lw.price).sum() / 29
    check("3 independent", "29-month share over-forecast, as measured = 51.7%", f"{share_a:.1f}" == "51.7",
          f"{over} over / {under} under / {len(lw) - over - under} exact of {len(lw)} -> {share_a:.3f}% "
          f"(over ÷ all {len(lw)} = {over / len(lw) * 100:.3f}%)")
    check("3 independent", "29-month share over-forecast, possibly stock-limited excluded = 52.7%", f"{share_b:.1f}" == "52.7",
          f"{over_b} over / {under_b} under of {int(keep.sum())} kept ({int((lw.limited == True).sum())} possibly stock-limited) -> {share_b:.3f}%")  # noqa: E712
    check("3 independent", "29-month candidate A: surplus removed ₱25,572 / shortage added ₱36,660 per month",
          f"{removed:,.0f}" == "25,572" and f"{added:,.0f}" == "36,660",
          f"removed ₱{removed:,.2f}, added ₱{added:,.2f} per month at selling price, VAT-inclusive; "
          f"{int((lw.ratio < 0.5).sum())} product-months tripped the collapse rule, {int((np.abs(fA - lw.forecast) > 1e-9).sum())} changed")
    return lw


# =========================================================================== #
# 4. Data rules
# =========================================================================== #
def data_rules(lw_indep: pd.DataFrame):
    dem = inp("demand_real_tierA.csv", dtype={"calendar_month": str})
    flags = dem.is_demo.astype(str).str.lower().value_counts().to_dict()
    pull_src = git("show", f"{SOURCE_COMMIT}:{SOURCE_PATH}/pull_inputs.py") + git("show", "HEAD:reports/diagnostics/fit_diagnosis_2026-10/run_fit_diagnosis.py")
    ok = flags == {"false": len(dem)} and "FROM Unilever_SKU_Demand_Fact_Real" in pull_src
    check("4 data rules", "demand: generated rows excluded (is_demo = false via Unilever_SKU_Demand_Fact_Real)", ok,
          f"is_demo values in demand_real_tierA.csv: {flags}; months {dem.calendar_month.min()} to {dem.calendar_month.max()}; "
          f"pull SQL reads Unilever_SKU_Demand_Fact_Real")
    with open(os.path.join(HERE, "pull_stock_counts.py"), encoding="utf-8") as fh:
        pull = fh.read()
    snaps = inp("stock_snapshots_unilever.csv", dtype={"_period": str})
    real = set(snaps.loc[(snaps.is_demo.astype(str) == "False") & snaps.fill_source.isna(), "_period"])
    gen = set(snaps.loc[~snaps._period.isin(real), "_period"])
    st = inp("stock_real_tierA_by_period.csv", dtype={"_period": str})
    used = set(st._period)
    ok = ("is_demo = false AND fill_source IS NULL" in pull) and used <= real and not (used & gen)
    check("4 data rules", "stock: real counts only (is_demo = false AND fill_source IS NULL)", ok,
          f"{len(used)} periods read, all among {len(real)} real periods ({min(real)} to {max(real)}); "
          f"0 of the {len(gen)} generated periods ({', '.join(sorted(snaps.loc[~snaps._period.isin(real)].fill_source.dropna().unique()))})")
    # each month uses its own opening count (period M-1): fresh recompute vs the committed weeks of cover
    rep = local_csv("long_window", "per_product_month.csv")[["product_key", "month", "opening_weeks", "closing_weeks"]]
    j = rep.merge(lw_indep[["product_key", "month", "open_w", "close_w", "wk"]], on=["product_key", "month"])
    gap_o = float((j.opening_weeks - j.open_w).abs().max())
    gap_c = float((j.closing_weeks - j.close_w).abs().max())
    # negative control: the same weeks of cover built from the LATEST real count (period 2026-03) for every month
    pack = pd.to_numeric(inp("product_dimension_tierA.csv").set_index("product_key").pack_size, errors="coerce")
    latest = st[st._period == max(real)]
    latest_pcs = j.product_key.map((latest.cases * latest.product_key.map(pack) + latest.loose_pieces.fillna(0))
                                   .set_axis(latest.product_key)).fillna(0.0)
    latest_w = latest_pcs / j.wk
    comparable = j.opening_weeks.notna() & latest_w.notna()
    agree_latest = int(((latest_w - j.opening_weeks).abs() < 1e-3)[comparable].sum())
    ok = gap_o < 1e-3 and gap_c < 1e-3 and len(j) == len(rep) and agree_latest < 0.05 * comparable.sum()
    check("4 data rules", "each month uses its own opening count (period M-1) and closing count (period M), not the latest", ok,
          f"{len(j)} product-months (29 months): fresh recompute vs committed weeks of cover, largest gap opening {gap_o:.1e}, "
          f"closing {gap_c:.1e} weeks; negative control: built from the latest count ({max(real)}), only {agree_latest} of "
          f"{int(comparable.sum())} opening values would agree")


# =========================================================================== #
# 5. Wording
# =========================================================================== #
def wording(lines, names):
    text_lines = list(lines)
    tabs = readme_tables(lines)
    table_of = {}
    for t in tabs:
        for ln, _ in t["rows"]:
            table_of[ln] = t
    section = ""
    blocks, cur = [], []
    sec_of = {}
    for i, l in enumerate(text_lines, 1):
        if l.startswith("#"):
            section = l.lstrip("# ").strip()
        sec_of[i] = section
        if l.strip() == "" or l.startswith("#") or l.startswith("|"):
            if cur:
                blocks.append(cur)
            cur = []
            continue
        if re.match(r"^\s*- ", l) and cur and not re.match(r"^\s{2,}- ", l):
            blocks.append(cur)
            cur = []
        cur.append(i)
    if cur:
        blocks.append(cur)
    block_of = {i: b for b in blocks for i in b}
    exempt_sections = {"Terms", "0.1 Rules (approximations from monthly counts)", "Files", "Data used"}
    period_re = re.compile(r"\d{4}-\d{2}|\b6 months\b|\b29 months\b|6-month|29-month|\bwindow\b")
    basis_re = re.compile(r"selling price|same price basis|same window and basis|same basis")
    miss_basis, miss_period = [], []
    for i, l in enumerate(text_lines, 1):
        if sec_of[i] in exempt_sections or l.startswith("#") or l.startswith("```"):
            continue
        if i in table_of:
            t = table_of[i]
            if t["head"][1:2] == ["Rule as implemented"] or t["head"][0] in ("Rule", "Term", "What", "File", "#"):
                continue
            ctx = " ".join(t["head"]) + " " + t["caption"] + " " + l
        elif i in block_of:
            ctx = re.sub(r"\s+", " ", " ".join(text_lines[j - 1] for j in block_of[i]))
        else:
            continue
        has_num = bool(re.search(r"\d", clean(l, names)))
        if "₱" in l and not basis_re.search(ctx):
            miss_basis.append(i)
        if has_num and ("₱" in l or "%" in l or "×" in l) and not period_re.search(ctx):
            miss_period.append(i)
    check("5 wording", "every peso figure carries its price basis (at selling price, VAT-inclusive)", not miss_basis,
          f"lines without the basis in their row/table/paragraph: {miss_basis}" if miss_basis else "all lines with ₱ covered")
    check("5 wording", "every result line names its period", not miss_period,
          f"lines without a period: {miss_period}" if miss_period else "all result lines covered")
    raw = "\n".join(lines)
    bad = []
    for n, sku in names.items():
        for m in re.finditer(re.escape(n), raw):
            after = raw[m.end():m.end() + 12]
            if not re.match(rf"\s*\({sku}\)", after):
                bad.append(f"{n} not followed by ({sku})")
    for m in re.finditer(r"(?<![\d.])\d{8}(?![\d.])", raw):
        sku = m.group(0)
        name = next((n for n, s in names.items() if s == sku), None)
        if name is None or not raw[:m.start()].rstrip(" (").endswith(name):
            bad.append(f"SKU {sku} not preceded by its product name")
    check("5 wording", "product NAME first, SKU after", not bad, "; ".join(bad) if bad else
          f"{sum(len(re.findall(re.escape(n), raw)) for n in names)} product mentions, all 'NAME (SKU)'")
    flat = re.sub(r"\s+", " ", "\n".join(lines[1:]))      # the title line names the scope; definitions follow it
    jargon = {"VAT": "VAT-inclusive (value-added tax)", "SKU": "SKU (stock-keeping unit)", "ABC": "ABC (Pareto)",
              "SSM": "SSM (San San Marketing)", "LP": "LP (linear-programming", "PO Qty": "\"PO Qty\" (purchase-order quantity)",
              "NaN": "NaN (not-a-number)", "MA3": "MA3 (moving average", "TSB": "TSB (Teunter", "XGBoost": "XGBoost (a gradient-boosted",
              "WAPE": "| WAPE | Weighted absolute percentage error", "k": "| k | Strength of the bias correction",
              "Tier A": "Tier A is the top class"}
    miss = [k for k, pat in jargon.items() if pat not in flat]
    early = []
    for k, pat in jargon.items():
        first = re.search(rf"(?<![\w-]){re.escape(k)}(?![\w-])" if k not in ("VAT",) else r"VAT", flat)
        if pat in flat and first and first.start() < flat.index(pat) and k not in ("k",):
            early.append(f"{k} used before it is spelled out")
    check("5 wording", "jargon spelled out", not miss and not early, "; ".join(miss + early) if (miss or early) else
          f"{len(jargon)} terms spelled out at or before first use: {', '.join(jargon)}")
    need = {"decision 1 threshold": r"at least \*\*5% of surplus pesos\*\* over the 29-month window",
            "decision 1 shortage": r"must not add more shortage pesos than it removes",
            "decision 1 outcome D": r"Recommendation: D \(flag only\)",
            "decision 2 accept 2026-02": r"The 2026-02 stock count\*\* \(taken 2026-03-02\) is \*\*accepted\*\*, pending confirmation from SSM",
            "decision 3 possibly partial": r"labelled \*\*\"possibly partial\"\*\*\. Open question for SSM",
            "decision 4 unverified + 2-week": r"\*\*UNVERIFIED\.\*\* \| The 2-week La Union fallback is reported below",
            "approximation wording": r"\*\*\"Possibly stock-limited\" is an approximation from monthly counts\.\*\*"}
    miss = [k for k, pat in need.items() if not re.search(pat, flat)]
    check("5 wording", "decisions recorded; 'stock-limited' described as an approximation from monthly counts", not miss,
          f"missing: {miss}" if miss else "all 4 decisions and the approximation wording present")


# =========================================================================== #
# 6. Repo hygiene (the dry merge is run separately, in git, after the commit)
# =========================================================================== #
def hygiene():
    commits = git("log", "--format=%h", f"{BASE}..HEAD").split()
    files = set(git("log", "--name-only", "--format=", f"{BASE}..HEAD").split())   # files touched by the branch's own commits
    pending = {l[3:] for l in git("status", "--porcelain", "--untracked-files=all", "--", HERE).splitlines()}
    allf = sorted(files | pending)
    bad_path = [f for f in allf if "/inputs/" in f or "/local/" in f or f.endswith("/per_product_month.csv")
                or f.startswith("data/raw") or f.endswith((".xlsx", ".xls", ".pkl", ".parquet"))]
    check("6 hygiene", "no pulled input or local/ per-month file in any commit on the branch or in the files to commit",
          not bad_path, f"{len(commits)} commit(s) on the branch, {len(allf)} files; flagged: {bad_path}")
    logp = git("log", "-p", "--format=commit %h", f"{BASE}..HEAD")
    added_csv_heads, cur = [], None
    for l in logp.splitlines():
        if l.startswith("+++ b/"):
            cur = l[6:]
        elif cur and cur.endswith(".csv") and l.startswith("+") and not l.startswith("+++"):
            added_csv_heads.append((cur, l[1:]))
            cur = None
    hits = []
    for f, head in added_csv_heads:
        cols = set(c.strip() for c in head.split(","))
        if cols & (RAW_STOCK_FIELDS | CLIENT_COLUMNS):
            hits.append(f"{f}: {sorted(cols & (RAW_STOCK_FIELDS | CLIENT_COLUMNS))}")
    for f in allf:
        if f.endswith(".csv") and os.path.exists(os.path.join(REPO, f)):
            cols = set(pd.read_csv(os.path.join(REPO, f), nrows=0).columns)
            if cols & (RAW_STOCK_FIELDS | CLIENT_COLUMNS):
                hits.append(f"{f} (to commit): {sorted(cols & (RAW_STOCK_FIELDS | CLIENT_COLUMNS))}")
    dove_fig = [l for l in logp.splitlines() if l.startswith("+") and "64314335" in l and re.search(r"−\d+ pieces in 2025-12", l)]
    hits += [f"README per-product sales figure in git log -p: {l[:80]}" for l in dove_fig]
    check("6 hygiene", "no per-product sales, prices or raw stock/sales fields in any commit (git log -p) or file to commit",
          not hits, "; ".join(hits) if hits else
          f"{len(added_csv_heads)} CSV headers in git log -p and {sum(f.endswith('.csv') for f in allf)} CSVs checked; none has "
          f"{sorted(RAW_STOCK_FIELDS | CLIENT_COLUMNS)}; no per-product monthly sales figure in any README version")
    ign = {p: subprocess.run(["git", "-C", REPO, "check-ignore", "-q", os.path.join(HERE, *p.split("/"))]).returncode == 0
           for p in ("inputs/stock_real_tierA_by_period.csv", "local/six_months/per_product_month.csv",
                     "local/long_window/per_product_month.csv")}
    present = {p: os.path.exists(os.path.join(HERE, *p.split("/"))) for p in ign}
    check("6 hygiene", "inputs/ and local/ (client data) are git-ignored", all(ign.values()) and all(present.values()),
          f"ignored: {ign}; present on this machine: {present}")


# =========================================================================== #
def main():
    os.makedirs(OUT, exist_ok=True)
    lines, names = readme_lines(), product_names()
    nc = number_check(lines, names)
    table_checks(lines, names)
    self_test(lines, names)
    arithmetic()
    lw = independent()
    data_rules(lw)
    wording(lines, names)
    hygiene()
    ch = pd.DataFrame(CHECKS)
    nc.to_csv(os.path.join(OUT, "number_check.csv"), index=False)
    pd.DataFrame(FIXES, columns=["section", "found", "fixed"]).assign(status="FIXED").to_csv(os.path.join(OUT, "fixes.csv"), index=False)
    ch.to_csv(os.path.join(OUT, "checks.csv"), index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_colwidth", 400)
    for r in ch.itertuples():
        print(f"[{r.status}] {r.section} | {r.check}\n        {r.evidence}")
    print(nc.status.value_counts().to_string())
    weak = nc[nc.strength.str.startswith("weak") & (nc.status == "committed file")]
    print(f"weak committed matches: {len(weak)}")
    return 0 if (ch.status == "PASS").all() else 1


if __name__ == "__main__":
    sys.exit(main())
