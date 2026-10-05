"""
Model audit 2026-10-03, Parts 1 (correctness) and 3 (leftover patterns). Offline: reads inputs/ only.

Scope: Unilever, real rows only (Unilever_SKU_Demand_Fact_Real, is_demo = false; generated rows carry
is_demo = true and a fill_source tag and never reach the view). Scored set = the 107 products of the
29-month figure (Tier A as of 2026-02, ABC 'single'), test months 2023-10..2026-02, one month ahead,
quantities in pieces. "served" = the router's forecast (route()); "MA3" = 3-month average benchmark.

Rules fixed before computing:
  error e        = forecast - actual (pieces); + = over-forecast (surplus), - = under (shortage)
  WAPE           = sum|e| / sum|actual| (diagnostic_metrics.wape); "pooled" = over all rows of a group;
                   "median product WAPE" = median over products of each product's own WAPE (the ~27%)
  bias %         = sum e / sum|actual| x 100 (run_followups.py:142)
  scaled error z = e / (product's mean |actual| over its scored months), so products of any size compare
  volume tercile = terciles of the 107 products' mean |actual| over their scored months
  noise yardstick for residual autocorrelation: MA3's one-step error on pure noise (independent months
                   around a fixed level) has lag-1 autocorrelation -1/12 = -0.083 (derivation in README)
  level-shift event at month t: mean(actual t..t+2) / mean(actual t-3..t-1) < 0.5 (collapse) or > 2 (surge);
                   uses future months, so it is a diagnostic label only, never a forecast input
  shuffle nulls  : 1,000 permutations, seed 20261003

    ../Capstone-Project/.venv/Scripts/python.exe reports/diagnostics/model_audit_2026-10-03/run_audit.py
"""
from __future__ import annotations

import json
import os
import time

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.diagnostic import acorr_ljungbox

import common as C
import analytics.forecasting.global_model as gm
from analytics.forecasting.diagnostic_metrics import mase, naive_scale, wape
from analytics.forecasting.router import route

SEED = 20261003
N_SHUFFLE = 1000
MB = pd.offsets.MonthBegin(1)
OUT: dict = {}


def ym(ts) -> str:
    return pd.Timestamp(ts).strftime("%Y-%m")


def write(df: pd.DataFrame, name: str, local: bool = False):
    path = os.path.join(C.LOCAL if local else C.HERE, name)
    df.to_csv(path, index=False, float_format="%.4f")


def group_stats(df: pd.DataFrame, by, extra: dict | None = None) -> pd.DataFrame:
    """Pooled WAPE and bias for served and MA3 per group, plus row/product counts."""
    rows = []
    for key, g in df.groupby(by, observed=True):
        a = g.actual.abs().sum()
        r = {**(dict(zip(by, key)) if isinstance(by, list) else {by: key}),
             "product_months": len(g), "products": g.product_key.nunique(),
             "wape_served": (g.value - g.actual).abs().sum() / a, "wape_ma3": (g.ma3 - g.actual).abs().sum() / a,
             "bias_pct_served": (g.value - g.actual).sum() / a * 100, "bias_pct_ma3": (g.ma3 - g.actual).sum() / a * 100,
             "mean_z_served": g.z_served.mean(), "share_over_served": float((g.value > g.actual).mean())}
        if extra:
            r.update({k: f(g) for k, f in extra.items()})
        rows.append(r)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Part 1
# --------------------------------------------------------------------------- #
def leakage_perturbation(series, pool_keys, coh, rng) -> pd.DataFrame:
    """Scramble every month >= T (the month being forecast and all later ones) in every series and in
    the XGBoost pool; a forecast for T that changes means it read the month or the future."""
    base = gm.GlobalForecaster({k: series[k] for k in pool_keys})
    rows = []
    for T in (pd.Timestamp("2024-06-01"), pd.Timestamp("2025-03-01"), pd.Timestamp("2026-01-01")):
        pert = {}
        for k in set(pool_keys) | set(coh):
            s = series[k].copy()
            fut = s.index >= T
            s[fut] = s[fut] * rng.uniform(0, 3, fut.sum()) + rng.normal(0, 100, fut.sum())
            pert[k] = s
        fc = gm.GlobalForecaster({k: pert[k] for k in pool_keys})
        d = {"value": [], "ma3": [], "tsb": [], "xgb_component": [], "xgb_any_bin": [], "bin": 0, "n": 0}
        for k in coh:
            s = series[k]
            if T not in s.index or not T > s.index[0]:
                continue
            a, b = route(s, T, base), route(pert[k], T, fc)
            d["n"] += 1
            d["bin"] += a["bin"] != b["bin"]
            if a["value"] is not None:
                d["value"].append(abs(a["value"] - b["value"]))
            d["ma3"].append(abs(a["ma3_value"] - b["ma3_value"]))
            if "tsb" in a["components"]:
                d["tsb"].append(abs(a["components"]["tsb"] - b["components"]["tsb"]))
            if a["components"].get("xgb") is not None:
                d["xgb_component"].append(abs(a["components"]["xgb"] - b["components"]["xgb"]))
            xa, xb = base.forecast(s, T)[0], fc.forecast(pert[k], T)[0]
            if xa is not None:
                d["xgb_any_bin"].append(abs(xa - xb))
        rows.append({"target_month": ym(T), "products": d["n"], "bin_changed": d["bin"],
                     "training_rows_base": base.booster_for(T)[1], "training_rows_perturbed": fc.booster_for(T)[1],
                     **{f"max_abs_change_{k}": (max(v) if v else np.nan) for k, v in d.items() if isinstance(v, list)},
                     **{f"n_{k}": len(v) for k, v in d.items() if isinstance(v, list)}})
    return pd.DataFrame(rows)


