"""
Forecast error in pieces and pesos - Unilever Tier A as of 2026-02 (ABC 'single', 132 products).
Offline: reads only inputs/ (pull_inputs.py, pull_stock_count.py). Nothing touches the database.

1. Rebuilds the per-product, per-month backtest with the served router (shared harness
   reports/diagnostics/fit_diagnosis_2026-10/run_fit_diagnosis.py) and stops unless it
   reproduces public.forecast_result (pulled copy) AND the committed REAL holdout rows of
   reports/simulation/synthetic_2026-10/series.csv.
2. Error per product per month in pieces and pesos, direction and runs, category/total
   accuracy, demand swing vs error, seasonality reconciliation, collapse flag.

Rules fixed before computing (README.md beside this file):
  error            = forecast - actual (pieces); > 0 over-forecast (surplus), < 0 under (shortage)
  selling price    = sum(net_amount) / sum(pieces) over the product's own test months;
                     net_amount = "Total Sales Amt Inc. Tax" -> at selling price, VAT-inclusive
  cost per piece   = stock count taken 2026-04-06 (period 2026-03): Stock Value / (cases x pack
                     size + loose pieces); no count / zero stock -> "no cost basis", never guessed
  surplus run      = 3+ consecutive over-forecast months (Yuan, 2026-10-03)
  collapse flag    = mean(last 3 months) < 0.5 x mean(last 12 months) (Yuan's example, 2026-10-03)
  STL bands        = >= 0.6 strong, >= 0.3 moderate (frontend/src/components/SkuDemandPatternPanel.jsx:80-83)
  lag-12 test      = |ACF(12)| > 1.96 / sqrt(n), n >= 24 (reports/SEASONALITY_AND_BASELINES.md:13, :28)

    ../Capstone-Project/.venv/Scripts/python.exe reports/diagnostics/forecast_error_business_2026-10-03/run_analysis.py
"""
from __future__ import annotations

import json
import os
import sys
from html import escape

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.tsa.stattools import acf

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "reports", "diagnostics", "fit_diagnosis_2026-10"))

import run_fit_diagnosis as F  # noqa: E402  (the shared served-router harness)
from analytics.forecasting.decomposition import stl_summary  # noqa: E402  (the dashboard's own STL function)
from analytics.forecasting.diagnostic_metrics import wape  # noqa: E402
from analytics.forecasting.global_model import FEATURE_NAMES  # noqa: E402
from analytics.segmentation.traits import coefficient_of_variation  # noqa: E402

INP = os.path.join(HERE, "inputs")
SERIES_CSV = os.path.join(REPO, "reports", "simulation", "synthetic_2026-10", "series.csv")
SEED = 20261003
LAST_MONTH = pd.Timestamp("2026-02-01")
SURPLUS_RUN = 3
COLLAPSE_RATIO = 0.5
COLLAPSE_SENSITIVITY = (0.4, 0.5, 0.6, 0.7)   # 0.7 = lower edge of the recent-level band on record (diagnostics/README.md)
STL_STRONG, STL_MODERATE = 0.6, 0.3
ACF_MIN_MONTHS, ACF_Z = 24, 1.96
N_PERM, N_NOISE = 200, 500
SELL = "at selling price, VAT-inclusive (value-added tax)"

# Client data stays out of git (Yuan, 2026-10-03): per-product sales (monthly or averaged, and anything equal to
# them by construction - last month's sales, the 3-month average) and per-product prices or costs. Full files go
# to local/ (git-ignored by this folder's .gitignore); the committed copies drop these columns, and the per-month
# files are local only. Aggregates, per-product error summaries (pieces / pesos) and flags are committed.
LOCAL = os.path.join(HERE, "local")
LOCAL_ONLY = {"per_product_month.csv", "longwindow_per_product_month.csv"}
CLIENT_COLUMNS = {
    "actual", "naive", "ma3", "mean_actual", "mean_forecast", "ma3_2026_03",
    "last3_months_pcs", "last3_mean", "last12_mean", "recent_avg_last3_pcs", "avg_last12_pcs",
    "price_sell_vat_inc", "cost_per_piece", "gsv_per_piece_sales_file", "cost_over_selling_price",
    "cost_over_sales_gsv_per_piece", "stock_value_over_lpp", "price_months_qty", "price_months_net",
}


def publish(df: pd.DataFrame, name: str, index: bool = False, fmt: str = "%.4f") -> None:
    """Full table to local/ (not committed); the same table minus CLIENT_COLUMNS beside this script."""
    os.makedirs(LOCAL, exist_ok=True)
    df.to_csv(os.path.join(LOCAL, name), index=index, float_format=fmt)
    if name not in LOCAL_ONLY:
        df.drop(columns=[c for c in df.columns if c in CLIENT_COLUMNS]).to_csv(
            os.path.join(HERE, name), index=index, float_format=fmt)


def read(name, **kw):
    return pd.read_csv(os.path.join(INP, name), **kw)


def ym(ts) -> str:
    return pd.Timestamp(ts).strftime("%Y-%m")


