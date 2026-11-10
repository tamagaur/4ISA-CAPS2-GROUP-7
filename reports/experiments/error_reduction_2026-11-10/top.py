"""
reports/experiments/error_reduction_2026-11-10/top.py - the products that carry the error (tasks 4 and 5). Backtest only.

    python reports/experiments/error_reduction_2026-11-10/top.py

TOP: products ranked by the served forecast's absolute error in the main window (2025-09..2026-02); the first 13 carry half
of it (4,520,004 pieces), the first 42 carry 80%. HIGH-MAPE: the planned products (lp_run 6) whose served MAPE in the main
window is over 100%. For each: classes by month, served / S1 / best candidate error, and the shape of the series (written
to local/, per product: hard rule 9). The committed JSON holds counts and rules only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab  # noqa: E402
from analytics.forecasting.diagnostic_metrics import mape  # noqa: E402

CANDS = ["served", "S1", "mean(S1,mapa12346)", "mean(S1,med6)", "ta3_sesfit", "naive", "t_ma12", "t_family"]


def profile(s: pd.Series, t0="2023-01", t1="2026-02") -> dict:
    """Shape descriptors of the whole real series (descriptive only; never fed to a forecast)."""
    x = s[(s.index >= f"{t0}-01") & (s.index <= f"{t1}-01")].fillna(0.0)
    nz = np.flatnonzero(x.to_numpy() > 0)
    x = x.iloc[nz[0]:] if len(nz) else x
    v = x.to_numpy()
    med = float(np.median(v)) if len(v) else 0.0
    spikes = int((v > 2 * med).sum()) if med > 0 else 0
    d = np.diff(v)
    ac1 = float(pd.Series(d).autocorr(1)) if len(d) > 3 else np.nan
    h1, h2 = v[: len(v) // 2].mean(), v[len(v) // 2:].mean()
    return {"months": len(v), "median": med, "cv": float(v.std() / v.mean()) if v.mean() else np.nan,
            "spike_months_gt2x_median": spikes, "zero_months": int((v == 0).sum()),
            "diff_autocorr_lag1": ac1, "second_half_over_first": float(h2 / h1) if h1 else np.nan,
            "max_over_median": float(v.max() / med) if med else np.nan}


def per_product(w: pd.DataFrame, k: int) -> dict:
    g = w[w.product_key == k]
    out = {"months": int(len(g)), "classes": g.cls.value_counts().to_dict(),
           "actual_pieces": float(g.actual.sum())}
    for c in CANDS:
        if c in g:
            e = g[c] - g.actual
            out[c] = {"abs_err": float(e.abs().sum()), "bias": float(e.sum() / g.actual.sum()) if g.actual.sum() else np.nan,
                      "mape": mape(g.actual.to_numpy(), g[c].to_numpy())}
    return out


def main() -> int:
    F = lab.load()
    df = pd.read_pickle(lab.LOCAL / "error_reduction_ta_rows_2026-11-10.pkl")
    meta, series, plan = F["meta"], F["series"], F["plan"]
    a, b = lab.WINDOWS["main 2025-09..2026-02"]
    w = df[(df.month >= a) & (df.month <= b)].copy()
    w["ae"] = (w.served - w.actual).abs()
    rank = w.groupby("product_key").ae.sum().sort_values(ascending=False)
    share = rank.cumsum() / rank.sum()
    top13 = list(rank.index[:13])
    top42 = list(rank.index[: int((share < 0.8).sum()) + 1])
    pm = w[w.product_key.isin(plan)].groupby("product_key").apply(
        lambda g: mape(g.actual.to_numpy(), g.served.to_numpy()), include_groups=False)
    hi = list(pm[pm > 1].index)
    detail = {}
    for k in dict.fromkeys(top13 + hi):
        detail[int(k)] = {"name": meta.at[k, "name"], "brand": meta.at[k, "brand"], "cat": meta.at[k, "cat"],
                          "planned": k in plan, "plan_q": F["plan_q"].get(k), "in_top13": k in top13, "high_mape": k in hi,
                          "served_error_share_main": float(rank.get(k, 0) / rank.sum()),
                          "served_mape_main": float(pm.get(k, np.nan)) if k in pm else None,
                          "main": per_product(w, k), "shape": profile(series[k]),
                          "monthly_main": w[w.product_key == k][["month", "actual", "served", "S1", "cls"]].round(0).to_dict("records")}
    (lab.LOCAL / "error_reduction_top_detail_2026-11-10.json").write_text(json.dumps(detail, indent=1, default=str))
    summ = {"main_window_abs_error_served": float(rank.sum()), "n_for_50pct": len(top13), "n_for_80pct": len(top42),
            "top13_share": float(rank.iloc[:13].sum() / rank.sum()),
            "top13_S1_abs_error": float((w[w.product_key.isin(top13)].S1 - w[w.product_key.isin(top13)].actual).abs().sum()),
            "top13_served_abs_error": float(rank.iloc[:13].sum()),
            "top13_planned": int(sum(k in plan for k in top13)), "high_mape_planned": len(hi),
            "high_mape_overlap_top13": int(len(set(hi) & set(top13)))}
    print(json.dumps(summ, indent=1))
    for k, d in detail.items():
        m = d["main"]
        print(f"{k:>6} {d['name'][:44]:44} top13={d['in_top13']!s:5} hiMAPE={d['high_mape']!s:5} plan={d['planned']!s:5} "
              f"share={100*d['served_error_share_main']:.1f}% cls={m['classes']} "
              f"err S={m['served']['abs_err']:.0f} S1={m['S1']['abs_err']:.0f} mapa={m['mean(S1,mapa12346)']['abs_err']:.0f} "
              f"ma12={m['t_ma12']['abs_err']:.0f} naive={m['naive']['abs_err']:.0f} biasS={100*m['served']['bias']:.0f}% "
              f"mapeS={100*(m['served']['mape'] or 0):.0f}% | cv={d['shape']['cv']:.2f} spikes={d['shape']['spike_months_gt2x_median']} "
              f"zeros={d['shape']['zero_months']} h2/h1={d['shape']['second_half_over_first']:.2f} max/med={d['shape']['max_over_median']:.1f}")
    json.dump(summ, open(lab.HERE / "results_top_summary.json", "w"), indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