def independent_bins(bt: pd.DataFrame, series) -> pd.DataFrame:
    """Bin re-derived without router code: months with sales > 0 from the first sale up to the month
    before; and the same thresholds on calendar months since the first sale."""
    def lab(n):
        return "insufficient" if n < 3 else "short" if n < 12 else "medium" if n < 24 else "long"
    sm, cm, cens = [], [], []
    for k, m in zip(bt.product_key, bt.month):
        h = series[k][series[k].index < m].to_numpy(dtype=float)
        first = np.flatnonzero(h > 0)
        h = h[first[0]:] if first.size else h
        sm.append(int((h > 0).sum()))
        cm.append(len(h))
    out = bt.assign(sales_months_indep=sm, calendar_months=cm)
    out["bin_indep"] = out.sales_months_indep.map(lab)
    out["bin_calendar"] = out.calendar_months.map(lab)
    return out


def part1(series, d, dims, tier_a, coh, bt, rng) -> pd.DataFrame:
    abc = C.read("abc_single_history.csv", dtype={"classification_period": str})
    tier_by_period = abc[abc.tier == "A"].groupby("classification_period").product_key.apply(set).to_dict()
    first_row = d.groupby("product_key").calendar_month.min()
    last_row = d.groupby("product_key").calendar_month.max()
    checks = []

    def check(item, area, result, evidence, value=""):
        checks.append({"item": item, "area": area, "result": result, "value": value, "evidence": evidence})

    # 1.1 leakage - perturbation test of the production code path
    t0 = time.time()
    leak = leakage_perturbation(series, tier_a, coh, rng)
    write(leak, "p1_leakage_perturbation.csv")
    worst = float(np.nanmax(leak.filter(like="max_abs_change").to_numpy()))
    OUT["leakage_perturbation"] = {"max_abs_change_any_forecast": worst, "bin_changes": int(leak.bin_changed.sum()),
                                   "seconds": round(time.time() - t0, 1)}
    check("1.1 features/training read only months before the forecast month", "leakage",
          "PASS" if worst == 0 and leak.bin_changed.sum() == 0 else "ISSUE",
          "p1_leakage_perturbation.csv; global_model.py:90,123; router.py:80", f"max change {worst:g} pcs")

    # 1.1/1.2 cohort chosen with the last test month
    bt = bt.assign(tier_a_asof_prev=[k in tier_by_period.get(ym(m - MB), set()) for k, m in zip(bt.product_key, bt.month)])
    by_month = group_stats(bt.assign(month=bt.month.map(ym)), "month",
                           {"tier_a_as_of_previous_month": lambda g: int(g.tier_a_asof_prev.sum())})
    write(by_month, "p3_by_test_month.csv")
    last = by_month[by_month.month == ym(C.LAST_MONTH)].iloc[0]
    other = bt[bt.month < C.LAST_MONTH]
    OUT["cohort_lookahead"] = {
        "share_scored_rows_tier_a_as_of_previous_month": float(bt.tier_a_asof_prev.mean()),
        "bias_pct_served_2026_02": float(last.bias_pct_served), "bias_pct_ma3_2026_02": float(last.bias_pct_ma3),
        "bias_pct_served_other_months": float((other.value - other.actual).sum() / other.actual.abs().sum() * 100),
        "bias_pct_ma3_other_months": float((other.ma3 - other.actual).sum() / other.actual.abs().sum() * 100)}
    check("1.1 cohort and XGBoost pool chosen using 2026-02 sales (the last test month)", "leakage (selection)",
          "ISSUE", "fit_diagnosis run_fit_diagnosis.py:113-120 (ABC_PERIOD '2026-02'); schema.sql:498 ('single' = that "
          "month's revenue); run_baseline_forecast.py:880-881 (pool = Tier A); p3_by_test_month.csv; quick_checks.py Q3",
          f"{bt.tier_a_asof_prev.mean():.1%} of scored rows were Tier A the month before; 2026-02 bias "
          f"{last.bias_pct_served:+.1f}% vs {OUT['cohort_lookahead']['bias_pct_served_other_months']:+.1f}% other months")

    # 1.3 router bins
    rb = independent_bins(bt, series)
    mism = int((rb.bin != rb.bin_indep).sum())
    cal_diff = rb[rb.bin != rb.bin_calendar]
    bins_month = rb.assign(month=rb.month.map(ym)).pivot_table(index="month", columns="bin", values="product_key",
                                                               aggfunc="count", fill_value=0).reset_index()
    eligible = sum(1 for k in coh for m in C.TEST_MONTHS if m in series[k].index and m > series[k].index[0])
    bins_month["insufficient_dropped"] = [
        sum(1 for k in coh if m in series[k].index and m > series[k].index[0]) for m in C.TEST_MONTHS
    ] - bins_month[[c for c in ("short", "medium", "long") if c in bins_month]].sum(axis=1)
    write(bins_month, "p1_router_bins_by_month.csv")
    trans = cal_diff.groupby(["bin", "bin_calendar"]).size().reset_index(name="product_months")
    write(trans, "p1_router_sales_vs_calendar_months.csv")
    OUT["router"] = {"bin_mismatch_vs_independent": mism, "rows": len(rb),
                     "rows_where_calendar_months_bin_differs": len(cal_diff),
                     "products_where_calendar_bin_differs": int(cal_diff.product_key.nunique()),
                     "insufficient_rows_dropped": int(eligible - len(rb)),
                     "first_long_month": ym(rb[rb.bin == "long"].month.min()),
                     "backups_fired": rb.backup_reason.fillna("none").str.split(":").str[0].value_counts().to_dict()}
    check("1.3 each product-month gets the bin its sales-month count gives", "router",
          "PASS" if mism == 0 else "ISSUE", "router.py:52-56,86; bins.py length_v2; p1_router_bins_by_month.csv",
          f"{mism} mismatches in {len(rb)} product-months")
    check("1.3 bin counts months WITH SALES, not months of history", "router (documentation)", "NOTE",
          "router.py:55; DEC-26 says 'sales months'; p1_router_sales_vs_calendar_months.csv",
          f"{len(cal_diff)} product-months ({cal_diff.product_key.nunique()} products) would get another bin on calendar months")
    cens = [k for k in coh if first_row[k] == "2023-01"]
    check("1.3 products on sale before the data starts look 'new' in 2023", "router (edge case)", "ISSUE",
          "build_series (run_baseline_forecast.py:202-204) starts at the first real row; data starts 2023-01; "
          "global_model.py:104 months_history", f"{len(cens)} of {len(coh)} products start 2023-01; no product can "
          f"be 'long' before {OUT['router']['first_long_month']}")

    # 1.3 / 1.4 edge cases
    nul = d[d.quantity_was_null]
    nul_coh = nul[nul.product_key.isin(coh)]
    nul_pool = nul[nul.product_key.isin(tier_a)]
    nul_rows = [{"product_name": dims.set_index("product_key").product_name.get(k), "sku_code": s, "product_key": k,
                 "month": m} for k, s, m in zip(nul_coh.product_key, nul_coh.sku_code, nul_coh.calendar_month)]
    OUT["null_quantity"] = {"product_months_real_view": len(nul), "with_peso_amount": int(nul.net_amount.notna().sum()),
                            "in_tier_a_pool": len(nul_pool), "in_scored_cohort": nul_rows}
    check("1.4 NULL quantity read as 0 pieces", "target/inputs", "ISSUE",
          "run_baseline_forecast.py:189 fillna(0.0) (and fit_diagnosis load_inputs); inputs: count(quantity_sold) < count(*)",
          f"{len(nul)} real product-months ({int(nul.net_amount.notna().sum())} with a peso amount, i.e. a sale "
          f"happened); {len(nul_pool)} in the Tier A pool, {len(nul_coh)} in the scored cohort")
    rv = C.read("real_view_vs_base.csv").iloc[0]
    prov = C.read("provenance.csv")
    check("1.4 generated/filled rows excluded", "target/inputs",
          "PASS" if rv.real_view_rows == rv.base_is_demo_false_rows and rv.base_real_rows_with_fill_source == 0 else "ISSUE",
          "schema.sql:865-866; migration 0038:56-57 (fill_source only on is_demo rows); inputs/real_view_vs_base.csv",
          f"view {int(rv.real_view_rows)} rows = base is_demo=false {int(rv.base_is_demo_false_rows)}; "
          f"real rows with fill_source {int(rv.base_real_rows_with_fill_source)}; excluded is_demo=true rows "
          f"{int(prov[prov.is_demo].rows.sum())} (fill_source synthetic_v2)")
    span = {k: pd.period_range(first_row[k], last_row[k], freq="M") for k in coh}
    present = d[d.product_key.isin(coh)].groupby("product_key").calendar_month.apply(set)
    gaps = [(k, str(p)) for k in coh for p in span[k] if str(p) not in present[k]]
    gaps_in_window = [g for g in gaps if g[1] >= "2023-10"]
    neg = d[(d.product_key.isin(coh)) & (d.quantity < 0)]
    neg_scored = bt[bt.actual < 0]
    check("1.4 months with no row are read as 0 sales (zero-fill)", "target/inputs", "NOTE",
          "run_baseline_forecast.py:204; ETL-gap check finds all 38 months present principal-wide (run log)",
          f"{len(gaps)} cohort product-months zero-filled ({len(gaps_in_window)} in the test window, "
          f"{len({g[0] for g in gaps})} products); 0 real rows have quantity 0")
    check("1.4 negative months (returns > sales)", "target/inputs", "PASS (as documented)",
          "DEC-15; router.py:55 (not a sales month), :122 (served MA3 floored at 0); baseline.py:180-187 (TSB: no-sale "
          "month); global_model.py:90 (in lags/scale); diagnostic_metrics.py:47-51 (|actual| in WAPE)",
          f"{len(neg)} negative product-months in the cohort's history, {len(neg_scored)} scored as actuals; "
          f"all real negative product-months: {int((d.quantity < 0).sum())}")
    nm = dims.product_name.str.upper().str.replace(r"\s+", " ", regex=True).str.strip()
    dup = dims[nm.duplicated(keep=False)].assign(name_norm=nm)
    dup_coh = dup[dup.product_key.isin(coh)]
    check("1.3 product code changes", "router (edge case)", "ISSUE (open, known)",
          "migration 0029 (supersedes_product_key added EMPTY, 19 Unilever pairs await SSM); inputs: 0 populated",
          f"{len(dup)} Unilever products share {dup.name_norm.nunique()} names; {len(dup_coh)} in the cohort: "
          + "; ".join(f"{r.product_name} ({r.sku_code})" for r in dup_coh.itertuples()))
    same = (dup.drop(columns="name_norm").assign(in_cohort=dup.product_key.isin(coh))
            .merge(first_row.rename("first_month"), left_on="product_key", right_index=True)
            .merge(last_row.rename("last_month"), left_on="product_key", right_index=True))
    lead = ["product_name", "sku_code", "product_key"]
    write(same[lead + [c for c in same.columns if c not in lead]], "p1_same_name_products.csv")
    # dead products: Tier A the month before, no row this month or later
    dead = 0
    for m in C.TEST_MONTHS:
        for k in tier_by_period.get(ym(m - MB), set()):
            if k in last_row.index and last_row[k] < ym(m):
                dead += 1
    check("1.3 dead products (stopped selling) are never scored", "router (edge case)", "NOTE",
          "common.backtest = run_followups.py:119 (month must be in the series; series end at the last real row)",
          f"{dead} product-months over 2023-10..2026-02 where a product was Tier A the month before and has no row "
          "that month or later (all Unilever); the 2026-02 cohort has none by construction")
    check("1.4 unit = pieces", "target/inputs", "PASS (code); source not re-opened",
          "DEC-11; schema.sql:458-463", "quantity_sold is the source's reported pieces column")

    # 1.2 backtest fairness
    check("1.2 rolling origin: refit / past-only data at every forecast month", "backtest", "PASS",
          "global_model.py:123 (strict month < target), :138-148 (one booster per target month); router.py:80; "
          "p1_leakage_perturbation.csv", "XGBoost retrained 29 times on months strictly before each one")
    check("1.2 model-per-bin choice and XGBoost settings picked on the months they are scored on", "backtest",
          "ISSUE", "DEC-26 (ARCHITECTURE.md:96) rests on the 2023-10..2026-02 rolling test = the same 29 months; "
          "memory of 2026-09-21 recon: XGBoost scaling/objective chosen after seeing 2025-09..2026-02",
          "MA3's figure carries no such selection; the served figure does (see README)")
    check("1.2 bin thresholds 3/12/24 tuned on test months?", "backtest", "PASS",
          "bins.py:14-15,35 (3 = eligibility gate, 12 = Round-1 cutoff, 24 = two yearly cycles; set before DEC-26)",
          "conventions, not fitted")

    # 1.5 blend
    lb = rb[rb.bin == "long"]
    both = lb[lb.method == "xgb_ma3_avg"]
    gap = float((both.value - (both.xgb + both.ma3_raw) / 2).abs().max()) if len(both) else np.nan
    check("1.5 long bin = (XGBoost + MA3) / 2", "blend", "PASS" if gap < 1e-9 else "ISSUE", "router.py:109",
          f"{len(both)} long product-months served the average; max |served - (xgb+ma3)/2| = {gap:g}; "
          f"{int((lb.method == 'ma3').sum())} long months fell back to MA3")
    check("1.5 blend weight tested?", "blend", "ISSUE (never tuned in the served design)",
          "router.py:109 hard-codes /2; see coverage_map.csv and quick_checks.py Q2", "0.5 fixed")

    # 1.6 scoring
    wp = C.per_product_wape(bt, "value")
    wp2 = bt.groupby("product_key").apply(lambda g: wape(g.actual, g.value), include_groups=False)
    same_rows = int(bt[["value", "ma3", "naive"]].notna().all(axis=1).sum())
    months_pp = bt.groupby("product_key").size()
    check("1.6 WAPE = sum|e| / sum|actual|", "scoring", "PASS" if float((wp - wp2).abs().max()) < 1e-12 else "ISSUE",
          "diagnostic_metrics.py:47-51", f"independent recompute max diff {float((wp - wp2).abs().max()):g}")
    check("1.6 same products and months for served, MA3, naive", "scoring", "PASS" if same_rows == len(bt) else "ISSUE",
          "run_followups.py:118-122,139-141", f"{same_rows} of {len(bt)} rows scored by all three")
    check("1.6 headline is a median of per-product WAPEs over unequal months", "scoring", "NOTE",
          "run_followups.py:156", f"months per product: min {months_pp.min()}, median {int(months_pp.median())}, "
          f"max {months_pp.max()}; a product scored on 3 months counts as much as one on 29")
    # MASE on the 29 months: scale = lag-1 naive MAE of the real months before 2023-10 (fit_diagnosis convention)
    mrows = []
    for k, g in bt.groupby("product_key"):
        s = gm.from_first_sale(series[k][series[k].index < C.TEST_MONTHS[0]])
        sc = naive_scale(s.to_numpy(dtype=float))
        if len(s) >= 2 and sc > 0:
            mrows.append({"product_key": k, "mase_served": mase(g.actual, g.value, sc), "mase_ma3": mase(g.actual, g.ma3, sc)})
    mm = pd.DataFrame(mrows)
    OUT["mase_29m"] = {"products_with_scale": len(mm), "median_served": float(mm.mase_served.median()),
                       "median_ma3": float(mm.mase_ma3.median()), "share_served_below_1": float((mm.mase_served < 1).mean()),
                       "share_ma3_below_1": float((mm.mase_ma3 < 1).mean())}
    check("1.6 MASE", "scoring", "PASS (formula); NOTE (coverage)", "diagnostic_metrics.py:63-83",
          f"defined for {len(mm)} of {len(coh)} products (needs 2+ real months before 2023-10); median served "
          f"{mm.mase_served.median():.3f}, MA3 {mm.mase_ma3.median():.3f}")
    write(pd.DataFrame(checks), "p1_checks.csv")
    return rb


