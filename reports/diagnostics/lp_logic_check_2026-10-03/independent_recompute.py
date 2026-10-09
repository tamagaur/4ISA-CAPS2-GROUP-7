"""
Independent recompute of the README's headline numbers (2026-10-03).

Fresh code: imports NOTHING from the app or from analyse.py / analyse_balance.py.
Every rule is re-implemented here from its written definition, the
constants are copied in with their source, and the order LP is re-solved with
scipy's HiGHS solver instead of the app's PuLP/CBC. Inputs are the raw pull
CSVs only (not the replay's per-product outputs).

  stock pieces  = cases x numeric pack size + loose pieces (not the SQL expression)
  cost / piece  = latest period's average unit cost per case / pack size
  sigma_d       = sample std of the monthly pieces actually on file / sqrt(mean weekdays per month)
  SS            = Z x sigma_d x sqrt(review + lead days)
  target T      = weekly forecast x (review + lead) / 5 + SS
  need          = max(0, forecast + T - stock)
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import linprog

ROOT = Path(__file__).resolve().parents[3]
PULL = ROOT / "scratch" / "lp_logic_check_2026-10-03" / "pull"
HERE = Path(__file__).resolve().parent

Z = 1.28                       # analytics/params.py:108 (90% service)
WPM = 365.25 / 12 / 7          # analytics/params.py:113-114
REVIEW, LEAD = 5.0, 3.0        # analytics/params.py PLACEHOLDERS review_days, lead_days
ALLOC_PCT = 103.0              # PLACEHOLDERS allocation_pct (ALLOCATION_DEFAULT_PCT)
WAREHOUSE = 3_800_000.0        # PLACEHOLDERS warehouse_capacity
STORAGE = 0.5                  # PLACEHOLDERS storage_cost_per_unit
TARGET_WEEKS = 3.0             # PLACEHOLDERS target_weeks, cover_rule 'aggregate'
W1, W2, W3 = 0.45, 0.35, 0.20  # LP_WEIGHTS cost, service level, storage
CYCLE, BASIS_YEAR = "2026-03-01", "2025"
COUNTS = {"2026-04-06": "2026-03", "2026-03-02": "2026-02"}

fl = pd.read_csv(PULL / "forecast_latest.csv")
abc = pd.read_csv(PULL / "abc_latest.csv")
lp = pd.read_csv(PULL / "lp_cycle.csv")
ud = pd.read_csv(PULL / "unilever_demand_monthly.csv")
sbp = pd.read_csv(PULL / "stock_by_period.csv")
meta = pd.read_csv(PULL / "snapshot_meta.csv")
sbp = sbp[sbp["principal"] == "unilever"].copy()
ud["q"] = pd.to_numeric(ud["quantity_sold"], errors="coerce").fillna(0.0)
out: dict = {}

# ---- the candidate pool, rebuilt: Tier A at the latest Unilever ABC period, forecast ok, MASE < 1 ----
uabc = abc[abc["principal"] == "unilever"]
tier_a = set(uabc[(uabc["classification_period"] == uabc["classification_period"].max()) & (uabc["tier"] == "A")]["product_key"])
pool = fl[(fl["product_key"].isin(tier_a)) & (fl["status"] == "ok") & (fl["mase"] < 1.0)
          & (fl["forecast_date"] == CYCLE)].set_index("product_key")["forecast_value"].astype(float)
out["pool_size"] = len(pool)

# ---- per-product inputs ----
sbp["pieces"] = np.where(sbp["pack_size_numeric"].notna(),
                         sbp["stock_cases"].fillna(0) * sbp["pack_size_numeric"] + sbp["loose_pieces"].fillna(0), np.nan)
with_cost = sbp.dropna(subset=["avg_cost_per_case", "pack_size_numeric"]).sort_values("_period").groupby("product_key").tail(1)
cost = (with_cost.set_index("product_key")["avg_cost_per_case"] / with_cost.set_index("product_key")["pack_size_numeric"])


def weekdays(month: str) -> int:
    start = pd.Timestamp(month + "-01")
    days = pd.date_range(start, start + pd.offsets.MonthEnd(0))
    return int((days.dayofweek < 5).sum())


ss, target, prior_pcs, prior_rev = {}, {}, {}, {}
for k, f in pool.items():
    hist = ud[ud["product_key"] == k]
    sigma_m = float(hist["q"].std(ddof=1))
    mean_wd = float(np.mean([weekdays(m) for m in hist["calendar_month"].unique()]))
    ss[k] = Z * sigma_m / math.sqrt(mean_wd) * math.sqrt(REVIEW + LEAD)
    target[k] = f / WPM * (REVIEW + LEAD) / 5 + ss[k]
    year = hist[hist["calendar_month"].str.startswith(BASIS_YEAR + "-")]
    prior_pcs[k], prior_rev[k] = float(year["q"].sum()), float(pd.to_numeric(year["net_amount"], errors="coerce").fillna(0).sum())
pend = lp[lp["status"] == "pending"].set_index("product_key")
out["max_abs_diff_vs_stored"] = {"ss_i": max(abs(ss[k] - pend.loc[k, "ss_i"]) for k in pool.index),
                                 "rop_i": max(abs(target[k] - pend.loc[k, "rop_i"]) for k in pool.index)}
allocation = sum(max(v, 0) for v in prior_pcs.values()) * ALLOC_PCT / 100 / 12
rev_total = sum(max(v, 0) for v in prior_rev.values())


def solve(stock: dict[int, float]):
    """The three-stage LP of analytics/optimization/lp.py's docstring, written fresh for scipy/HiGHS."""
    keys = list(pool.index)
    F = np.array([pool[k] for k in keys]); T = np.array([target[k] for k in keys]); SS = np.array([ss[k] for k in keys])
    S = np.array([stock.get(k, 0.0) for k in keys]); C = np.array([cost[k] for k in keys])
    R = np.array([max(prior_rev[k], 0) / rev_total for k in keys])
    need = np.maximum(0, F + T - S)
    lay_d = np.minimum(need, np.maximum(0, F - S))
    lay_s = np.minimum(need, np.maximum(0, F + SS - S)) - lay_d
    lay_r = need - lay_d - lay_s
    n = len(keys)
    caps = np.concatenate([lay_d, lay_s, lay_r])          # x = [demand layer, SS layer, rest layer, cover short]
    bounds = [(0, c) for c in caps] + [(0, None)]
    qsum = np.concatenate([np.ones(3 * n), [0.0]])
    A_ub = [qsum.copy(), qsum.copy()]
    b_ub = [allocation, WAREHOUSE - S.sum()]
    cov = np.concatenate([-np.tile(C, 3), [-1.0]])        # -(sum c Q) - short <= sum c (S - F) - N sum c w
    A_ub.append(cov); b_ub.append(float((C * (S - F)).sum() - TARGET_WEEKS * (C * F / WPM).sum()))
    stages = []
    for j in range(3):
        o = np.zeros(3 * n + 1); o[j * n:(j + 1) * n] = -1.0; stages.append(o)
    o = np.zeros(3 * n + 1); o[-1] = 1.0; stages.append(o)
    tc_ref, sc_ref, sl_ref = (C * need).sum(), (STORAGE * need).sum(), (R * need).sum()
    per = W1 * C / tc_ref - W2 * R / sl_ref + W3 * STORAGE / sc_ref
    stages.append(np.concatenate([np.tile(per, 3), [0.0]]) * need.sum())
    x = None
    for i, o in enumerate(stages):
        res = linprog(o, A_ub=np.array(A_ub), b_ub=np.array(b_ub), bounds=bounds, method="highs")
        assert res.status == 0, res.message
        x, val = res.x, res.fun
        if i < len(stages) - 1:
            A_ub.append(o.copy()); b_ub.append(val + 1e-9 * max(1.0, abs(val)) + 1e-7)
    q = x[:n] + x[n:2 * n] + x[2 * n:3 * n]
    short = need - q
    return {"need": need.sum(), "ordered": q.sum(), "short_pieces": short[short > 0].sum(),
            "short_products": int((short > 0.5).sum()), "allocation": allocation,
            "not_in_count": int(sum(k not in stock for k in keys))}


