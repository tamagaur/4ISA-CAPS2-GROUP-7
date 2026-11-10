"""The one ranked table of every forecast candidate (results_hunt/extra/combos.csv), written to results_ranked.md.
Rank: the WORSE of the two windows' pooled WAPE difference against S1, all products (consistency first).
Verdict: holds (lab.gate HOLDS, all products) / inside the noise (lower in both, interval or MASE fails) /
one window only / dead (worse in both). Oracles are listed apart: they use the months scored.
    python reports/experiments/error_hunt_2026-11-10/table.py"""
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
frames, verdicts = [], {}
for stem in ("hunt", "extra", "combos"):
    t = pd.read_csv(HERE / f"results_{stem}.csv")
    frames.append(t[t.line == "all months"])
    verdicts.update(json.loads((HERE / f"results_{stem}_verdicts.json").read_text()))
t = pd.concat(frames).drop_duplicates(["window", "set", "method"])


def label(v: str) -> str:
    if v.startswith("HOLDS"):
        return "holds" + (" (strict)" if "strict" in v else "")
    return {"lower in both, inside the noise or MASE higher": "inside the noise",
            "NOT HOLDING (one window only)": "one window only", "worse in both": "dead"}.get(v, v)


rows = []
for m, g in t.groupby("method"):
    if m == "S1":
        continue
    c = {(r.window[:4], r.set): r for r in g.itertuples()}
    try:
        ma, ea, mp, ep = c[("main", "all")], c[("earl", "all")], c[("main", "planned")], c[("earl", "planned")]
    except KeyError:
        continue
    rows.append({"approach": m, "worst": max(ma.d_wape_vs_S1, ea.d_wape_vs_S1),
                 "Main all WAPE (d)": f"{100 * ma.pooled_wape:.2f} ({100 * ma.d_wape_vs_S1:+.2f})",
                 "Main all MASE": f"{ma.mase:.3f}",
                 "Earlier all WAPE (d)": f"{100 * ea.pooled_wape:.2f} ({100 * ea.d_wape_vs_S1:+.2f})",
                 "Earlier all MASE": f"{ea.mase:.3f}",
                 "Main planned WAPE (d)": f"{100 * mp.pooled_wape:.2f} ({100 * mp.d_wape_vs_S1:+.2f})",
                 "Main planned MASE": f"{mp.mase:.3f}",
                 "Earlier planned WAPE (d)": f"{100 * ep.pooled_wape:.2f} ({100 * ep.d_wape_vs_S1:+.2f})",
                 "Earlier planned MASE": f"{ep.mase:.3f}",
                 "Verdict all": label(verdicts.get(m, {}).get("all", "")) if m != "served" else "(the old forecast)",
                 "Verdict planned": label(verdicts.get(m, {}).get("planned", "")) if m != "served" else ""})
r = pd.DataFrame(rows)
r["oracle"] = r.approach.str.startswith("ORACLE")
r = r.sort_values(["oracle", "worst"]).drop(columns=["worst", "oracle"])
base = t[t.method == "S1"].set_index(["window", "set"])
head = ("S1 (served since 2026-11-10): main all {:.2f} / MASE {:.3f}; earlier all {:.2f} / {:.3f}; main planned {:.2f} / {:.3f}; "
        "earlier planned {:.2f} / {:.3f}.").format(
    *[v for w in ("main 2025-09..2026-02", "earlier 2024-01..2025-08") for s in ("all",) for v in
      (100 * base.loc[(w, s)].pooled_wape, base.loc[(w, s)].mase)],
    *[v for w in ("main 2025-09..2026-02", "earlier 2024-01..2025-08") for v in
      (100 * base.loc[(w, "planned")].pooled_wape, base.loc[(w, "planned")].mase)])
cols = list(r.columns)
md = head + "\n\n" + "\n".join(["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
                               + ["| " + " | ".join(str(x) for x in row) + " |" for row in r.itertuples(index=False)])
(HERE / "results_ranked.md").write_text(md + "\n", encoding="utf-8")
print(md)
