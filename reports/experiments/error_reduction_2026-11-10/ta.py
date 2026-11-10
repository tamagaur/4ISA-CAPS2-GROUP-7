"""
reports/experiments/error_reduction_2026-11-10/ta.py - TEMPORAL AGGREGATION (task 2). Backtest only (see lab.py).

    python reports/experiments/error_reduction_2026-11-10/ta.py

Method (ADIDA, Nikolopoulos et al. 2011; MAPA, Kourentzes et al. 2014), fixed before scoring:
  At each forecast month t, the product's history before t (from its first sale) is cut into non-overlapping k-month
  buckets ending at t-1 (the oldest months that do not fill a bucket are dropped). The next bucket's total is forecast with
  simple exponential smoothing (SES) and divided by k (equal disaggregation), then multiplied by the served calendar
  factor of t, exactly as served is. A blank month inside a bucket is skipped (the bucket's mean of the months it has x k).
  SES alpha: fixed 0.3 ('ses03'), or fitted on the buckets before t by least squares on a grid 0.05..0.95 ('sesfit',
  needs >= 3 buckets, else 0.3). Fewer than 2 buckets: served is kept.
  k = 1 is the same SES on months: the control that separates "aggregating" from "smoothing".
  MAPA: the mean of the fitted-SES monthly forecasts over k = 1, 2, 3 ('mapa123') and over k = 1, 2, 3, 4, 6 ('mapa12346').
  Combinations: the mean with S1 (the forecast task 1 serves).
  Layering: 'S1>X' keeps S1's succession and fading treatments (and dead rows) and uses X on every other row.
Robust level, a control for "timing wrong, level right": the median of the last 6 months x calendar factor ('med6').
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab  # noqa: E402

ALPHAS = np.round(np.arange(0.05, 0.951, 0.05), 2)


def buckets(h: np.ndarray, k: int) -> np.ndarray:
    n = (len(h) // k) * k
    if n == 0:
        return np.array([])
    x = h[-n:].reshape(-1, k)
    with np.errstate(invalid="ignore"):
        m = np.nanmean(x, axis=1)
    return m * k


def ses_path(b: np.ndarray, alpha: float) -> tuple[float, float]:
    """(final level = the next-bucket forecast, in-sample one-step SSE)."""
    lvl, sse = b[0], 0.0
    for x in b[1:]:
        if np.isnan(x):
            continue
        sse += (x - lvl) ** 2
        lvl = alpha * x + (1 - alpha) * lvl
    return float(lvl), float(sse)


def ses(b: np.ndarray, alpha: float | None) -> float:
    if alpha is not None or len(b) < 3:
        return ses_path(b, 0.3 if alpha is None else alpha)[0]
    best = min(ALPHAS, key=lambda a: ses_path(b, a)[1])
    return ses_path(b, best)[0]


def candidates(F: dict) -> pd.DataFrame:
    rows, series = F["rows"].copy(), F["series"]
    rec = {c: [] for c in ("ta1_sesfit", "ta2_ses03", "ta3_ses03", "ta2_sesfit", "ta3_sesfit", "ta4_sesfit", "ta6_sesfit",
                           "ta3_ma2", "med6")}
    for r in rows.itertuples():
        h = lab.hist(series[r.product_key], r.t).to_numpy(float)
        h = np.where(np.isnan(h), np.nan, h)
        for k, a, name in ((1, None, "ta1_sesfit"), (2, 0.3, "ta2_ses03"), (3, 0.3, "ta3_ses03"), (2, None, "ta2_sesfit"),
                           (3, None, "ta3_sesfit"), (4, None, "ta4_sesfit"), (6, None, "ta6_sesfit")):
            b = buckets(h, k)
            rec[name].append(max(0.0, ses(b, a) / k * r.cal) if len(b) >= 2 else r.served)
        b = buckets(h, 3)
        rec["ta3_ma2"].append(max(0.0, np.nanmean(b[-2:]) / 3 * r.cal) if len(b) >= 2 else r.served)
        rec["med6"].append(float(np.nanmedian(h[-6:])) * r.cal if len(h) >= 3 else r.served)
    for c, v in rec.items():
        rows[c] = v
    rows["mapa123"] = rows[["ta1_sesfit", "ta2_sesfit", "ta3_sesfit"]].mean(axis=1)
    rows["mapa12346"] = rows[["ta1_sesfit", "ta2_sesfit", "ta3_sesfit", "ta4_sesfit", "ta6_sesfit"]].mean(axis=1)
    keep = rows.cls.isin(["SUCCESSION", "FADING", "DEAD"])
    for c in ("ta2_sesfit", "ta3_sesfit", "ta3_ses03", "mapa123", "mapa12346", "med6", "ta1_sesfit"):
        rows[f"mean(S1,{c})"] = np.where(keep, rows.S1, (rows.S1 + rows[c]) / 2)
        rows[f"S1>{c}"] = np.where(keep, rows.S1, rows[c])
    return rows


def main() -> int:
    F = lab.load()
    df = candidates(F).dropna(subset=["actual"])
    df.to_pickle(lab.LOCAL / "error_reduction_ta_rows_2026-11-10.pkl")
    methods = ["served", "S1", "ta1_sesfit", "ta2_ses03", "ta3_ses03", "ta2_sesfit", "ta3_sesfit", "ta3_ma2", "mapa123",
               "mapa12346", "med6"] + [c for c in df.columns if c.startswith(("mean(S1", "S1>"))]
    t = lab.table(df, methods, F["sc"], F["plan"])
    t.to_csv(lab.HERE / "results_ta.csv", index=False)
    verdict = {f"{s} | {m} vs {b}": lab.gate(t, m, b, s) for s in ("all", "planned") for b in ("served", "S1")
               for m in methods if m != b}
    # Burst sellers first: the BURST2 rows (trailing served MASE >= 1, two-sided errors), as the brief asks.
    burst = df[df.cls == "BURST2"]
    tb = lab.table(burst, methods, F["sc"], F["plan"], lines=False)
    tb.to_csv(lab.HERE / "results_ta_burst2.csv", index=False)
    verdict_b = {f"BURST2 {s} | {m} vs S1": lab.gate(tb, m, "S1", s) for s in ("all", "planned") for m in methods if m != "S1"}
    (lab.HERE / "results_ta_verdicts.json").write_text(json.dumps({"all_rows": verdict, "burst2_rows": verdict_b}, indent=1))
    pd.set_option("display.width", 250)
    print(lab.show(t, "S1"))
    print(json.dumps({k: v for k, v in verdict.items() if "HOLDS" in v}, indent=1))
    print(lab.show(tb, "S1"))
    print(json.dumps({k: v for k, v in verdict_b.items() if "HOLDS" in v or "lower in both" in v}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
