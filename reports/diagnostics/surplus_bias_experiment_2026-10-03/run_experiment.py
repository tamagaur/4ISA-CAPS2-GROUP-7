"""
Surplus-bias fix experiment, stock-aware - Unilever Tier A as of 2026-02 (ABC 'single').
Offline: reads only inputs/ (the forecast-error diagnostic's pull + pull_stock_counts.py).
Nothing touches the database.

Baseline = the served router, rebuilt through the shared harness
reports/diagnostics/fit_diagnosis_2026-10/run_fit_diagnosis.py (run_cohort, verdict_holdouts,
rolling_one_step with the product's served bin held fixed) - the same code path as the
forecast-error diagnostic. The run stops unless it reproduces public.forecast_result (pulled
copy) and the REAL holdout rows of reports/simulation/synthetic_2026-10/series.csv.

Rules fixed before computing (README.md beside this file):
  error            = forecast - actual (pieces); > 0 over-forecast (surplus), < 0 under (shortage)
  opening count    = stock count of period M-1 (Unilever's count for period P is taken in the first
                     days of P+1: 2026-02 -> 2026-03-02, inputs/stock_snapshots_unilever.csv)
  closing count    = stock count of period M
  pieces           = cases x pack_size + loose pieces (backend/stock_units.py STOCK_PIECES_EXPR)
  not in a count   = 0 on hand, flagged stock_not_in_count (Unilever's count never lists zero
                     rows - backend/stock_status.py COUNT_OMITS_ZERO_STOCK); a month with no real
                     count at all = "no count" (unknown), never 0
  average sales    = mean monthly pieces over the 12 months before M (from first sale, a month with
                     no row = 0), at least 3 months; 1 week = average x 12 / 52
  stock-limited    = opening or closing count is 0, or below 1 week of average sales
  high carryover   = opening count above 6 weeks of average sales
  recent bias (B)  = sum(error) / sum(|actual|) of the baseline's own one-step forecasts over the
                     previous 3 or 6 months (all of them must exist); applied only when at least 3
                     of those months have the same sign as that bias; adjustment = k x bias capped
                     at +/-30%; forecast x (1 - adjustment), floored at 0
  collapse (A)     = mean(last 3 months) < 0.5 x mean(last 12 months), history before M only,
                     >= 12 months since first sale (forecast-error diagnostic, run_analysis.py:416)
  over-run (D)     = 3+ over-forecast months in a row ending the month before M (baseline errors)
  pesos            = pieces x selling price per piece = sum(net_amount) / sum(pieces) over the
                     product's own test months: at selling price, VAT-inclusive (value-added tax)
  decision rule    = cuts surplus pesos, median product WAPE up by no more than 1.0 point, and
                     both hold in each half of the test window
  windows          = six_months: 2025-09..2026-02, served bin held fixed (reproduces series.csv);
                     long_window: 2023-10..2026-02, bin re-worked each month, rebuilt with the
                     forecast-error diagnostic's own run_followups.run_jobs, read from commit b4f6b77

    ../Capstone-Project/.venv/Scripts/python.exe reports/diagnostics/surplus_bias_experiment_2026-10-03/run_experiment.py [--window long_window]
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd
import xgboost as xgb

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "reports", "diagnostics", "fit_diagnosis_2026-10"))

import run_fit_diagnosis as F  # noqa: E402  (the shared served-router harness)
from analytics.forecasting import baseline  # noqa: E402
from analytics.forecasting.diagnostic_metrics import wape  # noqa: E402
from analytics.forecasting.global_model import (  # noqa: E402
    MIN_HISTORY, MIN_TRAINING_ROWS, NUM_ROUNDS, PARAMS, GlobalForecaster, build_features, from_first_sale,
)
from analytics.forecasting.router import ma3_value, rolling_one_step  # noqa: E402

INP = os.path.join(HERE, "inputs")
SERIES_CSV = os.path.join(REPO, "reports", "simulation", "synthetic_2026-10", "series.csv")
SELL = "at selling price, VAT-inclusive (value-added tax)"

# The forecast-error diagnostic's long window (window C) lives in run_followups.py on
# kelvin/forecast-error-business. Its files are read from the pinned commit (git show, shared object
# store), never from that branch's working folder, so later edits there cannot change this run.
# b4f6b77 replaced eebd741 (client data stripped): run_jobs / long_window are unchanged, but the per-row
# table is no longer committed. It is written to that folder's git-ignored local/, which is the per-row
# reference when present; the committed per-product summary and window totals are always checked.
SOURCE_COMMIT = "b4f6b77"
SOURCE_PATH = "reports/diagnostics/forecast_error_business_2026-10-03"
SOURCE_LOCAL_FULL = os.path.join("C:/Users/kyuan/dsd-forecast-error-business", SOURCE_PATH, "local",
                                 "longwindow_per_product_month.csv")
WINDOW_SPEC = {
    "six_months": {"test": list(pd.date_range("2025-09-01", "2026-02-01", freq="MS")),
                   "bin_rule": "served bin (as of 2026-03) held fixed - the forecast-error diagnostic's window A"},
    "long_window": {"test": list(pd.date_range("2023-10-01", "2026-02-01", freq="MS")),
                    "bin_rule": "bin re-worked each month from the history known then - the forecast-error "
                                "diagnostic's window C (run_followups.py long_window / run_jobs)"},
}
TEST: list = []                  # set by use_window()
HALVES: tuple = ()
PRIOR_MONTHS = 6                 # baseline forecasts before the window, for B's and D's look-back

AVG_MONTHS, AVG_MIN_MONTHS = 12, 3
WEEKS_PER_MONTH = 52 / 12
LOW_WEEKS, HIGH_WEEKS = 1.0, 6.0
LOW_WEEKS_SENSITIVITY = (0.5, 1.0, 2.0)
# Counts to try as missing: 2026-02 is the team-flagged outlier (backend/data_notes.py:26-29, decision
# pending); 2025-05 has 404 rows against 513-812 in every other real month and 36 of 96 selling Tier A
# products absent (part0_count_completeness.csv), so it looks partial.
MISSING_SETTINGS = ((), ("2026-02",), ("2025-05",))
# Decisions recorded 2026-10-03 (user). The main results use every real count as recorded.
COUNT_NOTES = {
    "2026-02": "team-flagged outlier (backend/data_notes.py:26-29); ACCEPTED 2026-10-03, pending SSM confirmation",
    "2025-05": "possibly partial (fewest rows of any real count); missing = 0 rule kept; open question for SSM",
}
# Recorded threshold (user, 2026-10-03): a forecast change must remove at least this share of surplus pesos
# over the 29-month window AND must not add more shortage pesos than it removes.
SURPLUS_CUT_MIN_PCT = 5.0
COLLAPSE_RATIO = 0.5
KS, WINDOWS, CAP, SAME_SIGN_MIN = (0.25, 0.5, 1.0), (3, 6), 0.30, 3
RUN_MIN = 3
WAPE_TOL_PTS = 1.0
BIN_LABEL = {"short": "3-11 months", "medium": "12-23 months", "long": "24+ months"}


def read(name, **kw):
    return pd.read_csv(os.path.join(INP, name), **kw)


def ym(ts) -> str:
    return pd.Timestamp(ts).strftime("%Y-%m")


def prev_month(ts, n=1) -> pd.Timestamp:
    return pd.Timestamp(ts) - pd.offsets.MonthBegin(n)


def use_window(name: str):
    global TEST, HALVES
    TEST = WINDOW_SPEC[name]["test"]
    half = (len(TEST) + 1) // 2
    HALVES = (TEST[:half], TEST[half:])


def missing_tag(missing) -> str:
    return "counts as recorded" if not missing else " + ".join(missing) + " count treated as missing"


# --------------------------------------------------------------------------- #
# 1. Baseline backtest (served router), extended 6 months back for the look-back rules
# --------------------------------------------------------------------------- #
def rebuild(window: str):
    tier = read("tier_a.csv")
    keys = sorted(tier["product_key"].astype(int))
    demand = read("demand_real_tierA.csv", dtype={"calendar_month": str})
    demand["quantity"] = pd.to_numeric(demand["quantity"], errors="coerce").fillna(0.0)
    recs, series, fc = F.run_cohort(demand, keys)
    bad = F.check_against_live(recs, read("forecast_result_live.csv"))
    if bad:
        raise SystemExit(f"does not reproduce forecast_result: {bad[:5]}")
    hold = F.verdict_holdouts(recs, series)
    common = sorted(k for k, h in hold.items() if h["source"] == "common")
    if window == "long_window":
        return (tier, recs, series, fc, *long_baseline(series, common))
    rows = []
    for k in common:
        s = series[k]
        first = from_first_sale(s).index[0]
        prior = [prev_month(TEST[0], n) for n in range(PRIOR_MONTHS, 0, -1)]
        months = [m for m in prior if m in s.index and m > first] + hold[k]["months"]
        df = rolling_one_step(s, months, fc, force_bin=recs[k]["bin"])
        df["product_key"] = k
        df["bin"] = recs[k]["bin"]
        rows.append(df)
    bt = pd.concat(rows, ignore_index=True).rename(columns={"value": "f0"})
    ref = pd.read_csv(SERIES_CSV)
    ref = ref[(ref.run == "REAL") & (ref.kind == "holdout") & ref.product_key.isin(common)]
    ref = ref.assign(month=pd.to_datetime(ref.month + "-01"))[["product_key", "month", "forecast", "actual"]]
    test = bt[bt.month.isin(TEST)]
    cmp_ = test.merge(ref, on=["product_key", "month"], how="outer", suffixes=("", "_ref"), indicator=True)
    if (cmp_["_merge"] != "both").any():
        raise SystemExit(f"key mismatch vs series.csv: {cmp_['_merge'].value_counts().to_dict()}")
    gap = float((cmp_.f0 - cmp_.forecast).abs().max())
    if gap > 1e-6 or float((cmp_.actual - cmp_.actual_ref).abs().max()) > 1e-9:
        raise SystemExit(f"differs from series.csv: forecast gap {gap}")
    repro = {"forecast_result_rows_matched": len(recs), "series_csv_rows_matched": int(len(ref)),
             "series_csv_max_forecast_gap": gap}
    return tier, recs, series, fc, bt, common, repro


def long_baseline(series: dict, common: list):
    """Window C of the forecast-error diagnostic, rebuilt with ITS OWN run_jobs (route() with no
    forced bin, one forecaster over the Tier A pool), plus the PRIOR_MONTHS before 2023-10 for the
    look-back rules. Stops unless it reproduces the source's per-product summary and window totals (committed at
    SOURCE_COMMIT) and, when present, the source's git-ignored per-row table."""
    import subprocess
    import tempfile
    src = tempfile.mkdtemp(prefix="surplus_bias_src_")
    for name in ("run_analysis.py", "run_followups.py", "longwindow_per_product_summary.csv", "window_comparison.csv"):
        blob = subprocess.run(["git", "-C", REPO, "show", f"{SOURCE_COMMIT}:{SOURCE_PATH}/{name}"],
                              capture_output=True, check=True).stdout
        with open(os.path.join(src, name), "wb") as fh:
            fh.write(blob)
    head = subprocess.run(["git", "-C", REPO, "log", "-1", "--format=%h %s", SOURCE_COMMIT],
                          capture_output=True, text=True, check=True).stdout.strip()
    sys.path.insert(0, src)
    import run_followups as RF  # noqa: E402  (its long_window() rule: months in the series, after its first row)
    prior = [prev_month(TEST[0], n) for n in range(PRIOR_MONTHS, 0, -1)]
    jobs = [(k, m, None) for k in common for m in prior + TEST if m in series[k].index and m > series[k].index[0]]
    bt = RF.run_jobs(series, series, jobs)
    bt = bt[bt.value.notna()].rename(columns={"value": "f0"})[["product_key", "month", "actual", "f0", "ma3", "naive",
                                                                 "method", "backup_fired", "bin"]]
    test = bt[bt.month.isin(TEST)]
    tol = 0.00005 + 1e-9                                       # the source CSVs are written with 4 decimals
    # (1) per product, against the committed per-product summary (window_metrics' own definitions)
    per = pd.DataFrame([{"product_key": k, "months": len(x), "wape": wape(x.actual, x.f0), "ma3_wape": wape(x.actual, x.ma3),
                         "naive_wape": wape(x.actual, x.naive) if x.naive.notna().all() else np.nan,
                         "mean_abs_error_pcs": (x.f0 - x.actual).abs().mean(),
                         "bias_pct": (x.f0 - x.actual).sum() / x.actual.abs().sum() * 100}
                        for k, x in test.groupby("product_key")]).set_index("product_key")
    ref_p = pd.read_csv(os.path.join(src, "longwindow_per_product_summary.csv")).set_index("product_key")
    if set(per.index) != set(ref_p.index) or (per.months != ref_p.months.reindex(per.index)).any():
        raise SystemExit("product set or months per product differ from longwindow_per_product_summary.csv")
    gaps = {c: float((per[c] - ref_p[c].reindex(per.index)).abs().max()) for c in
            ("wape", "ma3_wape", "naive_wape", "mean_abs_error_pcs", "bias_pct")}
    if max(gaps.values()) > tol:
        raise SystemExit(f"differs from longwindow_per_product_summary.csv: {gaps}")
    # (2) window totals, against the committed window_comparison.csv column C
    wc = pd.read_csv(os.path.join(src, "window_comparison.csv"), index_col=0).iloc[:, 2]
    e = test.f0 - test.actual
    price = test.product_key.map(prices(test))
    totals = {"product_months": len(test), "product_months_over": int((e > 0).sum()), "product_months_under": int((e < 0).sum()),
              "product_months_exact": int((e == 0).sum()),
              "avg_monthly_surplus_pesos_sell": float((e.clip(lower=0) * price).sum() / len(TEST)),
              "avg_monthly_shortage_pesos_sell": float(((-e).clip(lower=0) * price).sum() / len(TEST))}
    tgap = {k: abs(v - float(wc[k])) for k, v in totals.items()}
    if max(tgap.values()) > 0.0000005 + 1e-9:                  # window_comparison.csv has 6 decimals
        raise SystemExit(f"differs from window_comparison.csv: {tgap}")
    # (3) per row, against the source's own full table in its git-ignored local/ (this machine only)
    row = {"per_row_reference": "not available (the source's local/ table is not on this machine)"}
    if os.path.exists(SOURCE_LOCAL_FULL):
        ref = pd.read_csv(SOURCE_LOCAL_FULL)
        ref = ref.assign(month=pd.to_datetime(ref.month + "-01"))[["product_key", "month", "forecast", "actual"]]
        cmp_ = test.merge(ref, on=["product_key", "month"], how="outer", suffixes=("", "_ref"), indicator=True)
        if (cmp_["_merge"] != "both").any():
            raise SystemExit(f"key mismatch vs the source's local table: {cmp_['_merge'].value_counts().to_dict()}")
        gap = float((cmp_.f0 - cmp_.forecast).abs().max())
        if gap > tol or float((cmp_.actual - cmp_.actual_ref).abs().max()) > tol:
            raise SystemExit(f"differs from the source's local table: forecast gap {gap}")
        row = {"per_row_reference": f"{SOURCE_PATH}/local/longwindow_per_product_month.csv (git-ignored, written by "
                                    f"{SOURCE_COMMIT}'s code)", "per_row_matched": int(len(ref)), "per_row_max_forecast_gap": gap}
    return bt, common, {"source_commit": head, "per_product_summary_matched": int(len(ref_p)),
                        "per_product_max_gap": max(gaps.values()), "window_totals_matched": totals,
                        "window_totals_max_gap": max(tgap.values()), **row}


