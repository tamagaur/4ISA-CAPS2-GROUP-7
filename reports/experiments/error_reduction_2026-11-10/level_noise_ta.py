"""
reports/experiments/error_reduction_2026-11-10/level_noise_ta.py - POST HOC (after classes2.py and the Knorr scores):
temporal aggregation on the products a rule can find before the month: classes2's LEVEL_NOISE detection (trailing served
MASE >= 1 over the 6 months before t, mean of the last 6 months / the 6 before within 0.85..1.15), treatment MAPA over
k = 1,2,3,4,6 (ta.py) instead of the 12-month mean; also the same detection with no drift condition (all trailing MASE >= 1,
not DEAD/SUCCESSION/FADING/PROMO). Backtest only (see lab.py).
"""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab  # noqa: E402

F = lab.load()
df = pd.read_pickle(lab.LOCAL / "error_reduction_classes2_rows_2026-11-10.pkl")
open_ = df.cls.isin(["NEW", "STABLE", "BURST", "BURST2"])
rules = {"LEVEL_NOISE->mapa12346": open_ & (df.trail_mase >= 1) & df.drift.between(0.85, 1.15),
         "MASE>=1->mapa12346": open_ & (df.trail_mase >= 1),
         "MASE>=1->mean(S1,mapa12346)": open_ & (df.trail_mase >= 1)}
for n, m in rules.items():
    src = df["mean(S1,mapa12346)"] if "mean(" in n else df.mapa12346
    df[n] = np.where(m, src, df.S1)
t = lab.table(df, ["served", "S1"] + list(rules), F["sc"], F["plan"])
v = {f"{s} | {n}": lab.gate(t, n, "S1", s) for s in ("all", "planned") for n in rules}
t.to_csv(lab.HERE / "results_level_noise_ta.csv", index=False)
(lab.HERE / "results_level_noise_ta.json").write_text(json.dumps(v, indent=1))
print(lab.show(t[t.method.isin(list(rules))], "S1")); print(json.dumps(v, indent=1))