# --------------------------------------------------------------------------- #
# 1. Backtest, reproduced
# --------------------------------------------------------------------------- #
def rebuild():
    tier = read("tier_a.csv")
    keys = sorted(tier["product_key"].astype(int))
    demand = read("demand_real_tierA.csv", dtype={"calendar_month": str})
    demand["quantity"] = pd.to_numeric(demand["quantity"], errors="coerce").fillna(0.0)
    live = read("forecast_result_live.csv")
    recs, series, fc = F.run_cohort(demand, keys)
    bad = F.check_against_live(recs, live)
    if bad:
        raise SystemExit(f"does not reproduce forecast_result: {bad[:5]}")
    hold = F.verdict_holdouts(recs, series)
    scored = F.score_holdouts(recs, series, fc, hold)
    rows = []
    for k, df in scored.items():
        s = series[k]
        for r in df.itertuples():
            prev = r.month - pd.offsets.MonthBegin(1)
            rows.append({"product_key": k, "month": r.month, "actual": r.actual, "forecast": r.value,
                         "ma3": r.ma3, "naive": float(s.loc[prev]) if prev in s.index else np.nan,
                         "method": r.method, "backup_fired": r.backup_fired, "bin": recs[k]["bin"],
                         "score_source": hold[k]["source"]})
    bt = pd.DataFrame(rows)
    ref = pd.read_csv(SERIES_CSV)
    ref = ref[(ref.run == "REAL") & (ref.kind == "holdout")]
    ref = ref.assign(month=pd.to_datetime(ref.month + "-01"))[["product_key", "month", "forecast", "actual"]]
    cmp_ = bt.merge(ref, on=["product_key", "month"], how="outer", suffixes=("", "_ref"), indicator=True)
    if (cmp_["_merge"] != "both").any():
        raise SystemExit(f"key mismatch vs series.csv: {cmp_['_merge'].value_counts().to_dict()}")
    gap = float((cmp_.forecast - cmp_.forecast_ref).abs().max())
    gap_a = float((cmp_.actual - cmp_.actual_ref).abs().max())
    if gap > 1e-6 or gap_a > 1e-9:
        raise SystemExit(f"differs from series.csv: forecast {gap}, actual {gap_a}")
    return tier, recs, series, fc, bt, {"live_mismatches": 0, "series_csv_rows": int(len(ref)),
                                        "series_csv_max_forecast_gap": gap}


# --------------------------------------------------------------------------- #
# 2. Prices
# --------------------------------------------------------------------------- #
def prices(bt: pd.DataFrame, dims: pd.DataFrame) -> pd.DataFrame:
    money = read("demand_money_tierA.csv", dtype={"calendar_month": str})
    money["month"] = pd.to_datetime(money.calendar_month + "-01")
    test = bt[["product_key", "month"]].merge(money, on=["product_key", "month"], how="left")
    g = test.groupby("product_key")[["quantity", "net_amount", "gsv"]].sum()
    gsv_missing = test.groupby("product_key").gsv.apply(lambda x: int(x.isna().sum()))
    price = (g.net_amount / g.quantity).where((g.quantity > 0) & (g.net_amount > 0))
    price_gsv = (g.gsv / g.quantity).where((g.quantity > 0) & (g.gsv > 0) & (gsv_missing == 0))
    out = pd.DataFrame({"price_sell_vat_inc": price, "price_months_qty": g.quantity, "price_months_net": g.net_amount,
                        "gsv_per_piece_sales_file": price_gsv})

    sc = read("stock_count_2026-04-06_tierA.csv")
    d = dims[["product_key", "pack_size"]].copy()
    d["pack"] = pd.to_numeric(d.pack_size, errors="coerce")
    sc = sc.merge(d, on="product_key", how="left")
    sc["pieces"] = sc.cases * sc.pack + sc.loose_pieces.fillna(0)
    sc["cost_per_piece"] = (sc.stock_value / sc.pieces).where((sc.pieces > 0) & (sc.stock_value > 0))
    sc["lpp_implied_value"] = (sc.cases + sc.loose_pieces.fillna(0) / sc.pack) * sc.unit_cost_per_case
    sc["stock_value_over_lpp"] = sc.stock_value / sc.lpp_implied_value

    def status(r):
        if pd.isna(r.get("cases")):
            return "no cost basis: not in the 2026-03 stock count (taken 2026-04-06)"
        if pd.isna(r.pack):
            return "no cost basis: pack size missing"
        if not r.pieces > 0:
            return "no cost basis: zero stock in the count"
        if not r.stock_value > 0:
            return "no cost basis: stock value not positive"
        return "ok"
    allp = dims[["product_key"]].merge(sc.drop(columns=["pack_size"]), on="product_key", how="left")
    allp["pack"] = allp["pack"].fillna(allp.product_key.map(d.set_index("product_key").pack))
    allp["cost_status"] = allp.apply(status, axis=1)
    out = out.reindex(dims.product_key)
    out.index.name = "product_key"
    out = out.reset_index().merge(allp[["product_key", "cases", "loose_pieces", "pack", "pieces", "stock_value",
                                        "unit_cost_per_case", "cost_per_piece", "stock_value_over_lpp",
                                        "cost_status"]], on="product_key", how="left")
    out["cost_over_selling_price"] = out.cost_per_piece / out.price_sell_vat_inc
    out["cost_over_sales_gsv_per_piece"] = out.cost_per_piece / out.gsv_per_piece_sales_file
    return out


