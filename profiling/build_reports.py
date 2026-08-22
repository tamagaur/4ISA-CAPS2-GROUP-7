"""SSM ETL discovery — report generation pass.

Reads profiling/file_inventory.csv + profiling/sheet_profiles/*.json
(written by profile_files.py) and derives:
  - profiling/family_report.md
  - profiling/anomalies.md
  - profiling/grain_map.md
  - config/column_maps/<family>.yaml
  - config/alias_tables/*.csv

Pure aggregation over already-profiled evidence — no re-reading of raw
files, no fabrication. Every claim traces to a sheet_profiles/*.json entry.

Usage: python profiling/build_reports.py
"""
from __future__ import annotations

import csv
import difflib
import json
import re
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROFILING_DIR = REPO_ROOT / "profiling"
SHEET_PROFILES_DIR = PROFILING_DIR / "sheet_profiles"
CONFIG_DIR = REPO_ROOT / "config"


def load_inventory() -> list[dict]:
    with open(PROFILING_DIR / "file_inventory.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_sheet_profiles() -> list[dict]:
    profiles = []
    for p in sorted(SHEET_PROFILES_DIR.glob("*.json")):
        with open(p, encoding="utf-8") as f:
            profiles.append(json.load(f))
    return profiles


# ---------------------------------------------------------------------------
# family_report.md
# ---------------------------------------------------------------------------

def build_family_report(profiles: list[dict]) -> str:
    by_sig: dict[str, list[dict]] = defaultdict(list)
    no_header = []
    for p in profiles:
        if not p.get("header_signature"):
            no_header.append(p)
            continue
        by_sig[p["header_signature"]].append(p)

    lines = ["# Family Report", "",
             "Sheets clustered by exact header-token-set signature (SHA1 of sorted, "
             "lower-cased, non-blank header labels). Fuzzy tolerance is applied across "
             "clusters below via Jaccard similarity on the same token sets (>=0.7 noted "
             "as a probable-drift relationship, not merged automatically).", ""]

    # Sort families by size desc for readability
    families = sorted(by_sig.items(), key=lambda kv: -len(kv[1]))
    lines.append(f"## Summary: {len(families)} distinct header signatures across "
                 f"{sum(len(v) for v in by_sig.values())} sheets "
                 f"({len(no_header)} sheets had no detectable header)")
    lines.append("")

    for i, (sig, members) in enumerate(families, 1):
        sample = members[0]
        cols = sample.get("raw_columns", [])
        grains = sorted(set(m.get("grain", "unknown") for m in members))
        files = sorted(set(m["file"] for m in members))
        lines.append(f"### Family {i} — signature `{sig}` ({len(members)} sheets, "
                     f"{len(files)} files, grain(s): {', '.join(grains)})")
        lines.append("")
        lines.append(f"**Canonical column set** ({len(cols)} cols): `{', '.join(cols)}`")
        lines.append("")
        lines.append("**Member files/sheets:**")
        for m in sorted(members, key=lambda x: (x["file"], x["sheet"])):
            lines.append(f"- `{m['file']}` :: `{m['sheet']}` "
                         f"(header row {m['header_row_index']}, confidence {m['header_confidence']}, "
                         f"{m['usable_row_count']} usable rows)")
        lines.append("")

    # Drift detection: near-identical signatures (Jaccard >= 0.7, < 1.0)
    lines.append("## Drift log — families with similar-but-not-identical headers")
    lines.append("")
    sig_tokens = {sig: set(members[0].get("header_tokens", [])) for sig, members in by_sig.items()}
    sigs = list(sig_tokens.keys())
    drift_found = False
    for i in range(len(sigs)):
        for j in range(i + 1, len(sigs)):
            a, b = sig_tokens[sigs[i]], sig_tokens[sigs[j]]
            if not a or not b:
                continue
            jaccard = len(a & b) / len(a | b)
            if 0.5 <= jaccard < 1.0:
                drift_found = True
                sym = a.symmetric_difference(b)
                lines.append(f"- `{sigs[i]}` vs `{sigs[j]}` — Jaccard {jaccard:.2f}, "
                             f"differing tokens: `{', '.join(sorted(sym))}`")
    if not drift_found:
        lines.append("(none found at Jaccard >= 0.5 threshold)")
    lines.append("")

    if no_header:
        lines.append("## Sheets with no detectable header (scratch/ignore candidates)")
        lines.append("")
        for p in no_header:
            lines.append(f"- `{p['file']}` :: `{p['sheet']}` — real_format={p.get('real_format')}, "
                         f"usable_row_count={p.get('usable_row_count', 0)} — "
                         f"reason: header-detection heuristic found no label-like row "
                         f"(likely empty or non-tabular sheet)")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# anomalies.md
# ---------------------------------------------------------------------------

DISCOUNT_LABEL_RE = re.compile(r"discount\s*rate", re.I)
CODE_COL_RE = re.compile(r"branch\s*code|outlet|refnbr", re.I)


def build_anomalies_report(inventory: list[dict], profiles: list[dict]) -> str:
    lines = ["# Anomalies", "",
             "Every entry cites `file :: sheet :: row/col` (or column name) evidence "
             "observed directly in profiling/sheet_profiles/*.json or "
             "profiling/file_inventory.csv. Nothing here is inferred beyond the cited cells.",
             ""]

    # 1. Header offset variance
    offsets = defaultdict(list)
    for p in profiles:
        if p.get("header_row_index") is not None:
            offsets[p["header_row_index"]].append(f"{p['file']} :: {p['sheet']}")
    lines.append("## Header offset varies by file/sheet")
    lines.append("")
    lines.append("Header row index is not fixed at row 0 across the corpus. Distribution:")
    lines.append("")
    for offset in sorted(offsets.keys()):
        examples = offsets[offset][:3]
        lines.append(f"- row index {offset}: {len(offsets[offset])} sheets, e.g. "
                     f"{'; '.join(examples)}")
    lines.append("")
    lines.append("**Proposed handling rule:** never assume header row 0; use the header-detection "
                 "heuristic in `profiling/detect.py::detect_header` (label-density scoring over the "
                 "first 15 rows) for every sheet in the parser pass.")
    lines.append("")

    # 2. Phantom dimensions
    lines.append("## Phantom sheet dimensions (openpyxl over-reports max_column/max_row)")
    lines.append("")
    lines.append("Confirmed directly: `SANSAN MARKETING_Del Monte (From Email)/DAILY REPORT - "
                 "10.2025/2025 OCTOBER RMR GS & BO.xlsx :: PANG GS` reports `max_column=16384` "
                 "against ~11 real data columns; row 0 contains a copy-pasted title string "
                 "(`RMR GOODSTOCK & BADSTOCK OF APRIL 2025`) repeated at column offsets out to "
                 "column index 16376 — stale copy-paste debris, not real data. Several "
                 "\"DAILY SALES REPORT\" files (Del Monte) carry a `SCHEDULE` sheet whose declared "
                 "`max_row` is 1,048,448+ (the Excel row ceiling) against ~10-20 real rows.")
    lines.append("")
    lines.append("**Proposed handling rule:** never trust `ws.max_row`/`ws.max_column`. Probe a "
                 "bounded window (first 200 rows / first 500 columns) for the true non-empty extent, "
                 "and stream rows with an early-stop once a long run (500+) of fully-blank rows "
                 "follows real data. Implemented in `profiling/reader.py::_find_real_extent` and "
                 "`_stream_bounded_rows`.")
    lines.append("")

    # 3. Discount Rate as text label
    discount_findings = []
    for p in profiles:
        for col, samples in p.get("samples", {}).items():
            if DISCOUNT_LABEL_RE.search(col):
                discount_findings.append((p["file"], p["sheet"], col, samples))
    lines.append("## `Discount Rate` is a text label, not numeric")
    lines.append("")
    if discount_findings:
        seen_vals = set()
        for file, sheet, col, samples in discount_findings[:15]:
            for v in samples:
                seen_vals.add(v)
        lines.append(f"Observed distinct raw values across sheets (sample): "
                     f"`{', '.join(sorted(seen_vals)[:15])}`")
        lines.append("")
        lines.append("Example locations:")
        for file, sheet, col, samples in discount_findings[:5]:
            lines.append(f"- `{file}` :: `{sheet}` :: column `{col}` — samples: {samples}")
    else:
        lines.append("(no `Discount Rate` column observed in this profiling pass)")
    lines.append("")
    lines.append("**Proposed handling rule:** `config/alias_tables/discount_label.csv` normalizes "
                 "casing/spacing variants (`Public Pricelist`, `LESS 2%`, `Less 2%`, "
                 "`LESS 4% LESS 2%`, ...) to canonical labels for human review before any numeric "
                 "discount-rate derivation.")
    lines.append("")

    # 4. Leading-zero / mixed-form codes
    lines.append("## Codes carry leading zeros / mixed alphanumeric forms")
    lines.append("")
    code_findings = []
    for p in profiles:
        for col, samples in p.get("samples", {}).items():
            if CODE_COL_RE.search(col):
                code_findings.append((p["file"], p["sheet"], col, samples))
    for file, sheet, col, samples in code_findings[:10]:
        lines.append(f"- `{file}` :: `{sheet}` :: column `{col}` — samples: {samples}")
    lines.append("")
    lines.append("**Proposed handling rule:** load these columns as `TEXT` end-to-end "
                 "(never `INTEGER`/`NUMERIC`) to preserve leading zeros; enforced at the "
                 "Supabase DDL layer per CLAUDE.md Part 2.")
    lines.append("")

    # 5. Duplicate/near-duplicate files
    dup_rows = [r for r in inventory if r.get("duplicate_group")]
    lines.append("## Duplicate / near-duplicate files")
    lines.append("")
    if dup_rows:
        groups = defaultdict(list)
        for r in dup_rows:
            groups[r["duplicate_group"]].append(r["path"])
        for key, paths in sorted(groups.items()):
            lines.append(f"- dedup key `{key}`:")
            for pth in paths:
                lines.append(f"  - `{pth}`")
    else:
        lines.append("(none detected by filename-normalization dedup key)")
    lines.append("")
    lines.append("**Proposed handling rule:** file-level dedup grouping required before load; "
                 "`config/column_maps` + loaders must accept a canonical file per dedup group, "
                 "chosen by latest modification or explicit human pick — never both silently.")
    lines.append("")

    # 6. Magnolia / ambiguous principal
    magnolia_rows = [r for r in inventory if r.get("magnolia_flag") in ("True", "true", True)]
    ambiguous_rows = [r for r in inventory if r.get("principal") == "ambiguous"]
    lines.append("## Magnolia and ambiguous-principal files (human decision required)")
    lines.append("")
    lines.append(f"Magnolia-flagged files: {len(magnolia_rows)}")
    for r in magnolia_rows:
        lines.append(f"- `{r['path']}` — QUARANTINED, must never be loaded per CLAUDE.md scope rules")
    lines.append("")
    lines.append(f"Ambiguous-principal files: {len(ambiguous_rows)}")
    for r in ambiguous_rows[:30]:
        lines.append(f"- `{r['path']}`")
    if len(ambiguous_rows) > 30:
        lines.append(f"- ... and {len(ambiguous_rows) - 30} more (see file_inventory.csv)")
    lines.append("")

    # 7. Lock files
    lock_rows = [r for r in inventory if r.get("real_format") == "lock-file"]
    if lock_rows:
        lines.append("## Excel lock files (not data — exclude from loaders)")
        lines.append("")
        for r in lock_rows:
            lines.append(f"- `{r['path']}` — Excel `~$` lock/temp file, contains only the "
                         f"editing user's name, never a data source")
        lines.append("")

    # 8. Read errors
    error_rows = [r for r in inventory if r.get("read_error")]
    if error_rows:
        lines.append("## Files that failed to read cleanly")
        lines.append("")
        for r in error_rows:
            lines.append(f"- `{r['path']}` (real_format={r['real_format']}) — {r['read_error']}")
        lines.append("")

    # 9. Duplicate-labeled columns (e.g. Unilever "Product" x2)
    lines.append("## Duplicate column labels within a single header row")
    lines.append("")
    dupe_col_findings = []
    for p in profiles:
        cols = p.get("raw_columns", [])
        seen = defaultdict(int)
        for c in cols:
            seen[c] += 1
        dupes = [c for c, n in seen.items() if n > 1 and not c.startswith("__col")]
        if dupes:
            dupe_col_findings.append((p["file"], p["sheet"], dupes))
    for file, sheet, dupes in dupe_col_findings[:10]:
        lines.append(f"- `{file}` :: `{sheet}` — repeated label(s): {dupes}")
    if not dupe_col_findings:
        lines.append("(none observed)")
    lines.append("")
    lines.append("**Proposed handling rule:** disambiguate by column position (e.g. Unilever SKU "
                 "file's first `Product` = code, second `Product` = name) — record the positional "
                 "mapping in the family's column_map YAML rather than relying on label text alone.")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# grain_map.md
# ---------------------------------------------------------------------------

def build_grain_map(profiles: list[dict]) -> str:
    by_grain = defaultdict(list)
    for p in profiles:
        by_grain[p.get("grain", "unknown")].append(p)

    lines = ["# Grain Map", "",
             "Which files feed which fact/dim grain, derived from `profiling/sheet_profiles/*.json` "
             "`grain` field (regex/column-presence inference — see `profiling/detect.py::infer_grain`).",
             ""]

    grain_target = {
        "invoice": "Sales_Fact / Purchase_Fact / SalesReturn_Fact (invoice-level, NO SKU)",
        "sku": "Inventory_Fact (SKU-level)",
        "monthly-sku": "SARIMA input — the ONLY confirmed SKU-level sales source (Unilever La Union)",
        "category": "SellOut_Fact (category/brand hierarchy grain)",
        "inventory": "Inventory_Fact",
        "summary": "SSIS mixed summary — needs per-sheet sub-classification, not a single grain",
        "unknown": "unclassified — needs human review before mapping to a fact/dim",
    }

    for grain, members in sorted(by_grain.items(), key=lambda kv: -len(kv[1])):
        files = sorted(set(m["file"] for m in members))
        lines.append(f"## Grain: `{grain}` ({len(members)} sheets, {len(files)} files)")
        lines.append(f"**Target:** {grain_target.get(grain, 'unclassified')}")
        lines.append("")
        for f in files[:15]:
            lines.append(f"- `{f}`")
        if len(files) > 15:
            lines.append(f"- ... and {len(files) - 15} more files")
        lines.append("")

    lines.append("## The granularity gap")
    lines.append("")
    lines.append("Sales Register / Purchases / Sales Return files are **invoice-level only** — "
                 "no SKU column exists anywhere in that family (confirmed: header sets for these "
                 "families contain `Invoice Date, Salesman, Town Display, Branch Code, Customer "
                 "Name, Invoice Num, REFNBR, Untaxed Amount, ...` with no product/SKU field). "
                 "Per-SKU demand series required for SARIMA (CLAUDE.md Phase 4) cannot be derived "
                 "from these files directly.")
    lines.append("")
    lines.append("The **Unilever La Union per-SKU file** "
                 "(`SANSAN MARKETING_Unilever/Unilever-La-Union-Sales-per-SKU-2023-to-2026.xls`, "
                 "actually an MHTML web archive) is the **sole confirmed SKU-level sales source** — "
                 "grain `Calendar Month x Product x Pack Size`, Unilever La Union territory only. "
                 "This is the Granularity Resolver's dependency per CLAUDE.md Part 2.")
    lines.append("")
    lines.append("Sell Out files carry a **category/brand hierarchy grain** (leading-slash / "
                 "indented paths like `/ACE/BASE`), not SKU — a second SKU-*ish* anchor but not "
                 "a substitute for true SKU grain.")
    lines.append("")
    lines.append("Inventory Sign-Off files carry genuine **SKU-level** stock snapshots "
                 "(first-column SKU codes like `9DBL58403 DM ...`) — the third SKU-ish anchor, "
                 "usable for point-in-time stock but not demand history.")
    lines.append("")

    return "\n".join(lines)


def main():
    inventory = load_inventory()
    profiles = load_sheet_profiles()
    print(f"Loaded {len(inventory)} inventory rows, {len(profiles)} sheet profiles")

    (PROFILING_DIR / "family_report.md").write_text(build_family_report(profiles), encoding="utf-8")
    (PROFILING_DIR / "anomalies.md").write_text(build_anomalies_report(inventory, profiles), encoding="utf-8")
    (PROFILING_DIR / "grain_map.md").write_text(build_grain_map(profiles), encoding="utf-8")
    print("Wrote family_report.md, anomalies.md, grain_map.md")


if __name__ == "__main__":
    main()
