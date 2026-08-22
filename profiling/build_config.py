"""SSM ETL discovery — config proposal generation.

Derives config/column_maps/<family>.yaml and config/alias_tables/*.csv
from profiling/sheet_profiles/*.json. Every raw_value/canonical_value in
the alias tables is seeded from an observed cell value — nothing invented.

Fuzzy matching: auto-accept >= 92, review queue 80-91, reject < 80
(difflib.SequenceMatcher ratio * 100, per CLAUDE.md Part 4 thresholds).

Usage: python profiling/build_config.py
"""
from __future__ import annotations

import csv
import difflib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from profile_files import REGION_PATTERNS  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
PROFILING_DIR = REPO_ROOT / "profiling"
SHEET_PROFILES_DIR = PROFILING_DIR / "sheet_profiles"
CONFIG_DIR = REPO_ROOT / "config"

AUTO_ACCEPT = 92
REVIEW_MIN = 80


def load_sheet_profiles() -> list[dict]:
    profiles = []
    for p in sorted(SHEET_PROFILES_DIR.glob("*.json")):
        with open(p, encoding="utf-8") as f:
            profiles.append(json.load(f))
    return profiles


# Canonical target names for known raw columns (seeded from the family
# header sets actually observed — see profiling/family_report.md).
CANONICAL_MAP = {
    "invoice date": "invoice_date",
    "salesman": "salesman_name",
    "town display": "town",
    "branch code": "branch_code",
    "customer name": "customer_name",
    "invoice num": "invoice_number",
    "refnbr": "reference_number",
    "untaxed amount": "untaxed_amount",
    "discount rate": "discount_label",
    "discount amount": "discount_amount",
    "tax": "tax_amount",
    "net amount": "net_amount",
    "balance": "balance_amount",
    "return slip #": "return_slip_number",
    "return type": "return_type",
    "posted": "posted_flag",
    "quantity": "quantity",
    "cost": "unit_cost",
    "valuation": "valuation_amount",
    "valuation with vat": "valuation_with_vat_amount",
    "valuation w/ vat": "valuation_with_vat_amount",
    "cas": "cases",
    "pcs": "pieces",
    "pkg": "package_count",
    "in pcs": "quantity_in_pieces",
    "in cases": "quantity_in_cases",
    "total without tax": "sell_out_amount_untaxed",
    "product quantity": "sell_out_quantity",
    "calendar month": "calendar_month",
    "product": "product_code_or_name",
    "pack size": "pack_size",
    "sale qty aggr.cs": "sale_quantity_cases",
    "sale qty aggr.pc": "sale_quantity_pieces",
    "gsv total sales amt inc. tax": "gross_sales_value_taxed",
}


def build_column_maps(profiles: list[dict]):
    by_sig: dict[str, list[dict]] = defaultdict(list)
    for p in profiles:
        if p.get("header_signature"):
            by_sig[p["header_signature"]].append(p)

    for sig, members in by_sig.items():
        sample = members[0]
        cols = sample.get("raw_columns", [])
        files = sorted(set(m["file"] for m in members))
        family_name = f"family_{sig}"

        lines = [
            f"# Proposed raw -> canonical column map for family {sig}",
            f"# Seeded from {len(members)} sheet(s) across {len(files)} file(s):",
        ]
        for f in files[:5]:
            lines.append(f"#   - {f}")
        if len(files) > 5:
            lines.append(f"#   ... and {len(files) - 5} more")
        lines.append("# STATUS: proposal — human review required before use in loaders.")
        lines.append("")
        lines.append("family: " + family_name)
        lines.append("columns:")
        for i, col in enumerate(cols):
            col_norm = str(col).strip().lower()
            canonical = CANONICAL_MAP.get(col_norm, "UNMAPPED_" + re.sub(r"[^a-z0-9]+", "_", col_norm).strip("_"))
            lines.append(f"  - raw: \"{col}\"")
            lines.append(f"    position: {i}")
            lines.append(f"    canonical: {canonical}")
            dtype = sample.get("dtypes", {}).get(col, "unknown")
            lines.append(f"    observed_dtype: {dtype}")
        out_path = CONFIG_DIR / "column_maps" / f"{family_name}.yaml"
        out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Wrote {len(by_sig)} column map proposals to config/column_maps/")


