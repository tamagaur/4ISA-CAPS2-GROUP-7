"""Compact view of results_hunt.csv: one line per method, both windows x both sets, pooled WAPE delta vs S1 (pts), MASE.
    python reports/experiments/error_hunt_2026-11-10/summarize.py [results_file.csv] [verdicts.json]"""
import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
f = HERE / (sys.argv[1] if len(sys.argv) > 1 else "results_hunt.csv")
v = json.loads((HERE / (sys.argv[2] if len(sys.argv) > 2 else "results_hunt_verdicts.json")).read_text())
t = pd.read_csv(f)
t = t[t.line == "all months"]
out = []
for m, g in t.groupby("method", sort=False):
    rec = {"method": m}
    for _, r in g.iterrows():
        w = "M" if r.window.startswith("main") else "E"
        s = "all" if r.set == "all" else "pl"
        rec[f"{w}{s}_wape"] = round(100 * r.pooled_wape, 2)
        rec[f"{w}{s}_d"] = round(100 * r.d_wape_vs_S1, 2)
        rec[f"{w}{s}_ci"] = f"[{100 * r.ci_lo_vs_S1:+.1f},{100 * r.ci_hi_vs_S1:+.1f}]"
        rec[f"{w}{s}_mase"] = round(r.mase, 3)
    rec["v_all"] = v.get(m, {}).get("all", "")[:22]
    rec["v_pl"] = v.get(m, {}).get("planned", "")[:22]
    out.append(rec)
o = pd.DataFrame(out)
cols = ["method", "Mall_wape", "Mall_d", "Mall_ci", "Mall_mase", "Eall_wape", "Eall_d", "Eall_ci", "Eall_mase",
        "Mpl_d", "Mpl_mase", "Epl_d", "Epl_mase", "v_all", "v_pl"]
pd.set_option("display.width", 250)
print(o[cols].sort_values("Mall_d").to_string(index=False))