# --------------------------------------------------------------------------- #
# 2. Stock labels per product-month (Part 0)
# --------------------------------------------------------------------------- #
def stock_pieces():
    snap = read("stock_snapshots_unilever.csv", dtype={"_period": str})
    real_periods = set(snap[(snap.is_demo == False) & snap.fill_source.isna()]._period)  # noqa: E712
    st = read("stock_real_tierA_by_period.csv", dtype={"_period": str})
    dims = read("product_dimension_tierA.csv", dtype={"sku_code": str})
    st = st.merge(dims[["product_key", "pack_size"]], on="product_key")
    st["pieces"] = st.cases * pd.to_numeric(st.pack_size, errors="coerce") + st.loose_pieces.fillna(0)
    return real_periods, {(int(k), p): float(v) for k, p, v in zip(st.product_key, st._period, st.pieces)}


def labels(series: dict, real_periods: set, pieces: dict, low_weeks=LOW_WEEKS, missing=()) -> pd.DataFrame:
    periods = set(real_periods) - set(missing)

    def side(k, period):
        if period not in periods:
            return np.nan, "no count"
        v = pieces.get((k, period))
        return (0.0, "stock_not_in_count") if v is None else (v, "count")

    rows = []
    for k, s0 in series.items():
        s = from_first_sale(s0)
        vals = s.to_numpy(dtype=float)
        for t, m in enumerate(s.index):
            o, o_src = side(k, ym(prev_month(m)))
            c, c_src = side(k, ym(m))
            prev = vals[max(0, t - AVG_MONTHS):t]
            avg = float(prev.mean()) if len(prev) >= AVG_MIN_MONTHS else np.nan
            week = avg / WEEKS_PER_MONTH if np.isfinite(avg) and avg > 0 else np.nan
            have = [(v, nm) for v, nm in ((o, "opening"), (c, "closing")) if np.isfinite(v)]
            reasons = [f"{nm} zero" for v, nm in have if v <= 0]
            if np.isfinite(week):
                reasons += [f"{nm} < {low_weeks:g} wk" for v, nm in have if 0 < v < low_weeks * week]
            if not have:
                limited = pd.NA
            elif reasons:
                limited = True
            elif np.isfinite(week):
                limited = False
            else:
                limited = pd.NA                       # counts positive but no average to compare with
            carry = (o > HIGH_WEEKS * week) if (np.isfinite(o) and np.isfinite(week)) else pd.NA
            rows.append({"product_key": k, "month": m, "actual": vals[t], "opening_pcs": o, "opening_src": o_src,
                         "closing_pcs": c, "closing_src": c_src, "avg_monthly_pcs": avg,
                         "opening_weeks": o / week if np.isfinite(week) and np.isfinite(o) else np.nan,
                         "closing_weeks": c / week if np.isfinite(week) and np.isfinite(c) else np.nan,
                         "sides": "both" if len(have) == 2 else (have[0][1] + " only" if have else "none"),
                         "stock_limited": limited, "limited_reason": "; ".join(reasons),
                         "limited_only_by_not_in_count": bool(reasons) and all(
                             (nm == "opening" and o_src == "stock_not_in_count") or
                             (nm == "closing" and c_src == "stock_not_in_count")
                             for nm in [r.split()[0] for r in reasons]),
                         "high_carryover": carry})
    out = pd.DataFrame(rows)
    out["stock_limited"] = out.stock_limited.astype("boolean")
    out["high_carryover"] = out.high_carryover.astype("boolean")
    return out


