"""
scripts.run_baseline_forecast - Unilever Category A baseline forecasting
(MA3 / Naive / SBA), report-only by default.

Companion to scripts/run_sarima.py, following the same shape (live DB read,
per-SKU loop, status classification, model_params provenance) but running the
baseline methods from analytics.forecasting.baseline instead of SARIMA. See
that module's docstring for why SARIMA was retired for this data.

This run is REPORT-ONLY unless --write is passed (off by default):
  - always: prints the review tables below, writes
    reports/baseline_forecast_per_sku.csv and reports/BASELINE_FORECAST_RUN.md
  - --write only: additionally upserts Forecast_Result for status='ok' SKUs
    using the rule_method (deployable) pick. The LP-handoff numeric fallback
    for insufficient_data / dead_sku SKUs (trailing average, provisional
    flag) is NOT implemented this pass - its spec lives in the plan and the
    policy fields are stamped null in model_params so the --write path has a
    contract to fill later.

Real data only: reads Unilever_SKU_Demand_Fact_Real (the _Real view
structurally excludes is_demo=true), never the base table. The ABC period is
resolved to the latest classification_period that is not after the latest
real demand month - run_sarima.py's unconditional MAX(classification_period)
resolves to a synthetic-only period on this data.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

import numpy as np
import pandas as pd
import psycopg2
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from analytics.forecasting.sarima import train_holdout_split, HOLDOUT_FRACTION
from analytics.forecasting.baseline import (
    MIN_MONTHS_WITH_SALES,
    MASE_GATE,
    MA_WINDOW,
    SBA_ALPHA,
    SBA_ALPHA_TUNED,
    ABC_TIER_A_CUTOFF,
    RULE_METHOD_MAP,
    TIE_BREAK_ORDER,
    demand_class,
    evaluate_baseline,
    build_forecasters,
    naive_forecast,
    moving_average_forecast,
    sba_forecast,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

METHODS = ("naive", "ma3", "sba")
PRINCIPAL = "unilever"

# The 38 real calendar months this data is expected to cover. Used for the
# ETL-gap check - a month with zero demand rows across EVERY SKU is an ETL
# gap, not zero demand. Re-confirmed live each run against the DB.
EXPECTED_MONTHS = pd.period_range("2023-01", "2026-02", freq="M").astype(str).tolist()

REPORTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "reports"))
PER_SKU_CSV = os.path.join(REPORTS_DIR, "baseline_forecast_per_sku.csv")
RUN_MD = os.path.join(REPORTS_DIR, "BASELINE_FORECAST_RUN.md")

# Full-catalog class x method win counts (fixed evidence, printed so the
# SBA/naive-only rule_method mapping is visibly justified, not asserted).
CLASS_EVIDENCE_ROWS = [
    ("smooth", 263, 50, 68, 112, 25, 8),
    ("erratic", 39, 2, 14, 16, 1, 6),
    ("intermittent", 426, 204, 81, 88, 40, 13),
    ("lumpy", 358, 152, 72, 80, 18, 36),
]


# --------------------------------------------------------------------------- #
# DB access
# --------------------------------------------------------------------------- #
def connect():
    load_dotenv(override=False)
    db_url = os.environ.get("SUPABASE_DB_URL")
    if not db_url:
        logger.error("SUPABASE_DB_URL not set in .env")
        sys.exit(1)
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    return conn


def resolve_abc_period(cur) -> str:
    """Latest ABC classification_period that is not after the latest real
    demand month. run_sarima.py's unconditional MAX resolves to a
    synthetic-only period on this data - hence the <= guard."""
    cur.execute(
        """
        SELECT MAX(classification_period)
        FROM ABC_Classification
        WHERE principal = %s
          AND classification_period <= (
              SELECT MAX(calendar_month) FROM Unilever_SKU_Demand_Fact_Real
          )
        """,
        (PRINCIPAL,),
    )
    row = cur.fetchone()
    if not row or row[0] is None:
        logger.error("No usable ABC classification_period found for Unilever.")
        sys.exit(1)
    return row[0]


def fetch_tier_a(cur, abc_period: str) -> pd.DataFrame:
    cur.execute(
        """
        SELECT abc.product_key, pd.sku_code
        FROM ABC_Classification abc
        JOIN Product_Dimension pd ON pd.product_key = abc.product_key
        WHERE abc.principal = %s
          AND abc.classification_period = %s
          AND abc.tier = 'A'
        ORDER BY abc.product_key
        """,
        (PRINCIPAL, abc_period),
    )
    return pd.DataFrame(cur.fetchall(), columns=["product_key", "sku_code"])


def fetch_demand(cur) -> pd.DataFrame:
    cur.execute(
        """
        SELECT product_key, sku_code, calendar_month, SUM(quantity_sold) AS quantity
        FROM Unilever_SKU_Demand_Fact_Real
        GROUP BY product_key, sku_code, calendar_month
        ORDER BY product_key, calendar_month
        """
    )
    df = pd.DataFrame(cur.fetchall(), columns=["product_key", "sku_code", "calendar_month", "quantity"])
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0.0)
    return df


# --------------------------------------------------------------------------- #
# Series + per-SKU evaluation
# --------------------------------------------------------------------------- #
def build_series(sku_df: pd.DataFrame) -> pd.Series:
    """Zero-filled monthly series. Zeros are real demand and SBA's gap
    structure depends on them - the zero-fill stays in the modeling series;
    only the eligibility gate looks at real observations instead (fix #1)."""
    idx = pd.to_datetime(sku_df["calendar_month"] + "-01")
    s = pd.Series(sku_df["quantity"].to_numpy(dtype=float), index=idx).sort_index()
    return s.resample("MS").asfreq().fillna(0.0)


def one_step(method: str, series: pd.Series) -> float:
    """Deployable one-step-ahead point forecast on the FULL series (used only
    by the --write path)."""
    if method == "naive":
        return float(naive_forecast(series, 1)[0])
    if method == "ma3":
        return float(moving_average_forecast(series, 1, MA_WINDOW)[0])
    if method == "sba":
        return float(sba_forecast(series, 1, SBA_ALPHA)[0])
    raise ValueError(method)


def pick_oracle(per_method: dict) -> str:
    """Lowest holdout MASE; ties (and all-undefined) resolve by TIE_BREAK_ORDER
    (naive -> ma3 -> sba). Deterministic - reruns never disagree."""
    scored = [
        (m, per_method[m]["mase"])
        for m in METHODS
        if per_method[m]["mase"] is not None and not (
            isinstance(per_method[m]["mase"], float) and np.isnan(per_method[m]["mase"])
        )
    ]
    if not scored:
        return TIE_BREAK_ORDER[0]
    best = min(v for _, v in scored)
    tied = {m for m, v in scored if v == best}
    for m in TIE_BREAK_ORDER:
        if m in tied:
            return m
    return sorted(tied)[0]


def evaluate_sku(series: pd.Series) -> dict:
    """Run all 3 methods + both selection methods for one status='ok' SKU."""
    train, holdout = train_holdout_split(series, holdout_fraction=HOLDOUT_FRACTION)
    horizon = len(holdout)
    forecasters = build_forecasters(horizon, SBA_ALPHA)

    per_method = {}
    for m in METHODS:
        fc = forecasters[m](train)
        metrics = evaluate_baseline(fc, holdout, train)
        if m == "sba":
            metrics["alpha"] = SBA_ALPHA
            metrics["alpha_tuned"] = SBA_ALPHA_TUNED
        if m == "ma3":
            metrics["window"] = MA_WINDOW
        per_method[m] = metrics

    train_class = demand_class(train)
    oracle_method = pick_oracle(per_method)
    rule_method = RULE_METHOD_MAP.get(train_class, "naive")

    return {
        "per_method": per_method,
        "train_class": train_class,
        "oracle_method": oracle_method,
        "rule_method": rule_method,
        "train_len": len(train),
        "holdout_len": horizon,
        "flat_training_window": bool(per_method[METHODS[0]]["mase_denominator_zero"]),
        "train_start": train.index.min().strftime("%Y-%m"),
        "train_end": train.index.max().strftime("%Y-%m"),
        "holdout_start": holdout.index.min().strftime("%Y-%m"),
        "holdout_end": holdout.index.max().strftime("%Y-%m"),
    }


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--principal", choices=["unilever"], default="unilever",
                        help="Fixed to unilever (Del Monte has no real SKU grain, DEC-03).")
    parser.add_argument("--write", action="store_true", default=False,
                        help="Additionally upsert Forecast_Result for status='ok' SKUs "
                             "(rule_method pick). OFF by default - this run is report-only.")
    args = parser.parse_args()

    conn = connect()
    cur = conn.cursor()

    abc_period = resolve_abc_period(cur)
    latest_demand_month = _scalar(cur, "SELECT MAX(calendar_month) FROM Unilever_SKU_Demand_Fact_Real")
    logger.info(f"ABC period resolved: {abc_period}  (latest real demand month: {latest_demand_month})")

    tier_a = fetch_tier_a(cur, abc_period)
    demand = fetch_demand(cur)

    # ---- ETL-gap check (fresh, every run) -------------------------------- #
    months_present = set(demand["calendar_month"].unique())
    print("\n" + "=" * 78)
    print("ETL-GAP CHECK - demand rows present per expected calendar month (any SKU)")
    print("=" * 78)
    etl_gaps = []
    for mth in EXPECTED_MONTHS:
        ok = mth in months_present
        if not ok:
            etl_gaps.append(mth)
        print(f"  {mth}  {'PASS' if ok else 'FAIL  <-- ZERO ROWS ACROSS EVERY SKU - ETL GAP, NOT DEMAND'}")
    extra = sorted(months_present - set(EXPECTED_MONTHS))
    if extra:
        print(f"  NOTE: demand rows also exist outside the expected window: {extra}")
    if etl_gaps:
        print(f"\n  *** {len(etl_gaps)} ETL GAP MONTH(S): {etl_gaps} - a per-SKU missing month in")
        print("      one of these is a FILE gap, not 'this SKU sold nothing'. ***")
    else:
        print("\n  All 38 expected months have demand rows - a per-SKU missing month")
        print("  reads as 'this SKU had zero sales that month'.")

    # ---- per-SKU loop --------------------------------------------------- #
    demand_by_key = {k: g for k, g in demand.groupby("product_key")}
    sku_code_by_key = demand.groupby("product_key")["sku_code"].first().to_dict()

    records = []
    for _, ta in tier_a.iterrows():
        p_key = ta["product_key"]
        sku_code = ta["sku_code"] or sku_code_by_key.get(p_key) or str(p_key)
        sku_df = demand_by_key.get(p_key)

        if sku_df is None or sku_df.empty:
            records.append(_row_shell(p_key, sku_code, abc_period, months_span=0,
                                      months_with_sales=0, full_class="unclassifiable",
                                      status="insufficient_data"))
            continue

        series = build_series(sku_df)
        months_span = int(len(series))
        months_with_sales = int((series > 0).sum())
        full_class = demand_class(series)

        # first/last month with a real positive sale, from the UNtrimmed rows
        sold_months = sorted(
            m for m, q in zip(sku_df["calendar_month"], sku_df["quantity"]) if q > 0
        )
        first_sale_month = sold_months[0] if sold_months else None
        last_sale_month = sold_months[-1] if sold_months else None

        def _with_window(rec):
            rec["first_sale_month"] = first_sale_month
            rec["last_sale_month"] = last_sale_month
            return rec

        if months_with_sales < MIN_MONTHS_WITH_SALES:
            records.append(_with_window(_row_shell(p_key, sku_code, abc_period, months_span,
                                                   months_with_sales, full_class, "insufficient_data")))
            continue

        if months_span >= 6 and series.tail(6).sum() <= 0:
            records.append(_with_window(_row_shell(p_key, sku_code, abc_period, months_span,
                                                   months_with_sales, full_class, "dead_sku")))
            continue

        ev = evaluate_sku(series)
        rec = _with_window(_row_shell(p_key, sku_code, abc_period, months_span, months_with_sales,
                                      full_class, "ok"))
        rec["train_months"] = ev["train_len"]
        rec["holdout_months"] = ev["holdout_len"]
        rec["train_start"] = ev["train_start"]
        rec["train_end"] = ev["train_end"]
        rec["holdout_start"] = ev["holdout_start"]
        rec["holdout_end"] = ev["holdout_end"]
        rec["demand_class_train"] = ev["train_class"]
        rec["oracle_method"] = ev["oracle_method"]
        rec["rule_method"] = ev["rule_method"]
        rec["flat_training_window"] = ev["flat_training_window"]
        rec["lp_input_method"] = None
        rec["provisional"] = None
        for m in METHODS:
            mm = ev["per_method"][m]
            rec[f"{m}_mase"] = mm["mase"]
            rec[f"{m}_mape"] = mm["mape"]
            rec[f"{m}_mae"] = mm["mae"]
            rec[f"{m}_rmse"] = mm["rmse"]
            rec[f"{m}_mase_gate_passed"] = mm["mase_gate_passed"]
            rec[f"{m}_mase_denominator_zero"] = mm["mase_denominator_zero"]
        rec["_series_mean"] = float(series.mean())
        rec["_per_method"] = ev["per_method"]  # transient, dropped before CSV
        records.append(rec)

    df = pd.DataFrame(records)

    # LP-handoff policy fields for non-forecastable rows (spec only this pass)
    non_ok = df["status"].isin(["insufficient_data", "dead_sku"])
    df.loc[df["status"] == "insufficient_data", "lp_input_method"] = "trailing_avg_provisional"
    df.loc[df["status"] == "dead_sku", "lp_input_method"] = "zero_no_order"
    df.loc[non_ok, "provisional"] = df.loc[non_ok, "status"].map(
        {"insufficient_data": True, "dead_sku": False}
    )

    _print_report(df, abc_period, latest_demand_month)

    # ---- status-transition tracking (7) ------------------------------- #
    _print_transitions(df)

    # ---- sample SKUs (8) --------------------------------------------- #
    print("\n" + "=" * 78)
    print("8. SAMPLE SKUs (full detail)")
    print("=" * 78)
    _print_samples(df[df["status"] == "ok"].copy())

    # ---- pre-acceptance checks --------------------------------------- #
    _pre_acceptance(df, cur, abc_period)

    # ---- write files ------------------------------------------------- #
    _write_csv(df)
    _write_md(df, abc_period, latest_demand_month)

    # ---- optional DB write ----------------------------------------- #
    if args.write:
        _write_forecast_result(cur, df)
    else:
        print("\n(--write not passed: Forecast_Result untouched, this was report-only.)")

    conn.close()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _scalar(cur, sql):
    cur.execute(sql)
    return cur.fetchone()[0]


