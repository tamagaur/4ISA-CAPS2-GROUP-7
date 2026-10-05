"""
Offline analysis for the LP logic check (2026-10-03). Reads pull_data.py's
CSVs only (no database), writes the CSVs beside this file and prints every
figure README.md quotes.

The LP is replayed with scripts/run_lp.py's own functions (product_input,
_sigma_d_for_product, plan_cycle), fed the inputs run_lp's own queries
returned, so the only thing a variant changes is the one input named.
"""
from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from analytics.allocation import basis_year  # noqa: E402
from analytics.forecasting.diagnostic_metrics import mase, naive_scale  # noqa: E402
from analytics.forecasting.router import rolling_one_step  # noqa: E402
from analytics.forecasting.split import train_holdout_split  # noqa: E402
from analytics.params import (  # noqa: E402
    BUSINESS_DAYS_PER_WEEK, COVER_KPI_HISTORY_MONTHS, MASE_GATE, PLACEHOLDERS, POLICY_COVER_WEEKS, WEEKS_PER_MONTH,
)
from scripts.run_baseline_forecast import build_series  # noqa: E402
from scripts.run_lp import _sigma_d_for_product, build_parser, plan_cycle, product_input  # noqa: E402

logging.getLogger().setLevel(logging.ERROR)  # run_lp logs one line per product

PULL = ROOT / "scratch" / "lp_logic_check_2026-10-03" / "pull"
OUT = Path(__file__).resolve().parent
FIT = ROOT / "reports" / "diagnostics" / "fit_diagnosis_2026-10" / "per_sku.csv"
CYCLE = "2026-03-01"
CLOSE_PERIOD, OPEN_PERIOD = "2026-03", "2026-02"   # counted 2026-04-06 and 2026-03-02
FIGURES: dict = {}
# Client data (project rule: no per-product sales or prices in git). The per-product tables are written in full to
# the git-ignored local/ folder; the committed copy beside this file drops the columns matching CLIENT_COLUMNS
# (price per piece and every per-product peso column). Totals and other aggregate tables are written whole.
LOCAL = OUT / "local"
CLIENT_COLUMNS = re.compile(r"_php$")


def publish(df: pd.DataFrame, name: str) -> None:
    """Full table to local/ (not committed); the same table minus CLIENT_COLUMNS beside this file."""
    LOCAL.mkdir(exist_ok=True)
    df.to_csv(LOCAL / name, index=False)
    df.drop(columns=[c for c in df.columns if CLIENT_COLUMNS.search(c)]).to_csv(OUT / name, index=False)


def load(name: str) -> pd.DataFrame:
    return pd.read_csv(PULL / f"{name}.csv")


def none_if_nan(v):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)


products = load("products").set_index("product_key")
NAME = products["product_name"].to_dict()
SKU = products["sku_code"].to_dict()

# --------------------------------------------------------------------------
# Inputs exactly as run_lp.main() builds them
# --------------------------------------------------------------------------
cands = load("candidates")
demand = load("run_lp_demand")
for col in ("total_quantity", "total_amount"):
    demand[col] = pd.to_numeric(demand[col], errors="coerce").fillna(0)   # fetch_demand_history
demand["period"] = demand["period"].astype(str)
sac = load("run_lp_stock_and_cost")
COST = {int(r.product_key): none_if_nan(r.cost_per_piece) for r in sac.itertuples()}

sbp = load("stock_by_period")
sbp = sbp[sbp["principal"] == "unilever"]


def stock_file(period: str) -> dict[int, float | None]:
    """product_key -> stock pieces in that period's count (None: no usable pack size)."""
    rows = sbp[sbp["_period"] == period]
    return {int(r.product_key): none_if_nan(r.stock_pieces) for r in rows.itertuples() if not pd.isna(r.product_key)}


STOCK = {CLOSE_PERIOD: stock_file(CLOSE_PERIOD), OPEN_PERIOD: stock_file(OPEN_PERIOD)}
VALUE = {p: {int(r.product_key): float(r.stock_value_pesos) for r in sbp[sbp["_period"] == p].itertuples()
             if not pd.isna(r.product_key)} for p in STOCK}

# Check: the latest count in my per-period pull = run_lp's STOCK_AND_COST_QUERY.
mismatch = [int(r.product_key) for r in sac.itertuples()
            if bool(r.in_stock_file) != (int(r.product_key) in STOCK[CLOSE_PERIOD])
            or (r.in_stock_file and abs((none_if_nan(r.stock_pieces) or 0) - (STOCK[CLOSE_PERIOD][int(r.product_key)] or 0)) > 1e-6)]