# --------------------------------------------------------------------------- #
# 3-4. Per month and per product
# --------------------------------------------------------------------------- #
def runs(dirs: list[str]) -> dict:
    longest = {"over": 0, "under": 0}
    cur_dir, cur_len = None, 0
    for d in dirs:
        if d == cur_dir and d != "exact":
            cur_len += 1
        else:
            cur_dir, cur_len = d, (0 if d == "exact" else 1)
        if d in longest:
            longest[d] = max(longest[d], cur_len)
    return {"longest_over_run": longest["over"], "longest_under_run": longest["under"],
            "current_run_direction": cur_dir, "current_run_months": cur_len}


def per_month(bt, px, dims):
    m = bt.merge(px[["product_key", "price_sell_vat_inc", "cost_per_piece", "cost_status"]], on="product_key")
    m = m.merge(dims[["product_key", "product_name", "sku_code", "category_path"]], on="product_key")
    m["error"] = m.forecast - m.actual
    m["abs_error"] = m.error.abs()
    m["direction"] = np.where(m.error > 0, "over", np.where(m.error < 0, "under", "exact"))
    m["abs_error_pesos_sell"] = m.abs_error * m.price_sell_vat_inc
    m["surplus_pieces"] = m.error.clip(lower=0)
    m["shortage_pieces"] = (-m.error).clip(lower=0)
    m["surplus_value_at_cost"] = m.surplus_pieces * m.cost_per_piece
    m["surplus_value_sell"] = m.surplus_pieces * m.price_sell_vat_inc
    m["shortage_value_sell"] = m.shortage_pieces * m.price_sell_vat_inc
    m["month"] = m.month.map(ym)
    cols = ["product_name", "sku_code", "product_key", "category_path", "bin", "method", "score_source", "month",
            "actual", "forecast", "error", "abs_error", "direction", "ma3", "naive", "price_sell_vat_inc",
            "abs_error_pesos_sell", "surplus_pieces", "shortage_pieces", "shortage_value_sell", "surplus_value_sell",
            "cost_per_piece", "surplus_value_at_cost", "cost_status", "backup_fired"]
    return m[cols].sort_values(["product_key", "month"]).reset_index(drop=True)


def per_product(pm, recs, dims, px):
    rows = []
    for k, g in pm.groupby("product_key"):
        g = g.sort_values("month")
        n = len(g)
        r = {"product_key": k, "test_months": n, "test_first": g.month.iloc[0], "test_last": g.month.iloc[-1],
             "score_source": g.score_source.iloc[0],
             "mean_actual": g.actual.mean(), "mean_forecast": g.forecast.mean(),
             "wape": wape(g.actual, g.forecast), "ma3_wape": wape(g.actual, g.ma3),
             "naive_wape": wape(g.actual, g.naive) if g.naive.notna().all() else np.nan,
             "mean_abs_error_pcs": g.abs_error.mean(), "mean_abs_error_pesos_sell": g.abs_error_pesos_sell.mean(),
             "mean_signed_error_pcs": g.error.mean(),
             "bias_pct": g.error.sum() / g.actual.abs().sum() * 100 if g.actual.abs().sum() > 0 else np.nan,
             "pct_months_over": (g.direction == "over").mean() * 100,
             "pct_months_under": (g.direction == "under").mean() * 100,
             "mean_monthly_surplus_at_cost": g.surplus_value_at_cost.mean(),
             "mean_monthly_shortage_sell": g.shortage_value_sell.mean()}
        if n >= 2:
            r.update(runs(list(g.direction)))
            r["surplus_risk_3plus_over"] = r["longest_over_run"] >= SURPLUS_RUN
            r["currently_over_3plus"] = r["current_run_direction"] == "over" and r["current_run_months"] >= SURPLUS_RUN
        else:
            r.update({"longest_over_run": np.nan, "longest_under_run": np.nan,
                      "current_run_direction": "not assessable (1 test month)", "current_run_months": np.nan,
                      "surplus_risk_3plus_over": np.nan, "currently_over_3plus": np.nan})
        rows.append(r)
    s = pd.DataFrame(rows)
    base = dims[["product_key", "product_name", "sku_code", "category_path"]].copy()
    base["status"] = base.product_key.map(lambda k: recs[k]["status"])
    base["bin"] = base.product_key.map(lambda k: recs[k]["bin"])
    base["served_method"] = base.product_key.map(lambda k: recs[k]["method"])
    base["forecast_2026_03"] = base.product_key.map(lambda k: recs[k]["forecast"])
    base["ma3_2026_03"] = base.product_key.map(lambda k: recs[k].get("ma3_value", np.nan))
    out = base.merge(s, on="product_key", how="left").merge(
        px[["product_key", "price_sell_vat_inc", "cost_per_piece", "cost_status"]], on="product_key", how="left")
    out.loc[out.status != "ok", "score_source"] = "not scored: fewer than 3 months with sales (no backtest)"
    return out