def _row_shell(p_key, sku_code, abc_period, months_span, months_with_sales, full_class, status):
    """A CSV row with every column present; ok-only fields left null."""
    rec = {
        "sku_code": sku_code,
        "product_key": int(p_key),
        "months_span": months_span,
        "months_with_sales": months_with_sales,
        "demand_class_full": full_class,
        "demand_class_train": None,
        "status": status,
        "oracle_method": None,
        "rule_method": None,
        "flat_training_window": None,
        "lp_input_method": None,
        "provisional": None,
        "abc_period_used": abc_period,
        "min_months_threshold": MIN_MONTHS_WITH_SALES,
        "abc_tier_a_cutoff": ABC_TIER_A_CUTOFF,
        # sale-window + train/test-split visibility (columns only, no logic change)
        "first_sale_month": None,
        "last_sale_month": None,
        "train_months": None,
        "holdout_months": None,
        "train_start": None,
        "train_end": None,
        "holdout_start": None,
        "holdout_end": None,
        "_series_mean": None,
        "_per_method": None,
    }
    for m in METHODS:
        for suffix in ("mase", "mape", "mae", "rmse", "mase_gate_passed", "mase_denominator_zero"):
            rec[f"{m}_{suffix}"] = None
    return rec


def _pct(n, d):
    return (100.0 * n / d) if d else float("nan")