# --------------------------------------------------------------------------- #
# Part 3
# --------------------------------------------------------------------------- #
def lag1_pairs(df: pd.DataFrame, col: str) -> tuple[np.ndarray, np.ndarray]:
    df = df.sort_values(["product_key", "month"])
    prev = df.groupby("product_key")[col].shift(1)
    consecutive =(df.month - df.groupby("product_key").month.shift(1)).dt.days.between(28, 31)
    ok = prev.notna() & consecutive
    return df[col][ok].to_numpy(), prev[ok].to_numpy()


def shuffle_within(df: pd.DataFrame, col: str, rng) -> pd.Series:
    key = rng.random(len(df))
    order = df.assign(_k=key).sort_values(["product_key", "_k"]).index
    out = df[col].copy()
    out.loc[df.sort_values(["product_key", "month"]).index] = df.loc[order, col].to_numpy()
    return out


def add_errors(bt: pd.DataFrame) -> pd.DataFrame:
    df = bt.copy()
    df["level"] = df.product_key.map(df.groupby("product_key").actual.apply(lambda a: a.abs().mean()))
    df["e_served"], df["e_ma3"] = df.value - df.actual, df.ma3 - df.actual
    df["z_served"], df["z_ma3"] = df.e_served / df.level, df.e_ma3 / df.level
    return df.sort_values(["product_key", "month"]).reset_index(drop=True)