FIGURES["check_latest_count_equals_run_lp_query"] = f"{len(sac) - len(mismatch)}/{len(sac)}"


def stock_and_cost_for(period: str) -> dict:
    """run_lp's {product_key: (in_stock_file, stock_pieces, cost_per_piece)} with the stock taken from
    `period`'s count. Cost per piece is held at run_lp's own value so only the stock count changes."""
    return {k: (k in STOCK[period], STOCK[period].get(k), COST[k]) for k in COST}


def build_products(period: str):
    out, gated = [], []
    sc = stock_and_cost_for(period)
    for row in cands.itertuples():
        pdem = demand[demand["product_key"] == row.product_key]
        sigma, reason = _sigma_d_for_product(pdem, row.principal) if not pdem.empty else (None, "no demand")
        if sigma is None:
            gated.append((row.product_key, reason))
            continue
        p, reason = product_input(row.product_key, row.sku_id, row.principal, float(row.forecast_value), sigma,
                                  sc, demand, prior_year=basis_year(str(row.forecast_date)))
        if p is None:
            gated.append((row.product_key, reason))
            continue
        out.append(p)
    return out, gated


def solve(period: str, pct: float):
    prods, gated = build_products(period)
    args = build_parser().parse_args(["--allocation-pct", str(pct)])
    return prods, gated, plan_cycle(prods, args)


# --------------------------------------------------------------------------
# Issue 1 - stock timing
# --------------------------------------------------------------------------
lp = load("lp_cycle")
pending = lp[lp["status"] == "pending"].set_index("product_key")

# Replay check against the stored cycle (the 2026-09-30 run, 105%).
prods105, gated105, plan105 = solve(CLOSE_PERIOD, 105)
d_rop = max(abs(s.target_stock - pending.loc[p.product_key, "rop_i"]) for p, s in zip(prods105, plan105.skus))
d_ss = max(abs(s.safety_stock - pending.loc[p.product_key, "ss_i"]) for p, s in zip(prods105, plan105.skus))
d_q = max(abs(plan105.orders[s.sku_id] - pending.loc[p.product_key, "q_i"]) for p, s in zip(prods105, plan105.skus))
FIGURES["replay_vs_stored_2026-03_pending"] = {"products": len(prods105), "gated_out": len(gated105),
                                               "max_abs_diff_rop_i": d_rop, "max_abs_diff_ss_i": d_ss,
                                               "max_abs_diff_q_i_at_105": d_q}

variants = {}
for label, period in (("closing_count_2026-04-06", CLOSE_PERIOD), ("opening_count_2026-03-02", OPEN_PERIOD)):
    prods, gated, plan = solve(period, 103)
    variants[label] = (prods, plan)

rows = []
close_prods, close_plan = variants["closing_count_2026-04-06"]
open_prods, open_plan = variants["opening_count_2026-03-02"]
for pc, sc_, po, so in zip(close_prods, close_plan.skus, open_prods, open_plan.skus):
    assert pc.product_key == po.product_key
    oc, oo = close_plan.orders[sc_.sku_id], open_plan.orders[so.sku_id]
    rows.append({
        "product_name": NAME.get(pc.product_key), "sku_code": SKU.get(pc.product_key), "product_key": pc.product_key,
        "forecast_mar2026_pcs": round(sc_.demand, 2), "safety_stock_pcs": round(sc_.safety_stock, 2),
        "target_stock_pcs": round(sc_.target_stock, 2),
        "stock_2026-03-02_pcs": round(so.stock_on_hand, 2), "in_2026-03-02_count": po.in_stock_file,
        "stock_2026-04-06_pcs": round(sc_.stock_on_hand, 2), "in_2026-04-06_count": pc.in_stock_file,
        "need_with_opening_pcs": round(so.need, 2), "need_with_closing_pcs": round(sc_.need, 2),
        "order_103_opening_pcs": round(oo, 2), "order_103_closing_pcs": round(oc, 2),
        "short_103_opening_pcs": round(so.need - oo, 2), "short_103_closing_pcs": round(sc_.need - oc, 2),
        "cost_per_piece_php": round(sc_.procurement_cost_per_unit, 4),
    })
issue1 = pd.DataFrame(rows)
publish(issue1, "issue1_stock_timing_per_product.csv")