def _method_series(df_ok, method, field):
    return pd.to_numeric(df_ok[f"{method}_{field}"], errors="coerce").dropna()


def _print_report(df, abc_period, latest_demand_month):
    df_ok = df[df["status"] == "ok"].copy()
    n_total = len(df)

    print("\n" + "=" * 78)
    print("1. POPULATION CAVEAT")
    print("=" * 78)
    print(
        "  rule_method's class->method mapping was DERIVED from the full 1,807-SKU\n"
        "  catalog (1,096-SKU evaluable subset, all ABC tiers combined) and is\n"
        "  APPLIED here to Unilever Tier A only. Different populations. The larger\n"
        "  sample gives a stabler rule; this is stated, not hidden."
    )

    print("\n" + "=" * 78)
    print("2. AGGREGATE ACCURACY - all 3 methods, status='ok' SKUs, own valid subset")
    print("=" * 78)
    hdr = f"  {'metric':<34}" + "".join(f"{m:>12}" for m in METHODS)
    print(hdr)
    print("  " + "-" * (34 + 12 * len(METHODS)))

    def line(label, fn):
        print(f"  {label:<34}" + "".join(f"{fn(m):>12}" for m in METHODS))

    def fmt(x):
        return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.3f}"

    mase = {m: _method_series(df_ok, m, "mase") for m in METHODS}
    mape = {m: _method_series(df_ok, m, "mape") for m in METHODS}
    mae = {m: _method_series(df_ok, m, "mae") for m in METHODS}
    rmse = {m: _method_series(df_ok, m, "rmse") for m in METHODS}

    line("MASE median", lambda m: fmt(mase[m].median()))
    line("MASE mean", lambda m: fmt(mase[m].mean()))
    line("MASE<1.0 pass count", lambda m: f"{int((mase[m] < 1.0).sum())}/{len(mase[m])}")
    line("MASE<1.0 pass %", lambda m: fmt(_pct((mase[m] < 1.0).sum(), len(mase[m]))))
    line("MAPE median", lambda m: fmt(mape[m].median()))
    line("MAPE<20% pass count", lambda m: f"{int((mape[m] < 0.20).sum())}/{len(mape[m])}")
    line("MAPE<20% pass %", lambda m: fmt(_pct((mape[m] < 0.20).sum(), len(mape[m]))))
    line("MAE median", lambda m: fmt(mae[m].median()))

    # MAE as % of that SKU's own mean monthly demand (median across SKUs)
    def mae_pct_of_mean(m):
        sub = df_ok[[f"{m}_mae", "_series_mean"]].copy()
        sub[f"{m}_mae"] = pd.to_numeric(sub[f"{m}_mae"], errors="coerce")
        sub["_series_mean"] = pd.to_numeric(sub["_series_mean"], errors="coerce")
        sub = sub[(sub["_series_mean"] > 0)].dropna()
        return (100.0 * sub[f"{m}_mae"] / sub["_series_mean"]).median()

    line("MAE as % of SKU mean (median)", lambda m: fmt(mae_pct_of_mean(m)))
    line("RMSE median", lambda m: fmt(rmse[m].median()))

    def rmse_over_mae(m):
        sub = df_ok[[f"{m}_rmse", f"{m}_mae"]].copy()
        sub = sub.apply(pd.to_numeric, errors="coerce")
        sub = sub[sub[f"{m}_mae"] > 0].dropna()
        return (sub[f"{m}_rmse"] / sub[f"{m}_mae"]).median()

    line("RMSE/MAE ratio (median)", lambda m: fmt(rmse_over_mae(m)))

    wins = df_ok["oracle_method"].value_counts().to_dict()
    line("outright wins (oracle-based)", lambda m: str(int(wins.get(m, 0))))

    print("\n" + "=" * 78)
    print("3. COUNTS")
    print("=" * 78)
    n_ok = int((df["status"] == "ok").sum())
    n_ins = int((df["status"] == "insufficient_data").sum())
    n_dead = int((df["status"] == "dead_sku").sum())
    n_flat = int((df_ok["flat_training_window"] == True).sum())  # noqa: E712
    print(f"  total real Tier A SKUs ....................... {n_total}")
    print(f"  forecastable (status='ok') .................. {n_ok}")
    print(f"  insufficient_data .......................... {n_ins}")
    print(f"  dead_sku .................................. {n_dead}")
    print(f"  MASE-unevaluable (flat training window, ok) . {n_flat}")

    print("\n" + "=" * 78)
    print("4. LP-HANDOFF-AFFECTED COUNT")
    print("=" * 78)
    print(f"  {n_ins + n_dead} Tier A SKUs ({n_ins} insufficient_data + {n_dead} dead_sku) need the")
    print("  LP fallback policy (trailing avg / zero), NOT a model forecast.")
    print("  Numeric fallback + provisional flag = --write-path work, not done this pass.")

    print("\n" + "=" * 78)
    print("5. PASS RATES - oracle vs. rule vs. plain-MA3-alone (MASE<1.0)")
    print("=" * 78)
    oracle_pass, oracle_n = _selected_pass(df_ok, "oracle_method")
    rule_pass, rule_n = _selected_pass(df_ok, "rule_method")
    ma3 = mase["ma3"]
    ma3_pass, ma3_n = int((ma3 < 1.0).sum()), len(ma3)
    print(f"  oracle-selected  MASE<1.0 : {oracle_pass}/{oracle_n}  ({_pct(oracle_pass, oracle_n):.1f}%)   [UPPER BOUND - peeks at holdout]")
    print(f"  rule-selected    MASE<1.0 : {rule_pass}/{rule_n}  ({_pct(rule_pass, rule_n):.1f}%)   [deployable]")
    print(f"  plain MA3 alone  MASE<1.0 : {ma3_pass}/{ma3_n}  ({_pct(ma3_pass, ma3_n):.1f}%)")
    print(f"  gap rule vs oracle : {_pct(oracle_pass, oracle_n) - _pct(rule_pass, rule_n):+.1f} pp")
    print(f"  gap rule vs MA3    : {_pct(ma3_pass, ma3_n) - _pct(rule_pass, rule_n):+.1f} pp")
    print("  (rule below MA3-alone is the EXPECTED honest result - see class evidence below.)")

    print("\n" + "=" * 78)
    print("6. CLASS EVIDENCE - full-catalog class x method win counts")
    print("=" * 78)
    print(f"  {'class (n)':<22}{'naive':>8}{'ma3':>8}{'sba':>8}{'croston':>10}{'tsb':>8}")
    for name, n, nv, m3, sb, cr, ts in CLASS_EVIDENCE_ROWS:
        print(f"  {name + ' (' + str(n) + ')':<22}{nv:>8}{m3:>8}{sb:>8}{cr:>10}{ts:>8}")
    print("  MA3 is never #1 in any class -> a per-class rule never surfaces it, by")
    print("  construction. No MA3 branch is added without per-class evidence; none exists.")