def part3(df: pd.DataFrame, series, dims, coh, rng) -> None:
    level = df.groupby("product_key")["level"].first()

    # calendar month of year
    moy = group_stats(df.assign(month_of_year=df.month.dt.month), "month_of_year")
    kw_s = stats.kruskal(*[g.z_served.to_numpy() for _, g in df.groupby(df.month.dt.month)])
    kw_m = stats.kruskal(*[g.z_ma3.to_numpy() for _, g in df.groupby(df.month.dt.month)])
    write(moy, "p3_by_calendar_month.csv")
    # row-level test: rows in one month share a shock, so this p-value overstates the evidence; the
    # month-level repeatability test below (p3_portfolio_month_effect.csv) is the one to read
    OUT["calendar_month"] = {"kruskal_p_rowlevel_overstated_served": kw_s.pvalue,
                             "kruskal_p_rowlevel_overstated_ma3": kw_m.pvalue}

    # portfolio month effect: the MA3 miss of the COMPANY total (all real Unilever products, known at forecast
    # time), month by month, and whether it repeats in the same calendar month a year later
    total = pd.concat([s for s in series.values()], axis=1).sum(axis=1).sort_index()
    total = total[(total.index >= "2023-01-01") & (total.index <= C.LAST_MONTH)]
    ratio = (total / total.rolling(3).mean().shift(1) - 1).dropna()
    zbar = df.groupby("month").agg(z_served=("z_served", "mean"), z_ma3=("z_ma3", "mean"))
    pme = pd.DataFrame({"total_ma3_miss_pct": -ratio * 100}).join(zbar.rename(columns=lambda c: f"cohort_mean_{c}"))
    pme["total_ma3_miss_pct_same_month_last_year"] = pme.total_ma3_miss_pct.shift(12)
    pme["cohort_mean_z_ma3_same_month_last_year"] = pme.cohort_mean_z_ma3.shift(12)
    rep = {}
    for a, b, lab in (("total_ma3_miss_pct", "total_ma3_miss_pct_same_month_last_year", "company_total"),
                      ("cohort_mean_z_ma3", "cohort_mean_z_ma3_same_month_last_year", "cohort_107")):
        p = pme[[a, b]].dropna()
        r = stats.pearsonr(p[a], p[b])
        rep[lab] = {"pairs": len(p), "first": ym(p.index.min()), "last": ym(p.index.max()), "corr": float(r.statistic),
                    "p_value": float(r.pvalue), "same_sign": int((np.sign(p[a]) == np.sign(p[b])).sum())}
    OUT["portfolio_month_effect_repeats_next_year"] = rep
    write(pme.reset_index(names="month").assign(month=lambda x: x.month.map(ym)), "p3_portfolio_month_effect.csv")

    # volume tercile
    terc = pd.qcut(level, 3, labels=["low", "mid", "high"])
    df["volume_tercile"] = df.product_key.map(terc)
    vt = group_stats(df, "volume_tercile", {
        "median_product_wape_served": lambda g: C.per_product_wape(g, "value").median(),
        "median_product_wape_ma3": lambda g: C.per_product_wape(g, "ma3").median()})
    write(vt, "p3_by_volume_tercile.csv")

    # bin
    write(group_stats(df, "bin", {"median_product_wape_served": lambda g: C.per_product_wape(g, "value").median(),
                                  "median_product_wape_ma3": lambda g: C.per_product_wape(g, "ma3").median()}),
          "p3_by_bin.csv")

    # months since first sale (calendar), split by whether the product was already selling when data starts
    first = {k: gm.from_first_sale(series[k]).index[0] for k in coh}
    df["months_since_first_sale"] = [(m.year - first[k].year) * 12 + m.month - first[k].month
                                     for k, m in zip(df.product_key, df.month)]
    df["age_bucket"] = pd.cut(df.months_since_first_sale, [0, 5, 11, 23, 999], labels=["1-5", "6-11", "12-23", "24+"])
    df["on_sale_before_data"] = df.product_key.map(lambda k: first[k] == pd.Timestamp("2023-01-01"))
    write(group_stats(df, ["on_sale_before_data", "age_bucket"]), "p3_by_months_since_first_sale.csv")

    # residual autocorrelation
    ac_rows = []
    for col in ("z_served", "z_ma3"):
        x, xp = lag1_pairs(df, col)
        r = float(np.corrcoef(x, xp)[0, 1])
        slope = float(np.polyfit(xp, x, 1)[0])
        null = []
        for _ in range(N_SHUFFLE):
            sh = df.assign(_s=shuffle_within(df, col, rng))
            a_, b_ = lag1_pairs(sh, "_s")
            null.append(np.corrcoef(a_, b_)[0, 1])
        # product-cluster bootstrap of the pooled lag-1 correlation
        keys = df.product_key.unique()
        groups = {k: g for k, g in df.groupby("product_key")}
        boot = []
        for _ in range(N_SHUFFLE):
            pick = rng.choice(keys, len(keys))
            bb = pd.concat([groups[k].assign(product_key=i) for i, k in enumerate(pick)])
            a_, b_ = lag1_pairs(bb, col)
            boot.append(np.corrcoef(a_, b_)[0, 1])
        per = []
        lb_sig = 0
        for k, g in df.groupby("product_key"):
            if len(g) >= 12:
                v = g[col].to_numpy()
                per.append(pd.Series(v).autocorr(1))
                lb_sig += bool(acorr_ljungbox(v, lags=[3], return_df=True).lb_pvalue.iloc[0] < 0.05)
        ac_rows.append({"errors_of": "served" if col == "z_served" else "MA3", "pairs": len(x),
                        "pooled_lag1_corr": r, "pooled_lag1_corr_95ci_low": float(np.percentile(boot, 2.5)),
                        "pooled_lag1_corr_95ci_high": float(np.percentile(boot, 97.5)),
                        "slope_this_on_last_month": slope,
                        "shuffle_null_mean": float(np.mean(null)), "shuffle_null_95_low": float(np.percentile(null, 2.5)),
                        "shuffle_null_95_high": float(np.percentile(null, 97.5)),
                        "pure_noise_expectation_ma3": -1 / 12,
                        "products_12plus_months": len(per), "median_product_lag1_acf": float(np.nanmedian(per)),
                        "products_ljung_box_lag3_p_below_0_05": lb_sig})
    write(pd.DataFrame(ac_rows), "p3_autocorrelation.csv")
    # lags 1-3 against MA3's own pure-noise autocorrelation (-1/12, -1/6, -1/4: MA3 errors share months by
    # construction), and the Ljung-Box rejection rate that pure noise gives MA3 errors of the same lengths
    lag_rows = []
    for col in ("z_ma3", "z_served"):
        for L in (1, 2, 3):
            prev = df.groupby("product_key")[col].shift(L)
            gap = (df.month - df.groupby("product_key").month.shift(L)).dt.days
            ok = prev.notna() & gap.between(28 * L, 31 * L)
            lag_rows.append({"errors_of": "MA3" if col == "z_ma3" else "served", "lag": L, "pairs": int(ok.sum()),
                             "pooled_corr": float(np.corrcoef(df[col][ok], prev[ok])[0, 1]),
                             "pure_noise_expectation_ma3": {1: -1 / 12, 2: -1 / 6, 3: -1 / 4}[L]})
    write(pd.DataFrame(lag_rows), "p3_autocorrelation_lags.csv")
    lens = df.groupby("product_key").size()
    lens = lens[lens >= 12]
    rej = []
    for _ in range(200):
        for n in lens:
            y = rng.normal(100, 30, n + 3)
            e = y[3:] - np.convolve(y, np.ones(3) / 3, "valid")[:-1]
            rej.append(acorr_ljungbox(e, lags=[3], return_df=True).lb_pvalue.iloc[0] < 0.05)
    write(pd.DataFrame([{"test": "Ljung-Box lag 3 on MA3 errors of pure noise, same product lengths, 200 draws each",
                         "rejection_rate": float(np.mean(rej)), "products": len(lens),
                         "expected_products_flagged_if_pure_noise": float(np.mean(rej)) * len(lens)}]),
          "p3_ljungbox_null.csv")

    # common month shocks across products
    def month_share(z: pd.Series, months: pd.Series) -> float:
        gm_ = z.groupby(months).transform("mean")
        return float(((gm_ - z.mean()) ** 2).sum() / ((z - z.mean()) ** 2).sum())
    sh_rows = []
    days = {m: int(np.isin(pd.date_range(m, m + pd.offsets.MonthEnd(0)).dayofweek, range(6)).sum()) for m in C.TEST_MONTHS}
    for col, ecol in (("z_served", "e_served"), ("z_ma3", "e_ma3")):
        share = month_share(df[col], df.month)
        null = [month_share(shuffle_within(df, col, rng), df.month) for _ in range(N_SHUFFLE)]
        by_m = df.groupby("month").agg(zbar=(col, "mean"), E=(ecol, "sum"), E2=(ecol, lambda e: (e ** 2).sum()))
        ratio = float(np.sqrt((by_m.E ** 2).mean() / by_m.E2.mean()))
        wd = pd.Series(days).reindex(by_m.index)
        rr = stats.pearsonr(wd, by_m.zbar)
        sh_rows.append({"errors_of": "served" if col == "z_served" else "MA3",
                        "share_of_scaled_error_variance_explained_by_test_month": share,
                        "shuffle_null_mean": float(np.mean(null)), "shuffle_null_95_high": float(np.percentile(null, 97.5)),
                        "total_error_vs_independent_errors_ratio_pcs": ratio,
                        "corr_month_mean_error_vs_mon_sat_days": float(rr.statistic), "p_value": float(rr.pvalue),
                        "months": len(by_m)})
    write(pd.DataFrame(sh_rows), "p3_common_month_shocks.csv")

    # December / January
    dj = df[df.month.dt.month.isin([12, 1])]
    write(group_stats(dj.assign(month=dj.month.map(ym)), "month"), "p3_dec_jan.csv")
    rest = df[~df.month.dt.month.isin([12, 1])]
    OUT["dec_jan"] = {"pooled_wape_served_dec_jan": float(dj.e_served.abs().sum() / dj.actual.abs().sum()),
                      "pooled_wape_served_other": float(rest.e_served.abs().sum() / rest.actual.abs().sum()),
                      "mean_z_served_dec": float(df[df.month.dt.month == 12].z_served.mean()),
                      "mean_z_served_jan": float(df[df.month.dt.month == 1].z_served.mean()),
                      "mean_z_served_other": float(rest.z_served.mean())}

    # level shifts (collapses / surges) and where the error sits
    ev = []
    for k, g in df.groupby("product_key"):
        s = series[k]
        for m in g.month:
            past = [m - MB * i for i in (3, 2, 1)]
            fut = [m + MB * i for i in (0, 1, 2)]
            if all(p in s.index for p in past + fut):
                pm, fm = s.loc[past].mean(), s.loc[fut].mean()
                if pm > 0 and (fm / pm < 0.5 or fm / pm > 2):
                    ev.append((k, m, "collapse" if fm / pm < 0.5 else "surge"))
    evdf = pd.DataFrame(ev, columns=["product_key", "month", "kind"])
    df["after_event"] = "none"
    for k, m, kind in ev:
        sel = (df.product_key == k) & df.month.isin([m, m + MB, m + 2 * MB])
        df.loc[sel & (df.after_event == "none"), "after_event"] = kind
    brk = []
    tot_s, tot_m = df.e_served.abs().sum(), df.e_ma3.abs().sum()
    for kind, g in df.groupby("after_event"):
        brk.append({"window": kind, "product_months": len(g), "share_of_rows": len(g) / len(df),
                    "share_of_abs_error_served": g.e_served.abs().sum() / tot_s,
                    "share_of_abs_error_ma3": g.e_ma3.abs().sum() / tot_m,
                    "pooled_wape_served": g.e_served.abs().sum() / g.actual.abs().sum(),
                    "pooled_wape_ma3": g.e_ma3.abs().sum() / g.actual.abs().sum(),
                    "events": int((evdf.kind == kind).sum()) if kind != "none" else 0,
                    "products_with_event": int(evdf[evdf.kind == kind].product_key.nunique()) if kind != "none" else 0})
    write(pd.DataFrame(brk), "p3_level_shifts.csv")
    p674 = df[df.product_key == 674][["month", "actual", "value", "ma3", "bin", "method"]]
    write(p674.assign(month=p674.month.map(ym)), "product_674_detail.csv", local=True)
    OUT["product_674"] = {"name": dims.set_index("product_key").product_name.get(674),
                          "events": [(ym(m), kd) for k, m, kd in ev if k == 674]}

    # noise yardsticks: two-sided interpolation, local-level floor
    nxt = []
    for k, m in zip(df.product_key, df.month):
        s = series[k]
        a, b = m - MB, m + MB
        nxt.append((s.loc[a] + s.loc[b]) / 2 if a in s.index and b in s.index else np.nan)
    df["two_sided"] = nxt
    ts = df[df.two_sided.notna()]
    ll = []
    for k in coh:
        y = gm.from_first_sale(series[k][series[k].index <= C.LAST_MONTH]).to_numpy(dtype=float)
        dy = np.diff(y)
        if len(dy) < 12:
            continue
        c = dy - dy.mean()
        g0, g1 = float((c ** 2).mean()), float((c[1:] * c[:-1]).mean())
        s_eps = max(-g1, 0.0)
        s_eta = max(g0 - 2 * s_eps, 0.0)
        p_star = (s_eta + np.sqrt(s_eta ** 2 + 4 * s_eta * s_eps)) / 2
        v_opt, v_ma3 = p_star + s_eps, 14 / 9 * s_eta + 4 / 3 * s_eps
        g = df[df.product_key == k]
        act_mse = float((g.e_ma3 ** 2).mean())
        lvl = float(np.abs(y).mean())
        ll.append({"product_key": k, "noise_sd_over_level": np.sqrt(s_eps) / lvl, "level_shift_sd_over_level": np.sqrt(s_eta) / lvl,
                   "best_possible_over_ma3_error_sd": np.sqrt(v_opt / v_ma3) if v_ma3 > 0 else np.nan,
                   "ma3_mse_actual_over_model": act_mse / v_ma3 if v_ma3 > 0 else np.nan,
                   "wape_ma3": C.per_product_wape(g, "ma3").iloc[0], "wape_served": C.per_product_wape(g, "value").iloc[0]})
    ll = pd.DataFrame(ll)
    ll["wape_floor_estimate"] = ll.wape_ma3 * ll.best_possible_over_ma3_error_sd
    noise = pd.DataFrame([{
        "yardstick": "two-sided: average of the month before and the month after (uses the future)",
        "product_months": len(ts), "pooled_wape": ts.two_sided.sub(ts.actual).abs().sum() / ts.actual.abs().sum(),
        "median_product_wape": C.per_product_wape(ts, "two_sided").median(),
        "same_rows_pooled_wape_served": ts.e_served.abs().sum() / ts.actual.abs().sum(),
        "same_rows_median_product_wape_served": C.per_product_wape(ts, "value").median(),
        "same_rows_median_product_wape_ma3": C.per_product_wape(ts, "ma3").median()}, {
        "yardstick": "local-level model (level that drifts + month noise), best possible one-month forecast",
        "product_months": int(df.product_key.isin(ll.product_key).sum()), "products": len(ll),
        "median_noise_sd_over_level": ll.noise_sd_over_level.median(),
        "median_level_shift_sd_over_level": ll.level_shift_sd_over_level.median(),
        "median_best_possible_over_ma3_error_sd": ll.best_possible_over_ma3_error_sd.median(),
        "median_ma3_mse_actual_over_model": ll.ma3_mse_actual_over_model.median(),
        "median_product_wape_floor_estimate": ll.wape_floor_estimate.median(),
        "median_product_wape_ma3": ll.wape_ma3.median(), "median_product_wape_served": ll.wape_served.median()}])
    write(noise, "p3_noise_yardsticks.csv")

    # per product summary (no monthly quantities)
    per = pd.DataFrame({"wape_served": C.per_product_wape(df, "value"), "wape_ma3": C.per_product_wape(df, "ma3"),
                        "wape_naive": C.per_product_wape(df, "naive"),
                        "bias_pct_served": df.groupby("product_key").apply(
                            lambda g: g.e_served.sum() / g.actual.abs().sum() * 100, include_groups=False),
                        "months_scored": df.groupby("product_key").size(),
                        "lag1_acf_served_errors": df.groupby("product_key").z_served.apply(lambda z: z.autocorr(1)),
                        "volume_tercile": terc, "bins_seen": df.groupby("product_key").bin.apply(lambda b: "/".join(sorted(set(b))))})
    per = per.reset_index().merge(ll[["product_key", "noise_sd_over_level", "level_shift_sd_over_level", "wape_floor_estimate"]],
                                  on="product_key", how="left")
    per = dims[["product_key", "product_name", "sku_code", "category_path"]].merge(per, on="product_key")
    per.insert(3, "on_sale_before_data", per.product_key.map(lambda k: first[k] == pd.Timestamp("2023-01-01")))
    write(per[["product_name", "sku_code"] + [c for c in per.columns if c not in ("product_name", "sku_code")]],
          "p3_per_product.csv")
    traces(df, series, dims, ll)
    df["month"] = df.month.map(ym)
    write(df, "backtest_detail.csv", local=True)
    OUT["headline"] = {"products": int(df.product_key.nunique()), "product_months": len(df),
                       "median_product_wape_served": float(per.wape_served.median()),
                       "median_product_wape_ma3": float(per.wape_ma3.median()),
                       "median_product_wape_naive": float(per.wape_naive.median()),
                       "pooled_wape_served": float(df.e_served.abs().sum() / df.actual.abs().sum()),
                       "pooled_wape_ma3": float(df.e_ma3.abs().sum() / df.actual.abs().sum())}


