"""Run after rebuild2.py: round the rebuilt series to 1e-6 (least-squares leaves ~5.7e-13 where the truth is 0,
which the harness features would count as a sale month). Applied to series_tierA.pkl, series_synth.pkl, series_synth.csv."""
import numpy as np, pandas as pd
S = pd.read_pickle("series_tierA.pkl"); n = 0
for k, (fs, x) in S.items():
    y = np.round(x, 6); n += int((y != x).sum()); S[k] = (fs, y)
pd.to_pickle(S, "series_tierA.pkl")
SS = pd.read_pickle("series_synth.pkl")
for k, (f0, x, ph) in SS.items(): SS[k] = (f0, np.round(x, 6), ph)
pd.to_pickle(SS, "series_synth.pkl")
d = pd.read_csv("series_synth.csv"); d["quantity"] = d.quantity.round(6); d.to_csv("series_synth.csv", index=False)
print("values changed by rounding:", n)