def _selected_pass(df_ok, col):
    """Count ok SKUs whose `col`-selected method has MASE < 1.0 (undefined
    MASE does not count as a pass)."""
    n = 0
    passed = 0
    for _, r in df_ok.iterrows():
        method = r[col]
        if not method:
            continue
        n += 1
        v = r[f"{method}_mase"]
        if v is not None and not (isinstance(v, float) and np.isnan(v)) and v < 1.0:
            passed += 1
    return passed, n


def _print_samples(df_ok):
    if df_ok.empty:
        print("  (no status='ok' SKUs)")
        return
    disagree = df_ok[df_ok["oracle_method"] != df_ok["rule_method"]]
    agree = df_ok[df_ok["oracle_method"] == df_ok["rule_method"]]

    picks = []
    # at least one disagreement, then a class mix (from either agree or
    # disagree so rarer classes still surface)
    picks.extend(disagree.head(3).index.tolist())
    for cls in ("smooth", "erratic", "intermittent", "lumpy", "unclassifiable"):
        cand = agree[agree["demand_class_train"] == cls]
        if cand.empty:
            cand = df_ok[df_ok["demand_class_train"] == cls]
        if not cand.empty:
            picks.append(cand.index[0])
    # short-history example
    short = df_ok.sort_values("months_with_sales").head(2).index.tolist()
    picks.extend(short)
    seen = []
    for i in picks:
        if i not in seen:
            seen.append(i)
    seen = seen[:10]
    if len(seen) < 10:
        for i in df_ok.index:
            if i not in seen:
                seen.append(i)
            if len(seen) == 10:
                break

    for i in seen:
        r = df_ok.loc[i]
        print(f"\n  {r['sku_code']}  span={r['months_span']} sold={r['months_with_sales']} "
              f"class(train)={r['demand_class_train']} status={r['status']}")
        for m in METHODS:
            v = r[f"{m}_mase"]
            gate = r[f"{m}_mase_gate_passed"]
            mark = "  --" if v is None else ("  PASS" if gate else "  fail")
            vs = "undef" if v is None else f"{v:.3f}"
            mape = r[f"{m}_mape"]
            mps = "n/a" if mape is None or (isinstance(mape, float) and np.isnan(mape)) else f"{mape:.3f}"
            print(f"      {m:<6} MASE={vs:<8} MAPE={mps:<8} "
                  f"MAE={r[f'{m}_mae']:.2f}  RMSE={r[f'{m}_rmse']:.2f}{mark}")
        flag = "  <-- oracle != rule" if r["oracle_method"] != r["rule_method"] else ""
        print(f"      -> oracle_method={r['oracle_method']}   rule_method={r['rule_method']}{flag}")