tot = []
for label, (prods, plan) in variants.items():
    s = plan.summary()
    tot.append({"variant": label, "allocation_pct": 103, "products": len(prods),
                "not_in_count_counted_as_0": sum(1 for p in prods if not p.in_stock_file),
                "stock_on_hand_pcs": round(sum(x.stock_on_hand for x in plan.skus), 0),
                "need_pcs": round(s["need"], 0), "ordered_pcs": round(s["ordered"], 0),
                "short_pcs": round(s["shortfall"], 0), "products_short": len(s["short_skus"]),
                "products_order_0_overstocked": len(s["overstocked_skus"]),
                "allocation_ceiling_pcs": round(sum(plan.allocation.values()), 0),
                "allocation_binds": all(s["allocation_binds"].values()),
                "month_end_cover_weeks": round(s["month_end_cover_weeks"], 3)})
issue1_tot = pd.DataFrame(tot)

# Dashboard KPI "N of M Category A below safety stock" (dashboard.py:1229-1257, 1296-1305):
# Tier A at the latest ABC period, stock in pieces at ONE count (NULL = no row or no pack size),
# ss_i of the current cycle's pending rows; both present or excluded.
abc = load("abc_latest")
abc_period = abc[abc["principal"] == "unilever"]["classification_period"].max()
tier_a = abc[(abc["classification_period"] == abc_period) & (abc["tier"] == "A")]
FIGURES["tier_a_period"], FIGURES["tier_a_count"] = abc_period, len(tier_a)
below = {}
for label, period in (("closing_count_2026-04-06", CLOSE_PERIOD), ("opening_count_2026-03-02", OPEN_PERIOD)):
    comp = [(k, STOCK[period].get(k), pending.loc[k, "ss_i"]) for k in tier_a["product_key"]
            if k in pending.index and STOCK[period].get(k) is not None]
    b = [k for k, st, ss in comp if st < ss]
    below[label] = (len(b), len(comp), b)
issue1_tot["tier_a_below_ss"] = issue1_tot["variant"].map(lambda v: below[v][0])
issue1_tot["tier_a_comparable"] = issue1_tot["variant"].map(lambda v: below[v][1])
issue1_tot.to_csv(OUT / "issue1_totals.csv", index=False)
issue1["below_ss_at_opening"] = issue1["product_key"].isin(below["opening_count_2026-03-02"][2])
issue1["below_ss_at_closing"] = issue1["product_key"].isin(below["closing_count_2026-04-06"][2])
publish(issue1, "issue1_stock_timing_per_product.csv")

# The opening count is flagged as an outlier (backend/data_notes.py:26-29): how broad is the jump?
meta = load("snapshot_meta")
um = meta[(meta["principal"] == "unilever") & (meta["_period"] >= "2025-01")][
    ["_period", "snapshot_min", "row_count", "value_pesos"]].rename(columns={"snapshot_min": "counted_on"})
# ESTIMATE, not a record (Unilever has no purchase rows): receipts implied by the counts,
# closing value - previous closing value + the month's pieces sold x run_lp's cost-per-piece rule.
_ud = load("unilever_demand_monthly")
_ud["q"] = pd.to_numeric(_ud["quantity_sold"], errors="coerce").fillna(0.0)
_lat = sbp.dropna(subset=["avg_cost_per_case", "pack_size_numeric"]).sort_values("_period").groupby("product_key").tail(1)
_cpp = (_lat.set_index("product_key")["avg_cost_per_case"] / _lat.set_index("product_key")["pack_size_numeric"])
_sales_cost = _ud.assign(v=_ud["q"] * _ud["product_key"].map(_cpp)).groupby("calendar_month")["v"].sum()
um = um.sort_values("_period").reset_index(drop=True)
um["sales_at_last_purchase_price_php"] = um["_period"].map(_sales_cost)
um["implied_receipts_estimate_php"] = um["value_pesos"] - um["value_pesos"].shift(1) + um["sales_at_last_purchase_price_php"]
um.to_csv(OUT / "issue1_unilever_stock_counts.csv", index=False)
_a = sbp[sbp["_period"] == "2026-01"].set_index("product_key")["stock_value_pesos"]
_b = sbp[sbp["_period"] == OPEN_PERIOD].set_index("product_key")["stock_value_pesos"]
_r = (_b / _a[_a > 0]).dropna()
FIGURES["whole_file_opening_count_jump"] = {
    "products_in_feb3_and_mar2": len(_r), "ratio_quartiles_mar2_vs_feb3": _r.quantile([.25, .5, .75]).round(2).to_dict(),
    "products_over_1.5x": int((_r > 1.5).sum()),
}
pool = issue1["product_key"]
feb3 = stock_file("2026-01")
ratio = pd.DataFrame({
    "product_key": pool,
    "r_open_vs_feb3": [(STOCK[OPEN_PERIOD].get(k) or 0) / feb3[k] if feb3.get(k) else np.nan for k in pool],
    "r_open_vs_apr6": [(STOCK[OPEN_PERIOD].get(k) or 0) / STOCK[CLOSE_PERIOD][k] if STOCK[CLOSE_PERIOD].get(k) else np.nan for k in pool],
})
FIGURES["pool_opening_count_jump"] = {
    "median_ratio_mar2_vs_feb3": round(float(ratio["r_open_vs_feb3"].median()), 2),
    "median_ratio_mar2_vs_apr6": round(float(ratio["r_open_vs_apr6"].median()), 2),
    "products_mar2_over_1.5x_feb3": int((ratio["r_open_vs_feb3"] > 1.5).sum()),
    "products_with_feb3_value": int(ratio["r_open_vs_feb3"].notna().sum()),
    "pool_value_php": {p: round(sum(VALUE[p].get(k, 0.0) for k in pool), 2) for p in VALUE},
}

