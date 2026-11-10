"""
reports/experiments/error_reduction_2026-11-10/classes2.py - more forecastability classes (task 6), layered on S1. Backtest
only (see lab.py). Rules and treatments are fixed in this header before the first scoring run; history strictly before t,
blank months read as 0 as in classify.py. A rule applies only to rows that S1 leaves on the served forecast (classes NEW,
STABLE, BURST, BURST2; never DEAD, SUCCESSION, FADING), and, unless named, not to PROMO/LOW.

  SOFTFADE_x   collapse ratio (last-3 mean / last-12 mean) in [0.5, x), x in {0.6, 0.7, 0.8}: the fading rule's treatment,
               min(served, last-3 mean), one step earlier in a decline. Three thresholds reported, none chosen on a window.
  FADE_LAST    FADING rows get min(served, last month) instead of min(served, last-3 mean) (classify.py's variant).
  RISING       collapse ratio >= 1.25 (last 3 months well above the last 12): max(served, last-3 mean x calendar factor).
  POST_SPIKE   last month > 2 x median of the 6 months before it: min(served, median of the last 6 months x calendar factor)
               (do not chase a spike that just happened).
  LEVEL_NOISE  trailing served MASE >= 1 over the 6 months before t (>= 4 scored, classify.burst_v2) AND no drift (mean of the
               last 6 months / mean of the 6 before within 0.85..1.15): the product's own 12-month mean x calendar factor.
  PROMO_MED    PROMO/LOW rows: median of the last 6 months x calendar factor (bundles switch on and off; the median ignores
               the on-off months that a mean chases).
Each is scored alone on top of S1, and the ones that hold are scored together ('S2').
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab  # noqa: E402


def features(F: dict, df: pd.DataFrame) -> pd.DataFrame:
    W = F["W"].fillna(0.0)
    rec = []
    for r in df.itertuples():
        h = W.loc[W.index < r.t, r.product_key]
        nz = np.flatnonzero(h.to_numpy() > 0)
        h = h.iloc[nz[0]:].to_numpy() if len(nz) else np.array([])
        n = len(h)
        rec.append({"f_last": h[-1] if n else 0.0, "f_m3": h[-3:].mean() if n else 0.0, "f_m12": h[-12:].mean() if n else 0.0,
                    "f_med6": float(np.median(h[-6:])) if n else 0.0,
                    "spike": bool(n >= 7 and np.median(h[-7:-1]) > 0 and h[-1] > 2 * np.median(h[-7:-1])),
                    "drift": (h[-6:].mean() / h[-12:-6].mean()) if n >= 12 and h[-12:-6].mean() > 0 else np.nan,
                    "cr": (h[-3:].mean() / h[-12:].mean()) if n > 3 and h[-12:].mean() > 0 else np.nan})
    return pd.concat([df.reset_index(drop=True), pd.DataFrame(rec)], axis=1)


def main() -> int:
    F = lab.load()
    df = features(F, pd.read_pickle(lab.LOCAL / "error_reduction_ta_rows_2026-11-10.pkl"))
    open_ = df.cls.isin(["NEW", "STABLE", "BURST", "BURST2"])
    rules = {}
    for x in (0.6, 0.7, 0.8):
        m = open_ & (df.cr >= 0.5) & (df.cr < x)
        rules[f"SOFTFADE_{x}"] = (m, np.minimum(df.S1, df.f_m3))
    rules["FADE_LAST"] = (df.cls == "FADING", np.minimum(df.served, df["f_last"]))
    rules["RISING"] = (open_ & (df.cr >= 1.25), np.maximum(df.S1, df.f_m3 * df.cal))
    rules["POST_SPIKE"] = (open_ & df.spike, np.minimum(df.S1, df.f_med6 * df.cal))
    rules["LEVEL_NOISE"] = (open_ & (df.trail_mase >= 1) & df.drift.between(0.85, 1.15), df.f_m12 * df.cal)
    rules["PROMO_MED"] = (df.cls == "PROMO/LOW", df.f_med6 * df.cal)
    for name, (mask, val) in rules.items():
        df[name] = np.where(mask, val, df.S1)
        df[f"_hit_{name}"] = mask
    methods = ["served", "S1"] + list(rules)
    t = lab.table(df, methods, F["sc"], F["plan"])
    verdict = {f"{s} | {m}": lab.gate(t, m, "S1", s) for s in ("all", "planned") for m in rules}
    hits = {}
    for wname, (a, b) in lab.WINDOWS.items():
        w = df[(df.month >= a) & (df.month <= b)]
        hits[wname] = {n: {"product_months": int(w[f"_hit_{n}"].sum()), "products": int(w[w[f"_hit_{n}"]].product_key.nunique())}
                       for n in rules}
    held = [n for n in rules if verdict[f"all | {n}"].startswith("HOLDS") and not verdict[f"planned | {n}"].startswith("worse")]
    s2 = df.S1.copy()
    for n in held:
        s2 = pd.Series(np.where(df[f"_hit_{n}"], df[n], s2))
    df["S2"] = s2.to_numpy()
    t2 = lab.table(df, ["served", "S1", "S2"], F["sc"], F["plan"])
    t = pd.concat([t, t2[t2.method == "S2"]])
    t.to_csv(lab.HERE / "results_classes2.csv", index=False)
    v2 = {f"{s} | S2 ({'+'.join(held) or 'nothing held'})": lab.gate(t2, "S2", "S1", s) for s in ("all", "planned")}
    v2.update({f"{s} | S2 vs served": lab.gate(t2, "S2", "served", s) for s in ("all", "planned")})
    (lab.HERE / "results_classes2.json").write_text(json.dumps({"verdicts": verdict, "hits": hits, "held": held, "S2": v2},
                                                               indent=1))
    df.to_pickle(lab.LOCAL / "error_reduction_classes2_rows_2026-11-10.pkl")
    pd.set_option("display.width", 250)
    print(lab.show(t, "S1"))
    print(json.dumps({"verdicts": verdict, "hits": hits, "held": held, "S2": v2}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