def _print_transitions(df):
    print("\n" + "=" * 78)
    print("7. STATUS-TRANSITION TRACKING (vs. prior run's CSV)")
    print("=" * 78)
    if not os.path.exists(PER_SKU_CSV):
        print("  No prior run found - this is the baseline; transition tracking starts next run.")
        return
    prior = pd.read_csv(PER_SKU_CSV, dtype={"sku_code": str})
    if "status" not in prior.columns or "sku_code" not in prior.columns:
        print("  Prior CSV missing status/sku_code columns - skipping transition tracking.")
        return
    merged = df[["sku_code", "status"]].merge(
        prior[["sku_code", "status"]], on="sku_code", how="inner", suffixes=("_now", "_prior")
    )
    changed = merged[merged["status_now"] != merged["status_prior"]]
    if changed.empty:
        print(f"  {len(merged)} SKUs matched prior run - no status changes.")
        return
    combo = (changed["status_prior"] + " -> " + changed["status_now"]).value_counts()
    for k, v in combo.items():
        tag = "   <-- GRADUATION" if k == "insufficient_data -> ok" else ""
        print(f"  {k:<40} {v}{tag}")
    new_skus = set(df["sku_code"]) - set(prior["sku_code"])
    gone = set(prior["sku_code"]) - set(df["sku_code"])
    if new_skus:
        print(f"  ({len(new_skus)} SKU(s) in this run not in prior)")
    if gone:
        print(f"  ({len(gone)} SKU(s) in prior run not in this one)")


def _pre_acceptance(df, cur, abc_period):
    print("\n" + "=" * 78)
    print("PRE-ACCEPTANCE CHECKS")
    print("=" * 78)

    # 1. NaN/inf outside documented null cases. Documented: every metric on
    #    insufficient_data / dead_sku rows (no forecast run), MASE on a
    #    flat-training-window ok row, MAPE on an all-zero-holdout ok row.
    #    Real problems: a NaN in mae/rmse, or any inf, on a status='ok' row.
    bad = 0
    for _, r in df[df["status"] == "ok"].iterrows():
        for m in METHODS:
            for s in ("mase", "mape", "mae", "rmse"):
                v = pd.to_numeric(pd.Series([r[f"{m}_{s}"]]), errors="coerce").iloc[0]
                if not isinstance(v, float):
                    continue
                if np.isinf(v):
                    bad += 1
                elif np.isnan(v):
                    if s == "mape":
                        continue
                    if s == "mase" and bool(r[f"{m}_mase_denominator_zero"]):
                        continue
                    bad += 1
    print(f"  NaN/inf outside documented null cases (status='ok' rows): {bad}  ({'OK' if bad == 0 else 'INVESTIGATE'})")

    # 2. printed ABC period matches a fresh live query
    fresh = resolve_abc_period(cur)
    match = fresh == abc_period
    print(f"  ABC period fresh re-query: {fresh}  (matches printed {abc_period}: {match})")
    if not match:
        print("  *** ABC PERIOD MISMATCH - do not trust this run. ***")


