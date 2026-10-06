"""
Quality check 2026-10-03 - repo hygiene. Read-only on the branches; the dry merges run in a throwaway detached
worktree that is aborted and removed. Writes qc_hygiene.csv (counts only, no commit hashes, so a rerun after the
commit that adds this file gives the same file).

  1. No per-product sales or prices in any commit on kelvin/model-audit since 953cda3 or on kelvin/blank-qty-fix
     since 01930d7: no file under inputs/ or local/; no committed CSV with a sales / price / quantity column; no
     README line that names a product code next to a piece count; the piece counts removed 2026-10-03 absent.
  2. Dry merge of each branch into group7/kelvin-etl: conflicts counted, then git merge --abort.

    ../Capstone-Project/.venv/Scripts/python.exe reports/diagnostics/model_audit_2026-10-03/qc_hygiene.py
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
MAIN = "C:/Users/kyuan/Capstone-Project"
BRANCHES = {"kelvin/model-audit": "953cda3", "kelvin/blank-qty-fix": "01930d7"}
TARGET = "group7/kelvin-etl"
FOLDER = "reports/diagnostics/model_audit_2026-10-03/"
PRODUCT_COLUMNS = {"product_key", "sku_code", "product_name"}
# a per-product sales / price table = a product column AND one of these (counts and ratios are not sales)
SALES_COLUMNS = re.compile(r"^(actual|forecast|value|quantity|qty|pieces|net_amount|price.*|level|ma3|naive|tsb|xgb|"
                           r".*_pieces|.*_pesos)$")
# a README line that pairs a product code with a piece count or a peso price
COUNT_OR_PRICE = re.compile(r"\d[\d,]{2,}(\.\d+)?\s*(pieces|pcs)\b|₱\s?\d")
# product 674's pieces, removed 2026-10-03; built from split pieces so this file does not match itself
REMOVED = re.compile("|".join(a + b for a, b in (("35,", "885"), ("32,", "110"), ("29,", "806"), ("20,", "365"),
                                                 ("1,693", " in"), ("−124", " pieces"))))


def git(*args, cwd=MAIN) -> str:
    return subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, encoding="utf-8").stdout


def main():
    rows = []
    for branch, base in BRANCHES.items():
        commits = git("rev-list", f"{base}..{branch}").split()
        files = {f for c in commits for f in git("show", "--name-only", "--format=", c).split()}
        bad_paths = [f for f in files if re.search(r"/(inputs|local)/", f)]
        bad_cols, bad_lines, removed = [], 0, 0
        for c in commits:
            for f in git("show", "--name-only", "--format=", c).split():
                blob = git("show", f"{c}:{f}")
                if f.endswith(".csv") and blob:
                    header = blob.splitlines()[0].split(",")
                    if PRODUCT_COLUMNS & {h.strip() for h in header}:
                        bad_cols += [f"{f}:{h}" for h in header if SALES_COLUMNS.match(h.strip())]
                if f.endswith(".md"):
                    bad_lines += sum(1 for line in blob.splitlines()
                                     if re.search(r"\(\d{8}\b", line) and COUNT_OR_PRICE.search(line))
                removed += len(REMOVED.findall(blob))
        rows += [
            {"branch": branch, "check": "commits on the branch since its base", "value": len(commits), "result": "info"},
            {"branch": branch, "check": "files under inputs/ or local/ in any commit", "value": len(bad_paths),
             "result": "PASS" if not bad_paths else "FAIL"},
            {"branch": branch, "check": "per-product CSV columns with sales, quantity or price (product column + sales column)",
             "value": len(bad_cols), "result": "PASS" if not bad_cols else "FAIL"},
            {"branch": branch, "check": "README lines pairing a product code with a piece count or peso price", "value": bad_lines,
             "result": "PASS" if not bad_lines else "FAIL"},
            {"branch": branch, "check": "product 674 piece counts removed 2026-10-03 (any commit)", "value": removed,
             "result": "PASS" if not removed else "FAIL"},
        ]
    # dry merges into group7/kelvin-etl, in a throwaway worktree
    tmp = os.path.join(tempfile.gettempdir(), "dsd-qc-dry-merge")
    git("worktree", "add", "--detach", tmp, TARGET)
    try:
        for branch in BRANCHES:
            out = subprocess.run(["git", "-C", tmp, "merge", "--no-commit", "--no-ff", branch],
                                 capture_output=True, text=True, encoding="utf-8")
            conflicts = git("diff", "--name-only", "--diff-filter=U", cwd=tmp).split()
            changed = git("diff", "--cached", "--name-only", cwd=tmp).split()
            git("merge", "--abort", cwd=tmp)
            clean = git("status", "--short", cwd=tmp).strip() == ""
            rows.append({"branch": branch, "check": f"dry merge into {TARGET}: conflicts", "value": len(conflicts),
                         "result": "PASS" if out.returncode == 0 and not conflicts else "FAIL"})
            rows.append({"branch": branch, "check": f"dry merge into {TARGET}: files the merge would change",
                         "value": len(changed), "result": "info"})
            rows.append({"branch": branch, "check": "after git merge --abort: worktree clean", "value": int(clean),
                         "result": "PASS" if clean else "FAIL"})
    finally:
        git("worktree", "remove", "--force", tmp)
    out = pd.DataFrame(rows)
    out.to_csv(os.path.join(HERE, "qc_hygiene.csv"), index=False)
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