# --------------------------------------------------------------------------- #
# 5-6. Monthly totals, category / total accuracy
# --------------------------------------------------------------------------- #
def monthly_totals(pm, source="common"):
    c = pm[pm.score_source == source]
    cost_ok = c.cost_status == "ok"
    g = c.groupby("month")
    t = pd.DataFrame({
        "products": g.product_key.nunique(),
        "abs_error_pcs": g.abs_error.sum(), "actual_pcs": g.actual.sum(),
        "abs_error_pesos_sell": g.abs_error_pesos_sell.sum(),
        "shortage_value_sell": g.shortage_value_sell.sum(),
        "surplus_value_sell": g.surplus_value_sell.sum(),
        "surplus_value_at_cost_costed": c[cost_ok].groupby("month").surplus_value_at_cost.sum(),
        "surplus_value_sell_costed": c[cost_ok].groupby("month").surplus_value_sell.sum(),
        "surplus_value_sell_no_cost_basis": c[~cost_ok].groupby("month").surplus_value_sell.sum(),
        "actual_pesos_sell": (c.actual * c.price_sell_vat_inc).groupby(c.month).sum(),
    }).fillna({"surplus_value_at_cost_costed": 0, "surplus_value_sell_costed": 0,
               "surplus_value_sell_no_cost_basis": 0})
    t.loc["average per month"] = t.mean()
    return t.reset_index()


def aggregate_accuracy(pm, source="common"):
    c = pm[pm.score_source == source].copy()
    c["actual_pesos"] = c.actual * c.price_sell_vat_inc
    c["forecast_pesos"] = c.forecast * c.price_sell_vat_inc
    c["ma3_pesos"] = c.ma3 * c.price_sell_vat_inc
    groups = [(cat, g) for cat, g in c.groupby("category_path")] + [("TOTAL (all categories)", c)]
    rows = []
    for name, g in groups:
        agg = g.groupby("month")[["actual", "forecast", "ma3", "actual_pesos", "forecast_pesos", "ma3_pesos"]].sum()
        prod = g.groupby("product_key").apply(lambda x: wape(x.actual, x.forecast), include_groups=False)
        rows.append({"level": name, "products": g.product_key.nunique(), "months": agg.shape[0],
                     "aggregate_wape_pcs": wape(agg.actual, agg.forecast),
                     "aggregate_wape_pesos_sell": wape(agg.actual_pesos, agg.forecast_pesos),
                     "aggregate_ma3_wape_pesos_sell": wape(agg.actual_pesos, agg.ma3_pesos),
                     "product_median_wape": float(prod.median()),
                     "product_pooled_wape_pcs": float(g.abs_error.sum() / g.actual.abs().sum()),
                     "product_pooled_wape_pesos_sell": float((g.abs_error * g.price_sell_vat_inc).sum()
                                                             / g.actual_pesos.abs().sum())})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# 7. Demand swing vs error (+ SVG scatter)
# --------------------------------------------------------------------------- #
def swing_vs_error(summary, series):
    c = summary[summary.score_source == "common"].copy()
    c["cv_full"] = c.product_key.map(lambda k: coefficient_of_variation(series[k][series[k].index <= LAST_MONTH].to_numpy()))
    c["cv_before_test"] = c.product_key.map(
        lambda k: coefficient_of_variation(series[k][series[k].index < F.WINDOW_START].to_numpy()))
    res = {}
    for col in ("cv_full", "cv_before_test"):
        d = c[[col, "wape"]].dropna()
        pr, pp = stats.pearsonr(d[col], d.wape)
        sr, sp = stats.spearmanr(d[col], d.wape)
        res[col] = {"n": int(len(d)), "pearson_r": pr, "pearson_p": pp, "r_squared": pr ** 2,
                    "spearman_rho": sr, "spearman_p": sp}
    c["cv_full_tercile"] = pd.qcut(c.cv_full, 3, labels=["low swing", "middle", "high swing"])
    terc = c.groupby("cv_full_tercile", observed=True).agg(products=("product_key", "size"),
                                                           cv_min=("cv_full", "min"), cv_max=("cv_full", "max"),
                                                           median_wape=("wape", "median"))
    return c, res, terc.reset_index()