# --------------------------------------------------------------------------
# Issue 2 - MASE gate
# --------------------------------------------------------------------------
fl = load("forecast_latest")
ud = load("unilever_demand_monthly")
ud["quantity"] = pd.to_numeric(ud["quantity_sold"], errors="coerce").fillna(0.0)   # fetch_demand
recomputed, checked = 0, 0
series_end = {}
for r in fl[fl["status"] == "ok"].itertuples():
    df = ud[ud["product_key"] == r.product_key][["calendar_month", "quantity"]]
    s = build_series(df)
    series_end[r.product_key] = s.index.max().strftime("%Y-%m")
    if r.bin not in ("short", "medium"):
        continue   # the long bin needs the global XGBoost model; fit_diagnosis_2026-10 reproduced all 119
    train, hold = train_holdout_split(s)
    sc = rolling_one_step(s, list(hold.index), None, force_bin=r.bin)
    m = mase(sc["actual"].to_numpy(), sc["value"].to_numpy(), naive_scale(train.to_numpy(dtype=float)))
    checked += 1
    recomputed += int(abs(round(m, 3) - float(r.mase)) < 0.0015)
FIGURES["mase_recomputed_short_medium"] = f"{recomputed}/{checked}"

fit = pd.read_csv(FIT)
m2 = fl[fl["status"] == "ok"].merge(
    fit[["product_key", "verdict_source", "holdout_first", "holdout_months", "holdout_mase", "mase_scale"]],
    on="product_key", how="left", suffixes=("", "_common"))
m2 = m2[m2["verdict_source"] == "common"].copy()
m2["stored_window"] = [
    f"{(pd.Period(series_end[k], 'M') - (int(h) - 1)).strftime('%Y-%m')}..{series_end[k]} ({int(h)} mo)"
    for k, h in zip(m2["product_key"], m2["holdout_months"])]
m2["common_window"] = "2025-09..2026-02 (6 mo)"
m2["pass_stored"] = m2["mase"] < MASE_GATE
m2["pass_common"] = m2["holdout_mase"] < MASE_GATE
m2["flips"] = m2["pass_stored"] != m2["pass_common"]
m2["in_lp_pool_2026-03"] = m2["product_key"].isin(cands["product_key"])
m2["product_name"] = m2["product_key"].map(NAME)
m2["sku_code"] = m2["product_key"].map(SKU)
m2["direction"] = np.where(~m2["flips"], "", np.where(m2["pass_stored"], "pass -> fail", "fail -> pass"))
cols = ["product_name", "sku_code", "product_key", "bin", "method", "stored_window", "mase", "common_window",
        "holdout_mase", "direction", "in_lp_pool_2026-03"]
