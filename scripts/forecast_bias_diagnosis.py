"""
scripts/forecast_bias_diagnosis.py - which way the served forecast misses, and why (2026-11-10). READ-ONLY.

    python -m scripts.forecast_bias_diagnosis            # print the aggregates
    python -m scripts.forecast_bias_diagnosis --write    # also per-product rows to local/ (git-ignored, rule 9)

Window: Sep 2025 - Feb 2026 (DIAG_START..DIAG_END). These months are SEEN by this diagnosis: the selection rule
(docs/CHALLENGER_SELECTION_RULE.md) excludes them from any challenger comparison.

What it reads, all in one READ ONLY transaction each:
  * the dashboard card's own scored rows (backend.marts.accuracy_rows_query, the default backtest
    backend.marts.DEFAULT_BACKTEST_LABEL, as-served, calendar-adjusted) and the same rows of its twin without the calendar
    factor (the same label without ", calendar-adjusted"): signed error per product, and the card's "too high 3 or more
    months in a row" set (accuracy_summary's over_forecast_runs);
  * the real demand (run_baseline_forecast.fetch_demand), from which every flagged product-month is recomputed through
    router.route() as it is served (each product's own calendar factor, calendar.for_product, and its treatment context),
    so each forecast can be split into its parts. The recomputed served value must equal the mart's stored forecast_pieces
    (checked, printed).
  Until 2026-11-13 this read runs 11 / 10 and recomputed with the company calendar factor and no treatments: the served
  forecast of 2026-11-10, whose figures docs/CHALLENGER_FORECAST.md records with that date. Run today it diagnoses what is
  served today.

Mechanism tests on each flagged product's run (the over-forecast months in a row ending at its last scored month):
  (c) calendar   the run is shorter than 3 when the same forecasts are scored without the calendar factor
                 (route's value_before_calendar), i.e. the factor alone made at least one of those months "too high";
  (b) spike      the run is shorter than 3 when the 3-month moving average inside the served value is replaced by the
                 MEDIAN of the same 3 months (a median of 3 ignores exactly one outlier; nothing else changes). TSB has
                 no 3-month window, so a TSB-served run is "not testable" for (b);
  (a) decline    the served forecast before the calendar factor falls at every step of the run AND the mean actual of
                 the run is below the mean actual of the 3 months before it: the forecast follows a falling level down,
                 one step behind. A step down (one drop, then flat) qualifies: the window rolls the high months out.
A product can meet several; the table counts each test and every combination. No threshold beyond the review rule's 3.

Chance baseline: if each month were over or under independently, P(the last 3 scored months all over) = p^3 with
p = the observed share of over-forecast product-months, so the expected number of flagged products is
sum over products with >= 3 scored months of p^3 (and of 0.5^3 for a coin with no bias at all).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import analytics.forecasting.global_model as gm  # noqa: E402
from analytics.forecasting.calendar import calendar_basis, company_totals, for_product  # noqa: E402
from analytics.forecasting.router import route  # noqa: E402
from analytics.params import REVIEW_OVER_RUN_MONTHS, abc_method  # noqa: E402
from scripts.backtest_forecast_run import read_tier_a, ym  # noqa: E402
from scripts.run_baseline_forecast import build_series, fetch_contexts, fetch_demand  # noqa: E402

DIAG_START, DIAG_END = "2025-09-01", "2026-02-01"
CAL_SUFFIX = ", calendar-adjusted"   # the card's default run carries it; its calendar-off twin: backend/marts.unadjusted_twin_labels
LOCAL_OUT = REPO / "local" / "forecast_bias_diagnosis_rows.csv"


def db_url() -> str:
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env", override=False)
    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        sys.exit("SUPABASE_DB_URL is not set")
    return url


def card_rows(url: str, run_id: int, start: str, end: str) -> list[dict]:
    """The scored rows the dashboard card reads for one run (accuracy_rows_query), READ ONLY."""
    import backend.marts as M
    sql, params = M.accuracy_rows_query(start, end, run_id)
    conn = psycopg2.connect(url)
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute(re.sub(r":(\w+)", r"%(\1)s", sql), params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.rollback()
    finally:
        conn.close()
    return rows


def run_ids(url: str) -> tuple[int, int]:
    """(the card's default run, its calendar-off twin), by label: backend.marts.DEFAULT_BACKTEST_LABEL."""
    import backend.marts as M
    cal = M.DEFAULT_BACKTEST_LABEL
    off, base = M.unadjusted_twin_labels(cal)     # the twin's label since migration 0080 (", calendar factor not applied"), else the bare one
    conn = psycopg2.connect(url)
    try:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute("SELECT label, MAX(run_id) FROM mart.forecast_run WHERE label IN (%s, %s, %s) GROUP BY label", (cal, off, base))
        got = dict(cur.fetchall())
        conn.rollback()
    finally:
        conn.close()
    plain = off if off in got else base
    if cal not in got or plain not in got:
        sys.exit(f"the card's default run or its calendar-off twin is not stored: {sorted(got)}")
    return int(got[cal]), int(got[plain])


def read_demand(url: str):
    """(demand frame as the runner reads it, the served treatments' contexts)."""
    conn = psycopg2.connect(url)
    try:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION READ ONLY")
        demand = fetch_demand(cur)
        contexts = fetch_contexts(cur, demand)
        conn.rollback()
    finally:
        conn.close()
    return demand, contexts


def signed_error_table(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)[["product_key", "month", "forecast_pieces", "actual_pieces"]]
    df = df.astype({"forecast_pieces": float, "actual_pieces": float})
    df["err"] = df.forecast_pieces - df.actual_pieces
    g = df.groupby("product_key")
    return pd.DataFrame({"months": g.size(), "mean_err": g.err.mean(), "over": g.err.apply(lambda e: int((e > 0).sum())),
                         "under": g.err.apply(lambda e: int((e < 0).sum())), "sum_actual": g.actual_pieces.sum(),
                         "sum_err": g.err.sum()})


def over_run_set(rows: list[dict], start: str, end: str) -> dict[int, dict]:
    import backend.marts as M
    s = M.accuracy_summary(rows, start, end, REVIEW_OVER_RUN_MONTHS, review_limit=10_000)
    return {int(it["product_key"]): it for it in s["over_forecast_runs"]["items"]}


def components(series: pd.Series, t: pd.Timestamp, fc, totals, context=None) -> dict:
    """The served value and its parts. `totals` is the product's own calendar (calendar.for_product). The value without the
    calendar factor is route() again with none, the same treatment context; the median-of-3 variant is not testable
    (None) where a treatment replaced the value."""
    r = route(series, t, fc, calendar_totals=totals, context=context)
    r_off = route(series, t, fc, calendar_totals=None, context=context)
    hist = series[series.index < t].dropna()
    hist = gm.from_first_sale(hist) if len(gm.from_first_sale(hist)) else hist
    med3 = float(np.median(hist.tail(3).to_numpy(dtype=float)))
    method, ma3 = r["method"], max(0.0, float(r["ma3_value"]))
    pre = float(r_off["value"])
    if method == "ma3":
        pre_med = max(0.0, med3)
    elif method == "xgb_ma3_avg":
        pre_med = max(0.0, (float(r["components"]["xgb"]) + med3) / 2.0)
    else:
        pre_med = None                                   # TSB: no 3-month window to replace
    if r.get("treatment"):
        pre_med = None                                   # succession / fading replaced the value: no window to replace
    f = float(r.get("calendar_factor", 1.0))
    return {"value": float(r["value"]), "pre_calendar": pre, "calendar_factor": f, "method": method, "bin": r["bin"],
            "ma3": ma3, "med3": med3, "value_med3": None if pre_med is None else max(0.0, pre_med * f)}


def run_back(flags: list[bool]) -> int:
    n = 0
    for x in reversed(flags):
        if not x:
            break
        n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--skip-mase", action="store_true", help="skip the two MASE pass-rate recomputes (slow: XGBoost)")
    args = ap.parse_args()
    url = db_url()

    # Context months before DIAG_START so a run that ends in September is seen whole (the mart counts runs over
    # the run's scored rows, from the window start 2023-10).
    ctx_start = "2023-10-01"
    run_cal, run_plain = run_ids(url)
    rows_cal = card_rows(url, run_cal, ctx_start, DIAG_END)
    rows_plain = card_rows(url, run_plain, ctx_start, DIAG_END)
    in_diag = lambda rs: [r for r in rs if DIAG_START[:7] <= str(r["month"])[:7] <= DIAG_END[:7]]  # noqa: E731
    out: dict = {"window": f"{DIAG_START[:7]}..{DIAG_END[:7]}", "run_calendar_on": run_cal, "run_calendar_off": run_plain}

    # 1. Signed error per product, both runs, diagnosis window only.
    for name, rs in (("calendar_on", rows_cal), ("calendar_off", rows_plain)):
        t = signed_error_table(in_diag(rs))
        six = t[t.months == 6]
        p_over = float((pd.DataFrame(in_diag(rs)).astype({"forecast_pieces": float, "actual_pieces": float})
                        .pipe(lambda d: (d.forecast_pieces > d.actual_pieces).mean())))
        out[name] = {
            "products": int(len(t)), "product_months": int(t.months.sum()),
            "mean_err_positive": int((t.mean_err > 0).sum()), "mean_err_negative": int((t.mean_err < 0).sum()),
            "mean_err_zero": int((t.mean_err == 0).sum()),
            "share_months_over": round(p_over, 4),
            "net_bias_pooled": round(float(t.sum_err.sum() / t.sum_actual.abs().sum()), 4),
            "with_6_scored_months": int(len(six)),
            "over_6_of_6": int((six.over == 6).sum()), "over_5plus_of_6": int((six.over >= 5).sum()),
            "chance_over_6_of_6_coin": round(len(six) * 0.5 ** 6, 2),
            "chance_over_5plus_of_6_coin": round(len(six) * (7 / 64), 2),
            "persistently_positive_mean_and_majority_over": int(((t.mean_err > 0) & (t.over > t.months / 2)).sum()),
        }
    flagged = over_run_set(in_diag(rows_cal), DIAG_START, DIAG_END)
    flagged_plain = over_run_set(in_diag(rows_plain), DIAG_START, DIAG_END)
    out["flagged_card_calendar_on"] = len(flagged)
    out["flagged_card_calendar_off"] = len(flagged_plain)
    out["flagged_in_both"] = len(set(flagged) & set(flagged_plain))

    # Chance baseline for the flag.
    d = pd.DataFrame(in_diag(rows_cal)).astype({"forecast_pieces": float, "actual_pieces": float})
    eligible = int((d.groupby("product_key").size() >= REVIEW_OVER_RUN_MONTHS).sum())
    p = float((d.forecast_pieces > d.actual_pieces).mean())
    out["chance_flagged_at_observed_over_share"] = round(eligible * p ** 3, 1)
    out["chance_flagged_coin"] = round(eligible * 0.5 ** 3, 1)
    out["eligible_products_3plus_months"] = eligible

    # 2. Recompute the flagged products' months through route(), with parts.
    demand, contexts = read_demand(url)
    latest = demand.calendar_month.max()
    series = {int(k): build_series(g, latest) for k, g in demand.groupby("product_key")}
    totals = calendar_basis(demand)
    tier = read_tier_a(url, abc_method("unilever"))
    cal_df = pd.DataFrame(rows_cal).astype({"forecast_pieces": float, "actual_pieces": float})
    cal_df["month"] = cal_df.month.astype(str).str[:7]
    # Each flagged product's run = its last run_length scored rows up to DIAG_END. The mart counts runs over
    # scored rows, so a run can skip months in which the product was not Tier A (counted below).
    cal_df = cal_df[cal_df.month <= DIAG_END[:7]].sort_values(["product_key", "month"])
    need = pd.concat([cal_df[cal_df.product_key == k].tail(int(it["run_length"])) for k, it in flagged.items()])
    months_needed = sorted(need.month.unique())
    recs, max_gap = [], 0.0
    for mo in months_needed:
        t = pd.Timestamp(f"{mo}-01")
        prev = ym(t - pd.offsets.MonthBegin(1))
        fc = gm.GlobalForecaster({k: series[k] for k in sorted(tier.get(prev, set())) if k in series})
        for r in need[need.month == mo].itertuples():
            c = components(series[int(r.product_key)], t, fc, for_product(totals, int(r.product_key)), contexts.get(int(r.product_key)))
            # The mart stores the dead-rule value (0) for a dead product-month; route() does not know the rule.
            stored = float(r.forecast_pieces)
            if stored == 0.0 and c["value"] != 0.0:
                c = {**c, "value": 0.0, "pre_calendar": 0.0, "value_med3": 0.0 if c["value_med3"] is not None else None,
                     "method": "zero_no_order"}
            max_gap = max(max_gap, abs(c["value"] - stored))
            recs.append({"product_key": int(r.product_key), "month": mo, "actual": float(r.actual_pieces),
                         "stored": stored, **c})
    comp = pd.DataFrame(recs).sort_values(["product_key", "month"])
    out["recompute_rows"] = int(len(comp))
    out["recompute_max_gap_vs_mart_pieces"] = round(max_gap, 6)

    # 3. Mechanism per flagged product, over its run.
    per = []
    for k, it in flagged.items():
        g = comp[comp.product_key == k].reset_index(drop=True)
        n = int(it["run_length"])
        run = g
        if len(run) != n or not (run.value > run.actual).all():
            sys.exit(f"product {k}: recomputed run ({len(run)} rows) does not reproduce the card's run of {n}")
        # The flag needs the last 3 rows over; a test breaks it when any of those 3 is no longer over.
        last3 = run.tail(REVIEW_OVER_RUN_MONTHS)
        cal = not bool((last3.pre_calendar > last3.actual).all())
        spike = None if last3.value_med3.isna().any() else not bool((last3.value_med3 > last3.actual).all())
        months_i = pd.to_datetime(run.month + "-01")
        gaps = int(((months_i.diff().dt.days > 31)).sum())
        # Decline: the pre-calendar forecast falls at every step of the run; the run's actuals sit below the 3 before.
        s = series[k]
        first = pd.Timestamp(f"{run.month.iloc[0]}-01")
        before = s[(s.index < first)].dropna().tail(3)
        falling_fc = bool((np.diff(run.pre_calendar.to_numpy()) < 0).all()) if n > 1 else False
        level_down = bool(len(before) == 3 and run.actual.mean() < before.mean())
        decline = falling_fc and level_down
        per.append({"product_key": k, "run_length": n, "run_skips_months": gaps > 0, "methods": "/".join(sorted(run.method.unique())),
                    "calendar": cal, "spike": spike, "decline": decline, "falling_forecast": falling_fc,
                    "level_down": level_down, "run_over_pieces": float((run.value - run.actual).sum()),
                    "run_over_pieces_from_calendar": float((run.value - run.pre_calendar).sum())})
    m = pd.DataFrame(per)
    out["mechanism"] = {
        "products": int(len(m)),
        "runs_that_skip_months": int(m.run_skips_months.sum()),
        "run_length_counts": m.run_length.value_counts().sort_index().to_dict(),
        "decline": int(m.decline.sum()),
        "spike": int(m.spike.eq(True).sum()), "spike_not_testable_tsb": int(m.spike.isna().sum()),
        "calendar": int(m.calendar.sum()),
        "falling_forecast_only": int(m.falling_forecast.sum()), "level_down_only": int(m.level_down.sum()),
        "served_method_in_run": m.methods.value_counts().to_dict(),
        "combinations": m.assign(spike=m.spike.map({True: "spike", False: "-", None: "spike?"}))
                         .apply(lambda r: "+".join([x for x, on in (("decline", r.decline), ("calendar", r.calendar)) if on]
                                                   + ([r.spike] if r.spike != "-" else [])) or "none", axis=1)
                         .value_counts().to_dict(),
        "share_of_run_overforecast_from_calendar": round(float(m.run_over_pieces_from_calendar.sum()
                                                               / m.run_over_pieces.sum()), 4),
    }
    # 4. The company total in pieces, month by month (a level falling for everyone makes every trailing model high).
    tot = company_totals(demand)
    out["company_total_pieces"] = {ym(i): round(float(v)) for i, v in tot[tot.index >= "2024-09-01"].items()}

    # 5. Accuracy with the calendar factor OFF beside ON: the card's figures for the window and the whole backtest,
    #    and the MASE pass rate (the stored-MASE protocol of Forecast_Result) recomputed both ways.
    import backend.marts as M
    acc = {}
    for label, (a, b) in (("2025-09..2026-02", (DIAG_START[:7], DIAG_END[:7])), ("2023-10..2026-02", ("2023-10", "2026-02"))):
        for name, rs in (("calendar_on", rows_cal), ("calendar_off", rows_plain)):
            sub = [r for r in rs if a <= str(r["month"])[:7] <= b]
            x = M.accuracy_summary(sub, a, b, REVIEW_OVER_RUN_MONTHS, review_limit=0)
            err = sum(float(r["forecast_pieces"]) - float(r["actual_pieces"]) for r in sub)
            act = sum(abs(float(r["actual_pieces"])) for r in sub)
            acc[f"{label} {name}"] = {
                "product_months": x["product_months"], "products": x["products"],
                "company_total_pesos": x["company_total"]["value"], "typical_product_weighted_pieces": x["wape_pieces"],
                "median_product_wape": x["median_product_wape"], "surplus_share_of_miss_pesos": x["surplus_share_of_miss_pesos"],
                "net_bias_pieces": round(err / act, 4), "over_3plus_in_a_row": x["over_forecast_runs"]["count"]}
    out["accuracy_calendar_off_vs_on"] = acc
    if not args.skip_mase:
        from scripts.accuracy_as_served import mase_pass_rate
        for name, ct in (("calendar_on", totals), ("calendar_off", None)):
            r = mase_pass_rate(url, demand, latest, ct, contexts)
            out[f"mase_pass_{name}"] = {"passes": r["passes"], "scored": r["scored"], "median_mase": round(r["median_mase"], 4),
                                       "stored_forecast_result": r["stored"]}
    print(json.dumps(out, indent=2, default=str))
    if args.write:
        LOCAL_OUT.parent.mkdir(exist_ok=True)
        comp.merge(m, on="product_key", how="left").to_csv(LOCAL_OUT, index=False)
        print(f"[write] {LOCAL_OUT} (git-ignored)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
