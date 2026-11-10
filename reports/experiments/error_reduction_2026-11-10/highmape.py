"""
reports/experiments/error_reduction_2026-11-10/highmape.py - task 5: the planned products (lp_run 6) whose served MAPE in
2025-09..2026-02 is over 100%. What they share, and the precision and recall of rules that use only history before each
month. Backtest only (see lab.py). Aggregates to results_highmape.json; per product to local/.
Rules (fixed before scoring): R_PROMO = promo/bundle name (treatments.PROMO_NAME_RE); R_S1 = succession or fading fired in
any main-window month; R_SMALL = mean monthly actual of the 12 months before the window < 2,000 pieces; R_ANY = any of them.
"""
import json, re, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab  # noqa: E402
from analytics.forecasting.diagnostic_metrics import mape  # noqa: E402
from analytics.forecasting.treatments import PROMO_NAME_RE  # noqa: E402

F = lab.load()
df = pd.read_pickle(lab.LOCAL / "error_reduction_classes2_rows_2026-11-10.pkl")
w = df[(df.month >= "2025-09") & (df.month <= "2026-02") & df.product_key.isin(F["plan"])]
W = F["W"].fillna(0.0)
rows = []
for k, g in w.groupby("product_key"):
    pre = W.loc[(W.index >= "2024-09-01") & (W.index < "2025-09-01"), k]
    name = F["meta"].at[k, "name"]
    ratio = (g.actual / g.served.replace(0, np.nan))
    rows.append({"product_key": k, "name": name,
                 "mape_served": mape(g.actual.to_numpy(), g.served.to_numpy()),
                 "mape_S1": mape(g.actual.to_numpy(), g.S1.to_numpy()),
                 "mape_promo_med": mape(g.actual.to_numpy(), g.PROMO_MED.to_numpy()),
                 "abs_err_served": float((g.served - g.actual).abs().sum()), "abs_err_S1": float((g.S1 - g.actual).abs().sum()),
                 "min_actual_over_forecast": float(ratio.min()), "months_actual_lt_quarter_forecast": int((ratio < 0.25).sum()),
                 "R_PROMO": bool(re.search(PROMO_NAME_RE, name)), "R_S1": bool(g.cls.isin(["SUCCESSION", "FADING"]).any()),
                 "R_SMALL": bool(pre.mean() < 2000), "pre_mean": float(pre.mean())})
p = pd.DataFrame(rows)
p["high"] = p.mape_served > 1
p["R_ANY"] = p.R_PROMO | p.R_S1 | p.R_SMALL
res = {"planned_in_window": len(p), "high_mape": int(p.high.sum()),
       "high_mape_with_a_month_below_quarter_of_forecast": int((p.high & (p.months_actual_lt_quarter_forecast > 0)).sum()),
       "others_with_such_a_month": int((~p.high & (p.months_actual_lt_quarter_forecast > 0)).sum()),
       "abs_err_share_of_planned_served": float(p[p.high].abs_err_served.sum() / p.abs_err_served.sum()),
       "high_mape_still_over_100_with_S1": int((p.high & (p.mape_S1 > 1)).sum()),
       "rules": {}}
for r in ("R_PROMO", "R_S1", "R_SMALL", "R_ANY"):
    res["rules"][r] = {"catches_high": int((p.high & p[r]).sum()), "flags_others": int((~p.high & p[r]).sum()),
                       "precision": round(float((p.high & p[r]).sum() / max(p[r].sum(), 1)), 3)}
promo = p[p.high & p.R_PROMO]
res["promo_high_median_mape"] = {"served": float(promo.mape_served.median()), "promo_med": float(promo.mape_promo_med.median())}
(lab.HERE / "results_highmape.json").write_text(json.dumps(res, indent=1))
p.sort_values("mape_served", ascending=False).to_csv(lab.LOCAL / "error_reduction_highmape_2026-11-10.csv", index=False)
print(json.dumps(res, indent=1))
print(p[p.high].sort_values("mape_served", ascending=False)[["product_key", "name", "mape_served", "mape_S1", "mape_promo_med",
      "abs_err_served", "abs_err_S1", "months_actual_lt_quarter_forecast", "R_PROMO", "R_S1", "R_SMALL", "pre_mean"]].round(2).to_string())

# Added after the first run (labelled post hoc): R_ONOFF = in the 12 months before the window (from the first sale), a month
# below a quarter of that 12-month mean - an on/off history.
def onoff(k):
    h = W.loc[W.index < "2025-09-01", k]
    nz = np.flatnonzero(h.to_numpy() > 0)
    h = h.iloc[nz[0]:].tail(12) if len(nz) else h.iloc[:0]
    return bool(len(h) >= 6 and (h < 0.25 * h.mean()).any())
p["R_ONOFF"] = p.product_key.map(onoff)
for r in ("R_ONOFF",):
    res["rules"][r + " (post hoc)"] = {"catches_high": int((p.high & p[r]).sum()), "flags_others": int((~p.high & p[r]).sum()),
                                        "precision": round(float((p.high & p[r]).sum() / max(p[r].sum(), 1)), 3)}
p["R_PROMO_OR_ONOFF"] = p.R_PROMO | p.R_ONOFF
res["rules"]["R_PROMO or R_ONOFF (post hoc)"] = {"catches_high": int((p.high & p.R_PROMO_OR_ONOFF).sum()),
    "flags_others": int((~p.high & p.R_PROMO_OR_ONOFF).sum()),
    "precision": round(float((p.high & p.R_PROMO_OR_ONOFF).sum() / max(p.R_PROMO_OR_ONOFF.sum(), 1)), 3)}
(lab.HERE / "results_highmape.json").write_text(json.dumps(res, indent=1))
print({k: v for k, v in res["rules"].items() if "post hoc" in k})
print(p[p.high][["product_key", "R_ONOFF"]].T.to_string())
