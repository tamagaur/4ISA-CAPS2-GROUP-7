"""
Model audit 2026-10-03 - restated headline (decision 1, 2026-10-03): the same 29 months (2023-10..2026-02) on two
cohorts side by side, in pieces and in pesos. Offline: reads inputs/ and the two cached backtests
(local/served_backtest.pkl from run_audit.py, local/asof_cohort_backtest.csv from quick_checks.py).

  at-the-time cohort  each test month, the products that were Tier A in the month before it (ABC 'single',
                      known when the forecast was made); 337 products; XGBoost pool = the same as-of rule
  today's Tier A      the 107 products of the ~27% figure (Tier A as of 2026-02, scorable 2025-09..2026-02)

Rules fixed before computing (the peso basis of kelvin/forecast-error-business eebd741, run_analysis.prices):
  price per piece = SUM(net_amount) / SUM(quantity) over the product's own scored months, real rows only;
                    "at selling price, VAT-inclusive (value-added tax)"; no price when either sum is not positive
  TOTAL level     = add every product's actual and forecast within a month (pieces x price for pesos), then
                    WAPE over the 29 monthly totals: sum|total forecast - total actual| / sum|total actual|
  surplus         = forecast above actual (pieces x price), shortage = forecast below actual; per month = summed
                    over products, then averaged over the 29 months
  The 107-product column must reproduce eebd741 (followups_results.json, window C) before anything is written.

    ../Capstone-Project/.venv/Scripts/python.exe reports/diagnostics/model_audit_2026-10-03/headline_pesos.py
"""
from __future__ import annotations

import json
import os
import subprocess

import pandas as pd

import common as C
from analytics.forecasting.diagnostic_metrics import wape

SELL = "at selling price, VAT-inclusive (value-added tax)"


def prices(bt: pd.DataFrame, money: pd.DataFrame) -> pd.Series:
    """eebd741 run_analysis.prices: SUM(net_amount) / SUM(quantity) over the product's scored months.
    A blank (NULL) quantity month is skipped in the quantity sum but its pesos count, exactly as there."""
    test = bt[["product_key", "month"]].merge(money, on=["product_key", "month"], how="left")
    g = test.groupby("product_key")[["quantity_raw", "net_amount"]].sum()
    return (g.net_amount / g.quantity_raw).where((g.quantity_raw > 0) & (g.net_amount > 0))


def metrics(bt: pd.DataFrame, px: pd.Series) -> dict:
    m = bt.assign(price=bt.product_key.map(px), forecast=bt.value)
    m["error"] = m.forecast - m.actual
    priced = m[m.price.notna()]
    by = priced.assign(a_p=priced.actual * priced.price, f_p=priced.forecast * priced.price,
                       m_p=priced.ma3 * priced.price, abs_p=priced.error.abs() * priced.price,
                       sur_p=priced.error.clip(lower=0) * priced.price,
                       sho_p=(-priced.error).clip(lower=0) * priced.price).groupby("month")
    tot = by[["a_p", "f_p", "m_p", "abs_p", "sur_p", "sho_p"]].sum()
    pcs = m.groupby("month")[["actual", "forecast", "ma3"]].sum()
    per = m.groupby("product_key").apply(lambda g: pd.Series({"w": wape(g.actual, g.forecast), "w3": wape(g.actual, g.ma3)}),
                                         include_groups=False)
    a = m.actual.abs().sum()
    return {
        "products": int(m.product_key.nunique()), "product_months": int(len(m)), "months": int(m.month.nunique()),
        "median_product_wape_served": float(per.w.median()), "median_product_wape_ma3": float(per.w3.median()),
        "pooled_wape_pcs_served": float(m.error.abs().sum() / a),
        "pooled_wape_pcs_ma3": float((m.ma3 - m.actual).abs().sum() / a),
        "bias_pct_served": float(m.error.sum() / a * 100),
        "share_product_months_over_forecast": float((m.error > 0).mean()),
        "total_wape_pcs_served": wape(pcs.actual, pcs.forecast), "total_wape_pcs_ma3": wape(pcs.actual, pcs.ma3),
        "products_without_price": int(m[m.price.isna()].product_key.nunique()),
        "product_months_without_price": int(m.price.isna().sum()),
        "total_wape_pesos_served": wape(tot.a_p, tot.f_p), "total_wape_pesos_ma3": wape(tot.a_p, tot.m_p),
        "avg_monthly_sales_pesos": float(tot.a_p.mean()), "avg_monthly_miss_pesos": float(tot.abs_p.mean()),
        "avg_monthly_surplus_pesos": float(tot.sur_p.mean()), "avg_monthly_shortage_pesos": float(tot.sho_p.mean()),
        "surplus_share_of_miss_pesos": float(tot.sur_p.sum() / tot.abs_p.sum()),
        "miss_share_of_sales_pesos": float(tot.abs_p.sum() / tot.a_p.abs().sum()),
    }