def traces(df: pd.DataFrame, series, dims, ll: pd.DataFrame) -> None:
    """Files behind README statements that are not in the tables above. Ratios and counts only:
    no product's monthly pieces or prices leave local/ (client data rule, 2026-10-03)."""
    name = dims.set_index("product_key")
    # collapse examples: each month as a share of the product's own 2025-06..2025-11 average
    rows = []
    for k in (674, 613):
        s = series[k]
        level = float(s.loc["2025-06-01":"2025-11-01"].mean())
        for _, r in df[(df.product_key == k) & (df.month >= "2025-12-01")].iterrows():
            rows.append({"product_name": name.product_name.get(k), "sku_code": name.sku_code.get(k), "product_key": k,
                         "month": ym(r.month), "bin": r.bin, "served_method": r.method,
                         "actual_over_level": r.actual / level, "served_over_level": r.value / level,
                         "ma3_over_level": r.ma3 / level, "tsb_over_level": r.tsb / level if pd.notna(r.tsb) else np.nan,
                         "level_definition": "average of the product's own 2025-06..2025-11 sales (not shown)"})
    write(pd.DataFrame(rows), "p3_collapse_examples.csv")
    # launched inside the data and 24+ months old: how concentrated the over-forecast is
    g = df[(~df.on_sale_before_data) & (df.age_bucket == "24+")]
    per = g.groupby("product_key").agg(e=("e_served", "sum"))
    top = int(per.e.idxmax())
    h = g[g.after_event == "none"]
    write(pd.DataFrame([{
        "group": "launched inside the data (first sale after 2023-01), 24+ months since first sale",
        "products": len(per), "product_months": len(g), "products_net_over": int((per.e > 0).sum()),
        "bias_pct_served": g.e_served.sum() / g.actual.abs().sum() * 100,
        "top_product_name": name.product_name.get(top), "top_sku_code": name.sku_code.get(top),
        "top_product_share_of_group_net_over_forecast": float(per.e.max() / per.e.sum()),
        "bias_pct_served_without_collapse_or_surge_windows": h.e_served.sum() / h.actual.abs().sum() * 100,
        "product_months_without_collapse_or_surge_windows": len(h)}]), "p3_age24_concentration.csv")
    # TSB on the medium bin vs plain exponential smoothing (weight 0.3) on the same history
    med = df[df.bin == "medium"]
    same, with_zero = 0, 0
    for k, m, t in zip(med.product_key, med.month, med.tsb):
        x = gm.from_first_sale(series[k][series[k].index < m]).to_numpy(dtype=float)
        with_zero += bool((x <= 0).any())
        lvl = x[x > 0].mean()
        for v in x:
            if v > 0:
                lvl += 0.3 * (v - lvl)
        same += abs(t - lvl) <= 1e-9 * max(abs(t), 1.0)
    write(pd.DataFrame([{"medium_bin_product_months": len(med), "tsb_equals_ses_0_3": same,
                         "share_equal": same / len(med), "history_has_a_zero_or_negative_month": with_zero}]),
          "p2_tsb_equals_ses.csv")
    # how large these counts are: product monthly level vs pure count (Poisson) noise
    lv = df.groupby("product_key")["level"].first()
    write(pd.DataFrame([{"products": len(lv), "median_product_mean_monthly_pieces": float(lv.median()),
                         "products_under_400_pieces_a_month": int((lv < 400).sum()),
                         "poisson_noise_sd_over_level_at_median": float(1 / np.sqrt(lv.median())),
                         "observed_noise_sd_over_level_median": float(ll.noise_sd_over_level.median())}]),
          "p2_count_scale.csv")


