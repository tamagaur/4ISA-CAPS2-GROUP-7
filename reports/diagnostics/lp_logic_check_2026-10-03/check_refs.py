"""
Check every file:line reference in README.md against a git revision
(default: kelvin-etl). Prints, per reference, whether the cited lines are
identical at 83cafc4 (where the check was written) and at the target, plus
the target's text, so each one can be read against the claim it supports.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
BASE, TARGET = "83cafc4", (sys.argv[1] if len(sys.argv) > 1 else "kelvin-etl")
README = (HERE / "README.md").read_text(encoding="utf-8")

ALIASES = {  # bare names the README uses -> repo paths
    "lp.py": "analytics/optimization/lp.py", "run_lp.py": "scripts/run_lp.py", "stock_units.py": "backend/stock_units.py",
    "dashboard.py": "backend/routers/dashboard.py", "recommendations.py": "backend/routers/recommendations.py",
    "data_notes.py": "backend/data_notes.py", "diagnostic_metrics.py": "analytics/forecasting/diagnostic_metrics.py",
    "split.py": "analytics/forecasting/split.py", "router.py": "analytics/forecasting/router.py",
    "run_baseline_forecast.py": "scripts/run_baseline_forecast.py", "Charts.jsx": "frontend/src/components/Charts.jsx",
    "params.py": "analytics/params.py", "schema.sql": "analytics/db/schema.sql",
    "0010_gsv_and_guards.sql": "analytics/db/migrations/0010_gsv_and_guards.sql", "grain_map.md": "profiling/grain_map.md",
}


def show(rev: str, path: str) -> list[str] | None:
    out = subprocess.run(["git", "show", f"{rev}:{path}"], capture_output=True, text=True, encoding="utf-8",
                         errors="replace", cwd=HERE)
    return out.stdout.splitlines() if out.returncode == 0 else None


refs: list[tuple[str, str]] = []
# `path:12-34`, `path:12`, `path:12, 34-40` and `path` (233-251, 784) styles
for m in re.finditer(r"`?([\w./-]+\.(?:py|sql|md|jsx))`?((?::\d+(?:-\d+)?(?:,\s*\d+(?:-\d+)?)*)|(?:\s*\((?:\d+(?:-\d+)?\+?(?:,\s*)?)+\)))", README):
    name, spans = m.group(1), m.group(2)
    path = name if "/" in name else ALIASES.get(name, name)
    for span in re.findall(r"\d+(?:-\d+)?", spans):
        refs.append((path, span))

# Cited in forms the pattern can't attribute to a file (a bare `:584-616` after an earlier file name, or a
# function name followed by "(403-409)"): listed by hand from the README text.
refs += [("backend/routers/dashboard.py", s) for s in ("584-616", "899-920")] + \
        [("analytics/optimization/lp.py", "22-23")] + \
        [("scripts/run_lp.py", s) for s in ("403-409", "823", "575-596", "542-560", "915-917", "794-812", "503-539",
                                            "684-698", "464-480", "51-60", "242-249")] + \
        [("backend/routers/dashboard.py", "1299-1313"), ("backend/schemas/recommendations.py", "101-116"),
         ("frontend/src/components/Dashboard.jsx", "520-528"),
         ("frontend/src/components/ReorderRecommendations.jsx", "109"), ("backend/stock_units.py", "83-92")]

seen, bad, rows = set(), 0, []
for path, span in refs:
    if (path, span) in seen:
        continue
    seen.add((path, span))
    lo, hi = (int(x) for x in (span.split("-") + [span])[:2]) if "-" in span else (int(span), int(span))
    a, b = show(BASE, path), show(TARGET, path)
    if b is None or hi > len(b):
        bad += 1
        print(f"MISSING  {path}:{span}")
        rows.append({"reference": f"{path}:{span}", "status": "missing", "text_at_target": None})
        continue
    same = a is not None and a[lo - 1:hi] == b[lo - 1:hi]
    print(f"{'same   ' if same else 'CHANGED'}  {path}:{span}  | {b[lo - 1].strip()[:110]}")
    rows.append({"reference": f"{path}:{span}", "status": "same" if same else "changed", "text_at_target": b[lo - 1].strip()[:160]})
pd.DataFrame(rows, columns=["reference", "status", "text_at_target"]).to_csv(HERE / "check_refs.csv", index=False)
print(f"\n{len(seen)} distinct references, {bad} missing at {TARGET}")
