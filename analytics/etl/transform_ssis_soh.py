"""
analytics.etl.transform_ssis_soh — Transform driver for doc_type
ssis_soh (Unilever SOH inventory snapshots), fact "inventory",
principal "unilever".

Reads staging/ssis_soh/*.parquet (written by
analytics/etl/extract/ssis_soh.py under rulings R1-R7) and produces the
Inventory_Fact-shaped rows for that (fact, principal), plus two new
deliverables ruled on for this Transform pass:

  R8  Product_Dimension candidate rows for every real SKU that doesn't
      join to the existing (synthetic-free) Unilever SKU universe —
      PREPARED ONLY, never inserted (no DB connection happens anywhere
      in this module).
  R9  A log of every SKU whose CATEGORY DESC changed across its own
      snapshots, with every (snapshot_date, category_desc) pair —
      category_path for both Inventory_Fact-adjacent output and the R8
      candidates is taken from each SKU's MOST RECENT snapshot, per
      this ruling.

Column mapping to the existing Inventory_Fact schema (analytics/db/schema.sql):
  stock_qty_cases (Extract-derived)            -> quantity_on_hand
  stock_qty_pieces (Extract-derived)            -> quantity_pieces
  stock_value                                   -> valuation        (exists: migrations/0004_add_valuation.sql;
                                                                       NOT yet in schema.sql's CREATE TABLE baseline —
                                                                       known drift, not this module's problem to fix)
  last_purchase_price_gsv_per_cs                -> NO HOME. There is no `cost` column anywhere in
                                                     Inventory_Fact (checked schema.sql's CREATE TABLE, every
                                                     migration under analytics/db/migrations/, and
                                                     backend/routers/dashboard.py, which explicitly documents
                                                     "a cost column that doesn't exist"). Del Monte's own
                                                     inventory_sign_off.yaml maps a raw "Cost" header to a
                                                     canonical "cost" column, but that column has exactly the
                                                     same fate — nowhere in Inventory_Fact for it to land, so
                                                     there is no live Del Monte convention to match, only the
                                                     same absence repeated. Kept in this module's output as an
                                                     informational column (last_purchase_price_gsv_per_cs) for
                                                     visibility, NOT renamed to "cost", NOT loaded — this module
                                                     does not write to Inventory_Fact or add a column to it (no
                                                     migration is written here, per this turn's instructions).
                                                     The header's own text ("GSV/CS") already answers the
                                                     per-case-vs-per-unit question without guessing: it is
                                                     GSV PER CASE, not per piece/unit.
  snapshot_date, _period                        -> snapshot_date, _period (both already real per R5 — no
                                                     _snapshot_date_from_period() synthetic-first-of-month
                                                     fabrication needed here, unlike Del Monte's inventory_sign_off)
  sku_code                                      -> sku_code
  (constant) principal='unilever', is_demo=False, region=None (Storage
  Location dropped at Extract per R6 — no real region concept for this
  source)

Columns with confirmed NO home in Inventory_Fact (reported, not added):
  Blocked Stock (CS/PC), Status, PO Qty, Open SO Quantity,
  Balance Quantity, Batch, PACK SIZE
  See NO_HOME_COLUMNS_REPORT below for the per-column downstream-need
  assessment this module's report prints.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from analytics.etl.transform import REPO_ROOT, DedupReport, dedup_facts

STAGING_SUBDIR = "ssis_soh"
NATURAL_KEY = ["sku_code", "snapshot_date"]

# R8/downstream-need assessment for columns with no Inventory_Fact home.
# "Blocked Stock" and "Status" are the dead-stock signal per this turn's
# instructions — flagged with a stronger note than the others.
NO_HOME_COLUMNS_REPORT = {
    "blocked_stock_raw / blocked_stock_cases / blocked_stock_pieces / blocked_stock_total_units": (
        "NEEDED DOWNSTREAM — this, together with Status, is the dead-stock "
        "signal the safety-stock/ROP work will eventually need (blocked "
        "stock isn't sellable, so it shouldn't count toward available "
        "quantity_on_hand the way this Transform currently treats it — see "
        "the note on quantity_on_hand below). No Inventory_Fact column "
        "exists for it; flagging for a schema decision, not adding one here."
    ),
    "status": (
        "NEEDED DOWNSTREAM — paired with Blocked Stock as the dead-stock "
        "signal (e.g. Status='Active' vs a discontinued/inactive value). "
        "Not carried into the Inventory_Fact-shaped output; kept in the raw "
        "staged data (staging/ssis_soh/) if needed before a schema change."
    ),
    "po_qty_raw": (
        "Not needed for Inventory_Fact itself (open purchase orders are a "
        "procurement-pipeline signal, not an on-hand quantity) — likely "
        "belongs on Purchase_Fact / LP replenishment inputs if ever used, "
        "not this fact."
    ),
    "open_so_quantity_raw": (
        "Not needed for Inventory_Fact itself (open sales orders are a "
        "demand-pipeline signal, not an on-hand quantity) — likely belongs "
        "with Sales_Fact-adjacent work if ever used, not this fact."
    ),
    "balance_quantity_raw": (
        "Not confirmed to carry information beyond stock_quantity_raw "
        "(observed, not verified invariant, to equal it row-for-row in "
        "sampled files — see column_maps/ssis_soh.yaml) — no clear "
        "downstream need until that relationship is confirmed or refuted "
        "against more data."
    ),
    "batch": (
        "Not needed — every sampled value is the literal string "
        "'VALUATED', not an actual batch/lot number (see "
        "column_maps/ssis_soh.yaml); carries no information as observed."
    ),
    "pack_size": (
        "Already consumed at Extract time (combined into "
        "stock_qty_total_units / blocked_stock_total_units) — no separate "
        "downstream need for the raw pack_size value itself once those "
        "derived columns exist, but it stays in the raw staged data for "
        "traceability."
    ),
}


@dataclass
class RowRejection:
    reason: str
    count: int
    detail: str = ""


@dataclass
class CategoryDriftRecord:
    sku_code: str
    snapshots: list[tuple[str, str | None]]  # (snapshot_date iso, category_desc)


@dataclass
class ProductDimensionCandidate:
    grain: str
    principal: str
    sku_code: str
    product_name: str | None
    category_path: str | None


@dataclass
class SsisSohTransformResult:
    inventory_fact_df: pd.DataFrame
    rejections: list[RowRejection]
    dedup_report: DedupReport
    category_drift: list[CategoryDriftRecord]
    product_dimension_candidates: list[ProductDimensionCandidate]
    input_rows: int
    distinct_snapshots_in: int


def _load_staged(staging_dir: Path) -> pd.DataFrame:
    doc_dir = staging_dir / STAGING_SUBDIR
    parquet_files = sorted(doc_dir.glob("*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(f"No staged ssis_soh parquet files under {doc_dir} — run Extract first.")
    return pd.concat([pd.read_parquet(f) for f in parquet_files], ignore_index=True)


def _most_recent_by_sku(df: pd.DataFrame, value_col: str) -> pd.Series:
    """For each sku_code, the value_col from its row with the max
    snapshot_date (R9's "most recent snapshot wins" rule). Ties (same SKU,
    same snapshot_date, which R2's dedupe should already prevent
    file-to-file, but a within-sheet duplicate SKU row is a different
    failure mode) resolve to pandas' stable last-row-wins, not a guess
    dressed up as a rule — none observed in this corpus (checked below via
    the natural-key dedup report)."""
    idx = df.sort_values("snapshot_date").groupby("sku_code", dropna=True).tail(1)
    return idx.set_index("sku_code")[value_col]


def transform_ssis_soh(
    staging_dir: Path | None = None,
    real_sku_codes: set[str] | None = None,
    repo_root: Path = REPO_ROOT,
) -> SsisSohTransformResult:
    staging_dir = staging_dir or (repo_root / "staging")
    raw = _load_staged(staging_dir)
    input_rows = len(raw)
    distinct_snapshots_in = raw["snapshot_date"].nunique(dropna=True)

    rejections: list[RowRejection] = []

    # Reject rows with no sku_code — confirmed (spot-checked) to be a
    # totals/blank row (huge stock_value, every other field null) that the
    # source sheet carries in its data body, one per snapshot. Cannot form
    # the natural key [sku_code, snapshot_date] at all, and is not a real
    # inventory row — never a real SKU with a null code.
    null_sku_mask = raw["sku_code"].isna()
    if null_sku_mask.any():
        rejections.append(RowRejection(
            "null sku_code (totals/blank row in source sheet body)",
            int(null_sku_mask.sum()),
            "spot-checked: this row's other fields are all null except a large "
            "stock_value figure — a per-sheet totals row, not a real SKU.",
        ))
    df = raw.loc[~null_sku_mask].copy()

    # --- R9: category drift, logged before collapsing to one row per SKU ---
    cat = df[["sku_code", "snapshot_date", "category_desc"]].dropna(subset=["sku_code"])
    category_drift: list[CategoryDriftRecord] = []
    for sku, group in cat.groupby("sku_code"):
        distinct_cats = group["category_desc"].dropna().unique()
        if len(distinct_cats) > 1:
            snaps = sorted(
                (
                    (row.snapshot_date.isoformat() if hasattr(row.snapshot_date, "isoformat") else str(row.snapshot_date)),
                    row.category_desc,
                )
                for row in group.itertuples()
            )
            category_drift.append(CategoryDriftRecord(sku_code=sku, snapshots=snaps))

    latest_category = _most_recent_by_sku(df, "category_desc")
    latest_product_name = _most_recent_by_sku(df, "article_description")

    # --- Inventory_Fact-shaped output ---
    out = pd.DataFrame({
        "sku_code": df["sku_code"],
        "snapshot_date": df["snapshot_date"],
        "_period": df["_period"],
        "principal": "unilever",
        "region": None,
        "quantity_on_hand": df["stock_qty_cases"],
        "quantity_pieces": df["stock_qty_pieces"],
        "valuation": df["stock_value"],
        # Informational only — NOT a home in Inventory_Fact, see module
        # docstring. Carried through so the report's NaN/negative check
        # below has real numbers to check, and so this isn't silently lost
        # before a schema decision is made.
        "last_purchase_price_gsv_per_cs": df["last_purchase_price_gsv_per_cs"],
        "is_demo": False,
        "_src_file": df["_src_file"],
        "_src_sheet": df["_src_sheet"],
    })

    out, dedup_report = dedup_facts(out, NATURAL_KEY, amount_col="quantity_on_hand")

    # --- R8: Product_Dimension candidates for non-joining Article Nos ---
    product_dimension_candidates: list[ProductDimensionCandidate] = []
    if real_sku_codes is not None:
        all_skus = df["sku_code"].dropna().unique()
        non_joining = sorted(s for s in all_skus if s not in real_sku_codes)
        for sku in non_joining:
            product_dimension_candidates.append(ProductDimensionCandidate(
                grain="sku",
                principal="unilever",
                sku_code=sku,
                product_name=latest_product_name.get(sku),
                category_path=latest_category.get(sku),
            ))

    return SsisSohTransformResult(
        inventory_fact_df=out,
        rejections=rejections,
        dedup_report=dedup_report,
        category_drift=category_drift,
        product_dimension_candidates=product_dimension_candidates,
        input_rows=input_rows,
        distinct_snapshots_in=distinct_snapshots_in,
    )


def write_outputs(result: SsisSohTransformResult, out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {}

    fact_path = out_dir / "inventory_fact_unilever_soh.parquet"
    result.inventory_fact_df.to_parquet(fact_path, index=False, engine="pyarrow")
    paths["inventory_fact"] = fact_path

    pd_rows = [
        {
            "grain": c.grain, "principal": c.principal, "sku_code": c.sku_code,
            "product_name": c.product_name, "category_path": c.category_path,
        }
        for c in result.product_dimension_candidates
    ]
    pd_path = out_dir / "product_dimension_candidates_r8.csv"
    pd.DataFrame(pd_rows, columns=["grain", "principal", "sku_code", "product_name", "category_path"]).to_csv(pd_path, index=False)
    paths["product_dimension_candidates"] = pd_path

    drift_rows = []
    for rec in result.category_drift:
        for snap_date, cat_val in rec.snapshots:
            drift_rows.append({"sku_code": rec.sku_code, "snapshot_date": snap_date, "category_desc": cat_val})
    drift_path = out_dir / "category_drift_r9.csv"
    pd.DataFrame(drift_rows, columns=["sku_code", "snapshot_date", "category_desc"]).to_csv(drift_path, index=False)
    paths["category_drift"] = drift_path

    return paths