def _write_csv(df):
    out = df.drop(columns=[c for c in ("_per_method", "_series_mean") if c in df.columns])
    os.makedirs(REPORTS_DIR, exist_ok=True)
    out.to_csv(PER_SKU_CSV, index=False)
    print(f"\nWrote {PER_SKU_CSV}  ({len(out)} rows, every real Tier A SKU)")


def _write_md(df, abc_period, latest_demand_month):
    df_ok = df[df["status"] == "ok"].copy()
    lines = []
    lines.append("# Baseline Forecast Run - Unilever Category A (MA3 / Naive / SBA)\n")
    lines.append(f"- ABC period used: `{abc_period}`  (latest real demand month: `{latest_demand_month}`)")
    lines.append(f"- Methods: naive, ma3 (window={MA_WINDOW}), sba (alpha={SBA_ALPHA}, tuned={SBA_ALPHA_TUNED})")
    lines.append(f"- Holdout fraction: {HOLDOUT_FRACTION}  ·  MASE gate: {MASE_GATE}  ·  eligibility: months_with_sales >= {MIN_MONTHS_WITH_SALES}")
    lines.append(f"- Report-only run (no `--write`).\n")

    n_total = len(df)
    n_ok = int((df["status"] == "ok").sum())
    n_ins = int((df["status"] == "insufficient_data").sum())
    n_dead = int((df["status"] == "dead_sku").sum())
    lines.append("## Counts\n")
    lines.append(f"| total Tier A | ok | insufficient_data | dead_sku | LP-fallback (ins+dead) |")
    lines.append(f"|---|---|---|---|---|")
    lines.append(f"| {n_total} | {n_ok} | {n_ins} | {n_dead} | {n_ins + n_dead} |\n")

    lines.append("## Aggregate accuracy (status='ok', own valid subset per method)\n")
    lines.append("| metric | naive | ma3 | sba |")
    lines.append("|---|---|---|---|")

    def ms(m, f):
        return _method_series(df_ok, m, f)

    def cell(fn):
        return " | ".join(fn(m) for m in METHODS)

    def f3(x):
        return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.3f}"

    mase = {m: ms(m, "mase") for m in METHODS}
    mape = {m: ms(m, "mape") for m in METHODS}
    lines.append(f"| MASE median | {cell(lambda m: f3(mase[m].median()))} |")
    lines.append(f"| MASE mean | {cell(lambda m: f3(mase[m].mean()))} |")
    lines.append(f"| MASE<1.0 % | {cell(lambda m: f3(_pct((mase[m] < 1.0).sum(), len(mase[m]))))} |")
    lines.append(f"| MAPE median | {cell(lambda m: f3(mape[m].median()))} |")
    lines.append(f"| MAPE<20% % | {cell(lambda m: f3(_pct((mape[m] < 0.20).sum(), len(mape[m]))))} |")
    lines.append(f"| MAE median | {cell(lambda m: f3(ms(m, 'mae').median()))} |")
    lines.append(f"| RMSE median | {cell(lambda m: f3(ms(m, 'rmse').median()))} |")
    wins = df_ok["oracle_method"].value_counts().to_dict()
    lines.append(f"| outright wins (oracle) | {cell(lambda m: str(int(wins.get(m, 0))))} |\n")

    oracle_pass, oracle_n = _selected_pass(df_ok, "oracle_method")
    rule_pass, rule_n = _selected_pass(df_ok, "rule_method")
    ma3v = mase["ma3"]
    lines.append("## Pass rates (MASE<1.0)\n")
    lines.append("| selection | pass | rate |")
    lines.append("|---|---|---|")
    lines.append(f"| oracle (upper bound) | {oracle_pass}/{oracle_n} | {_pct(oracle_pass, oracle_n):.1f}% |")
    lines.append(f"| rule (deployable) | {rule_pass}/{rule_n} | {_pct(rule_pass, rule_n):.1f}% |")
    lines.append(f"| plain MA3 alone | {int((ma3v < 1.0).sum())}/{len(ma3v)} | {_pct((ma3v < 1.0).sum(), len(ma3v)):.1f}% |\n")

    lines.append("## rule_method mapping\n")
    lines.append("Derived from the full 1,807-SKU catalog (1,096 evaluable, all tiers), applied to Tier A only.\n")
    lines.append("| class | -> method |")
    lines.append("|---|---|")
    for k, v in RULE_METHOD_MAP.items():
        lines.append(f"| {k} | {v} |")
    lines.append("\n### Full-catalog class x method win counts (evidence)\n")
    lines.append("| class (n) | naive | ma3 | sba | croston | tsb |")
    lines.append("|---|---|---|---|---|---|")
    for name, n, nv, m3, sb, cr, ts in CLASS_EVIDENCE_ROWS:
        lines.append(f"| {name} ({n}) | {nv} | {m3} | {sb} | {cr} | {ts} |")
    lines.append("\nMA3 is never the #1 method in any single class, so a class-conditional rule never selects it.\n")

    os.makedirs(REPORTS_DIR, exist_ok=True)
    with open(RUN_MD, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"Wrote {RUN_MD}")


DEPLOYED_METHOD = "ma3"  # the verdict — see module docstring; SARIMA / routing / ensemble all lose to plain MA3 here