def main():
    os.makedirs(C.LOCAL, exist_ok=True)
    rng = np.random.default_rng(SEED)
    t0 = time.time()
    series, d, dims, tier_a = C.load()
    coh = C.cohort_107()
    cache = os.path.join(C.LOCAL, "served_backtest.pkl")     # delete to recompute (~30 s)
    if os.path.exists(cache):
        bt = pd.read_pickle(cache)
    else:
        bt = C.backtest(series, coh, C.TEST_MONTHS, gm.GlobalForecaster({k: series[k] for k in tier_a}))
        bt.to_pickle(cache)
    ref = C.eebd("longwindow_per_product_month.csv")
    ref["month"] = pd.to_datetime(ref.month + "-01")
    j = ref.merge(bt, on=["product_key", "month"], how="outer", indicator=True)
    OUT["reproduction"] = {"rows": len(bt), "rows_only_in_eebd741": int((j._merge == "left_only").sum()),
                           "rows_only_here": int((j._merge == "right_only").sum()),
                           "max_abs_forecast_gap_vs_eebd741_csv": float((j.forecast - j.value).abs().max()),
                           "bin_mismatches": int((j.bin_x != j.bin_y).sum())}
    if OUT["reproduction"]["max_abs_forecast_gap_vs_eebd741_csv"] > 1e-4 or OUT["reproduction"]["rows_only_here"]:
        raise SystemExit(f"does not reproduce eebd741: {OUT['reproduction']}")
    rb = part1(series, d, dims, tier_a, coh, add_errors(bt), rng)
    part3(add_errors(rb), series, dims, coh, rng)
    OUT["seconds"] = round(time.time() - t0, 1)
    with open(os.path.join(C.HERE, "audit_results.json"), "w") as fh:
        json.dump(OUT, fh, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    print(json.dumps(OUT, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o)))


if __name__ == "__main__":
    main()
