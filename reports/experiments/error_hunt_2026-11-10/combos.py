"""
reports/experiments/error_hunt_2026-11-10/combos.py - combinations of the candidates that were lower in at least one window,
the headline median product WAPE, and the error by review period. Backtest only (hunt.py / extra.py rows in local/).

    python reports/experiments/error_hunt_2026-11-10/combos.py

Combinations (fixed before scoring, from the single-candidate table): S1_clip with gbm_mix, with S1_td_peso_half, with
S1_bias_c, and all four together (equal mean of the adjustments, as ratios to S1).
Review period: the same served forecasts summed over 2 and 3 consecutive months (S1 at each month, made at that month)
against the actual total; and over the flavour group (hunt.py) per month. NOT the same target as the monthly table: it
says how much of the monthly error is timing inside a longer order cycle.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "error_reduction_2026-11-10"))
import hunt  # noqa: E402
import lab  # noqa: E402


def med_product_wape(d, m):
    g = d.assign(e=(d[m] - d.actual).abs()).groupby("product_key")[["e", "actual"]].sum()
    g = g[g.actual > 0]
    return float((g.e / g.actual).median())


def main() -> int:
    F = hunt.load()
    rows = pd.read_pickle(lab.LOCAL / "error_hunt_rows_extra_2026-11-10.pkl")
    S1 = rows.S1.replace(0, np.nan)
    adj = {c: (rows[c] / S1).fillna(1.0) for c in ("S1_clip", "gbm_mix", "S1_td_peso_half", "S1_bias_c")}
    rows["c_clip_gbm"] = rows.S1 * (adj["S1_clip"] + adj["gbm_mix"]) / 2
    rows["c_clip_td"] = rows.S1 * (adj["S1_clip"] + adj["S1_td_peso_half"]) / 2
    rows["c_clip_bias"] = rows.S1 * (adj["S1_clip"] + adj["S1_bias_c"]) / 2
    rows["c_all4"] = rows.S1 * sum(adj.values()) / 4
    for c in ("c_clip_gbm", "c_clip_td", "c_clip_bias", "c_all4"):
        rows[c] = rows[c].where(rows.S1 > 0, rows.S1)
    methods = ["S1_clip", "gbm_mix", "c_clip_gbm", "c_clip_td", "c_clip_bias", "c_all4"]
    t = lab.table(rows, ["S1"] + methods, F["sc"], F["plan7"], bases=("S1",))
    t.to_csv(HERE / "results_combos.csv", index=False)
    v = {m: {s: lab.gate(t, m, "S1", s) for s in ("all", "planned")} for m in methods}
    (HERE / "results_combos_verdicts.json").write_text(json.dumps(v, indent=1))

    res = {"median_product_wape": {}, "review_period": {}}
    allrows = pd.read_pickle(hunt.OUT_ROWS)
    for wname, (a, b) in lab.WINDOWS.items():
        w = rows[(rows.month >= a) & (rows.month <= b)]
        for sname, sdf in {"all": w, "planned": w[w.product_key.isin(F["plan7"])]}.items():
            res["median_product_wape"][f"{wname} | {sname}"] = {m: med_product_wape(sdf, m) for m in
                                                                ["served", "S1", "S1_clip", "c_clip_gbm", "ORACLE_prodlevel", "ORACLE_colevel"]}
    # review period: sums over k consecutive scored months of the same product (only complete runs)
    r = rows.sort_values(["product_key", "t"])
    for k in (1, 2, 3):
        for wname, (a, b) in lab.WINDOWS.items():
            w = r[(r.month >= a) & (r.month <= b)]
            num = den = 0.0
            for _, g in w.groupby("product_key"):
                g = g.set_index("t")
                for i in range(0, len(g) - k + 1, k):
                    blk = g.iloc[i:i + k]
                    if len(blk) == k and (blk.index[-1] - blk.index[0]).days < 31 * k:
                        num += abs(blk.S1.sum() - blk.actual.sum())
                        den += blk.actual.sum()
            res["review_period"][f"{k} month(s) | {wname}"] = num / den if den else None
    # flavour group per month
    r["gk"] = r.product_key.map(F["gk"])
    for wname, (a, b) in lab.WINDOWS.items():
        w = r[(r.month >= a) & (r.month <= b)]
        g = w.groupby(["gk", "t"])[["S1", "actual"]].sum()
        res["review_period"][f"flavour group, 1 month | {wname}"] = float((g.S1 - g.actual).abs().sum() / g.actual.sum())
    (HERE / "results_combos.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))
    print(json.dumps(v, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