def scatter_svg(c: pd.DataFrame, res: dict, pre: dict, path: str):
    W, H, L, R, T, B = 760, 490, 64, 24, 76, 56
    x, y = c.cv_full.to_numpy(), c.wape.to_numpy() * 100
    xmax = float(np.ceil(x.max() * 5) / 5)
    ymax = float(np.ceil(y.max() / 20) * 20)
    px = lambda v: L + v / xmax * (W - L - R)
    py = lambda v: H - B - v / ymax * (H - T - B)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" '
           f'aria-label="Scatter of demand swing (coefficient of variation) against forecast error (WAPE) for {len(c)} products">',
           "<style>svg{--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--grid:#e4e3df;--s1:#2a78d6;font-family:system-ui,sans-serif}"
           "@media (prefers-color-scheme: dark){svg{--surface:#1a1a19;--ink:#ffffff;--ink2:#c3c2b7;--grid:#3a3a37;--s1:#3987e5}}"
           ".g{stroke:var(--grid);stroke-width:1}.t{fill:var(--ink2);font-size:12px}.h{fill:var(--ink);font-size:14px;font-weight:600}"
           ".d{fill:var(--s1);stroke:var(--surface);stroke-width:2}.f{stroke:var(--ink2);stroke-width:1.5;stroke-dasharray:5 4;fill:none}</style>",
           f'<rect width="{W}" height="{H}" fill="var(--surface)"/>',
           f'<text class="h" x="{L}" y="24">Demand swing vs forecast error, Unilever Tier A as of 2026-02 ({len(c)} products)</text>',
           f'<text class="t" x="{L}" y="42">Test months 2025-09 to 2026-02. Pearson r = {res["pearson_r"]:.2f} '
           f'(r² = {res["r_squared"]:.2f}), Spearman ρ = {res["spearman_rho"]:.2f}.</text>',
           f'<text class="t" x="{L}" y="58">Swing measured before the test months only (known in advance): '
           f'r = {pre["pearson_r"]:.2f}, ρ = {pre["spearman_rho"]:.2f}.</text>']
    for v in np.arange(0, ymax + 1e-9, 20):
        out.append(f'<line class="g" x1="{L}" x2="{W - R}" y1="{py(v):.1f}" y2="{py(v):.1f}"/>'
                   f'<text class="t" x="{L - 8}" y="{py(v) + 4:.1f}" text-anchor="end">{v:.0f}%</text>')
    for v in np.arange(0, xmax + 1e-9, 0.2):
        out.append(f'<text class="t" x="{px(v):.1f}" y="{H - B + 18}" text-anchor="middle">{v:.1f}</text>')
    out.append(f'<text class="t" x="{(L + W - R) / 2}" y="{H - 12}" text-anchor="middle">'
               "Demand swing: coefficient of variation of monthly pieces sold (std ÷ mean, first sale to 2026-02)</text>")
    out.append(f'<text class="t" transform="translate(16 {(T + H - B) / 2}) rotate(-90)" text-anchor="middle">'
               "Forecast error: WAPE, test months</text>")
    b, a = np.polyfit(x, y, 1)
    x0, x1 = float(x.min()), float(x.max())
    out.append(f'<line class="f" x1="{px(x0):.1f}" y1="{py(a + b * x0):.1f}" x2="{px(x1):.1f}" y2="{py(a + b * x1):.1f}"/>')
    for r in c.itertuples():
        out.append(f'<circle class="d" cx="{px(r.cv_full):.1f}" cy="{py(r.wape * 100):.1f}" r="4.5">'
                   f"<title>{escape(r.product_name)} ({r.sku_code}): swing {r.cv_full:.2f}, error {r.wape * 100:.0f}%</title></circle>")
    top = c[c.wape >= 0.95]
    if len(top):
        out.append(f'<text class="t" x="{px(float(top.cv_full.min())) - 10:.1f}" y="{py(float(top.wape.max()) * 100) - 12:.1f}">'
                   f"{len(top)} products at {top.wape.min() * 100:.0f}–{top.wape.max() * 100:.0f}% error (named in README §2)</text>")
    out.append("</svg>")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))


# --------------------------------------------------------------------------- #
# 8. Seasonality: dashboard STL band vs the lag-12 test
# --------------------------------------------------------------------------- #
def band(strength):
    return "Strong" if strength >= STL_STRONG else ("Moderate" if strength >= STL_MODERATE else "Weak")