flips = m2[m2["flips"]][cols].rename(columns={"mase": "mase_stored_gate", "holdout_mase": "mase_common_window"})
flips.sort_values(["direction", "mase_stored_gate"]).to_csv(OUT / "issue2_mase_flips.csv", index=False)
FIGURES["mase"] = {
    "ok_rows": int((fl["status"] == "ok").sum()), "common_window_rows": len(m2),
    "pass_stored": int(m2["pass_stored"].sum()), "pass_common": int(m2["pass_common"].sum()),
    "flips": int(m2["flips"].sum()),
    "pass_to_fail": int((m2["flips"] & m2["pass_stored"]).sum()),
    "fail_to_pass": int((m2["flips"] & ~m2["pass_stored"]).sum()),
    "flips_in_lp_pool": int((m2["flips"] & m2["in_lp_pool_2026-03"]).sum()),
    "within_0.1_of_gate_stored": int(((m2["mase"] - 1).abs() < 0.1).sum()),
}

# --------------------------------------------------------------------------
# Issue 3 - weeks of cover
# --------------------------------------------------------------------------
stock_php = float(meta[(meta["principal"] == "unilever") & (meta["_period"] == CLOSE_PERIOD)]["value_pesos"].iloc[0])
latest_sales = ud.loc[ud["net_amount"].notna(), "calendar_month"].max()
cover_end = min(latest_sales, CLOSE_PERIOD)
window = [str(p) for p in pd.period_range(end=cover_end, periods=COVER_KPI_HISTORY_MONTHS, freq="M")]
w = ud[ud["calendar_month"].isin(window)]
by_month = w.groupby("calendar_month")[["net_amount", "gsv", "quantity"]].sum(min_count=1)
net_week = by_month["net_amount"].mean() / WEEKS_PER_MONTH
gsv_week = by_month["gsv"].mean() / WEEKS_PER_MONTH

# Cost per piece per product: run_lp's rule (latest period with a cost) applied to every Unilever product.
lat = sbp.dropna(subset=["avg_cost_per_case", "pack_size_numeric"]).sort_values("_period").groupby("product_key").tail(1)
cpp = (lat.set_index("product_key")["avg_cost_per_case"] / lat.set_index("product_key")["pack_size_numeric"]).to_dict()
w = w.assign(cpp=w["product_key"].map(cpp))
cov = w.dropna(subset=["cpp"])
cost_ratio = float((cov["quantity"] * cov["cpp"]).sum() / cov["net_amount"].sum())
stock_pcs = float(sbp[sbp["_period"] == CLOSE_PERIOD]["stock_pieces"].sum())
pcs_week = by_month["quantity"].mean() / WEEKS_PER_MONTH
cover = pd.DataFrame([
    {"basis": "shown: stock at cost / sales incl. VAT (dashboard.py:1337-1368)", "ratio_sales_to_shown_basis": 1.0,
     "weekly_sales_php_or_pcs": net_week, "weeks": stock_php / net_week},
    {"basis": "GSV: stock at Last Purchase Price (GSV/CS) / sales at GSV (demand fact gsv column)",
     "ratio_sales_to_shown_basis": gsv_week / net_week, "weekly_sales_php_or_pcs": gsv_week, "weeks": stock_php / gsv_week},
    {"basis": "cost: stock at cost / pieces sold x run_lp cost per piece", "ratio_sales_to_shown_basis": cost_ratio,
     "weekly_sales_php_or_pcs": net_week * cost_ratio, "weeks": stock_php / (net_week * cost_ratio)},
    {"basis": "ex-VAT only: sales / 1.12", "ratio_sales_to_shown_basis": 1 / 1.12,
     "weekly_sales_php_or_pcs": net_week / 1.12, "weeks": stock_php / (net_week / 1.12)},
    {"basis": "pieces: stock pieces / pieces sold", "ratio_sales_to_shown_basis": None,
     "weekly_sales_php_or_pcs": pcs_week, "weeks": stock_pcs / pcs_week},
])
cover.to_csv(OUT / "issue3_weeks_of_cover.csv", index=False)
FIGURES["cover"] = {
    "stock_php_2026-04-06": stock_php, "window": f"{window[0]}..{window[-1]}", "months_with_sales": int(by_month["net_amount"].notna().sum()),
    "avg_month_net_php": by_month["net_amount"].mean(), "avg_month_gsv_php": by_month["gsv"].mean(),
    "gsv_null_rows": int(w["gsv_null"].sum()), "rows": int(w["row_count"].sum()),
    "cost_basis_net_coverage": float(cov["net_amount"].sum() / w["net_amount"].sum()),
    "stock_pcs_rows_without_pack": int(sbp[(sbp["_period"] == CLOSE_PERIOD)]["stock_pieces"].isna().sum()),
}