def main():
    d = C.read("demand_real_all.csv", dtype={"calendar_month": str})
    money = pd.DataFrame({"product_key": d.product_key, "month": pd.to_datetime(d.calendar_month + "-01"),
                          "quantity_raw": d.quantity, "net_amount": d.net_amount})
    fixed = pd.read_pickle(os.path.join(C.LOCAL, "served_backtest.pkl"))
    asof = pd.read_csv(os.path.join(C.LOCAL, "asof_cohort_backtest.csv"))
    asof["month"] = pd.to_datetime(asof.month + "-01")
    res = {"at-the-time cohort (Tier A the month before each test month)": metrics(asof, prices(asof, money)),
           "today's Tier A (Tier A as of 2026-02, the ~27% figure)": metrics(fixed, prices(fixed, money))}

    ref = json.loads(subprocess.run(["git", "-C", C.EEBD_REPO, "show", C.EEBD_REF + "followups_results.json"],
                                    capture_output=True, text=True, check=True).stdout)["window_comparison"]["C: 29 months, bin re-worked"]
    mine = res["today's Tier A (Tier A as of 2026-02, the ~27% figure)"]
    pairs = {"total_wape_pesos_served": "total_wape_pesos_sell", "total_wape_pesos_ma3": "total_ma3_wape_pesos_sell",
             "avg_monthly_surplus_pesos": "avg_monthly_surplus_pesos_sell",
             "avg_monthly_shortage_pesos": "avg_monthly_shortage_pesos_sell",
             "avg_monthly_miss_pesos": "avg_monthly_miss_pesos_sell", "avg_monthly_sales_pesos": "avg_monthly_sales_pesos_sell",
             "surplus_share_of_miss_pesos": "surplus_share_of_miss", "total_wape_pcs_served": "total_wape_pcs",
             "median_product_wape_served": "median_product_wape", "median_product_wape_ma3": "median_product_ma3_wape"}
    gaps = {k: abs(mine[k] - ref[v]) / max(abs(ref[v]), 1e-12) for k, v in pairs.items()}
    if max(gaps.values()) > 1e-6:
        raise SystemExit(f"107-product column does not reproduce eebd741: {gaps}")
    out = pd.DataFrame(res).rename_axis("measure").reset_index()
    def unit(k: str) -> str:
        if "wape" in k or "share" in k:
            return "ratio" + (" (pesos " + SELL + ")" if "pesos" in k else " (pieces)" if "pcs" in k else "")
        if "pct" in k:
            return "% of sum|actual| (pieces)"
        if k.endswith("_pesos"):
            return "pesos per month, " + SELL
        return "count"
    out.insert(1, "unit", out.measure.map(unit))
    out.to_csv(os.path.join(C.HERE, "headline_two_cohorts.csv"), index=False, float_format="%.6f")
    with open(os.path.join(C.HERE, "headline_two_cohorts_check.json"), "w") as fh:
        json.dump({"reproduces_eebd741_window_C_max_relative_gap": max(gaps.values()), "pairs_checked": pairs}, fh, indent=2)
    pd.set_option("display.width", 250)
    print(out.to_string(index=False))
    print("max relative gap vs eebd741:", max(gaps.values()))


if __name__ == "__main__":
    main()
