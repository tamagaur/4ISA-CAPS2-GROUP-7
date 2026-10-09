"""
Model audit 2026-10-03, Part 4 QUICK CHECKS (each under 10 minutes; timed). Offline: inputs/ + run_audit.py's
cached served backtest (local/served_backtest.pkl). Nothing here is a model decision: every result is
exploratory, on the same 29 months the served design was chosen on, unless a check says it holds months out.

Same products (107, Tier A as of 2026-02) and months (2023-10..2026-02) as the ~27% figure unless stated.
"XGBoost alone" is scored on every product-month where it gives a number (all bins), so the objective/pool
effect is visible on more than the 759 long-bin rows. "long average" = what the long bin would serve:
(XGBoost + MA3) / 2 with the router's guards (router.py:109-121).

Rules fixed before computing:
  Q1 objectives   absolute error (served), squared error, Poisson, Tweedie (variance power 1.5). Poisson and
                  Tweedie need labels >= 0, so negative scaled targets are clipped to 0 for those two only.
                  Everything else as served (global_model.PARAMS, 300 rounds, seed, Tier A pool).
  Q2 blend weight w x XGBoost + (1 - w) x MA3, w in {0, .25, .5, .75, 1}; same guards. w is CHOSEN on test months
                  2023-10..2024-12 (lowest median product WAPE, rows where XGBoost exists) and CONFIRMED on
                  2025-01..2026-02, which the choice never saw.
  Q3 look-ahead   XGBoost pool: Tier A as of 2026-02 (served) vs Tier A as of the month before each forecast
                  month (no look-ahead) vs every real Unilever product. Scored cohort: the fixed 107 vs Tier A as
                  of the month before each test month (ABC 'single', known at forecast time).
  Q4 calendar     factor(T) = average over EARLIER years of [company total in T's calendar month / average of
                  the 3 months before it]; company total = all real Unilever products. Forecast x factor.
                  No fitted parameter. Needs a ratio one year back, so rows start 2024-04.
  paired interval = 95% bootstrap over products of the change in median product WAPE (2,000 draws, seed 20261003)

    ../Capstone-Project/.venv/Scripts/python.exe reports/diagnostics/model_audit_2026-10-03/quick_checks.py
"""
from __future__ import annotations

import json
import os
import time

import numpy as np
import pandas as pd

import common as C
import analytics.forecasting.global_model as gm

SEED = 20261003
MB = pd.offsets.MonthBegin(1)
OUT: dict = {}


def ym(ts) -> str:
    return pd.Timestamp(ts).strftime("%Y-%m")


def write(df, name):
    df.to_csv(os.path.join(C.HERE, name), index=False, float_format="%.4f")


def hist_max(series, bt) -> np.ndarray:
    out = []
    for k, m in zip(bt.product_key, bt.month):
        h = gm.from_first_sale(series[k][series[k].index < m])
        out.append(float(h.max()) if len(h) else np.nan)
    return np.asarray(out)


def guarded(value: np.ndarray, ma3_raw: np.ndarray, hmax: np.ndarray) -> np.ndarray:
    """router.py:109-122: no XGBoost -> MA3; above historical max or below 0 -> MA3; served MA3 floored at 0."""
    v = np.where(np.isnan(value), np.nan, value)
    bad = np.isnan(v) | (v > hmax) | (v < 0)
    return np.where(bad, np.maximum(ma3_raw, 0.0), v)


def scores(df: pd.DataFrame, col: str) -> dict:
    a = df.actual.abs().sum()
    return {"rows": len(df), "products": df.product_key.nunique(),
            "median_product_wape": float(C.per_product_wape(df, col).median()),
            "pooled_wape": float((df[col] - df.actual).abs().sum() / a),
            "bias_pct": float((df[col] - df.actual).sum() / a * 100)}


def versus(df, base_col, alt_col, rng) -> dict:
    d, lo, hi, better, worse = C.paired_ci(C.per_product_wape(df, base_col), C.per_product_wape(df, alt_col), rng)
    return {"median_wape_change": d, "ci_low": lo, "ci_high": hi, "products_better": better, "products_worse": worse}