lp_res, below = {}, {}
for label, period in COUNTS.items():
    rows = sbp[sbp["_period"] == period]
    stock_lp = {int(r.product_key): float(r.pieces) for r in rows.itertuples() if not pd.isna(r.pieces)}
    lp_res[label] = solve(stock_lp)
    # dashboard KPI: Tier A with a pending ss_i and a stock row in pieces (no row / no pack size = excluded)
    comp = [k for k in tier_a if k in pend.index and k in stock_lp]
    below[label] = {"below": sum(stock_lp[k] < pend.loc[k, "ss_i"] for k in comp), "comparable": len(comp)}
out["lp"] = lp_res
out["tier_a_below_ss"] = below

# ---- policy card (stored rop_i / ss_i, fresh cost per piece) ----
w = np.array([pool[k] for k in pend.index]) / WPM
c = np.array([cost[k] for k in pend.index])
rule = (3 * w * c).sum()
peak = (pend["rop_i"].to_numpy() * c).sum()
avg = ((pend["ss_i"].to_numpy() + w * REVIEW / 5 / 2) * c).sum()
out["policy"] = {"rule_php": rule, "peak_minus_rule_php": peak - rule, "average_vs_rule_pct": (avg - rule) / rule * 100}

# ---- weeks of cover (stock summed from per-product rows, not the period total) ----
window = [str(p) for p in pd.period_range("2025-03", "2026-02", freq="M")]
mon = ud[ud["calendar_month"].isin(window)].groupby("calendar_month")[["net_amount", "gsv"]].sum(min_count=1)
stock_php = float(sbp[sbp["_period"] == "2026-03"]["stock_value_pesos"].sum())
out["cover"] = {"shown": stock_php / (mon["net_amount"].mean() / WPM), "gsv_matched": stock_php / (mon["gsv"].mean() / WPM),
                "stock_php": stock_php}

(HERE / "independent_recompute.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
print(json.dumps(out, indent=1, default=float))