def fuzzy_cluster(values: list[str]) -> list[dict]:
    """Cluster raw values into canonical groups by pairwise similarity.
    Returns rows: raw_value, canonical_value, match_score, status."""
    if not values:
        return []
    unique_vals = sorted(set(v for v in values if v and v.strip()))
    if not unique_vals:
        return []

    # Greedy clustering: each value either joins an existing cluster
    # (best match >= REVIEW_MIN) or starts a new one (becomes its own
    # canonical seed).
    clusters: list[dict] = []  # {"canonical": str, "members": [(raw, score)]}
    for val in unique_vals:
        norm = re.sub(r"\s+", " ", val.strip().lower())
        best_cluster, best_score = None, 0.0
        for c in clusters:
            score = difflib.SequenceMatcher(None, norm, c["norm"]).ratio() * 100
            if score > best_score:
                best_score, best_cluster = score, c
        if best_cluster is not None and best_score >= REVIEW_MIN:
            best_cluster["members"].append((val, round(best_score, 1)))
        else:
            clusters.append({"canonical": val, "norm": norm, "members": [(val, 100.0)]})

    rows = []
    for c in clusters:
        for raw, score in c["members"]:
            status = "auto" if score >= AUTO_ACCEPT else "review"
            rows.append({
                "raw_value": raw, "canonical_value": c["canonical"],
                "match_score": score, "status": status,
            })
    return rows


ALIAS_TARGETS = {
    "discount_label": re.compile(r"discount\s*rate", re.I),
    "salesman": re.compile(r"^salesman$", re.I),
    "town": re.compile(r"town\s*display", re.I),
}


def collect_region_tokens(profiles: list[dict]) -> list[str]:
    """Region isn't a raw column — it's inferred from filename/sheet-name
    tokens (see profile_files.py::infer_regions). Reuse the same
    REGION_PATTERNS so the alias table stays in sync with the inference
    logic instead of drifting from a second hand-copied regex set."""
    tokens: set[str] = set()
    for p in profiles:
        text = f"{p.get('file', '')} {p.get('sheet', '')}"
        for _region, pattern in REGION_PATTERNS:
            m = pattern.search(text)
            if m:
                tokens.add(m.group(0))
    return sorted(tokens)


def build_alias_tables(profiles: list[dict]):
    collected: dict[str, list[str]] = defaultdict(list)

    for p in profiles:
        samples = p.get("samples", {})
        for col, vals in samples.items():
            for target, pattern in ALIAS_TARGETS.items():
                if pattern.search(col):
                    collected[target].extend(str(v) for v in vals)

    collected["region"] = collect_region_tokens(profiles)

    # doc_type_prefix from REFNBR-style evidence (principal_evidence strings
    # already contain "REFNBR 'X' matches prefix 'Y'" — extract prefixes).
    prefix_re = re.compile(r"matches prefix '([A-Z]+)'")
    for p in profiles:
        for ev in p.get("principal_evidence", []):
            m = prefix_re.search(ev)
            if m:
                collected["doc_type_prefix"].append(m.group(1))

    for name, values in collected.items():
        values = sorted(set(values))
        rows = fuzzy_cluster(values)
        out_path = CONFIG_DIR / "alias_tables" / f"{name}.csv"
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["raw_value", "canonical_value", "match_score", "status"])
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        print(f"Wrote {len(rows)} proposed aliases to config/alias_tables/{name}.csv")

    # Ensure the minimum required set exists even if empty, per prompt spec.
    for required in ("discount_label", "region", "doc_type_prefix", "salesman", "town"):
        out_path = CONFIG_DIR / "alias_tables" / f"{required}.csv"
        if not out_path.exists():
            with open(out_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["raw_value", "canonical_value", "match_score", "status"])
                writer.writeheader()
            print(f"Wrote empty placeholder config/alias_tables/{required}.csv (no observed values)")


def main():
    profiles = load_sheet_profiles()
    print(f"Loaded {len(profiles)} sheet profiles")
    build_column_maps(profiles)
    build_alias_tables(profiles)


if __name__ == "__main__":
    main()