def main():
    rng = np.random.default_rng(SEED)
    series, d, dims, tier_a = C.load()
    coh = C.cohort_107()
    bt = pd.read_pickle(os.path.join(C.LOCAL, "served_backtest.pkl"))
    bt["hmax"] = hist_max(series, bt)
    pool132 = {k: series[k] for k in tier_a}
    t_tab = time.time()
    tab132 = C.feature_table(pool132)
    OUT["feature_table_132_seconds"] = round(time.time() - t_tab, 1)

    # ------------------------------------------------------------------ Q1 objectives
    t0 = time.time()
    variants = {"absoluteerror (served)": ({}, None), "squarederror": ({"objective": "reg:squarederror"}, None),
                "poisson": ({"objective": "count:poisson"}, 0.0),
                "tweedie_1.5": ({"objective": "reg:tweedie", "tweedie_variance_power": 1.5}, 0.0)}
    xs = {}
    for name, (over, floor) in variants.items():
        ff = C.FastForecaster(pool132, tab132, params={**gm.PARAMS, **over}, label_floor=floor)
        xs[name] = C.xgb_all(series, coh, C.TEST_MONTHS, ff).set_index(["product_key", "month"]).xgb
    q = bt.set_index(["product_key", "month"]).join(pd.DataFrame(xs)).reset_index()
    served_long = q[q.bin == "long"]
    gap = float((guarded(((served_long["absoluteerror (served)"] + served_long.ma3_raw) / 2).to_numpy(),
                         served_long.ma3_raw.to_numpy(), served_long.hmax.to_numpy()) - served_long["value"]).abs().max())
    if gap > 1e-9:
        raise SystemExit(f"Q1: served objective does not reproduce the served long-bin forecast: {gap}")
    allx = q.dropna(subset=list(variants))
    rows = []
    for name in variants:
        q[f"avg_{name}"] = guarded(((q[name] + q.ma3_raw) / 2).to_numpy(), q.ma3_raw.to_numpy(), q.hmax.to_numpy())
        lg = q[q.bin == "long"]
        rows.append({"objective": name, "scope": "XGBoost alone, every bin", **scores(allx, name),
                     **{f"vs_served_{k}": v for k, v in versus(allx, "absoluteerror (served)", name, rng).items()}})
        rows.append({"objective": name, "scope": "long average (served design)", **scores(lg, f"avg_{name}"),
                     **{f"vs_served_{k}": v for k, v in versus(lg, "avg_absoluteerror (served)", f"avg_{name}", rng).items()},
                     **{f"vs_ma3_{k}": v for k, v in versus(lg, "ma3", f"avg_{name}", rng).items()}})
    rows.append({"objective": "MA3 (benchmark)", "scope": "XGBoost alone, every bin (same rows)", **scores(allx, "ma3")})
    rows.append({"objective": "MA3 (benchmark)", "scope": "long average (served design) (same rows)",
                 **scores(q[q.bin == "long"], "ma3")})
    write(pd.DataFrame(rows), "q1_xgb_objective.csv")
    OUT["Q1_seconds"] = round(time.time() - t0, 1)
    OUT["Q1_negative_training_labels_clipped_for_poisson_tweedie"] = int((tab132.y < 0).sum())
    OUT["Q1_training_rows_latest"] = int((tab132.month < C.LAST_MONTH).sum())

    # ------------------------------------------------------------------ Q2 blend weight
    t0 = time.time()
    xg = q.dropna(subset=["absoluteerror (served)"]).copy()
    weights = (0.0, 0.25, 0.5, 0.75, 1.0)
    for w in weights:
        xg[f"w{w}"] = guarded((w * xg["absoluteerror (served)"] + (1 - w) * xg.ma3_raw).to_numpy(),
                              xg.ma3_raw.to_numpy(), xg.hmax.to_numpy())
    sel = xg[xg.month <= "2024-12-01"]
    conf = xg[xg.month >= "2025-01-01"]
    conf_long = conf[conf.bin == "long"]
    rows = []
    for w in weights:
        for lab, part in (("choose: 2023-10..2024-12, every bin", sel), ("confirm: 2025-01..2026-02, every bin", conf),
                          ("confirm: 2025-01..2026-02, long bin only", conf_long), ("all 29 months (in-sample)", xg)):
            rows.append({"weight_on_xgboost": w, "window": lab, **scores(part, f"w{w}")})
    wt = pd.DataFrame(rows)
    chosen = float(wt[wt.window.str.startswith("choose")].sort_values("median_product_wape").weight_on_xgboost.iloc[0])
    OUT["Q2"] = {"chosen_weight_on_selection_months": chosen,
                 "confirm_chosen_vs_half": versus(conf, "w0.5", f"w{chosen}", rng),
                 "confirm_chosen_vs_ma3": versus(conf, "w0.0", f"w{chosen}", rng),
                 "confirm_long_chosen_vs_half": versus(conf_long, "w0.5", f"w{chosen}", rng),
                 "seconds": round(time.time() - t0, 1)}
    write(wt, "q2_blend_weight.csv")

    # ------------------------------------------------------------------ Q3 look-ahead in pool and cohort
    t0 = time.time()
    abc = C.read("abc_single_history.csv", dtype={"classification_period": str})
    tier_by = abc[abc.tier == "A"].groupby("classification_period").product_key.apply(set).to_dict()

    def asof(T):
        return tier_by.get(ym(T - MB), set())
    t_all = time.time()
    tab_all = C.feature_table(series)
    OUT["feature_table_all_seconds"] = round(time.time() - t_all, 1)
    pools = {"Tier A as of 2026-02 (served)": C.FastForecaster(series, tab_all, pool_at=lambda T: set(tier_a)),
             "Tier A as of the month before (no look-ahead)": C.FastForecaster(series, tab_all, pool_at=asof),
             "every real Unilever product": C.FastForecaster(series, tab_all)}
    px = {n: C.xgb_all(series, coh, C.TEST_MONTHS, f).set_index(["product_key", "month"]).xgb for n, f in pools.items()}
    p = bt.set_index(["product_key", "month"]).join(pd.DataFrame(px)).reset_index()
    chk = float((p["Tier A as of 2026-02 (served)"] - q["absoluteerror (served)"]).abs().max())
    if chk > 1e-9:
        raise SystemExit(f"Q3: filtered all-product table does not reproduce the served pool: {chk}")
    pall = p.dropna(subset=list(pools))
    rows = []
    for n in pools:
        p[f"avg_{n}"] = guarded(((p[n] + p.ma3_raw) / 2).to_numpy(), p.ma3_raw.to_numpy(), p.hmax.to_numpy())
        lg = p[p.bin == "long"]
        rows.append({"pool": n, "scope": "XGBoost alone, every bin", **scores(pall, n),
                     **{f"vs_served_pool_{k}": v for k, v in versus(pall, "Tier A as of 2026-02 (served)", n, rng).items()}})
        rows.append({"pool": n, "scope": "long average", **scores(lg, f"avg_{n}"),
                     **{f"vs_served_pool_{k}": v for k, v in
                        versus(lg, "avg_Tier A as of 2026-02 (served)", f"avg_{n}", rng).items()}})
    rows[0]["training_rows_at_2026_02"] = pools["Tier A as of 2026-02 (served)"].booster_for(C.LAST_MONTH)[1]
    rows[2]["training_rows_at_2026_02"] = pools["Tier A as of the month before (no look-ahead)"].booster_for(C.LAST_MONTH)[1]
    rows[4]["training_rows_at_2026_02"] = pools["every real Unilever product"].booster_for(C.LAST_MONTH)[1]
    write(pd.DataFrame(rows), "q3_pool_lookahead.csv")
    OUT["Q3_pool_seconds"] = round(time.time() - t0, 1)

    # scored cohort chosen at forecast time
    t0 = time.time()
    fc = pools["Tier A as of the month before (no look-ahead)"]
    parts = []
    for T in C.TEST_MONTHS:
        ks = sorted(k for k in asof(T) if k in series)
        parts.append(C.backtest(series, ks, [T], fc))
    ca = pd.concat(parts, ignore_index=True)
    rows = [{"cohort": "fixed 107 (Tier A as of 2026-02), served pool", "model": "served", **scores(bt, "value")},
            {"cohort": "fixed 107 (Tier A as of 2026-02), served pool", "model": "MA3", **scores(bt, "ma3")},
            {"cohort": "Tier A as of the month before each test month, no-look-ahead pool", "model": "served",
             **scores(ca, "value")},
            {"cohort": "Tier A as of the month before each test month, no-look-ahead pool", "model": "MA3",
             **scores(ca, "ma3")}]
    tierA_rows = sum(len(asof(T)) for T in C.TEST_MONTHS)
    rows[2]["tier_a_product_months"] = rows[3]["tier_a_product_months"] = tierA_rows
    rows[2]["not_scored_insufficient_or_no_row"] = rows[3]["not_scored_insufficient_or_no_row"] = tierA_rows - len(ca)
    # where the gap comes from: the extra products, or products scored on only a few months
    nmonths = ca.groupby("product_key").size()
    ca["in_fixed_107"] = ca.product_key.isin(coh)
    ca["scored_12_plus_months"] = ca.product_key.map(nmonths >= 12)
    for lab, part in (("as-of cohort: products also in the fixed 107", ca[ca.in_fixed_107]),
                      ("as-of cohort: products NOT in the fixed 107", ca[~ca.in_fixed_107]),
                      ("as-of cohort: products scored 12+ months", ca[ca.scored_12_plus_months]),
                      ("as-of cohort: products scored under 12 months", ca[~ca.scored_12_plus_months])):
        for model, col in (("served", "value"), ("MA3", "ma3")):
            rows.append({"cohort": lab, "model": model, **scores(part, col)})
    ca.assign(month=ca.month.map(ym)).to_csv(os.path.join(C.LOCAL, "asof_cohort_backtest.csv"), index=False)
    write(pd.DataFrame(rows), "q3_cohort_lookahead.csv")
    OUT["Q3_cohort_seconds"] = round(time.time() - t0, 1)
    OUT["Q3_cohort_served_minus_ma3_median_wape"] = {
        "fixed_107": rows[0]["median_product_wape"] - rows[1]["median_product_wape"],
        "as_of_cohort": rows[2]["median_product_wape"] - rows[3]["median_product_wape"]}

    # ------------------------------------------------------------------ Q4 company calendar factor
    t0 = time.time()
    total = pd.concat(list(series.values()), axis=1).sum(axis=1).sort_index()
    total = total[(total.index >= "2023-01-01") & (total.index <= C.LAST_MONTH)]
    ratio = (total / total.rolling(3).mean().shift(1)).dropna()          # first: 2023-04

    def factor(T):
        prev = [ratio[T - pd.DateOffset(years=y)] for y in (1, 2, 3) if (T - pd.DateOffset(years=y)) in ratio.index]
        return (float(np.mean(prev)), len(prev)) if prev else (np.nan, 0)
    fac = {T: factor(T) for T in C.TEST_MONTHS}
    c4 = bt.assign(factor=bt.month.map(lambda T: fac[T][0]), years_used=bt.month.map(lambda T: fac[T][1]))
    c4 = c4[c4.factor.notna()].copy()
    c4["ma3_x_factor"] = c4.ma3 * c4.factor
    c4["served_x_factor"] = c4.value * c4.factor
    rows = []
    for lab, part in (("all rows with a factor (2024-04..2026-02)", c4),
                      ("2024-04..2025-02 (1 year back)", c4[c4.month <= "2025-02-01"]),
                      ("2025-03..2026-02 (1-2 years back)", c4[c4.month >= "2025-03-01"])):
        for base, alt in (("ma3", "ma3_x_factor"), ("value", "served_x_factor")):
            rows.append({"window": lab, "forecast": "MA3" if base == "ma3" else "served",
                         **{f"plain_{k}": v for k, v in scores(part, base).items()},
                         **{f"x_factor_{k}": v for k, v in scores(part, alt).items() if k not in ("rows", "products")},
                         **versus(part, base, alt, rng)})
    write(pd.DataFrame(rows), "q4_calendar_factor.csv")
    write(pd.DataFrame([{"month": ym(T), "factor": f, "years_used": n} for T, (f, n) in fac.items()]),
          "q4_calendar_factor_by_month.csv")
    OUT["Q4_seconds"] = round(time.time() - t0, 1)

    with open(os.path.join(C.HERE, "quick_checks_results.json"), "w") as fh:
        json.dump(OUT, fh, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    print(json.dumps(OUT, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o)))


if __name__ == "__main__":
    main()