# --------------------------------------------------------------------------- #
# 3. Prices and the scored panel
# --------------------------------------------------------------------------- #
def prices(bt_test: pd.DataFrame) -> pd.Series:
    money = read("demand_money_tierA.csv", dtype={"calendar_month": str})
    money["month"] = pd.to_datetime(money.calendar_month + "-01")
    g = bt_test[["product_key", "month"]].merge(money, on=["product_key", "month"], how="left") \
        .groupby("product_key")[["quantity", "net_amount"]].sum()
    return (g.net_amount / g.quantity).where((g.quantity > 0) & (g.net_amount > 0)).rename("price")


def level_ratio(s: pd.Series, upto: pd.Timestamp):
    h = s[s.index <= upto]
    sold = np.flatnonzero(h.to_numpy() > 0)
    if not sold.size:
        return None, None
    h = h.iloc[int(sold[0]):]
    if len(h) < 12 or h.tail(12).mean() <= 0:
        return None, float(h.tail(3).mean())
    return float(h.tail(3).mean() / h.tail(12).mean()), float(h.tail(3).mean())


def look_back(bt: pd.DataFrame) -> pd.DataFrame:
    """Per test row: recent bias over the previous 3 / 6 baseline months, same-sign count,
    and the over-forecast run ending the month before."""
    e = bt.assign(err=bt.f0 - bt.actual).set_index(["product_key", "month"])
    out = []
    for (k, m) in bt[bt.month.isin(TEST)][["product_key", "month"]].itertuples(index=False):
        r = {"product_key": k, "month": m}
        for w in WINDOWS:
            ms = [prev_month(m, n) for n in range(1, w + 1)]
            if all((k, x) in e.index for x in ms):
                g = e.loc[[(k, x) for x in ms]]
                den = float(g.actual.abs().sum())
                b = float(g.err.sum() / den) if den > 0 else np.nan
                same = int((np.sign(g.err) == np.sign(b)).sum()) if np.isfinite(b) and b != 0 else 0
                r[f"bias{w}"], r[f"same{w}"] = b, same
            else:
                r[f"bias{w}"], r[f"same{w}"] = np.nan, 0
        run, x = 0, prev_month(m)
        while (k, x) in e.index and e.loc[(k, x), "err"] > 0:
            run, x = run + 1, prev_month(x)
        r["over_run_before"] = run
        out.append(r)
    return pd.DataFrame(out)


