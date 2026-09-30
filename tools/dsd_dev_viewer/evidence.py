"""
tools/dsd_dev_viewer/evidence.py - data for the viewer's Evidence tab.

Reads reports/evidence/ only: PREREGISTERED.csv (the criteria, committed before any
computation), AMENDMENTS.csv, and each chart's chNN.json plus the CSVs it draws.
Nothing is queried or recomputed here - every number on the tab was written by a
script under scripts/evidence/ and carries that script and its code commit.

The build stops if a pre-registered chart that is not marked NOT BUILT has no
result file, or a result names a CSV that is missing.
"""
from __future__ import annotations

import csv
import json
import os

# Which of each chart's CSVs the page draws (the others stay on disk as evidence).
DRAWN = {
    1: {"lines": None, "verdicts": None,
        "sku_series": ["pk", "sku_code", "product_name", "month", "bin", "actual", "ma3", "tsb", "ens_xgb_ma3@A", "sba", "naive"]},
    2: {"lines": None, "verdicts": ["family", "k", "window", "verdict", "n", "model_wape", "base_wape", "ci_lo", "ci_hi",
                                    "n_better", "n_worse"]},
    3: {"lines": None, "verdicts": None},
    4: {"lines": None, "verdicts": None},
    5: {"rates": None},
    6: {"skus": None, "months": None},
    7: {"curve": ["principal", "method", "period", "rank", "n_items", "rank_share", "label", "tier", "revenue_share",
                  "cumulative_share"], "tiers": None, "unilever_moves": None},
    8: {"totals": None, "diff_vs_0929": None},
    9: {"grid": ["w1", "w2", "w3", "n_short", "shortfall", "order_cost", "is_default", "neighbour", "cut_set_differs",
                 "short_skus"]},
    10: {"curve": None},
    11: {"index": ["principal", "series", "year", "moy", "month", "net_amount", "rows", "index", "months_in_year",
                   "partial_year"], "pairs": None, "rows_by_year": None},
}


def _cell(v: str):
    if v == "":
        return None
    if v in ("True", "False"):
        return v == "True"
    try:
        f = float(v)
    except ValueError:
        return v
    return int(f) if f.is_integer() and "." not in v and "e" not in v.lower() else f


def _table(path: str, cols=None) -> dict:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        r = csv.reader(fh)
        head = next(r)
        keep = [head.index(c) for c in (cols or head)]
        return {"cols": [head[i] for i in keep], "rows": [[_cell(row[i]) for i in keep] for row in r]}


def load(repo: str) -> dict:
    ev = os.path.join(repo, "reports", "evidence")
    with open(os.path.join(ev, "PREREGISTERED.csv"), encoding="utf-8-sig", newline="") as fh:
        prereg = list(csv.DictReader(fh))
    with open(os.path.join(ev, "AMENDMENTS.csv"), encoding="utf-8-sig", newline="") as fh:
        amend = list(csv.DictReader(fh))
    charts, problems = [], []
    for p in prereg:
        n = int(p["chart"])
        path = os.path.join(ev, f"ch{n:02d}.json")
        if not os.path.isfile(path):
            if p["otherwise"] == "NOT BUILT":
                charts.append({"chart": n, "title": p["title"], "verdict": "NOT BUILT", "criterion": p["flawed_if"],
                               "otherwise": p["otherwise"], "mase_gate_used": p["mase_gate_used"],
                               "rerun_after_5f": p["rerun_after_5f"], "checks": [], "data": {}, "files": {}})
                continue
            problems.append(f"chart {n}: {os.path.relpath(path, repo)} missing")
            continue
        with open(path, encoding="utf-8") as fh:
            meta = json.load(fh)
        data = {}
        for key, cols in DRAWN.get(n, {}).items():
            rel = meta["files"].get(key)
            if not rel or not os.path.isfile(os.path.join(repo, rel)):
                problems.append(f"chart {n}: file '{key}' ({rel}) missing")
                continue
            data[key] = _table(os.path.join(repo, rel), cols)
        meta["data"] = data
        meta["amendments"] = [a for a in amend if a["chart"] == str(n)]
        charts.append(meta)
    if problems:
        raise SystemExit("EVIDENCE TAB: BUILD FAILED\n  " + "\n  ".join(problems))
    return {"charts": charts, "amendments": amend, "prereg": "reports/evidence/PREREGISTERED.csv",
            "uncommitted": [c["chart"] for c in charts if "+uncommitted" in str(c.get("code_commit", ""))]}