def seasonality(tier, dims, series, rng):
    rows = []
    for k in tier.product_key.astype(int):
        s = series.get(k)
        if s is None:
            rows.append({"product_key": k, "dashboard_label": "no series"})
            continue
        s = s[s.index <= LAST_MONTH]
        periods = [ym(t) for t in s.index]
        st = stl_summary(periods, list(s.to_numpy(dtype=float)))
        y = np.asarray(st.get("observed", []), dtype=float) if st["available"] else None
        sold = np.flatnonzero(s.to_numpy() > 0)
        yy = s.to_numpy(dtype=float)[int(sold[0]):] if sold.size else np.array([])
        r = {"product_key": k, "months_from_first_sale": int(len(yy)),
             "dashboard_label": band(st["seasonal_strength"]) + " seasonality" if st["available"] else "Not enough history (< 36 months)",
             "stl_seasonal_strength": st.get("seasonal_strength", np.nan),
             "stl_peak_month": st.get("peak_month"), "stl_trough_month": st.get("trough_month")}
        if len(yy) >= ACF_MIN_MONTHS and yy.std() > 0:
            r12 = float(acf(yy, nlags=12, fft=False)[12])
            r.update({"acf_lag12": r12, "acf_bound": ACF_Z / np.sqrt(len(yy)), "acf_lag12_significant": bool(abs(r12) > ACF_Z / np.sqrt(len(yy)))})
        else:
            r.update({"acf_lag12": np.nan, "acf_bound": np.nan, "acf_lag12_significant": np.nan})
        if st["available"]:
            perm = np.array([stl_summary(periods[-len(y):], list(rng.permutation(y)))["seasonal_strength"] for _ in range(N_PERM)])
            r["stl_shuffle_p"] = (1 + int((perm >= st["seasonal_strength"]).sum())) / (1 + N_PERM)
            r["stl_shuffle_share_strong"] = float((perm >= STL_STRONG).mean())
        rows.append(r)
    out = dims[["product_key", "product_name", "sku_code"]].merge(pd.DataFrame(rows), on="product_key")

    def verdict(r):
        strong = isinstance(r.dashboard_label, str) and r.dashboard_label.startswith("Strong")
        if pd.isna(r.acf_lag12_significant):
            return "lag-12 test not run (< 24 months)"
        sig = bool(r.acf_lag12_significant)
        if strong and not sig:
            return "DISAGREE: dashboard Strong, lag-12 test not significant"
        if sig and not strong:
            return "DISAGREE: lag-12 test significant, dashboard not Strong"
        return "agree: seasonal" if sig else "agree: not seasonal"
    out["agreement"] = out.apply(verdict, axis=1)
    noise = []
    for n in (36, 37, 38):
        st_strong = acf_sig = 0
        for _ in range(N_NOISE):
            z = rng.normal(100, 20, n)
            st_strong += stl_summary([f"{2000 + i // 12}-{i % 12 + 1:02d}" for i in range(n)], list(z))["seasonal_strength"] >= STL_STRONG
            acf_sig += abs(acf(z, nlags=12, fft=False)[12]) > ACF_Z / np.sqrt(n)
        noise.append({"months": n, "simulations": N_NOISE, "share_strong_by_stl": st_strong / N_NOISE,
                      "share_significant_by_lag12": acf_sig / N_NOISE})
    return out, pd.DataFrame(noise)


def xgb_month_importance(fc) -> dict:
    booster, n_rows = fc.booster_for(F.PLANNING_MONTH)
    out = {"training_rows": n_rows}
    for kind in ("gain", "weight"):
        sc = booster.get_score(importance_type=kind)
        name = lambda f: FEATURE_NAMES[int(f[1:])] if f.startswith("f") and f[1:].isdigit() else f
        sc = {name(f): v for f, v in sc.items()}
        tot = sum(sc.values())
        rank = sorted(sc, key=sc.get, reverse=True)
        out[kind] = {"month_of_year_share": sc.get("month_of_year", 0.0) / tot if tot else np.nan,
                     "month_of_year_rank": rank.index("month_of_year") + 1 if "month_of_year" in rank else None,
                     "features_used": len(rank), "top3": rank[:3]}
    return out


# --------------------------------------------------------------------------- #
# 9. Collapse flag
# --------------------------------------------------------------------------- #
def level_ratio(s: pd.Series, upto: pd.Timestamp):
    """mean(last 3) / mean(last 12) of the months up to and including `upto`, from first sale;
    None if fewer than 12 months since first sale or the 12-month mean is not positive."""
    h = s[s.index <= upto]
    sold = np.flatnonzero(h.to_numpy() > 0)
    if not sold.size:
        return None
    h = h.iloc[int(sold[0]):]
    if len(h) < 12 or h.tail(12).mean() <= 0:
        return None
    return float(h.tail(3).mean() / h.tail(12).mean())


def collapse(summary, series, pm):
    s = summary.copy()
    s["ratio_last3_to_last12"] = s.product_key.map(lambda k: level_ratio(series[k], LAST_MONTH) if k in series else None)
    s["last3_mean"] = s.product_key.map(lambda k: series[k][series[k].index <= LAST_MONTH].tail(3).mean() if k in series else np.nan)
    s["last12_mean"] = s.product_key.map(lambda k: series[k][series[k].index <= LAST_MONTH].tail(12).mean() if k in series else np.nan)
    s["last3_months_pcs"] = s.product_key.map(
        lambda k: " / ".join(f"{v:,.0f}" for v in series[k][series[k].index <= LAST_MONTH].tail(3)) if k in series else "")
    s["collapse_flag"] = s.ratio_last3_to_last12 < COLLAPSE_RATIO
    s["served_over_ma3"] = s.forecast_2026_03 / s.ma3_2026_03
    sens = pd.DataFrame([{"threshold": t, "products_flagged": int((s.ratio_last3_to_last12 < t).sum()),
                          "assessable": int(s.ratio_last3_to_last12.notna().sum())} for t in COLLAPSE_SENSITIVITY])
    # Would the rule, using only history before each test month, have warned about over-forecasts?
    c = pm[pm.score_source == "common"].copy()
    c["ratio_before"] = [level_ratio(series[k], pd.Timestamp(m + "-01") - pd.offsets.MonthBegin(1))
                         for k, m in zip(c.product_key, c.month)]
    c["flag_before"] = np.where(c.ratio_before.isna(), "not assessable",
                                np.where(c.ratio_before < COLLAPSE_RATIO, "flagged", "not flagged"))
    g = c.groupby("flag_before")
    bt = pd.DataFrame({"product_months": g.size(), "products": g.product_key.nunique(),
                       "pct_over_forecast": g.direction.apply(lambda d: (d == "over").mean() * 100),
                       "bias_pct": g.apply(lambda x: x.error.sum() / x.actual.abs().sum() * 100, include_groups=False),
                       "wape": g.apply(lambda x: x.abs_error.sum() / x.actual.abs().sum(), include_groups=False)}).reset_index()
    return s, sens, bt