# --------------------------------------------------------------------------- #
# 4. Candidate E: train with stock-limited months excluded
# --------------------------------------------------------------------------- #
class ExcludingForecaster(GlobalForecaster):
    """GlobalForecaster whose training rows skip (product, month) pairs in `excluded`.
    The features still read the real history; only the rows the booster learns from change.
    With an empty `excluded` it builds exactly training_rows()'s rows, in the same order."""

    def __init__(self, pool: dict, excluded: dict):
        super().__init__(pool)
        self.excluded = excluded
        self.dropped: dict = {}

    def booster_for(self, target_month):
        if target_month not in self._cache:
            X, y, dropped = [], [], 0
            for k, series in self.pool.items():
                s = from_first_sale(series)
                values = s.to_numpy(dtype=float)
                ex = self.excluded.get(k, frozenset())
                for t in range(MIN_HISTORY, len(s)):
                    month = s.index[t]
                    if month >= target_month:
                        break
                    feats, scale = build_features(values[:t], month)
                    if feats is None:
                        continue
                    if month in ex:
                        dropped += 1
                        continue
                    X.append(feats)
                    y.append(values[t] / scale)
            booster = None
            if len(y) >= MIN_TRAINING_ROWS:
                booster = xgb.train(PARAMS, xgb.DMatrix(np.vstack(X), label=np.asarray(y)), num_boost_round=NUM_ROUNDS)
            self._cache[target_month] = (booster, len(y))
            self.dropped[target_month] = dropped
        return self._cache[target_month]


def route_e(series: pd.Series, month, fc: GlobalForecaster, bin_name: str, drop: frozenset, clean_history: bool):
    """router.route() with the bin held fixed, the global model from `fc`, and (clean_history)
    MA3 / TSB computed on the history with the months in `drop` removed. Guards unchanged:
    no XGBoost number, above the history's max or below zero -> MA3."""
    history = series[series.index < month]
    history = from_first_sale(history) if len(from_first_sale(history)) else history
    fit_on = history[~history.index.isin(list(drop))] if clean_history else history
    if not len(fit_on):
        fit_on = history
    ma3 = ma3_value(fit_on)
    if bin_name == "short":
        return max(0.0, ma3)
    if bin_name == "medium":
        value, reason = float(baseline.tsb_forecast(fit_on, 1)[0]), None
    else:
        xv, _, reason = fc.forecast(series, month)
        value = None if xv is None else (xv + ma3) / 2.0
    if value is None or reason is not None or value > float(history.to_numpy(dtype=float).max()) or value < 0:
        return max(0.0, ma3)
    return float(value)


