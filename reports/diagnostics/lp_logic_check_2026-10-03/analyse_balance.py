"""
Stock balance check for the Unilever stock counts (2026-10-03), offline.

    opening count + receipts - sales at the stock's price = closing count

Inputs (no database access here):
  pull/*.csv               pull_data.py and pull_balance.py (DB, read-only)
  ssis_soh_columns.csv     read_ssis_soh.py   (the counts' own workbooks)
  ssis_sales_monthly.csv   read_ssis_sales.py (those workbooks' invoice registers)

No receipt record exists for Unilever in any source (see the README), so the
balance cannot be closed against receipts: what it gives is the receipts each
count IMPLIES (closing - opening + sales), compared with the months before and
with the purchase orders open at the opening count. Implied receipts are an
ESTIMATE derived from real counts and sales, never a record.

Sales are valued on the stock count's price basis. The counts are valued at
"Last Purchase Price (GSV/CS)", without VAT. Two sales series:
  Ilocos Sur register  UL GSV (Unilever's GSV of the goods sold, no VAT), net of
                       credit notes; from the same workbooks as the counts
  La Union SKU file    the demand fact's GSV column (DB; what the LP and the
                       dashboard use); ends 2026-02
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PULL = ROOT / "scratch" / "lp_logic_check_2026-10-03" / "pull"
HERE = Path(__file__).resolve().parent
WEEKS_PER_MONTH = 365.25 / 12 / 7          # analytics/params.py:113-114
COVER_WINDOW = [str(p) for p in pd.period_range("2025-03", "2026-02", freq="M")]   # the dashboard's 12 months
FIG: dict = {}

meta = pd.read_csv(PULL / "snapshot_meta.csv")
counts = meta[meta["principal"] == "unilever"].set_index("_period")[["snapshot_min", "value_pesos"]]
soh = pd.read_csv(HERE / "ssis_soh_columns.csv").set_index("period")
FIG["counts_equal_workbook_soh"] = int(sum(abs(counts.loc[p, "value_pesos"] - soh.loc[p, "stock_value_col_php"]) < 0.01
                                           for p in soh.index if p in counts.index))
FIG["counts_equal_workbook_inventory_sheet"] = int(sum(abs(counts.loc[p, "value_pesos"] - soh.loc[p, "whse_retail_without_vat"]) < 0.01
                                                       for p in soh.index if p in counts.index))
FIG["workbooks"] = len(soh)
FIG["balance_qty_equals_stock_plus_po_minus_open_so"] = int(
    (abs(soh["balance_php"] - (soh["stock_php"] + soh["po_php"] - soh["open_so_php"])) < 1.0).sum())

sales = pd.read_csv(HERE / "ssis_sales_monthly.csv")
ilocos = sales.groupby("month")[["ul_gsv", "gsv", "total_inc_tax"]].sum()           # net of credit notes
ilocos_invoices = sales[~sales["billing"].str.startswith("Credit")].groupby("month")["ul_gsv"].sum()

ud = pd.read_csv(PULL / "unilever_demand_monthly.csv")
lu = ud.groupby("calendar_month")[["gsv", "net_amount"]].sum(min_count=1)

months = [str(p) for p in pd.period_range("2025-04", "2026-03", freq="M")]
rows = []
for m in months:
    prev = str(pd.Period(m, "M") - 1)
    o, c = counts.loc[prev], counts.loc[m]
    s_il = ilocos.loc[m, "ul_gsv"] if m in ilocos.index else np.nan
    s_lu = lu.loc[m, "gsv"] if m in lu.index else np.nan
    rows.append({
        "month": m, "opening_count_date": o["snapshot_min"], "opening_php": o["value_pesos"],
        "closing_count_date": c["snapshot_min"], "closing_php": c["value_pesos"],
        "receipts_recorded_php": None,
        "sales_ilocos_ul_gsv_php": s_il, "sales_la_union_gsv_php": s_lu,
        "la_union_over_ilocos": s_lu / s_il if s_lu == s_lu and s_il == s_il else np.nan,
        "implied_receipts_ilocos_php": c["value_pesos"] - o["value_pesos"] + s_il,
        "implied_receipts_la_union_php": c["value_pesos"] - o["value_pesos"] + s_lu,
        "closing_if_zero_receipts_ilocos_php": o["value_pesos"] - s_il,
        "open_po_at_opening_php": soh.loc[prev, "po_php"] if prev in soh.index else np.nan,
        "open_customer_orders_at_opening_php": soh.loc[prev, "open_so_php"] if prev in soh.index else np.nan,
    })
bal = pd.DataFrame(rows)
bal["implied_over_sales_ilocos"] = bal["implied_receipts_ilocos_php"] / bal["sales_ilocos_ul_gsv_php"]
bal["implied_below_open_po_ilocos"] = bal["implied_receipts_ilocos_php"] < bal["open_po_at_opening_php"]
bal["implied_below_open_po_la_union"] = bal["implied_receipts_la_union_php"] < bal["open_po_at_opening_php"]

# The La Union file's per-SKU negative balances (stock fell by more than its sales explain), from the
# derived_receipt_fact estimate already in the DB (is_demo = true, flag = 'negative_balance').
drf = pd.read_csv(PULL / "derived_receipt_fact_unilever.csv")
neg = drf.assign(neg=drf["flag"].eq("negative_balance")).groupby("_period").agg(skus=("neg", "size"), negative_skus=("neg", "sum"))
bal = bal.merge(neg, left_on="month", right_index=True, how="left")
bal.to_csv(HERE / "balance_monthly.csv", index=False)

base = bal[bal["month"] <= "2026-01"]
last3 = bal[bal["month"].isin(["2025-11", "2025-12", "2026-01"])]
FIG["baseline_months"] = f"{base['month'].min()}..{base['month'].max()} ({len(base)})"
FIG["implied_receipts_ilocos_baseline_php"] = {"min": base["implied_receipts_ilocos_php"].min(),
                                               "median": base["implied_receipts_ilocos_php"].median(),
                                               "max": base["implied_receipts_ilocos_php"].max()}
FIG["implied_over_sales_baseline"] = {"min": base["implied_over_sales_ilocos"].min(),
                                      "median": base["implied_over_sales_ilocos"].median(),
                                      "max": base["implied_over_sales_ilocos"].max()}
FIG["last3"] = last3[["month", "implied_receipts_ilocos_php", "implied_over_sales_ilocos"]].to_dict("records")
fm = bal[bal["month"].isin(["2026-02", "2026-03"])]
FIG["feb_mar"] = {"opening_2026-02-03": float(counts.loc["2026-01", "value_pesos"]),
                  "closing_2026-04-06": float(counts.loc["2026-03", "value_pesos"]),
                  "sales_ilocos": float(fm["sales_ilocos_ul_gsv_php"].sum()),
                  "implied_receipts_ilocos": float(fm["implied_receipts_ilocos_php"].sum())}
FIG["feb_mar"]["implied_over_sales"] = FIG["feb_mar"]["implied_receipts_ilocos"] / FIG["feb_mar"]["sales_ilocos"]
two = [(bal.loc[i, "implied_receipts_ilocos_php"] + bal.loc[i + 1, "implied_receipts_ilocos_php"])
       / (bal.loc[i, "sales_ilocos_ul_gsv_php"] + bal.loc[i + 1, "sales_ilocos_ul_gsv_php"])
       for i in range(len(base) - 1)]
FIG["two_month_implied_over_sales_baseline"] = {"min": min(two), "max": max(two)}
FIG["la_union_over_ilocos"] = {"min": bal["la_union_over_ilocos"].min(), "max": bal["la_union_over_ilocos"].max(),
                               "median": bal["la_union_over_ilocos"].median()}
FIG["months_implied_below_open_po"] = {
    "ilocos": bal.loc[bal["implied_below_open_po_ilocos"], "month"].tolist(),
    "la_union": bal.loc[bal["implied_below_open_po_la_union"], "month"].tolist()}

# ---- Weeks of cover on both counts, matched price basis --------------------------------------
pool = pd.read_csv(HERE / "issue1_stock_timing_per_product.csv")["product_key"]
sbp = pd.read_csv(PULL / "stock_by_period.csv")
sbp = sbp[sbp["principal"] == "unilever"]
w = ud[ud["calendar_month"].isin(COVER_WINDOW)]
pool_month = w[w["product_key"].isin(pool)].groupby("calendar_month")["gsv"].sum(min_count=1)
all_month = w.groupby("calendar_month")["gsv"].sum(min_count=1)
il_window = ilocos.loc[[m for m in COVER_WINDOW if m in ilocos.index], "ul_gsv"]
weekly = {"pool_la_union_gsv": pool_month.mean() / WEEKS_PER_MONTH,
          "all_la_union_gsv": all_month.mean() / WEEKS_PER_MONTH,
          "all_ilocos_ul_gsv": il_window.mean() / WEEKS_PER_MONTH}
cover = []
for period, label in (("2026-02", "2026-03-02"), ("2026-03", "2026-04-06")):
    pool_stock = float(sbp[(sbp["_period"] == period) & sbp["product_key"].isin(pool)]["stock_value_pesos"].sum())
    all_stock = float(counts.loc[period, "value_pesos"])
    cover += [
        {"count": label, "scope": "73 LP products", "stock_php": pool_stock, "sales_basis": "La Union file, GSV",
         "weekly_sales_php": weekly["pool_la_union_gsv"], "weeks": pool_stock / weekly["pool_la_union_gsv"]},
        {"count": label, "scope": "whole count", "stock_php": all_stock, "sales_basis": "La Union file, GSV",
         "weekly_sales_php": weekly["all_la_union_gsv"], "weeks": all_stock / weekly["all_la_union_gsv"]},
        {"count": label, "scope": "whole count", "stock_php": all_stock, "sales_basis": "Ilocos Sur register, UL GSV",
         "weekly_sales_php": weekly["all_ilocos_ul_gsv"], "weeks": all_stock / weekly["all_ilocos_ul_gsv"]},
    ]
cover = pd.DataFrame(cover)
cover.to_csv(HERE / "cover_both_counts.csv", index=False)
FIG["cover_window"] = f"{COVER_WINDOW[0]}..{COVER_WINDOW[-1]}"
FIG["cover_months"] = {"pool_la_union": int(pool_month.notna().sum()), "ilocos": len(il_window)}
FIG["pool_gsv_null_rows"] = int(w[w["product_key"].isin(pool)]["gsv_null"].sum())

(HERE / "balance_figures.json").write_text(json.dumps(FIG, indent=1, default=float), encoding="utf-8")
pd.set_option("display.width", 250)
pd.set_option("display.float_format", lambda v: f"{v:,.2f}")
print(bal.drop(columns=["receipts_recorded_php"]).to_string(index=False))
print(cover.to_string(index=False))
print(json.dumps(FIG, indent=1, default=float))
