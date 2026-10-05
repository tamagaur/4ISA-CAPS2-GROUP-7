"""
Arithmetic check of the report's outputs (2026-10-03): totals against the
per-product / per-month rows they summarise. Reads only the CSV/JSON files
beside this script, plus local/ for the policy card's per-product pesos (not
committed). Writes arithmetic_check.csv; exits 1 on any failure.

Tolerances: per-product CSVs are rounded to 2 decimals, so a sum of 73 rows
may differ from an unrounded total by up to 73 x 0.005 = 0.365; the
tolerance is 0.5 pieces or pesos for those, 0.01 for identities on unrounded
columns.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
rows: list[dict] = []


def check(name: str, lhs: float, rhs: float, tol: float) -> None:
    rows.append({"check": name, "lhs": lhs, "rhs": rhs, "diff": lhs - rhs, "tolerance": tol,
                 "pass": abs(lhs - rhs) <= tol})


def full(name: str) -> pd.DataFrame:
    """A per-product table with its price and peso columns: the git-ignored local/ copy (analyse.py CLIENT_COLUMNS).
    Those columns are not committed; without local/, rerun analyse.py."""
    path = HERE / "local" / name
    return pd.read_csv(path if path.exists() else HERE / name)


p1 = pd.read_csv(HERE / "issue1_stock_timing_per_product.csv")
t1 = pd.read_csv(HERE / "issue1_totals.csv").set_index("variant")
for v, tag, count_col in (("closing_count_2026-04-06", "closing", "in_2026-04-06_count"),
                          ("opening_count_2026-03-02", "opening", "in_2026-03-02_count")):
    t = t1.loc[v]
    need, order, short = p1[f"need_with_{tag}_pcs"], p1[f"order_103_{tag}_pcs"], p1[f"short_103_{tag}_pcs"]
    check(f"issue1 {tag}: total need = sum of per-product need", need.sum(), t["need_pcs"], 0.5)
    check(f"issue1 {tag}: ordered = sum of per-product orders", order.sum(), t["ordered_pcs"], 0.5)
    check(f"issue1 {tag}: pieces short = sum of per-product short", short.sum(), t["short_pcs"], 0.5)
    check(f"issue1 {tag}: products short = count of products with short > 0.5", int((short > 0.5).sum()), t["products_short"], 0)
    check(f"issue1 {tag}: per product, need - order = short (max abs gap)", float((need - order - short).abs().max()), 0.0, 0.011)
    check(f"issue1 {tag}: ordered + short = need", t["ordered_pcs"] + t["short_pcs"], t["need_pcs"], 1.0)
    check(f"issue1 {tag}: products ordering 0 = count with need 0", int((need == 0).sum()), t["products_order_0_overstocked"], 0)
    check(f"issue1 {tag}: stock on hand = sum of per-product stock", p1[f"stock_2026-{'04-06' if tag == 'closing' else '03-02'}_pcs"].sum(),
          t["stock_on_hand_pcs"], 0.5)
    check(f"issue1 {tag}: not in count = count of products missing from the count", int((~p1[count_col]).sum()),
          t["not_in_count_counted_as_0"], 0)
    check(f"issue1 {tag}: Tier A below SS = count in per-product list", int(p1[f"below_ss_at_{tag}"].sum()), t["tier_a_below_ss"], 0)
    check(f"issue1 {tag}: Tier A comparable = products in the count", int(p1[count_col].sum()), t["tier_a_comparable"], 0)
    stock_col = f"stock_2026-{'04-06' if tag == 'closing' else '03-02'}_pcs"
    listed = p1[p1[count_col]]
    check(f"issue1 {tag}: below-SS flag = stock < safety stock, per product (mismatches)",
          int(((listed[stock_col] < listed["safety_stock_pcs"]) != listed[f"below_ss_at_{tag}"]).sum()), 0, 0)
    check(f"issue1 {tag}: per product need = max(0, forecast + target - stock) (max abs gap)",
          float((p1[f"need_with_{tag}_pcs"] - (p1["forecast_mar2026_pcs"] + p1["target_stock_pcs"] - p1[stock_col]).clip(lower=0)).abs().max()),
          0.0, 0.011)

b = pd.read_csv(HERE / "balance_monthly.csv")
for r in b.itertuples():
    check(f"balance {r.month}: implied (Ilocos) = closing - opening + sales",
          r.implied_receipts_ilocos_php, r.closing_php - r.opening_php + r.sales_ilocos_ul_gsv_php, 0.01)
    check(f"balance {r.month}: closing if no receipts = opening - sales", r.closing_if_zero_receipts_ilocos_php,
          r.opening_php - r.sales_ilocos_ul_gsv_php, 0.01)
    if pd.notna(r.sales_la_union_gsv_php):
        check(f"balance {r.month}: implied (La Union) = closing - opening + sales",
              r.implied_receipts_la_union_php, r.closing_php - r.opening_php + r.sales_la_union_gsv_php, 0.01)
for prev, cur in zip(b["month"][:-1], b["month"][1:]):
    check(f"balance {cur}: opening = previous month's closing",
          float(b.loc[b.month == cur, "opening_php"].iloc[0]), float(b.loc[b.month == prev, "closing_php"].iloc[0]), 0.01)
f5 = json.loads((HERE / "balance_figures.json").read_text(encoding="utf-8"))
fm = b[b["month"].isin(["2026-02", "2026-03"])]
check("balance Feb+Mar: implied total = the two months added", f5["feb_mar"]["implied_receipts_ilocos"],
      fm["implied_receipts_ilocos_php"].sum(), 0.01)
check("balance Feb+Mar: implied total = 6 Apr - 3 Feb + Feb and Mar sales", f5["feb_mar"]["implied_receipts_ilocos"],
      f5["feb_mar"]["closing_2026-04-06"] - f5["feb_mar"]["opening_2026-02-03"] + f5["feb_mar"]["sales_ilocos"], 0.01)
ss = pd.read_csv(HERE / "ssis_sales_monthly.csv").groupby("month")["ul_gsv"].sum()
check("balance 2026-03: March sales = SSIS MARCH 2026.xlsx register total (UL GSV)",
      float(b.loc[b.month == "2026-03", "sales_ilocos_ul_gsv_php"].iloc[0]), float(ss["2026-03"]), 0.01)

p4 = full("issue4_policy_card_per_product.csv")
t4 = pd.read_csv(HERE / "issue4_policy_card_totals.csv").set_index("measure")["value"]
check("policy: rule = sum of per-product rule pesos", p4["rule_3wk_php"].sum(), t4["rule_3wk"], 0.5)
check("policy: peak = sum of per-product peak pesos", p4["peak_target_php"].sum(), t4["peak_targets"], 0.5)
check("policy: average = sum of per-product average pesos", p4["avg_target_php"].sum(), t4["average_targets"], 0.5)
check("policy: peak - rule = stated difference", t4["peak_targets"] - t4["rule_3wk"], t4["peak_minus_rule"], 0.01)
check("policy: average - rule = stated difference", t4["average_targets"] - t4["rule_3wk"], t4["average_minus_rule"], 0.01)
# Per row, the CSV holds pieces to 2 decimals and price per piece to 4, so a product recomputed from it can be off
# by up to pieces x 0.00005 + price x 0.005 (+ the peso column's own 0.005): checked as gap minus that bound <= 0.
def excess(pesos, pieces, price):
    return float(((pesos - pieces * price).abs() - (pieces.abs() * 0.00005 + price.abs() * 0.005 + 0.005)).max())


check("policy: per product, peak pesos = order-up-to x price (max gap beyond display rounding)",
      max(0.0, excess(p4["peak_target_php"], p4["order_up_to_pcs"], p4["cost_per_piece_php"])), 0.0, 0.0)
check("policy: per product, average pesos = (SS + weekly / 2) x price (max gap beyond display rounding)",
      max(0.0, excess(p4["avg_target_php"], p4["safety_stock_pcs"] + p4["weekly_pcs"] / 2, p4["cost_per_piece_php"])), 0.0, 0.0)
check("policy: per product, rule pieces = 3 x weekly (max abs gap)",
      float((p4["rule_3wk_pcs"] - 3 * p4["weekly_pcs"]).abs().max()), 0.0, 0.02)
check("policy: stock at 2026-04-06 = sum of per-product stock pesos", p4["stock_2026-04-06_php"].sum(),
      t4["ssm_stock_2026-04-06"], 0.5)

for name, csv in (("cover (issue 3)", "issue3_weeks_of_cover.csv"),):
    c = pd.read_csv(HERE / csv)
    stock = 22700825.83
    shown = c.iloc[0]
    check(f"{name}: shown weeks = stock / weekly sales", shown["weeks"], stock / shown["weekly_sales_php_or_pcs"], 1e-6)
    check(f"{name}: GSV weeks = shown weeks / ratio", c.iloc[1]["weeks"], shown["weeks"] / c.iloc[1]["ratio_sales_to_shown_basis"], 1e-6)
cb = pd.read_csv(HERE / "cover_both_counts.csv")
for r in cb.itertuples():
    check(f"cover {r.count} {r.scope} / {r.sales_basis}: weeks = stock / weekly", r.weeks, r.stock_php / r.weekly_sales_php, 1e-9)

out = pd.DataFrame(rows)
out.to_csv(HERE / "arithmetic_check.csv", index=False)
print(out[~out["pass"]].to_string(index=False) if (~out["pass"]).any() else "all passed")
print(f"{int(out['pass'].sum())}/{len(out)} checks pass")
sys.exit(0 if out["pass"].all() else 1)
