"""
analytics.etl.transform_driver — Transform-stage QC driver, the "M2" gate
(ARCHITECTURE.md §7's "Transform QC gate (must pass before Load)").

Mirrors extract/driver.py's role for the next stage: reads every doc_type
staged under staging/, runs transform_fact() for every (fact, principal)
source_of_truth.yaml declares, classifies every (src_file, src_sheet) it
finds as promoted / demoted / conflict / blocked, and writes
transform/_manifest.json in the same {"staged": [...], "reject": [...]}
shape extract/_shared.py::build_manifest() uses — so
analytics.etl._review.render_review("transform") renders it with the same
viewer Extract already uses (see _review.py's STATUS_LABELS for how the
viewer tells the two stages' status vocabularies apart).

Classification (zero silent skips — every staged sheet is accounted for):
  promoted  - kept as system-of-record, no dedup conflict
  demoted   - correctly excluded: wrong _sheet_role for this fact (DEC-04),
              or its doc_type is never any fact's primary source (only ever
              a cross_check_doc_types entry, e.g. daily_sales_report)
  conflict  - kept, but its rows landed in a DedupReport conflicting group —
              flagged for a human, never resolved silently
  blocked   - the fact/principal has natural_key: null, transform_fact()
              raised for some other reason, or the sheet's _principal isn't
              claimed by any (fact, principal) rule for its doc_type

promoted + demoted -> manifest "staged" (routine).
conflict + blocked -> manifest "reject" (needs a human look).

DEC-13: the manifest also carries a top-level "quantity_issues" section —
per (fact, principal), zero/negative/outlier counts and flagged rows for
each fact's real quantity column(s) (clean.py::flag_quantity_issues()).
Never drops or clamps a value; only makes it visible. Surfaced in
transform_signoff.py's sign-off checklist for human review.

Usage: python -m analytics.etl.transform_driver
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import yaml

from analytics.etl._review import render_review
from analytics.etl.clean import clean_pipeline, flag_quantity_issues
from analytics.etl.transform import (
    DEFAULT_CONFIG_DIR,
    REPO_ROOT,
    filter_source_of_truth,
    load_source_of_truth,
    transform_fact,
)

PRINCIPALS = ["unilever", "delmonte"]

# Canonical post-column-map field checked per fact to detect a REAL dedup
# conflict (two rows sharing a natural key but disagreeing on this value).
# transform_fact()'s own amount_col default is None, which means NO
# conflict detection happens at all (see dedup_facts() - without amount_col
# it treats any same-key group as a safe duplicate and silently collapses
# it) - a caller must opt in explicitly. This mapping is this driver's own
# judgment call for "what's the value that shouldn't disagree" per fact;
# it isn't sourced from any existing config (nothing else in this repo
# defines it) - revisit if a real conflict on real data isn't caught by it.
AMOUNT_COL_BY_FACT = {
    "sales": "net_amount",
    "sales_unilever_sku_demand": "quantity_sold",
    "sales_return": "net_amount",
    "purchase": "net_amount",
    "inventory": "quantity_on_hand",
    "sell_out": "net_amount",
}

# DEC-13: quantity column(s) checked per fact for zero/negative/outlier
# values (clean.py::flag_quantity_issues() — flagged, never dropped). Not
# every fact has a real quantity field (e.g. "sales" is invoice-grain, no
# quantity anywhere). Inventory lists both fields: quantity_pieces is the
# DEC-09-confirmed-pieces figure; quantity_on_hand's own unit is still
# unconfirmed (see DEC-09) — that's a separate, already-logged gap, not
# something this flagging needs to resolve to still be useful here.
QUANTITY_COLS_BY_FACT = {
    "sales_unilever_sku_demand": ["quantity_sold"],
    "sales_return": ["bo_units"],
    "purchase": ["units_received"],
    "inventory": ["quantity_pieces", "quantity_on_hand"],
    "sell_out": ["quantity"],
}


def _sheet_groups(df: pd.DataFrame):
    return df.groupby(["_src_file", "_src_sheet"], dropna=False)


def _sheet_record(src_file, src_sheet, group: pd.DataFrame) -> dict:
    first = group.iloc[0]
    return {
        "src_file": src_file,
        "src_sheet": src_sheet,
        "principal": first.get("_principal"),
        "region": first.get("_region"),
        "period": first.get("_period"),
        "doc_type": first.get("_doc_type"),
        "sheet_role": first.get("_sheet_role"),
        "grain": first.get("_grain"),
        "row_count": int(len(group)),
        "columns": [c for c in group.columns if not str(c).startswith("_")],
    }


def _status_records(df: pd.DataFrame, status: str, reason: str | None) -> list[dict]:
    records = []
    for (src_file, src_sheet), group in _sheet_groups(df):
        rec = _sheet_record(src_file, src_sheet, group)
        rec["checksum_status"] = status
        rec["reason"] = reason
        records.append(rec)
    return records


def _doc_type_owners(config_dir: Path = DEFAULT_CONFIG_DIR) -> dict[str, list[tuple[str, str]]]:
    """doc_type -> [(fact, principal), ...] for every entry's PRIMARY
    doc_type in source_of_truth.yaml. A doc_type that only ever appears in
    some other entry's cross_check_doc_types (e.g. daily_sales_report)
    deliberately has no owner here — see build_transform_manifest()."""
    path = config_dir / "source_of_truth.yaml"
    rules = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    owners: dict[str, list[tuple[str, str]]] = {}
    for fact, fact_rules in rules.items():
        for principal in PRINCIPALS:
            entry = fact_rules.get(principal) or fact_rules.get("both")
            if entry is None:
                continue
            owners.setdefault(entry["doc_type"], []).append((fact, principal))
    return owners


def _classify_fact_principal(
    df: pd.DataFrame, fact: str, principal: str, config_dir: Path = DEFAULT_CONFIG_DIR,
) -> tuple[list[dict], list]:
    """Classifies every (src_file, src_sheet) belonging to `principal`
    within `df` (one doc_type's full staged data) for this (fact,
    principal). Never raises — a transform_fact() failure is recorded as
    `blocked`, not propagated, so one bad fact doesn't hide every other
    fact's results from whoever is reviewing this manifest. Returns
    (records, quantity_issue_reports) — the latter always [] when this
    fact/principal never reached transform_fact() (blocked) or has no
    quantity column configured (QUANTITY_COLS_BY_FACT)."""
    principal_df = df[df["_principal"] == principal]
    if principal_df.empty:
        return [], []

    try:
        rule = load_source_of_truth(fact, principal, config_dir)
    except Exception as exc:
        return _status_records(principal_df, "blocked", f"could not load source_of_truth rule: {exc}"), []

    if rule.natural_key is None:
        return _status_records(
            principal_df, "blocked",
            f"natural_key unconfirmed for fact='{fact}' principal='{principal}' - see source_of_truth.yaml",
        ), []

    try:
        sot_df = filter_source_of_truth(principal_df, fact, principal, config_dir)
        _, report = transform_fact(
            principal_df, fact, principal, config_dir, amount_col=AMOUNT_COL_BY_FACT.get(fact),
        )
    except Exception as exc:
        return _status_records(principal_df, "blocked", f"transform_fact() raised: {exc}"), []

    sot_sheets = set(zip(sot_df["_src_file"], sot_df["_src_sheet"])) if not sot_df.empty else set()

    # clean.clean_pipeline() (2026-08): previously built, tested, and never
    # called by anything real - wiring it here is what actually makes
    # standardize_product_code()'s leading-zero preservation (branch_code
    # "000096" staying TEXT, not becoming 96) take effect on real data,
    # plus IQR outlier flagging and bo_rate. Run on the post-column-map
    # frame (real business field names), same precondition clean_pipeline's
    # own docstring documents. Doesn't touch natural-key columns or
    # amount_col values, so conflict classification and quantity flagging
    # below are unaffected by this - confirmed via a real re-run producing
    # identical promoted/demoted/conflict/blocked counts before and after.
    mapped_df, _ = clean_pipeline(report["mapped_df"], amount_col=AMOUNT_COL_BY_FACT.get(fact) or "net_amount")
    conflict_sheets: set[tuple] = set()
    conflicting_groups = report["dedup"].conflicting_groups
    if conflicting_groups and not mapped_df.empty:
        conflict_keys = {tuple(g["key"]) for g in conflicting_groups}
        key_tuples = list(mapped_df[rule.natural_key].itertuples(index=False, name=None))
        conflict_mask = pd.Series(key_tuples, index=mapped_df.index).isin(conflict_keys)
        conflict_sheets = set(zip(
            mapped_df.loc[conflict_mask, "_src_file"], mapped_df.loc[conflict_mask, "_src_sheet"],
        ))

    records = []
    for (src_file, src_sheet), group in _sheet_groups(principal_df):
        rec = _sheet_record(src_file, src_sheet, group)
        key = (src_file, src_sheet)
        if key not in sot_sheets:
            rec["checksum_status"] = "demoted"
            rec["reason"] = (
                f"_sheet_role='{rec['sheet_role']}' is not the system-of-record role "
                f"for fact='{fact}' (ARCHITECTURE.md DEC-04)"
            )
        elif key in conflict_sheets:
            rec["checksum_status"] = "conflict"
            rec["reason"] = f"dedup conflict on natural key {rule.natural_key} - needs a human look"
        else:
            rec["checksum_status"] = "promoted"
            rec["reason"] = None
        records.append(rec)

    quantity_reports = [
        flag_quantity_issues(mapped_df, col)
        for col in QUANTITY_COLS_BY_FACT.get(fact, [])
        if col in mapped_df.columns
    ]
    return records, quantity_reports


def build_transform_manifest(staging_dir: Path, config_dir: Path = DEFAULT_CONFIG_DIR) -> dict:
    """Pure function (only reads `staging_dir`) — the Transform-stage
    counterpart of extract/_shared.py::build_manifest(). See module
    docstring for the promoted/demoted/conflict/blocked classification and
    staged-vs-reject split."""
    owners = _doc_type_owners(config_dir)

    staged: list[dict] = []
    reject: list[dict] = []
    quantity_issues: dict[str, list[dict]] = {}

    for doc_dir in sorted(p for p in staging_dir.iterdir() if p.is_dir() and p.name != "_rejects"):
        doc_type = doc_dir.name
        parquet_files = sorted(doc_dir.glob("*.parquet"))
        if not parquet_files:
            continue
        df = pd.concat([pd.read_parquet(f) for f in parquet_files], ignore_index=True)

        owner_pairs = owners.get(doc_type, [])
        if not owner_pairs:
            for rec in _status_records(
                df, "demoted",
                f"doc_type='{doc_type}' is never a fact's primary source (cross-check "
                f"only, if referenced at all) - see source_of_truth.yaml",
            ):
                staged.append(rec)
            continue

        seen: set[tuple] = set()
        for fact, principal in owner_pairs:
            records, quantity_reports = _classify_fact_principal(df, fact, principal, config_dir)
            for rec in records:
                seen.add((rec["src_file"], rec["src_sheet"]))
                (staged if rec["checksum_status"] in ("promoted", "demoted") else reject).append(rec)
            if quantity_reports:
                quantity_issues[f"{fact}/{principal}"] = [asdict(r) for r in quantity_reports]

        # Safety net: any sheet in this doc_type not covered by any owning
        # (fact, principal) call above (e.g. an unrecognized _principal
        # value) must still be accounted for, never silently dropped.
        mask = ~df.apply(lambda r: (r["_src_file"], r["_src_sheet"]) in seen, axis=1)
        leftover = df[mask]
        if not leftover.empty:
            for rec in _status_records(
                leftover, "blocked",
                "not claimed by any (fact, principal) rule for this doc_type - unrecognized _principal?",
            ):
                reject.append(rec)

    return {"staged": staged, "reject": reject, "quantity_issues": quantity_issues}


def save_transform_manifest(manifest: dict, transform_dir: Path) -> Path:
    transform_dir.mkdir(parents=True, exist_ok=True)
    out_path = transform_dir / "_manifest.json"
    out_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return out_path


def main():
    staging_dir = REPO_ROOT / "staging"
    transform_dir = REPO_ROOT / "transform"

    manifest = build_transform_manifest(staging_dir)
    manifest_path = save_transform_manifest(manifest, transform_dir)
    review_path = render_review("transform", repo_root=REPO_ROOT)

    staged, reject = manifest["staged"], manifest["reject"]
    counts = {"promoted": 0, "demoted": 0, "conflict": 0, "blocked": 0}
    for rec in staged + reject:
        counts[rec["checksum_status"]] = counts.get(rec["checksum_status"], 0) + 1

    quantity_flag_total = sum(
        r["zero_count"] + r["negative_count"] + r["outlier_count"]
        for reports in manifest["quantity_issues"].values() for r in reports
    )

    print(f"Transform manifest written to {manifest_path}")
    print(f"Review viewer written to {review_path}")
    print(
        f"promoted={counts['promoted']} demoted={counts['demoted']} "
        f"conflict={counts['conflict']} blocked={counts['blocked']}"
    )
    print(f"quantity issues flagged (zero+negative+outlier): {quantity_flag_total}")


if __name__ == "__main__":
    main()