# --------------------------------------------------------------------------
# Issue 4 - policy card
# --------------------------------------------------------------------------
fc = fl.set_index("product_key")["forecast_value"]
pc = pending.join(fc, how="inner")
pc["w"] = pc["forecast_value"] / WEEKS_PER_MONTH
pc["c"] = [COST.get(k) if COST.get(k) is not None else PLACEHOLDERS["default_procurement_cost_per_unit"] for k in pc.index]
pc["rule_pcs"] = POLICY_COVER_WEEKS * pc["w"]
cycle_q = pc["w"] * PLACEHOLDERS["review_days"] / BUSINESS_DAYS_PER_WEEK      # one weekly PO = one week's demand
pc["avg_on_hand_pcs"] = pc["ss_i"] + cycle_q / 2
pc["rule_avg_if_3wk_is_peak_pcs"] = pc["rule_pcs"] - cycle_q / 2
out4 = pd.DataFrame({
    "product_name": pc.index.map(NAME), "sku_code": pc.index.map(SKU), "product_key": pc.index,
    "forecast_mar2026_pcs": pc["forecast_value"].round(2), "weekly_pcs": pc["w"].round(2),
    "safety_stock_pcs": pc["ss_i"].round(2), "order_up_to_pcs": pc["rop_i"].round(2),
    "rule_3wk_pcs": pc["rule_pcs"].round(2), "cost_per_piece_php": pc["c"].round(4),
    "peak_target_php": (pc["c"] * pc["rop_i"]).round(2), "avg_target_php": (pc["c"] * pc["avg_on_hand_pcs"]).round(2),
    "rule_3wk_php": (pc["c"] * pc["rule_pcs"]).round(2),
    "stock_2026-04-06_php": [round(VALUE[CLOSE_PERIOD].get(k, 0.0), 2) for k in pc.index],
})
publish(out4, "issue4_policy_card_per_product.csv")
rule_php = float((pc["c"] * pc["rule_pcs"]).sum())
peak_php = float((pc["c"] * pc["rop_i"]).sum())
avg_php = float((pc["c"] * pc["avg_on_hand_pcs"]).sum())
rule_avg_peak_php = float((pc["c"] * pc["rule_avg_if_3wk_is_peak_pcs"]).sum())
FIGURES["policy"] = {
    "products": len(pc), "missing_cost": int(sum(COST.get(k) is None for k in pc.index)),
    "pieces": {"sum_ss": pc["ss_i"].sum(), "sum_target": pc["rop_i"].sum(), "rule": pc["rule_pcs"].sum(),
               "ss_vs_rule_pct_less": (pc["rule_pcs"].sum() - pc["ss_i"].sum()) / pc["rule_pcs"].sum() * 100,
               "target_vs_rule_pct_less": (pc["rule_pcs"].sum() - pc["rop_i"].sum()) / pc["rule_pcs"].sum() * 100,
               "sum_average_on_hand": pc["avg_on_hand_pcs"].sum(),
               "average_vs_rule_pct_less": (pc["rule_pcs"].sum() - pc["avg_on_hand_pcs"].sum()) / pc["rule_pcs"].sum() * 100},
    "php": {"rule_3wk": rule_php, "peak_targets": peak_php, "peak_minus_rule": peak_php - rule_php,
            "peak_vs_rule_pct": (peak_php - rule_php) / rule_php * 100,
            "average_targets": avg_php, "average_minus_rule": avg_php - rule_php,
            "average_vs_rule_pct": (avg_php - rule_php) / rule_php * 100,
            "sensitivity_rule_average_if_3wk_is_its_peak": rule_avg_peak_php,
            "sensitivity_average_vs_that_pct": (avg_php - rule_avg_peak_php) / rule_avg_peak_php * 100,
            "ssm_stock_2026-04-06": float(out4["stock_2026-04-06_php"].sum()),
            "ssm_stock_2026-03-02": round(sum(VALUE[OPEN_PERIOD].get(k, 0.0) for k in pc.index), 2)},
    "weeks": {"peak": peak_php / (rule_php / POLICY_COVER_WEEKS), "average": avg_php / (rule_php / POLICY_COVER_WEEKS)},
}
pd.DataFrame([{"measure": k, "value": v} for k, v in FIGURES["policy"]["php"].items()]).to_csv(
    OUT / "issue4_policy_card_totals.csv", index=False)

(OUT / "figures.json").write_text(json.dumps(FIGURES, indent=1, default=float), encoding="utf-8")
print(issue1_tot.to_string(index=False))
print(cover.to_string(index=False))
print(json.dumps(FIGURES, indent=1, default=float))
