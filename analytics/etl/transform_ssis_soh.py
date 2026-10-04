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
  last_purchase_price_gsv_per_cs                -> unit_cost_per_case (schema.sql R11, added 2026-08 — this
                                                     docstring's claim of "NO HOME" was stale, predating R11.
                                                     scratch/run_ssis_soh_load.py:74 already had this exact
                                                     mapping; it was never carried into this module, so every
                                                     canonical load left Inventory_Fact.unit_cost_per_case NULL
                                                     for all 27,282 Unilever rows — found and fixed 2026-09-16
                                                     diagnosing a dashboard KPI/PR4 regression, see
                                                     reports/PROJECT_STATE_2026-09.md SS11). Del Monte's own
                                                     inventory_sign_off.yaml maps a raw "Cost" header to a
                                                     canonical "cost" column instead — a different unit (extended
                                                     peso total, not a per-case price), kept separate per R10/R11's
                                                     own reasoning below. The header's own text ("GSV/CS") already
                                                     answers the per-case-vs-per-unit question without guessing:
                                                     it is GSV PER CASE, not per piece/unit.
  snapshot_date, _period                        -> snapshot_date, _period (both already real per R5 — no
                                                     _snapshot_date_from_period() synthetic-first-of-month
                                                     fabrication needed here, unlike Del Monte's inventory_sign_off)
  sku_code                                      -> sku_code
  po_qty_raw ("PO Qty", CS/PC text)             -> po_qty_cases, po_qty_pieces (migration 0042, 2026-10-04):
                                                     the column as the file has it. Its MEANING is
                                                     unverified (pending SSM; DEC-34): it totals 1-3M
                                                     pieces every month, which doesn't fit in-transit
                                                     stock, so nothing treats it as such.
                                                     Parsed with the extract's own parse_cs_pc; a value
                                                     that isn't "<cases>/<pieces>" raises. A BLANK cell is
                                                     0 on order: of 11,811 non-blank values in the 39
                                                     staged counts, none is "0/0" (checked 2026-10-04), so
                                                     the file writes nothing instead of zero.
  (constant) principal='unilever', is_demo=False, region=None (Storage
  Location dropped at Extract per R6 — no real region concept for this
  source)

Columns with confirmed NO home in Inventory_Fact (reported, not added):
  Blocked Stock (CS/PC), Open SO Quantity, Balance Quantity,
  Batch, PACK SIZE
  Status -> stock_status (schema.sql R12) — fixed 2026-09-16, same class as
  unit_cost_per_case above. Blocked Stock (CS/PC) still has nowhere to
  land in terms of NEED, not schema — blocked_qty_cases/blocked_qty_pieces
  do exist (R12) but are confirmed genuinely empty at source (0/27,321
  non-null), so there is nothing to carry regardless of the column existing.
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
        "FIXED 2026-09-16 — now carried into the Inventory_Fact-shaped "
        "output as stock_status (schema.sql R12). Previously dropped; see "
        "module docstring."
    ),
    "po_qty_raw": (
        "CARRIED since 2026-10-04 as po_qty_cases/po_qty_pieces (migration "
        "0042), information only: its meaning is unverified pending SSM "
        "(DEC-34), so it is never subtracted from an order quantity. Kept "
        "apart from quantity_on_hand."
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
    # The rejected source rows themselves (2026-09-21, migration 0024) - `rejections`
    # above only carries a count, and etl_quarantine needs the rows.
    rejected_rows: pd.DataFrame = field(default_factory=pd.DataFrame)
    # PO Qty parse counts over the SKU rows: {rows, parsed, blank_as_zero}.
    # parsed + blank_as_zero == rows always; an unparseable value raises.
    po_qty_parse: dict = field(default_factory=dict)


def parse_po_qty(raw: pd.Series) -> tuple[pd.Series, pd.Series, dict]:
    """(cases, pieces, counts) for the "PO Qty" column. Blank = 0 on order
    (see the module docstring for the evidence); anything that isn't
    "<cases>/<pieces>" raises, through the extract's parse_cs_pc."""
    from analytics.etl.extract.ssis_soh import parse_cs_pc
    # A missing cell can come back from parquet as NaN, which is_blank
    # doesn't treat as blank.
    pairs = [parse_cs_pc(None if pd.isna(v) else v) for v in raw]
    blank = sum(1 for c, p in pairs if c is None and p is None)
    cases = pd.Series([0 if c is None else c for c, _ in pairs], index=raw.index, dtype="float64")
    pieces = pd.Series([0 if p is None else p for _, p in pairs], index=raw.index, dtype="float64")
    return cases, pieces, {"rows": len(pairs), "parsed": len(pairs) - blank, "blank_as_zero": blank}


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
    rejected_rows = raw.loc[null_sku_mask].copy()
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
    po_cases, po_pieces, po_qty_parse = parse_po_qty(df["po_qty_raw"])

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
        # unit_cost_per_case (schema.sql R11) — fixed 2026-09-16, see module
        # docstring above. Was carried through under the raw source name
        # (last_purchase_price_gsv_per_cs) and silently projected out by
        # run_canonical_load.py's column-projection step because nothing
        # named it into its real schema home.
        "unit_cost_per_case": df["last_purchase_price_gsv_per_cs"],
        # stock_status (schema.sql R12) — fixed 2026-09-16, same class/same
        # fix as unit_cost_per_case above. scratch/run_ssis_soh_load.py:77
        # already mapped raw "status" -> stock_status; never carried into
        # this module. blocked_qty_cases/blocked_qty_pieces (also R12) are
        # NOT fixed here — confirmed genuinely empty at source (0/27,321
        # non-null in staging/ssis_soh), nothing to carry.
        "stock_status": df["status"],
        # PO Qty (migration 0042), blank = 0. Meaning unverified (DEC-34).
        "po_qty_cases": po_cases,
        "po_qty_pieces": po_pieces,
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
        rejected_rows=rejected_rows,
        dedup_report=dedup_report,
        category_drift=category_drift,
        product_dimension_candidates=product_dimension_candidates,
        input_rows=input_rows,
        distinct_snapshots_in=distinct_snapshots_in,
        po_qty_parse=po_qty_parse,
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
