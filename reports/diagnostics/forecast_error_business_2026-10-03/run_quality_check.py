"""
Final quality check of README.md and its files (2026-10-03). Read-only and offline: reads the committed outputs,
local/ and inputs/ (both git-ignored), and the repo; writes only quality_check.csv and qc_numbers.csv.

1 NUMBER CHECK  every number in README.md looked up in the committed CSV / JSON files; unmatched numbers are
                listed as rule/parameter (a definition, not data) or UNSOURCED.
2 ARITHMETIC    surplus + shortage = miss; over + under + exact = scored product-months; category sums = total;
                review exposure adds up.
3 RECOMPUTE     fresh code - no import from run_analysis, run_followups, the fit_diagnosis harness, analytics.* or
                statsmodels. Actual sales and prices from inputs/; forecasts taken as given (6 months from
                reports/simulation/synthetic_2026-10/series.csv, an artifact of a different script; 29 months from
                local/longwindow_per_product_month.csv, forecast column only).
4 DATA RULES    generated rows excluded (is_demo via the _Real view; fill_source); stock count filter.
5 WORDING       peso price-basis label, product name before SKU, jargon spelled out at first use, DEC-26 wording.

    ../Capstone-Project/.venv/Scripts/python.exe reports/diagnostics/forecast_error_business_2026-10-03/run_quality_check.py
"""
from __future__ import annotations

import glob
import json
import os
import re

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
INP, LOCAL = os.path.join(HERE, "inputs"), os.path.join(HERE, "local")
README = os.path.join(HERE, "README.md")
SELL_LABEL, COST_LABEL = "selling price, VAT-inclusive (value-added tax)", "at cost (stock count)"
CHECKS: list[dict] = []


def check(area, item, ok, evidence):
    CHECKS.append({"area": area, "item": item, "status": "PASS" if ok else "FAIL", "evidence": evidence})


def jload(name):
    with open(os.path.join(HERE, name)) as fh:
        return json.load(fh)