def _clean_metric(v, scale=1.0):
    """None / NaN -> None; else float * scale, capped at the live NUMERIC(10,3) ceiling."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    return min(float(v) * scale, 999.999)


def _all_method_metrics(r):
    """Every method's holdout metrics, verbatim, for model_params provenance."""
    return {
        m: {
            "mase": _f(r[f"{m}_mase"]), "mape": _f(r[f"{m}_mape"]),
            "mae": _f(r[f"{m}_mae"]), "rmse": _f(r[f"{m}_rmse"]),
            "mase_gate_passed": (None if pd.isna(r[f"{m}_mase_gate_passed"])
                                 else bool(r[f"{m}_mase_gate_passed"])),
            "mase_denominator_zero": bool(r[f"{m}_mase_denominator_zero"]),
        }
        for m in METHODS
    }


def _f(v):
    v = pd.to_numeric(pd.Series([v]), errors="coerce").iloc[0]
    return None if pd.isna(v) else round(float(v), 4)


# ~90% normal-approximation multiplier (not 95%'s 1.96) — a deliberately
# modest claim for a 3-month moving average scored on a single train/holdout
# split, not a proper rolling-origin residual distribution. Rounder numbers
# read as more certain than this method earns.
CONFIDENCE_Z = 1.645


def _confidence_band(forecast_value: float, rmse) -> tuple[float | None, float | None]:
    """forecast_value +/- CONFIDENCE_Z * rmse, using the SKU's OWN real
    holdout RMSE from evaluate_baseline (rec["ma3_rmse"] in run_review_report
    — already computed for the MASE gate, just never written to
    Forecast_Result before now). None/None (not a fabricated band) when rmse
    itself is None/NaN, e.g. a 1-point holdout. Lower is floored at 0 — real
    demand can't be negative, and an unclipped band can dip below zero for a
    small forecast_value with a wide rmse."""
    rmse = _f(rmse)
    if rmse is None:
        return None, None
    return (
        round(max(0.0, forecast_value - CONFIDENCE_Z * rmse), 2),
        round(forecast_value + CONFIDENCE_Z * rmse, 2),
    )


