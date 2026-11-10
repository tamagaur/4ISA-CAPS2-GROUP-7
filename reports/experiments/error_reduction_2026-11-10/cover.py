"""
reports/experiments/error_reduction_2026-11-10/cover.py - STOCK COVER AS A CURVE (task 3). Backtest only (see lab.py).

    python reports/experiments/error_reduction_2026-11-10/cover.py

Population: the product-months where the plan's own entry test fails at forecast time, i.e. the served forecast's trailing
MASE over the 6 months before t is >= 1 (>= 4 scored months, classify.burst_v2's trail_mase), not DEAD, with >= 12 months of
history (so every percentile reads 12 months). BURST2 (the same test with two-sided errors) is reported as a subset.
Policy, as in classify.inventory: monthly review, zero lead time, lost sales, no stock carried between months (each month's
order-up-to level S is compared with that month's demand). Fill rate = sum min(S, a) / sum a; months short = share of months
with a > S; leftover = sum max(S - a, 0) / sum a, in months of sales; mean target in pieces.
Curves:
  COVER p      S = the p-th percentile (numpy linear) of the last 12 months, p in 80, 85, 90, 95, 97, 98, 99, 100 (the brief's
               90..99 plus two below and the maximum, for the shape). With 12 points, p97..p99 sit between the two largest
               months, so they converge on the maximum.
  FORECAST z   S = S1 + z x sigma, sigma = RMSE of S1's own errors on the product's earlier frame months (>= 3), else the
               standard deviation of the last 12 months; z for the same service levels (normal quantiles).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab  # noqa: E402

PCTS = [80, 85, 90, 95, 97, 98, 99, 100]


def main() -> int:
    F = lab.load()
    df = pd.read_pickle(lab.LOCAL / "error_reduction_ta_rows_2026-11-10.pkl").sort_values(["product_key", "month"])
    W = F["W"].fillna(0.0)
    sig, q = [], {p: [] for p in PCTS}
    n12 = []
    errs: dict = {}
    for r in df.itertuples():
        e = errs.setdefault(r.product_key, [])
        h = W.loc[W.index < r.t, r.product_key]
        nz = np.flatnonzero(h.to_numpy() > 0)
        h = h.iloc[nz[0]:].to_numpy() if len(nz) else np.array([])
        n12.append(len(h) >= 12)
        last12 = h[-12:]
        for p in PCTS:
            q[p].append(float(np.percentile(last12, p)) if len(h) >= 12 else np.nan)
        sig.append(float(np.sqrt(np.mean(np.square(e)))) if len(e) >= 3 else (float(last12.std()) if len(h) >= 3 else np.nan))
        if r.actual == r.actual:
            e.append(r.S1 - r.actual)
    df["sigma"], df["h12"] = sig, n12
    for p in PCTS:
        df[f"p{p}"] = q[p]
    pop = df[(df.trail_mase >= 1) & (df.cls != "DEAD") & df.h12 & df.actual.notna()]
    out = {}
    for wname, (a, b) in lab.WINDOWS.items():
        w0 = pop[(pop.month >= a) & (pop.month <= b)]
        for sname, w in {"all": w0, "planned": w0[w0.product_key.isin(F["plan"])],
                         "BURST2 subset": w0[w0.cls == "BURST2"]}.items():
            if w.empty:
                continue
            A = w.actual.to_numpy()
            res = {"product_months": int(len(w)), "products": int(w.product_key.nunique()), "curve": []}
            for p in PCTS:
                for kind, S in (("cover", w[f"p{p}"].to_numpy()),
                                ("forecast", np.maximum(0, w.S1.to_numpy() + (norm.ppf(p / 100) if p < 100 else 3.09)
                                                         * np.nan_to_num(w.sigma.to_numpy())))):
                    res["curve"].append({"policy": kind, "level": p,
                                         "fill_rate": round(float(np.minimum(S, A).sum() / A.sum()), 4),
                                         "months_short_pct": round(float(100 * (A > S).mean()), 1),
                                         "leftover_months_of_sales": round(float(np.maximum(S - A, 0).sum() / A.sum()), 3),
                                         "mean_target_pieces": round(float(S.mean()))})
            out[f"{wname} | {sname}"] = res
    (lab.HERE / "results_cover_curve.json").write_text(json.dumps(out, indent=1))
    for k, v in out.items():
        print(f"\n{k}: {v['products']} products, {v['product_months']} product-months")
        c = pd.DataFrame(v["curve"]).pivot(index="level", columns="policy",
                                           values=["months_short_pct", "leftover_months_of_sales", "fill_rate"])
        print(c.to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