# --------------------------------------------------------------------------- #
# 1. Number check
# --------------------------------------------------------------------------- #
def numeric_leaves(obj, label):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from numeric_leaves(v, f"{label}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from numeric_leaves(v, f"{label}[{i}]")
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        yield float(obj), label


J1, J2 = "results.json", "followups_results.json"
INPUT_SUMMARIES = ["inputs/base_is_demo_summary.csv", "inputs/stock_count_snapshots.csv", "inputs/forecast_result_dates.csv"]
# Each README section may only use these files (a number must come from its own section's sources, not from
# anywhere in the folder). Product rows of a table are narrowed further to that product's rows.
SECTION_SOURCES = {
    "intro": [J1], "top": [J1, J2, "window_comparison.csv", "monthly_totals.csv"],
    "1": [J1, *INPUT_SUMMARIES, "ROWCOUNTS"], "2": ["per_product_summary.csv", "monthly_totals.csv", J1],
    "3": ["per_product_summary.csv", J1], "4": ["category_total_accuracy.csv", J1],
    "5": [J1, "cv_terciles.csv", "cv_vs_wape.csv"],
    "6": [J1, "seasonality_reconciliation.csv", "seasonality_noise_calibration.csv", "monthly_totals.csv"],
    "7": ["collapse_flag.csv", "collapse_threshold_sensitivity.csv", "collapse_flag_backtest.csv", "per_product_summary.csv", J1],
    "8": ["window_comparison.csv", "window_category_total_accuracy.csv", "longwindow_per_product_summary.csv", J2],
    "9": ["xgb_month_ablation.csv", "xgb_month_ablation_2026-03.csv", J1, J2],
    "10": ["seasonality_rule_false_alarm_summary.csv", "seasonality_rule_false_alarm_by_length.csv",
           "seasonality_rule_labels.csv", "seasonality_reconciliation.csv", J2],
    "11": ["review_before_ordering.csv", "per_product_summary.csv", J2],
    "12": ["ROWCOUNTS", J1, J2], "13": [J1, J2],
}


def file_values(name, key=None):
    """(values, labels) from one source; key narrows a per-product file to that product's rows."""
    if name in (J1, J2):
        out = list(numeric_leaves(jload(name), name))
        return [v for v, _ in out], [lab for _, lab in out]
    if name == "ROWCOUNTS":
        vals, labs = [], []
        for path in glob.glob(os.path.join(HERE, "*.csv")) + glob.glob(os.path.join(LOCAL, "*.csv")) + \
                glob.glob(os.path.join(INP, "*.csv")):
            vals.append(float(len(pd.read_csv(path))))
            labs.append(f"rows:{os.path.relpath(path, HERE)}")
        return vals, labs
    df = pd.read_csv(os.path.join(HERE, name))
    if key is not None:
        if "product_key" not in df.columns:
            return [], []
        df = df[df.product_key == key]
    vals, labs = [], []
    for col in df.columns:
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        vals.extend(s.tolist())
        labs.extend([f"{name}:{col}"] * len(s))
    return vals, labs


def sources(section, key=None):
    vals, labs = [], []
    for name in SECTION_SOURCES.get(section, [J1, J2]):
        if key is not None and name not in (J1, J2) and name not in ("ROWCOUNTS",):
            v, lab = file_values(name, key)
        elif key is not None:
            continue                                            # product rows: that product's rows + nothing else
        else:
            v, lab = file_values(name)
        vals.extend(v)
        labs.extend(lab)
    return np.asarray(vals, dtype=float), np.asarray(labs)


# Definitions, settings and thresholds that are stated, not measured (each traces to a rule in the scripts or the
# decision register): seeds, simulation counts, thresholds, window lengths, VAT rate, runtimes.
PARAMETERS = {0.6, 0.3, 1.96, 0.5, 0.7, 0.4, 1.1, 0.9, 1.12, 5, 95, 50, 500, 200, 1000, 2000, 20260921, 20260922,
              20261003, 24, 36, 12, 3, 6, 29, 2, 1, 4, 3.5, 100, 0, 16, 20, 0.001}


def strip_for_numbers(text: str, names: list[str]) -> str:
    t = re.sub(r"`[^`]*`", " ", text)                            # code spans: files, line numbers, parameters
    t = re.sub(r"\]\([^)]*\)", "]", t)                          # link targets
    for n in sorted(names, key=len, reverse=True):              # product names carry pack sizes
        t = t.replace(n, " PRODUCT ")
    t = re.sub(r'"[^"]*~[^"]*"', " QUOTE ", t)                 # the question being answered, quoted ("~373 ... ~112")
    t = re.sub(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{4}-\d{2}\b", " DATE ", t)
    t = re.sub(r"\b20[12]\d\b", " YEAR ", t)                    # years written out ("October 2023", "2023–2025")
    t = re.sub(r"\b\d{2}:\d{2}\b", " TIME ", t)
    t = re.sub(r"§\d+(–§?\d+)?", " SECTION ", t)
    t = re.sub(r"\bDEC-\d+\b|\bR\d\b|\bMA\d+\b|ACF\(\d+\)|AR\(\d\)|\blag-\d+\b|\b\d+\+", " ID ", t)
    t = re.sub(r"\b\d{8}\b", " SKU ", t)                         # SKU codes are checked in the wording section
    return t


TOKEN = re.compile(r"(?<![\w.])([−+-]?)(₱)?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(\s?%|\s?points|M\b| million)?")


def number_check(names, key_by_name):
    rows = []
    with open(README, encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    section, cache, product_table = "intro", {}, False
    for ln, raw in enumerate(lines, 1):
        h = re.match(r"## (\d+)\.|## Is 30%", raw)
        if h:
            section = h.group(1) or "top"
        if section == "14":                                     # the quality-check section reports on this check itself
            continue
        if raw.startswith("|") and ln < len(lines) and lines[ln].startswith("|---"):
            product_table = raw.startswith("| Product |")       # header row: is this a one-row-per-product table?
        if not raw.startswith("|"):
            product_table = False
        key = None
        if raw.startswith("|") and product_table:
            for n in sorted(names, key=len, reverse=True):
                if n in raw:
                    key = key_by_name[n]
                    break
        if (section, key) not in cache:
            cache[(section, key)] = sources(section, key)
        vals, labs = cache[(section, key)]
        for m in TOKEN.finditer(strip_for_numbers(raw, names)):
            sign, peso, whole, frac, suffix = m.groups()
            v = float(whole.replace(",", "") + ("." + frac if frac else ""))
            d = len(frac) if frac else 0
            tol = 0.5 * 10 ** -d + 1e-9
            sgn = -1.0 if sign in ("−", "-") else 1.0
            suffix = (suffix or "").strip()
            scales = [1.0, 100.0] if suffix in ("%", "points") else ([1e-6] if suffix in ("M", "million") else [1.0, 100.0])
            hit = None
            for k in scales:
                for cand in (vals * k, np.abs(vals) * k):
                    ok = np.flatnonzero(np.abs(cand - v) <= tol)
                    if ok.size:
                        hit = labs[ok[0]]
                        break
                if hit:
                    break
            if hit is None and sgn < 0:
                ok = np.flatnonzero(np.abs(vals * 100 + v) <= tol)
                hit = labs[ok[0]] if ok.size else None
            status = "sourced" if hit else ("parameter" if v in PARAMETERS else "UNSOURCED")
            rows.append({"section": section, "line": ln, "product_row": key is not None, "token": m.group(0).strip(),
                         "value": sgn * v, "status": status, "first_source": hit or "", "text": raw.strip()[:140]})
    qc = pd.DataFrame(rows)
    qc.to_csv(os.path.join(HERE, "qc_numbers.csv"), index=False)
    un = qc[qc.status == "UNSOURCED"]
    check("1 numbers", "every README number (§14 excluded) found in its own section's files, product rows in that "
          "product's rows (or a stated parameter)", un.empty,
          f"{len(qc)} numbers: {int((qc.status == 'sourced').sum())} sourced ({int(qc.product_row.sum())} on product rows), "
          f"{int((qc.status == 'parameter').sum())} parameters, {len(un)} unsourced"
          + ("" if un.empty else f" (lines {sorted(set(un.line))[:25]})"))
    return qc


# --------------------------------------------------------------------------- #
# 2. Arithmetic
# --------------------------------------------------------------------------- #
def arithmetic():
    mt = pd.read_csv(os.path.join(HERE, "monthly_totals.csv"))
    months = mt[mt.month != "average per month"]
    gap = (months.shortage_value_sell + months.surplus_value_sell - months.abs_error_pesos_sell).abs().max()
    check("2 arithmetic", "monthly totals: shortage + surplus = total miss (each month, 107 products)", gap <= 1,
          f"largest gap ₱{gap:.4f} over {len(months)} months")
    split = (months.surplus_value_sell_costed + months.surplus_value_sell_no_cost_basis - months.surplus_value_sell).abs().max()
    check("2 arithmetic", "monthly totals: surplus with cost basis + without = surplus", split <= 1, f"largest gap ₱{split:.4f}")
    avg = mt[mt.month == "average per month"].iloc[0]
    cols = [c for c in mt.columns if c != "month"]
    agap = max(abs(months[c].mean() - avg[c]) for c in cols)
    check("2 arithmetic", "monthly totals: 'average per month' row = mean of the 6 months", agap <= 1, f"largest gap {agap:.4f}")

    w = pd.read_csv(os.path.join(HERE, "window_comparison.csv"), index_col=0)
    for col in w.columns:
        c = w[col]
        g1 = abs(c.avg_monthly_surplus_pesos_sell + c.avg_monthly_shortage_pesos_sell - c.avg_monthly_miss_pesos_sell)
        g2 = abs(c.surplus_share_of_miss + c.shortage_share_of_miss - 1)
        g3 = abs(c.product_months_over + c.product_months_under + c.product_months_exact - c.product_months)
        check("2 arithmetic", f"{col}: surplus + shortage = miss; shares add to 100%; over + under + exact = scored",
              g1 <= 1 and g2 <= 1e-9 and g3 == 0,
              f"₱ gap {g1:.4f}; share gap {g2:.2e}; months {int(c.product_months_over)} + {int(c.product_months_under)} + "
              f"{int(c.product_months_exact)} = {int(c.product_months)}")
    r = jload("results.json")["direction_common"]
    check("2 arithmetic", "first report: over + under + exact = 642 scored product-months",
          r["product_months_over"] + r["product_months_under"] + r["product_months_exact"] == 642 == jload("results.json")["direction_detail"]["product_months"],
          f"{r['product_months_over']} + {r['product_months_under']} + {r['product_months_exact']}")

    cat = pd.read_csv(os.path.join(HERE, "category_total_accuracy.csv"))
    tot = cat[cat.level.str.startswith("TOTAL")].iloc[0]
    parts = cat[~cat.level.str.startswith("TOTAL")]
    check("2 arithmetic", "category product counts add to the total (107)", parts.products.sum() == tot.products == 107,
          f"{' + '.join(str(int(x)) for x in parts.products)} = {int(parts.products.sum())}")
    for fname, label, src in (("per_product_month.csv", "A: 6 months", "common"), ("longwindow_per_product_month.csv", "C: 29 months", None)):
        pm = pd.read_csv(os.path.join(LOCAL, fname))
        if src:
            pm = pm[pm.score_source == src]
        pm["actual_pesos"] = pm.actual * pm.price_sell_vat_inc
        by_cat = pm.groupby("category_path")[["actual_pesos", "abs_error_pesos_sell", "surplus_value_sell", "shortage_value_sell"]].sum()
        whole = pm[["actual_pesos", "abs_error_pesos_sell", "surplus_value_sell", "shortage_value_sell"]].sum()
        g = float((by_cat.sum() - whole).abs().max())
        check("2 arithmetic", f"{label}: category sales and misses (₱ at {SELL_LABEL}) add to the total", g <= 1,
              f"largest gap ₱{g:.4f} across {len(by_cat)} categories; total sales ₱{whole.actual_pesos:,.0f}, miss ₱{whole.abs_error_pesos_sell:,.0f}")

    rv = pd.read_csv(os.path.join(HERE, "review_before_ordering.csv"))
    total = rv.exposure_pesos_sell_vat_inc.sum()
    fr = jload("followups_results.json")["review_exposure_total_pesos_sell_vat_inc"]
    check("2 arithmetic", "review list exposure adds to ₱339,703", round(total) == 339703 and abs(total - fr) <= 0.01,
          f"sum of {len(rv)} rows = ₱{total:,.2f}; followups_results.json = ₱{fr:,.2f}")
    full = pd.read_csv(os.path.join(LOCAL, "review_before_ordering.csv"))
    redo = (full.forecast_2026_03_pcs - full.recent_avg_last3_pcs).clip(lower=0) * full.price_sell_vat_inc
    g = float((redo - full.exposure_pesos_sell_vat_inc).abs().max())
    check("2 arithmetic", "each exposure = max(forecast − recent average, 0) × price", g <= 0.01, f"largest gap ₱{g:.6f}")


# --------------------------------------------------------------------------- #
# 3. Independent recompute (fresh code)
# --------------------------------------------------------------------------- #
def fresh_wape(a, f):
    a, f = np.asarray(a, float), np.asarray(f, float)
    return np.abs(f - a).sum() / np.abs(a).sum()


def recompute(names_by_key):
    money = pd.read_csv(os.path.join(INP, "demand_money_tierA.csv"), dtype={"calendar_month": str})
    # an empty quantity counts as 0 pieces sold, the pipeline's rule (run_fit_diagnosis.py:127, fillna(0.0));
    # one product-month has one (product key 150, 2025-12)
    n_nan = int(money.quantity.isna().sum())
    qty = {(int(k), m): (0.0 if pd.isna(q) else q) for k, m, q in zip(money.product_key, money.calendar_month, money.quantity)}
    check("3 recompute", "empty quantities treated as 0 pieces, as the pipeline does", n_nan == 1,
          f"{n_nan} product-month with an empty quantity in inputs/demand_money_tierA.csv")
    net = {(int(k), m): n for k, m, n in zip(money.product_key, money.calendar_month, money.net_amount)}

    def frame(df):
        df = df.copy()
        df["actual"] = [qty.get((k, m), 0.0) for k, m in zip(df.product_key, df.month)]      # missing month = 0 sold
        df["net"] = [net.get((k, m), 0.0) for k, m in zip(df.product_key, df.month)]
        g = df.groupby("product_key")
        df["price"] = df.product_key.map(g.net.sum() / g.actual.sum())
        return df

    def summarise(df):
        per = df.groupby("product_key").apply(lambda x: fresh_wape(x.actual, x.forecast), include_groups=False)
        df = df.assign(a_p=df.actual * df.price, f_p=df.forecast * df.price, e_p=(df.forecast - df.actual) * df.price)
        mon = df.groupby("month")[["a_p", "f_p"]].sum()
        return {"median_wape": float(per.median()), "products": int(per.size),
                "total_wape_pesos": float(np.abs(mon.f_p - mon.a_p).sum() / np.abs(mon.a_p).sum()),
                "surplus_share": float(df.e_p.clip(lower=0).sum() / df.e_p.abs().sum())}

    s = pd.read_csv(os.path.join(REPO, "reports", "simulation", "synthetic_2026-10", "series.csv"))
    six = s[(s.run == "REAL") & (s.kind == "holdout") & (s.score_source == "common")][["product_key", "month", "forecast"]]
    r6 = summarise(frame(six))
    lw = pd.read_csv(os.path.join(LOCAL, "longwindow_per_product_month.csv"))[["product_key", "month", "forecast"]]
    r29 = summarise(frame(lw))
    for label, got, want, d in (("6-month median product WAPE", r6["median_wape"] * 100, 29.3, 1),
                                ("29-month median product WAPE", r29["median_wape"] * 100, 26.9, 1),
                                (f"6-month total WAPE, ₱ at {SELL_LABEL}", r6["total_wape_pesos"] * 100, 8.3, 1),
                                (f"29-month total WAPE, ₱ at {SELL_LABEL}", r29["total_wape_pesos"] * 100, 10.7, 1),
                                ("29-month surplus share of the peso miss", r29["surplus_share"] * 100, 51.1, 1)):
        check("3 recompute", label, abs(got - want) <= 0.05 + 1e-9,
              f"fresh code {got:.3f}% vs README {want}% ({r6['products'] if '6-month' in label else r29['products']} products)")

    dem = pd.read_csv(os.path.join(INP, "demand_real_tierA.csv"), dtype={"calendar_month": str})
    seasonal = []
    for k, g in dem.groupby("product_key"):
        months = pd.period_range(g.calendar_month.min(), "2026-02", freq="M").strftime("%Y-%m")
        y = g.set_index("calendar_month").quantity.reindex(months, fill_value=0.0).to_numpy(float)
        first = np.flatnonzero(y > 0)
        if not first.size:
            continue
        y = y[first[0]:]
        n = len(y)
        if n < 24:
            continue
        dev = y - y.mean()
        r12 = (dev[:-12] * dev[12:]).sum() / (dev ** 2).sum()
        if abs(r12) > 1.96 / np.sqrt(n):
            seasonal.append(names_by_key[int(k)])
    want = {"BESTFOODS RGLR MYNS MAYOMAGICDOY24X220ML", "CREAM SILK HC ULTREBORN HFALL 24X180ML", "AXE DEO AP RLN DARKTEMP 24X25ML"}
    check("3 recompute", "'Repeats yearly' list (lag-12 test, 24+ months)", set(seasonal) == want,
          f"fresh code finds {len(seasonal)}: {sorted(seasonal)}")


# --------------------------------------------------------------------------- #
# 4. Data rules
# --------------------------------------------------------------------------- #
def read_text(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as fh:
        return fh.read()


def data_rules():
    dem = pd.read_csv(os.path.join(INP, "demand_real_tierA.csv"), dtype={"calendar_month": str})
    money = pd.read_csv(os.path.join(INP, "demand_money_tierA.csv"), dtype={"calendar_month": str})
    n_demo = int(dem.is_demo.astype(str).str.lower().eq("true").sum()) + int(money.any_is_demo.astype(str).str.lower().eq("true").sum())
    check("4 data rules", "demand rows carry no is_demo = true row", n_demo == 0,
          f"{len(dem)} + {len(money)} pulled product-months, is_demo = true: {n_demo}; months {dem.calendar_month.min()}..{dem.calendar_month.max()}")
    schema = read_text("analytics", "db", "schema.sql")
    view = re.search(r"CREATE OR REPLACE VIEW Unilever_SKU_Demand_Fact_Real AS\s*SELECT \* FROM Unilever_SKU_Demand_Fact WHERE is_demo = false;", schema)
    harness = read_text("reports", "diagnostics", "fit_diagnosis_2026-10", "run_fit_diagnosis.py")
    pull = read_text("reports", "diagnostics", "forecast_error_business_2026-10-03", "pull_inputs.py")
    reads_view = "FROM Unilever_SKU_Demand_Fact_Real" in harness and pull.count("FROM Unilever_SKU_Demand_Fact_Real") >= 1
    check("4 data rules", "demand read only through Unilever_SKU_Demand_Fact_Real (filter: is_demo = false)",
          bool(view) and reads_view and "assert_real_rows(demand)" in harness,
          "schema.sql view = WHERE is_demo = false; harness + pull_inputs.py read the view; harness calls assert_real_rows")
    mig = read_text("analytics", "db", "migrations", "0038_data_fills.sql")
    cons = re.search(r"unilever_sku_demand_fact_fill_source_check CHECK \(\s*fill_source IS NULL OR \(is_demo AND", mig)
    check("4 data rules", "gap fills cannot pass the is_demo filter (fill_source needs is_demo = true)", bool(cons),
          "0038_data_fills.sql: fill_source IS NULL OR (is_demo AND fill_source IN (...))")
    sc = read_text("reports", "diagnostics", "forecast_error_business_2026-10-03", "pull_stock_count.py")
    snaps = pd.read_csv(os.path.join(INP, "stock_count_snapshots.csv"))
    used = snaps[snaps.snapshot_date == "2026-04-06"]
    rows = pd.read_csv(os.path.join(INP, "stock_count_2026-04-06_tierA.csv"))
    ok = ("is_demo = false AND fill_source IS NULL" in sc and len(used) == 1 and str(used.is_demo.iloc[0]) == "False"
          and pd.isna(used.fill_source.iloc[0]) and rows.product_key.nunique() == len(rows) == 120)
    check("4 data rules", "stock count filtered on is_demo = false AND fill_source IS NULL", ok,
          f"pull_stock_count.py filter present; snapshot 2026-04-06: is_demo {used.is_demo.iloc[0]}, fill_source empty, "
          f"{int(used.rows.iloc[0])} rows, {len(rows)} Tier A products")


# --------------------------------------------------------------------------- #
# 5. Wording
# --------------------------------------------------------------------------- #
JARGON = {"WAPE": "weighted absolute percentage error", "MA3": "average of the last 3 months",
          "TSB": "Teunter", "STL": "Seasonal-Trend decomposition", "ACF": "autocorrelation",
          "CV": "coefficient of variation", "GSV": "gross sales value", "VAT": "value-added tax",
          "LP": "linear programming", "MASE": "mean absolute scaled error", "MAPE": "mean absolute percentage error",
          "XGBoost": "gradient-boosted", "SKU": "stock-keeping unit", "ABC": "Pareto", "AR(1)": "carries over",
          "DEC-26": "decision register", "UTC": "Coordinated Universal Time"}


def wording(names, skus):
    with open(README, encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    bad = []
    header = ""
    for i, ln in enumerate(lines):
        if ln.startswith("|") and i + 1 < len(lines) and lines[i + 1].startswith("|---"):
            header = ln
        if not ln.startswith("|"):
            header = "" if ln.strip() == "" or ln.startswith("#") else header
        peso_figure = "₱" in ln or (re.search(r"\bpesos?\b", ln)
                                     and re.search(r"\d+(\.\d+)?\s?(%|M\b| million)|\d{1,3},\d{3}", ln))
        if peso_figure:
            j = i
            while j - 1 >= 0 and lines[j - 1].strip() and not lines[j - 1].startswith("#"):
                j -= 1
            k = i + 1
            while k < len(lines) and lines[k].strip() and not lines[k].startswith("#"):
                k += 1
            para = lines[j:k]                                   # the whole paragraph, in order
            ctx = re.sub(r"\s+", " ", " ".join([header, *para]))   # labels may wrap across lines
            if SELL_LABEL not in ctx and COST_LABEL not in ctx:
                bad.append(i + 1)
    check("5 wording", "every peso figure carries its price basis (selling price VAT-incl, or at cost)", not bad,
          "all peso figures labelled in the line, its table header or its paragraph" if not bad else f"unlabelled lines {bad}")

    text = "\n".join(lines)
    flat = re.sub(r"\n\s*", " ", text)                          # names may wrap across lines
    order_bad = []
    for m in re.finditer(r"\b(\d{8})\b", flat):
        if m.group(1) not in skus:                              # seeds and other 8-digit numbers are not SKUs
            continue
        before = flat[max(0, m.start() - 220):m.start()]
        if not any(n in before for n in names):
            order_bad.append(m.group(1))
    n_sku = sum(1 for m in re.finditer(r"\b(\d{8})\b", flat) if m.group(1) in skus)
    check("5 wording", "product name before SKU", not order_bad,
          f"all {n_sku} SKU mentions follow their product name" if not order_bad else f"SKUs without a preceding name: {sorted(set(order_bad))}")

    missing = []
    for term, expansion in JARGON.items():
        pat = re.escape(term) if not term.isalpha() else rf"\b{re.escape(term)}\b"
        m = re.search(pat, text)
        if not m:
            continue
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.end())
        window = text[max(0, line_start - 400):line_end + 400].lower()
        if expansion.lower() not in window:
            missing.append(term)
    check("5 wording", "jargon spelled out at first use", not missing,
          "all terms expanded at first use" if not missing else f"not expanded at first use: {missing}")
    sentences = re.split(r"(?<=[.!?])\s+", flat)
    ties = [s for s in sentences if "DEC-26" in s and re.search(r"\btie", s)]
    claims = [s for s in sentences if re.search(r"\bbeats?\b[^.]*\bMA3\b|\bbetter than MA3\b", s)]
    unnegated = [s for s in claims if not re.search(r"\bnot\b|\bnever\b|n't", s)]
    check("5 wording", "DEC-26 'tied' wording kept, no claim of beating MA3", bool(ties) and not unnegated,
          f"{len(ties)} DEC-26 sentences say tie; {len(claims)} 'beat MA3' sentences, all negated" if ties and not unnegated
          else f"DEC-26 tie sentences: {len(ties)}; un-negated beat claims: {unnegated}")


def main():
    dims = pd.read_csv(os.path.join(INP, "product_dimension_tierA.csv"), dtype={"sku_code": str})
    names = dims.product_name.tolist()
    number_check(names, dict(zip(dims.product_name, dims.product_key.astype(int))))
    arithmetic()
    recompute(dict(zip(dims.product_key.astype(int), dims.product_name)))
    data_rules()
    wording(names, set(dims.sku_code))
    out = pd.DataFrame(CHECKS)
    out.to_csv(os.path.join(HERE, "quality_check.csv"), index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_colwidth", 160)
    import sys
    sys.stdout.reconfigure(encoding="utf-8")          # the Windows console default (cp1252) has no peso sign
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