# --------------------------------------------------------------------------- #
def main():
    if "--svg-only" in sys.argv:          # redraw the chart from the written outputs, no recompute
        with open(os.path.join(HERE, "results.json")) as fh:
            res = json.load(fh)["cv_vs_wape"]
        cv = pd.read_csv(os.path.join(HERE, "cv_vs_wape.csv"), dtype={"sku_code": str})
        scatter_svg(cv, res["cv_full"], res["cv_before_test"], os.path.join(HERE, "cv_vs_wape.svg"))
        return
    rng = np.random.default_rng(SEED)
    tier, recs, series, fc, bt, repro = rebuild()
    dims = read("product_dimension_tierA.csv", dtype={"sku_code": str})
    px = prices(bt, dims)
    pm = per_month(bt, px, dims)
    summ = per_product(pm, recs, dims, px)
    mt = monthly_totals(pm)
    agg = aggregate_accuracy(pm)
    cv, cvres, terc = swing_vs_error(summ, series)
    scatter_svg(cv, cvres["cv_full"], cvres["cv_before_test"], os.path.join(HERE, "cv_vs_wape.svg"))
    seas, noise = seasonality(tier, dims, series, rng)
    imp = xgb_month_importance(fc)
    col, sens, colbt = collapse(summ, series, pm)

    write = publish
    write(pm, "per_product_month.csv")
    write(summ, "per_product_summary.csv")
    write(mt, "monthly_totals.csv")
    write(agg, "category_total_accuracy.csv")
    write(cv[["product_name", "sku_code", "product_key", "category_path", "bin", "wape", "cv_full", "cv_before_test",
              "cv_full_tercile"]], "cv_vs_wape.csv")
    write(terc, "cv_terciles.csv")
    write(seas, "seasonality_reconciliation.csv")
    write(noise, "seasonality_noise_calibration.csv")
    write(col[["product_name", "sku_code", "product_key", "category_path", "status", "bin", "served_method",
               "last3_months_pcs", "last3_mean", "last12_mean", "ratio_last3_to_last12", "collapse_flag",
               "forecast_2026_03", "ma3_2026_03", "served_over_ma3"]].sort_values("ratio_last3_to_last12"),
          "collapse_flag.csv")
    write(sens, "collapse_threshold_sensitivity.csv")
    write(colbt, "collapse_flag_backtest.csv")
    # Raw stock-count fields (cases, loose pieces, stock value, price per case) stay in inputs/; per-piece prices
    # and costs go to local/ only (CLIENT_COLUMNS). Their aggregate checks are in results.json -> price_cost_checks.
    write(px.merge(dims[["product_key", "product_name", "sku_code"]], on="product_key")
          [["product_name", "sku_code", "product_key", "price_sell_vat_inc", "stock_value_over_lpp",
            "cost_per_piece", "cost_over_selling_price", "gsv_per_piece_sales_file", "cost_over_sales_gsv_per_piece",
            "cost_status"]], "price_and_cost_basis.csv")

    sc = summ[summ.status == "ok"]
    com = sc[sc.score_source == "common"]
    pm_c = pm[pm.score_source == "common"]
    ok = px[px.cost_status == "ok"]
    px_c = px[px.product_key.isin(com.product_key)]
    by_peso = com.sort_values("mean_abs_error_pesos_sell", ascending=False).mean_abs_error_pesos_sell
    near = com.assign(d=(com.mean_forecast - 373).abs()).nsmallest(1, "d").iloc[0]
    strong = seas[seas.dashboard_label.astype(str).str.startswith("Strong")]
    p674 = pm[pm.product_key == 674]
    runs_dist = lambda col: {str(int(k)): int(v) for k, v in com[col].value_counts().sort_index().items()}
    results = {
        "reproduction": repro,
        "counts": {"tier_a": int(len(summ)), "scored": int(len(sc)), "scored_common": int(len(com)),
                   "scored_one_month": int((sc.score_source != "common").sum()),
                   "not_scored": int((summ.status != "ok").sum()),
                   "cost_basis_ok": int((px.cost_status == "ok").sum()),
                   "cost_status": px.cost_status.value_counts().to_dict()},
        "product_level_common": {"median_wape": float(com.wape.median()), "median_ma3_wape": float(com.ma3_wape.median()),
                                 "median_naive_wape": float(com.naive_wape.median()),
                                 "median_mean_abs_error_pcs": float(com.mean_abs_error_pcs.median()),
                                 "median_mean_abs_error_pesos_sell": float(com.mean_abs_error_pesos_sell.median()),
                                 "median_mean_actual_pcs": float(com.mean_actual.median()),
                                 "products_beating_naive": int((com.wape < com.naive_wape).sum()),
                                 "products_beating_ma3": int((com.wape < com.ma3_wape).sum()),
                                 "products_worse_than_ma3": int((com.wape > com.ma3_wape).sum())},
        "direction_common": {"surplus_risk_3plus_over": int(com.surplus_risk_3plus_over.sum()),
                             "currently_over_3plus": int(com.currently_over_3plus.sum()),
                             "median_pct_months_over": float(com.pct_months_over.median()),
                             "product_months_over": int((pm[pm.score_source == "common"].direction == "over").sum()),
                             "product_months_under": int((pm[pm.score_source == "common"].direction == "under").sum()),
                             "product_months_exact": int((pm[pm.score_source == "common"].direction == "exact").sum())},
        "cv_vs_wape": cvres,
        "xgb_month_of_year": imp,
        "seasonality": {"labels": seas.dashboard_label.value_counts().to_dict(),
                        "agreement": seas.agreement.value_counts().to_dict(),
                        "acf_significant": int((seas.acf_lag12_significant == True).sum()),  # noqa: E712
                        "acf_tested": int(seas.acf_lag12_significant.notna().sum()),
                        "acf_significant_share": float((seas.acf_lag12_significant == True).sum()  # noqa: E712
                                                       / seas.acf_lag12_significant.notna().sum())},
        "collapse": {"flagged": int(col.collapse_flag.sum()), "assessable": int(col.ratio_last3_to_last12.notna().sum())},
        # aggregates of the per-product prices and costs, which themselves stay in local/
        "price_cost_checks": {
            "price_sell_vat_inc_min_median_max_107": [float(px_c.price_sell_vat_inc.min()),
                                                      float(px_c.price_sell_vat_inc.median()),
                                                      float(px_c.price_sell_vat_inc.max())],
            "products_with_selling_price": int(px.price_sell_vat_inc.notna().sum()),
            "stock_value_over_lpp_min_max": [float(ok.stock_value_over_lpp.min()), float(ok.stock_value_over_lpp.max())],
            "stock_value_over_lpp_n": int(ok.stock_value_over_lpp.notna().sum()),
            "cost_over_selling_price_median": float(ok.cost_over_selling_price.median()),
            "cost_over_selling_price_n": int(ok.cost_over_selling_price.notna().sum()),
            "cost_over_sales_gsv_median": float(ok.cost_over_sales_gsv_per_piece.median()),
            "cost_over_sales_gsv_n": int(ok.cost_over_sales_gsv_per_piece.notna().sum()),
            "products_no_cost_basis_among_107": int((px_c.cost_status != "ok").sum()),
            "products_with_cost_basis_among_107": int((px_c.cost_status == "ok").sum()),
        },
        "peso_miss_concentration": {"top10_share": float(by_peso.head(10).sum() / by_peso.sum()),
                                    "top20_share": float(by_peso.head(20).sum() / by_peso.sum())},
        "by_bin_median_wape": {b: {"products": int(len(g)), "served": float(g.wape.median()),
                                   "ma3": float(g.ma3_wape.median()), "naive": float(g.naive_wape.median())}
                               for b, g in com.groupby("bin")},
        "direction_detail": {"median_bias_pct": float(com.bias_pct.median()),
                             "products_net_over": int((com.bias_pct > 0).sum()),
                             "products_net_under": int((com.bias_pct < 0).sum()),
                             "products_ma3_same": int((com.wape == com.ma3_wape).sum()),
                             "longest_over_run_distribution": runs_dist("longest_over_run"),
                             "longest_under_run_distribution": runs_dist("longest_under_run"),
                             "current_run_direction": com.current_run_direction.value_counts().to_dict(),
                             "product_months": int(len(pm_c))},
        "sanity_check_373": {"product_name": near.product_name, "sku_code": near.sku_code,
                             "mean_forecast_pcs": float(near.mean_forecast), "mean_abs_error_pcs": float(near.mean_abs_error_pcs),
                             "wape": float(near.wape)},
        "product_674_errors_pcs": {m: float(e) for m, e in zip(p674.month, p674.error)},
        "strong_label_shuffle": {"strong": int(len(strong)), "shuffle_p_below_0.05": int((strong.stl_shuffle_p < 0.05).sum()),
                                 "shuffle_p_0.05_or_more": int((strong.stl_shuffle_p >= 0.05).sum()),
                                 "months_from_first_sale": sorted(int(v) for v in strong.months_from_first_sale.unique())},
    }
    with open(os.path.join(HERE, "results.json"), "w") as fh:
        json.dump(results, fh, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    print(json.dumps(results, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
    print(mt.to_string())
    print(agg.to_string())


if __name__ == "__main__":
    main()