def run_e(series: dict, panel: pd.DataFrame, lab: pd.DataFrame):
    """panel: product_key, month, bin (the bin the baseline used that month), f0. Pool = all Tier A series,
    as in run_cohort / run_jobs."""
    limited = lab[lab.stock_limited.fillna(False)]
    excluded = {int(k): frozenset(g.month) for k, g in limited.groupby("product_key")}
    check = ExcludingForecaster(series, {})
    efc = ExcludingForecaster(series, excluded)
    check_months = {TEST[0], TEST[len(TEST) // 2], TEST[-1]}
    rows, gaps = [], []
    for k, m, b, f0 in panel[["product_key", "month", "bin", "f0"]].itertuples(index=False):
        s = series[k]
        drop = frozenset(x for x in excluded.get(k, ()) if x < m)
        if m in check_months:                  # the subclass must reproduce the baseline with nothing excluded
            gaps.append(abs(route_e(s, m, check, b, frozenset(), True) - f0))
        rows.append({"product_key": k, "month": m,
                     "fE1": route_e(s, m, efc, b, drop, False),
                     "fE2": route_e(s, m, efc, b, drop, True)})
    info = {"max_gap_no_exclusion_vs_baseline": float(max(gaps)),
            "training_rows_dropped": {ym(m): int(v) for m, v in efc.dropped.items()},
            "training_rows_kept": {ym(m): int(efc._cache[m][1]) for m in efc._cache}}
    return pd.DataFrame(rows), info


# --------------------------------------------------------------------------- #
# 5. Scoring
# --------------------------------------------------------------------------- #
def score(p: pd.DataFrame, col: str, months: list | None = None) -> dict:
    """Metrics for forecast column `col` on panel rows p (optionally restricted to `months`).
    Pesos per month divide by the months of the window (or of the half), not by the months a subset
    happens to have, so the three bins add up to the 'all' row (a bin can start part-way through)."""
    n_months = len(months) if months is not None else len(TEST)
    if months is not None:
        p = p[p.month.isin(months)]
    if not len(p):
        return {}
    e = p[col] - p.actual
    prod = p.groupby("product_key").apply(lambda g: wape(g.actual, g[col]), include_groups=False)
    base = p.groupby("product_key").apply(lambda g: wape(g.actual, g.f0), include_groups=False)
    ok = prod.notna() & base.notna()
    return {"products": int(p.product_key.nunique()), "product_months": int(len(p)),
            "median_product_wape_pct": float(prod.median() * 100),
            "total_wape_pct": float(e.abs().sum() / p.actual.abs().sum() * 100),
            "signed_bias_pct": float(e.sum() / p.actual.abs().sum() * 100),
            "months_over": int((e > 0).sum()), "months_under": int((e < 0).sum()), "months_exact": int((e == 0).sum()),
            "surplus_pesos_per_month": float((e.clip(lower=0) * p.price).sum() / n_months),
            "shortage_pesos_per_month": float(((-e).clip(lower=0) * p.price).sum() / n_months),
            "products_better": int((prod[ok] < base[ok] - 1e-12).sum()),
            "products_worse": int((prod[ok] > base[ok] + 1e-12).sum())}


def compare(p: pd.DataFrame, cands: dict, scope_name: str) -> list:
    rows = []
    for name, col in cands.items():
        for scope, g in [("all", p)] + [(BIN_LABEL[b], p[p.bin == b]) for b in ("short", "medium", "long")]:
            r = {"candidate": name, "scope": scope, "rows": scope_name, **score(g, col)}
            nsl = g[~g.stock_limited.fillna(False)]
            s2 = score(nsl, col)
            r["surplus_pesos_per_month_excl_stock_limited"] = s2.get("surplus_pesos_per_month", np.nan)
            r["shortage_pesos_per_month_excl_stock_limited"] = s2.get("shortage_pesos_per_month", np.nan)
            for i, h in enumerate(HALVES, 1):
                sh, sb = score(g, col, h), score(g, "f0", h)
                if sh:
                    r[f"h{i}_surplus_change_pesos_per_month"] = sh["surplus_pesos_per_month"] - sb["surplus_pesos_per_month"]
                    r[f"h{i}_shortage_change_pesos_per_month"] = sh["shortage_pesos_per_month"] - sb["shortage_pesos_per_month"]
                    r[f"h{i}_median_wape_change_pts"] = sh["median_product_wape_pct"] - sb["median_product_wape_pct"]
            rows.append(r)
    df = pd.DataFrame(rows)
    b = df[df.candidate == "baseline"].set_index("scope")
    for c in ("median_product_wape_pct", "total_wape_pct", "signed_bias_pct", "surplus_pesos_per_month",
              "shortage_pesos_per_month", "surplus_pesos_per_month_excl_stock_limited"):
        df[f"{c}_change"] = df[c] - df.scope.map(b[c])
    df["surplus_cut_pct"] = -df.surplus_pesos_per_month_change / df.scope.map(b.surplus_pesos_per_month) * 100
    df["passes_wape"] = df.median_product_wape_pct_change <= WAPE_TOL_PTS
    df["cuts_surplus"] = df.surplus_pesos_per_month_change < 0
    df["holds_both_halves"] = ((df.h1_surplus_change_pesos_per_month < 0) & (df.h2_surplus_change_pesos_per_month < 0)
                               & (df.h1_median_wape_change_pts <= WAPE_TOL_PTS) & (df.h2_median_wape_change_pts <= WAPE_TOL_PTS))
    df["meets_decision_rule"] = df.passes_wape & df.cuts_surplus & df.holds_both_halves
    df["shortage_added_not_above_surplus_removed"] = df.shortage_pesos_per_month_change <= -df.surplus_pesos_per_month_change
    df["meets_recorded_threshold"] = (df.meets_decision_rule & (df.surplus_cut_pct >= SURPLUS_CUT_MIN_PCT)
                                      & df.shortage_added_not_above_surplus_removed)
    df.loc[df.candidate == "baseline", ["passes_wape", "cuts_surplus", "holds_both_halves", "meets_decision_rule",
                                        "shortage_added_not_above_surplus_removed", "meets_recorded_threshold"]] = False
    return df


# --------------------------------------------------------------------------- #
# 6. Part 0 tables
# --------------------------------------------------------------------------- #
def recount(p: pd.DataFrame, tag: str) -> list:
    sl = p.stock_limited.fillna(False).astype(bool)
    e = p.f0 - p.actual
    sur, sho = e.clip(lower=0) * p.price, (-e).clip(lower=0) * p.price
    n = p.month.nunique()
    a = {"view": "(a) as measured", "over": int((e > 0).sum()), "under": int((e < 0).sum()),
         "surplus_pesos_per_month": sur.sum() / n, "shortage_pesos_per_month": sho.sum() / n}
    b = {"view": "(b) stock-limited months excluded", "over": int(((e > 0) & ~sl).sum()), "under": int(((e < 0) & ~sl).sum()),
         "surplus_pesos_per_month": sur[~sl].sum() / n, "shortage_pesos_per_month": sho[~sl].sum() / n}
    c = {"view": "(c) stock-limited months relabelled as shortage", "over": int(((e > 0) & ~sl).sum()),
         "under": int(((e < 0) | sl).sum()), "surplus_pesos_per_month": sur[~sl].sum() / n,
         "shortage_pesos_per_month": sho.sum() / n,
         "note": "shortage pesos are a floor: the true shortfall in a stock-limited month is unknown"}
    out = []
    for r in (a, b, c):
        r.update({"setting": tag, "product_months": int(len(p)), "stock_limited_months": int(sl.sum()),
                  "exact": int(((e == 0) & (True if r["view"].startswith("(a)") else ~sl)).sum()),
                  "over_share_pct": r["over"] / (r["over"] + r["under"]) * 100,
                  "surplus_minus_shortage_pesos_per_month": r["surplus_pesos_per_month"] - r["shortage_pesos_per_month"]})
        out.append(r)
    return out


def carryover_table(lab: pd.DataFrame, keys: list, months: list | None, tag: str) -> pd.DataFrame:
    d = lab[lab.product_key.isin(keys)].sort_values(["product_key", "month"]).copy()
    d["next_actual"] = d.groupby("product_key").actual.shift(-1)
    d["next_month"] = d.groupby("product_key").month.shift(-1)
    d = d[(d.next_month == d.month + pd.offsets.MonthBegin(1)) & (d.avg_monthly_pcs > 0) & d.high_carryover.notna()]
    if months is not None:
        d = d[d.month.isin(months)]
    d["this_vs_avg"] = d.actual / d.avg_monthly_pcs
    d["next_vs_avg"] = d.next_actual / d.avg_monthly_pcs
    d["group"] = np.where(d.high_carryover.astype(bool), "high carryover (opening > 6 wk)",
                          np.where(d.stock_limited.fillna(False).astype(bool), "stock-limited", "neither"))
    g = d.groupby("group")
    return pd.DataFrame({"window": tag, "product_months": g.size(), "products": g.product_key.nunique(),
                         "median_this_month_vs_avg": g.this_vs_avg.median(),
                         "median_next_month_vs_avg": g.next_vs_avg.median(),
                         "share_next_month_below_avg_pct": g.next_vs_avg.apply(lambda x: (x < 1).mean() * 100),
                         "share_next_month_below_70pct_of_avg": g.next_vs_avg.apply(lambda x: (x < 0.7).mean() * 100),
                         }).reset_index()


def runs_table(p: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    rows = []
    for k, g in p.sort_values("month").groupby("product_key"):
        over = list(g.f0 > g.actual)
        sl = list(g.stock_limited.fillna(False).astype(bool))
        i, in_run = 0, [False] * len(over)
        while i < len(over):
            j = i
            while j < len(over) and over[j]:
                j += 1
            if j - i >= RUN_MIN:
                for x in range(i, j):
                    in_run[x] = True
            i = max(j, i + 1)
        if any(in_run):
            rows.append({"product_key": k, "run_months": sum(in_run),
                         "run_months_stock_limited": sum(a and b for a, b in zip(in_run, sl)),
                         "run_months_high_carryover": sum(a and bool(b) for a, b in
                                                          zip(in_run, g.high_carryover.fillna(False)))})
    t = pd.DataFrame(rows)
    t["run_still_open_at_end"] = t.product_key.map(
        lambda k: bool((p[p.product_key == k].sort_values("month").tail(RUN_MIN).pipe(lambda x: (x.f0 > x.actual).all()))))
    summ = {"products": int(len(t)), "run_months": int(t.run_months.sum()),
            "run_months_stock_limited": int(t.run_months_stock_limited.sum()),
            "products_with_any_stock_limited_run_month": int((t.run_months_stock_limited > 0).sum()),
            "products_all_run_months_stock_limited": int((t.run_months_stock_limited == t.run_months).sum()),
            "run_months_high_carryover": int(t.run_months_high_carryover.sum())}
    return t, summ


def by_reason(p: pd.DataFrame) -> pd.DataFrame:
    """Which side tripped the rule. A low OPENING count is known before the month's sales; a low
    CLOSING count can be the result of strong sales in that same month (sold through)."""
    r = p.limited_reason.fillna("")
    op, cl = r.str.contains("opening"), r.str.contains("closing")
    grp = np.select([p.stock_limited.isna(), op & cl, op, cl], ["can't tell (no label)", "both counts low",
                                                                "opening count low only", "closing count low only"],
                    "not stock-limited")
    e = p.f0 - p.actual
    d = p.assign(group=grp, over=e > 0, sales_vs_avg=p.actual / p.avg_monthly_pcs,
                 sur=e.clip(lower=0) * p.price, sho=(-e).clip(lower=0) * p.price)
    g = d.groupby("group")
    return pd.DataFrame({"product_months": g.size(), "over_forecast_pct": g.over.mean() * 100,
                         "median_sales_vs_12m_avg": g.sales_vs_avg.median(),
                         "surplus_pesos_per_month": g.sur.sum() / p.month.nunique(),
                         "shortage_pesos_per_month": g.sho.sum() / p.month.nunique()}).reset_index()


def completeness(lab: pd.DataFrame, snap: pd.DataFrame) -> pd.DataFrame:
    """Per real count: Tier A products that sold that month but are missing from the count.
    A high share means the count itself is probably partial, so 'missing = 0' would mislabel."""
    d = lab[lab.closing_src != "no count"].assign(period=lab.month.map(ym), sold=lab.actual > 0)
    d["sold_missing"] = d.sold & (d.closing_src == "stock_not_in_count")
    g = d.groupby("period")
    out = pd.DataFrame({"tier_a_products_selling": g.sold.sum(), "selling_but_missing_from_count": g.sold_missing.sum(),
                        "stock_limited": g.stock_limited.apply(lambda x: int(x.fillna(False).sum())),
                        "product_months": g.size()})
    out["missing_share_pct"] = out.selling_but_missing_from_count / out.tier_a_products_selling * 100
    out["stock_limited_pct"] = out.stock_limited / out.product_months * 100
    rows = snap[(snap.is_demo == False) & snap.fill_source.isna()].set_index("_period").rows  # noqa: E712
    out["all_unilever_rows_in_count"] = out.index.map(rows)
    out["count_note"] = out.index.map(lambda p: COUNT_NOTES.get(p, ""))
    return out.reset_index()


def coverage(lab_test: pd.DataFrame, tag: str) -> list:
    out = []
    for name, m in [("both sides", lab_test.sides == "both"), ("opening only", lab_test.sides == "opening only"),
                    ("closing only", lab_test.sides == "closing only"), ("no count either side", lab_test.sides == "none")]:
        out.append({"setting": tag, "item": name, "product_months": int(m.sum())})
    nic = (lab_test.opening_src == "stock_not_in_count") | (lab_test.closing_src == "stock_not_in_count")
    out += [{"setting": tag, "item": "a side rests on stock_not_in_count (missing from the count = 0)", "product_months": int(nic.sum())},
            {"setting": tag, "item": "stock-limited label known", "product_months": int(lab_test.stock_limited.notna().sum())},
            {"setting": tag, "item": "stock-limited", "product_months": int(lab_test.stock_limited.fillna(False).sum())},
            {"setting": tag, "item": "stock-limited only because a product was missing from the count",
             "product_months": int((lab_test.stock_limited.fillna(False) & lab_test.limited_only_by_not_in_count).sum())},
            {"setting": tag, "item": "high carryover", "product_months": int(lab_test.high_carryover.fillna(False).sum())},
            {"setting": tag, "item": "can't tell (no label)", "product_months": int(lab_test.stock_limited.isna().sum())}]
    return out


# --------------------------------------------------------------------------- #
def main():
    window = sys.argv[sys.argv.index("--window") + 1] if "--window" in sys.argv else "six_months"
    use_window(window)
    out_dir = os.path.join(HERE, window)
    os.makedirs(out_dir, exist_ok=True)
    tier, recs, series, fc, bt, common, repro = rebuild(window)
    dims = read("product_dimension_tierA.csv", dtype={"sku_code": str})
    real_periods, pcs = stock_pieces()
    lab = labels(series, real_periods, pcs)

    test = bt[bt.month.isin(TEST)].copy()
    price = prices(test)
    p = test.merge(lab.drop(columns=["actual"]), on=["product_key", "month"], how="left")
    p["price"] = p.product_key.map(price)
    lb = look_back(bt)
    p = p.merge(lb, on=["product_key", "month"], how="left")
    rl = [level_ratio(series[k], prev_month(m)) for k, m in zip(p.product_key, p.month)]
    p["collapse_ratio"] = [r[0] for r in rl]
    p["last3_before"] = [r[1] for r in rl]
    p["collapse"] = p.collapse_ratio < COLLAPSE_RATIO

    # ---- Part 0 ------------------------------------------------------------- #
    rc = []
    sub = {k: series[k] for k in common}
    cov_rows = []
    for miss in MISSING_SETTINGS:
        for wk in LOW_WEEKS_SENSITIVITY:
            l2 = labels(sub, real_periods, pcs, low_weeks=wk, missing=miss)
            q = test.merge(l2.drop(columns=["actual"]), on=["product_key", "month"], how="left")
            q["price"] = q.product_key.map(price)
            rc += recount(q, f"low stock < {wk:g} wk; {missing_tag(miss)}")
            if wk == LOW_WEEKS:
                cov_rows += coverage(q, missing_tag(miss))
    recount_df = pd.DataFrame(rc)
    cov = pd.DataFrame(cov_rows)
    runs_df, runs_sum = runs_table(p)
    carry = pd.concat([carryover_table(lab, common, None, "all months with a label, 2023-02 to 2026-01"),
                       carryover_table(lab, common, TEST[:-1], f"test window, {ym(TEST[0])} to {ym(TEST[-2])}")],
                      ignore_index=True)
    reasons = p[p.stock_limited.fillna(False)].limited_reason.str.split("; ").explode().value_counts()
    reason_df = by_reason(p)
    comp = completeness(lab, read("stock_snapshots_unilever.csv", dtype={"_period": str}))
    by_month = p.groupby(p.month.map(ym)).agg(product_months=("product_key", "size"),
                                              stock_limited=("stock_limited", lambda x: int(x.fillna(False).sum())),
                                              high_carryover=("high_carryover", lambda x: int(x.fillna(False).sum())))

    # ---- Candidates --------------------------------------------------------- #
    p["fA"] = np.where(p.collapse, np.maximum(0, np.minimum(p.f0, p.last3_before)), p.f0)
    bcols = {}
    for w in WINDOWS:
        on = p[f"same{w}"] >= SAME_SIGN_MIN
        for k in KS:
            adj = np.where(on, np.clip(k * p[f"bias{w}"].fillna(0), -CAP, CAP), 0.0)
            col = f"fB_k{k:g}_w{w}"
            p[col] = np.maximum(0.0, p.f0 * (1 - adj))
            bcols[f"B k={k:g}, {w}-month bias"] = col
    e_df, e_info = run_e(fc.pool, p, lab)
    p = p.merge(e_df, on=["product_key", "month"], how="left")
    cands = {"baseline": "f0", "A collapse cap": "fA", **bcols}
    pre = compare(p, cands, "all test months")
    allb = pre[(pre.scope == "all") & pre.candidate.str.startswith("B ")]
    ok = allb[allb.passes_wape]
    best_b = (ok.sort_values("surplus_pesos_per_month").iloc[0] if len(ok)
              else allb.sort_values("median_product_wape_pct").iloc[0]).candidate
    bcol = bcols[best_b]
    p["fC"] = np.where(p.collapse, np.maximum(0, np.minimum(p[bcol], p.last3_before)), p[bcol])
    cands[f"C = A + {best_b}"] = "fC"
    res = compare(p, cands, "all test months")
    nsl = p[p.stock_limited.notna() & ~p.stock_limited.fillna(False)]
    res_e = compare(nsl, {"baseline": "f0", "E1 XGBoost rows excluded": "fE1",
                          "E2 + MA3/TSB on cleaned history": "fE2"}, "non-stock-limited test months only")
    res = pd.concat([res, res_e], ignore_index=True)

    # ---- D: review flag only ------------------------------------------------ #
    p["flag_run"] = p.over_run_before >= RUN_MIN
    p["flag_D"] = p.flag_run | p.collapse
    e0 = p.f0 - p.actual
    p["surplus_pesos"], p["shortage_pesos"] = e0.clip(lower=0) * p.price, (-e0).clip(lower=0) * p.price
    d_rows = []
    for m, g in list(p.groupby(p.month.map(ym))) + [(f"all {len(TEST)} months", p)]:
        f = g[g.flag_D]
        d_rows.append({"month": m, "products": int(g.product_key.nunique()), "flagged": int(len(f)),
                       "flagged_by_run": int(g.flag_run.sum()), "flagged_by_collapse": int(g.collapse.sum()),
                       "flagged_over_forecast_pct": float((f.f0 > f.actual).mean() * 100) if len(f) else np.nan,
                       "unflagged_over_forecast_pct": float((g[~g.flag_D].f0 > g[~g.flag_D].actual).mean() * 100),
                       "flagged_share_of_surplus_pesos_pct": float(f.surplus_pesos.sum() / g.surplus_pesos.sum() * 100),
                       "flagged_share_of_shortage_pesos_pct": float(f.shortage_pesos.sum() / g.shortage_pesos.sum() * 100),
                       "flagged_share_of_sales_pesos_pct": float((f.actual * f.price).sum() / (g.actual * g.price).sum() * 100),
                       "flagged_stock_limited": int(f.stock_limited.fillna(False).sum())})
    d_df = pd.DataFrame(d_rows)

    # ---- Per product -------------------------------------------------------- #
    pp = []
    for k, g in p.groupby("product_key"):
        g = g.sort_values("month")
        r = {"product_key": k, "bin_last_test_month": g.bin.iloc[-1], "months": len(g),
             "stock_limited_months": int(g.stock_limited.fillna(False).sum()),
             "high_carryover_months": int(g.high_carryover.fillna(False).sum()),
             "flag_D_months": int(g.flag_D.sum())}
        for name, col in cands.items():
            r[f"wape_pct[{name}]"] = wape(g.actual, g[col]) * 100
        pp.append(r)
    pp = dims[["product_key", "product_name", "sku_code", "category_path"]].merge(pd.DataFrame(pp), on="product_key")

    # ---- Write -------------------------------------------------------------- #
    write = lambda df, name: df.to_csv(os.path.join(out_dir, name), index=False, float_format="%.4f")
    nm = dims.set_index("product_key")
    keep = ["product_name", "sku_code", "product_key", "bin", "month", "actual", "f0", "price", "opening_weeks",
            "opening_src", "closing_weeks", "closing_src", "sides", "stock_limited", "limited_reason",
            "limited_only_by_not_in_count", "high_carryover", "collapse_ratio", "collapse", "bias3", "same3",
            "bias6", "same6", "over_run_before", "flag_D", "fA", *bcols.values(), "fC", "fE1", "fE2"]
    out = p.assign(product_name=p.product_key.map(nm.product_name), sku_code=p.product_key.map(nm.sku_code),
                   month=p.month.map(ym))[keep].rename(columns={"f0": "baseline", "price": "price_per_piece_sell_vat_inc"})
    # per-product monthly sales and prices are client data (Yuan, 2026-10-03): the per-month table goes to the
    # git-ignored local/<window>/ only; everything committed is aggregates, per-product error summaries and flags
    local_dir = os.path.join(HERE, "local", window)
    os.makedirs(local_dir, exist_ok=True)
    out.sort_values(["product_key", "month"]).to_csv(os.path.join(local_dir, "per_product_month.csv"), index=False,
                                                     float_format="%.4f")
    write(recount_df, "part0_recount.csv")
    write(cov, "part0_coverage.csv")
    write(runs_df.merge(dims[["product_key", "product_name", "sku_code"]], on="product_key")
          [["product_name", "sku_code", "product_key", "run_months", "run_months_stock_limited",
            "run_months_high_carryover", "run_still_open_at_end"]], "part0_overrun_products.csv")
    write(carry, "part0_carryover_next_month.csv")
    write(by_month.reset_index(), "part0_labels_by_month.csv")
    write(reason_df, "part0_stock_limited_by_side.csv")
    write(comp, "part0_count_completeness.csv")
    write(res, "candidates_summary.csv")
    write(d_df, "candidate_D_review_flag.csv")
    write(pp, "per_product_candidates.csv")

    snap = read("stock_snapshots_unilever.csv", dtype={"_period": str})
    real = snap[(snap.is_demo == False) & snap.fill_source.isna()]  # noqa: E712
    gen = snap[~snap.index.isin(real.index)]
    st = read("stock_real_tierA_by_period.csv", dtype={"_period": str})
    piece_vals = np.array(list(pcs.values()))
    other_rows = real[real._period != "2025-05"].rows
    data_facts = {
        "real_count_periods": int(real._period.nunique()), "real_first": real._period.min(), "real_last": real._period.max(),
        "snapshots_per_real_period_max": int(real.groupby("_period").size().max()),
        "generated_snapshots": {fs: {"periods": int(g._period.nunique()), "first": g._period.min(), "last": g._period.max()}
                                for fs, g in gen.groupby("fill_source")},
        "rows_2025_05": int(real[real._period == "2025-05"].rows.iloc[0]),
        "rows_other_real_counts_min_max": [int(other_rows.min()), int(other_rows.max())],
        "tierA_rows_nan_cases": int(st.cases_nan.sum()), "tierA_rows_nan_loose": int(st.loose_nan.sum()),
        "tierA_duplicate_product_periods": int(st.duplicated(["product_key", "_period"]).sum()),
        "tierA_count_rows_zero_or_less_pieces": int((piece_vals <= 0).sum()),
        "products_with_usable_pack_size": int((pd.to_numeric(dims.pack_size, errors="coerce") > 0).sum()),
        "products": int(len(dims))}
    results = {"window": window, "test_months": [ym(TEST[0]), ym(TEST[-1]), len(TEST)],
               "recorded_decisions": {"threshold": f"remove >= {SURPLUS_CUT_MIN_PCT:g}% of surplus pesos over the 29-month window "
                                                   "and add no more shortage than it removes", "counts": COUNT_NOTES},
               "data_facts": data_facts,
               "halves": [[ym(h[0]), ym(h[-1])] for h in HALVES], "bin_rule": WINDOW_SPEC[window]["bin_rule"],
               "reproduction": repro, "common_products": len(common),
               "test_product_months": int(len(p)), "prices_missing": int(p.price.isna().sum()),
               "stock_periods_real": sorted(real_periods),
               "labels_test": {"stock_limited": int(p.stock_limited.fillna(False).sum()),
                               "stock_limited_unknown": int(p.stock_limited.isna().sum()),
                               "high_carryover": int(p.high_carryover.fillna(False).sum()),
                               "reasons": reasons.to_dict()},
               "overrun_3plus": runs_sum, "best_B": best_b, "E": e_info,
               "rows_changed": {name: {"product_months": int((p[col] - p.f0).abs().gt(1e-9).sum()),
                                       "products": int(p[(p[col] - p.f0).abs().gt(1e-9)].product_key.nunique())}
                                for name, col in {**cands, "E1": "fE1", "E2": "fE2"}.items()},
               "baseline_check": {"over": int((e0 > 0).sum()), "under": int((e0 < 0).sum()),
                                  "surplus_pesos_per_month": float(p.surplus_pesos.sum() / len(TEST)),
                                  "shortage_pesos_per_month": float(p.shortage_pesos.sum() / len(TEST))}}
    with open(os.path.join(out_dir, "results.json"), "w") as fh:
        json.dump(results, fh, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    print(json.dumps(results, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
    pd.set_option("display.width", 250)
    print(recount_df.to_string())
    print(cov.to_string())
    print(carry.to_string())
    print(by_month.to_string())
    print(reason_df.to_string())
    print(comp.to_string())
    cols = ["candidate", "scope", "rows", "products", "product_months", "median_product_wape_pct", "median_product_wape_pct_change",
            "total_wape_pct", "signed_bias_pct", "surplus_pesos_per_month", "surplus_cut_pct", "shortage_pesos_per_month_change",
            "products_better", "products_worse", "h1_surplus_change_pesos_per_month", "h2_surplus_change_pesos_per_month",
            "h1_median_wape_change_pts", "h2_median_wape_change_pts", "meets_decision_rule"]
    print(res[res.scope == "all"][cols].to_string())
    print(d_df.to_string())


if __name__ == "__main__":
    main()