def _write_forecast_result(cur, df):
    """--write path (atomic): upsert Forecast_Result for every real Tier A SKU.

      status='ok'                -> forecast_value = MA3 one-step-ahead, refit on
                                    the SKU's FULL real series; MA3's holdout
                                    mape/mase in the columns; confidence_lower/
                                    upper = forecast_value +/- CONFIDENCE_Z *
                                    the SKU's own real holdout RMSE (see
                                    _confidence_band — None/None if that RMSE
                                    is itself None); ALL THREE methods'
                                    metrics + oracle/rule picks in model_params.
      status='insufficient_data' -> forecast_value = trailing average of the real
                                    observed months, provisional=true, mape/mase
                                    NULL, mase_gate_passed null. LP fallback spec.
      status='dead_sku'          -> forecast_value = 0 (no order), provisional=false.

    forecast_date is the single planning month = (MAX real calendar_month) + 1,
    identical for every row, so the upsert key (product_key, forecast_date) is
    predictable and existing same-date rows are overwritten, not duplicated.
    Wrapped in one transaction — all rows commit together or none do.
    """
    upsert = """
        INSERT INTO Forecast_Result
        (product_key, forecast_date, forecast_value, confidence_lower, confidence_upper, mape, mase, status, model_params)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (product_key, forecast_date) DO UPDATE SET
            forecast_value   = EXCLUDED.forecast_value,
            confidence_lower = EXCLUDED.confidence_lower,
            confidence_upper = EXCLUDED.confidence_upper,
            mape             = EXCLUDED.mape,
            mase             = EXCLUDED.mase,
            status           = EXCLUDED.status,
            model_params     = EXCLUDED.model_params,
            generated_at     = now()
    """
    demand = fetch_demand(cur)
    demand_by_key = {k: g for k, g in demand.groupby("product_key")}
    cur.execute("SELECT MAX(calendar_month) FROM Unilever_SKU_Demand_Fact_Real")
    planning_date = (pd.Timestamp(cur.fetchone()[0] + "-01") + relativedelta(months=1)).date()
    logger.warning(f"--write: upserting {len(df)} Tier A rows to Forecast_Result at forecast_date={planning_date} "
                   f"(deployed method: {DEPLOYED_METHOD.upper()}). One transaction.")

    target_keys = [int(k) for k in df["product_key"]]
    conn = cur.connection
    prev_autocommit = conn.autocommit
    conn.autocommit = False
    counts = {"ok": 0, "insufficient_data": 0, "dead_sku": 0, "skipped_no_demand": 0, "orphans_deleted": 0}
    orphan_dump_path = None
    try:
        # --- orphaned rows: any existing Forecast_Result row whose product_key is
        #     NOT in the current real Tier A target set. On this DB these are the
        #     SARIMA rows keyed to a synthetic-inclusive ABC period (2026-08).
        #     Dump them in FULL (recoverable) before deleting, in this same txn.
        cur.execute("""
            SELECT fr.forecast_key, fr.product_key, pd.sku_code, pd.principal, pd.product_name,
                   fr.forecast_date::text, fr.forecast_value::float, fr.confidence_lower::float,
                   fr.confidence_upper::float, fr.mape::float, fr.mase::float, fr.status,
                   fr.model_params, fr.generated_at::text
            FROM forecast_result fr JOIN product_dimension pd ON pd.product_key = fr.product_key
            WHERE NOT (fr.product_key = ANY(%s))
            ORDER BY fr.product_key, fr.forecast_date
        """, (target_keys,))
        cols = [d[0] for d in cur.description]
        orphans = [dict(zip(cols, row)) for row in cur.fetchall()]
        if orphans:
            # name the dump by the period run_sarima.py's unconditional MAX() resolved
            # to (the synthetic-inclusive period these orphans were keyed to)
            cur.execute("SELECT MAX(classification_period) FROM abc_classification WHERE principal = %s",
                        (PRINCIPAL,))
            stale_period = cur.fetchone()[0]
            orphan_dump_path = os.path.join(REPORTS_DIR, f"orphaned_sarima_rows_{stale_period}.json")
            os.makedirs(REPORTS_DIR, exist_ok=True)
            with open(orphan_dump_path, "w", encoding="utf-8") as fh:
                json.dump({
                    "dumped_at": pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
                    "reason": (f"Forecast_Result rows for product_keys not in the real "
                               f"{df['abc_period_used'].iloc[0]} Unilever Tier A set — SARIMA output "
                               f"keyed to the ABC period {stale_period} (run_sarima.py's unconditional "
                               f"MAX(classification_period), which resolves to a synthetic-inclusive "
                               f"catalog ranking). Deleted by run_baseline_forecast.py --write in the "
                               f"same transaction as the MA3 upsert."),
                    "count": len(orphans),
                    "restore_hint": "re-INSERT these into Forecast_Result (drop forecast_key; it is identity-generated)",
                    "rows": orphans,
                }, fh, indent=2, default=str)
            logger.warning(f"--write: dumped {len(orphans)} orphaned rows -> {orphan_dump_path}, deleting them.")
            cur.execute("DELETE FROM forecast_result WHERE NOT (product_key = ANY(%s))", (target_keys,))
            counts["orphans_deleted"] = cur.rowcount

        for _, r in df.iterrows():
            p_key = int(r["product_key"])
            sku_df = demand_by_key.get(p_key)
            if sku_df is None or sku_df.empty:
                counts["skipped_no_demand"] += 1
                continue
            series = build_series(sku_df)
            status = r["status"]
            base_mp = {
                "abc_period_used": r["abc_period_used"],
                "min_months_threshold": MIN_MONTHS_WITH_SALES,
                "abc_tier_a_cutoff": ABC_TIER_A_CUTOFF,
                "months_span": int(r["months_span"]),
                "months_with_sales": int(r["months_with_sales"]),
                "demand_class_full": r["demand_class_full"],
            }

            if status == "ok":
                f_val = max(0.0, one_step(DEPLOYED_METHOD, series))
                ci_lower, ci_upper = _confidence_band(f_val, r["ma3_rmse"])
                mp = {
                    **base_mp,
                    "method": DEPLOYED_METHOD,
                    "method_rationale": "MA3 deployed for all Tier A; beat SARIMA / naive / SBA / "
                                        "demand-class routing / history-length routing / ensemble / "
                                        "per-SKU selector on this data",
                    "oracle_method": r["oracle_method"],
                    "rule_method": r["rule_method"],
                    "demand_class_train": r["demand_class_train"],
                    "train_months": int(r["train_months"]),
                    "holdout_months": int(r["holdout_months"]),
                    "ma_window": MA_WINDOW,
                    "sba_alpha": SBA_ALPHA,
                    "sba_alpha_tuned": SBA_ALPHA_TUNED,
                    "holdout_metrics_all_methods": _all_method_metrics(r),
                    "one_step_all_methods": {
                        "naive": round(one_step("naive", series), 3),
                        "ma3": round(f_val, 3),
                        "sba": round(one_step("sba", series), 3),
                    },
                    "provisional": False,
                    "lp_input_method": "ma3_one_step",
                }
                cur.execute(upsert, (
                    p_key, planning_date, float(f_val), ci_lower, ci_upper,
                    _clean_metric(r["ma3_mape"], 100.0), _clean_metric(r["ma3_mase"]),
                    "ok", json.dumps(mp),
                ))
                counts["ok"] += 1

            elif status == "insufficient_data":
                observed = series[series > 0]
                trailing = float(observed.mean()) if len(observed) else 0.0
                mp = {
                    **base_mp,
                    "method": "trailing_average",
                    "provisional": True,
                    "lp_input_method": "trailing_avg_provisional",
                    "mase_gate_passed": None,
                    "observed_months_used": int(len(observed)),
                    "trailing_average": round(trailing, 3),
                    "note": f"< {MIN_MONTHS_WITH_SALES} months of real sales — no holdout, no MASE. "
                            "Recomputed each run as more real months land.",
                }
                cur.execute(upsert, (
                    p_key, planning_date, float(max(0.0, trailing)),
                    None, None, None, None, "insufficient_data", json.dumps(mp),
                ))
                counts["insufficient_data"] += 1

            elif status == "dead_sku":
                mp = {
                    **base_mp,
                    "method": "zero_no_order",
                    "provisional": False,
                    "lp_input_method": "zero_no_order",
                    "mase_gate_passed": None,
                    "note": "no sale in the last 6 months — LP orders nothing.",
                }
                cur.execute(upsert, (
                    p_key, planning_date, 0.0, None, None, None, None, "dead_sku", json.dumps(mp),
                ))
                counts["dead_sku"] += 1

        conn.commit()
    except Exception:
        conn.rollback()
        # the delete never happened -> the dump would be misleading, remove it
        if orphan_dump_path and os.path.exists(orphan_dump_path):
            os.remove(orphan_dump_path)
        logger.error("--write: transaction rolled back, nothing written (orphan dump removed).")
        raise
    finally:
        conn.autocommit = prev_autocommit

    total = counts["ok"] + counts["insufficient_data"] + counts["dead_sku"]
    print(f"--write: committed {total} rows at {planning_date} — "
          f"ok={counts['ok']}, insufficient_data={counts['insufficient_data']}, "
          f"dead_sku={counts['dead_sku']}, skipped(no demand)={counts['skipped_no_demand']}; "
          f"orphaned SARIMA rows deleted={counts['orphans_deleted']}"
          + (f" (dump: {os.path.relpath(orphan_dump_path)})" if orphan_dump_path else "") + ".")


if __name__ == "__main__":
    main()
