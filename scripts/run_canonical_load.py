"""
scripts/run_canonical_load.py - raw files -> fact tables, one slice at a time,
plus the ledgered migration runner.

WHAT A RUN DOES (2026-09-30 rewrite; the earlier whole-staging/ rebuild with
frozen expected-row constants is gone - see "WHY" below):

  --schema-only          apply pending migrations (ledger: schema_migrations)
                         and exit. On a brand-new schema, schema.sql runs
                         first; on a ledgered schema it never re-runs.
  --slice SPEC ...       incremental load of one or more slices (the loop in
                         scripts/load_slices.py). SPEC is
                         principal:table:YYYY-MM[:branch[:source]], e.g.
                           delmonte:sales_fact:2025-12
                           delmonte:sales_fact:2025-11:pangasinan
                           delmonte:salesreturn_fact:2025-10:*:rmr
                           unilever:unilever_sku_demand_fact:2026-02
  --all-slices           full rebuild from data/raw: every family is
                         transformed as a whole (so cross-file dedup and
                         conflicts decide exactly as one big load would), then
                         written one transaction per slice.
  --refresh-coverage     recompute etl_coverage for every principal x table x
                         month (the seed step after migration 0033).

A SLICE is principal x table x workbook month x branch x source. Its rows are
found by LINEAGE (the extract's own infer_sheet_period/infer_sheet_region
applied to each row's _src_file/_src_sheet for sales_fact, whose region
column is the customer's town and whose _period is the invoice month; the
stored _period/region for every other table, where they are the workbook
month and the branch). One transaction per slice:
  delete the slice's real rows -> (if any real rows arrive) delete that
  table-month's synthetic rows (DEC-29) -> delete the slice's etl_quarantine
  rows -> plain INSERT of the file's real rows (a key that still collides
  belongs to another slice: the slice is refused, never overwritten) ->
  insert its quarantine rows -> dimension rules -> ledger check (the table
  must hold exactly what the event says) -> etl_coverage -> etl_load_event ->
  audit_log.
A refused slice (shrink guard, unsigned fingerprint, key owned by another
slice, missing file, changed layout) changes nothing; its event is written in
a separate transaction after the rollback.

Synthetic rows are never loaded from files. staging/'s SYNTH__ copies are the
stale pre-clean-pool pools, and data/raw/Synthetic Data is v1. Synthetic data
lives only in the database (scripts/build_synthetic_v2_clean_pool.py +
apply_synth_v2_cutover.py); the loader only ever removes it, per DEC-29.

The Del Monte fixes of 2026-09-28 (scripts/apply_dm_fixes_to_public.py,
batches 3-7) are rules here, applied to every slice they touch:
  fix 3  valuation = cost where the sign-off sheet has no valuation
         (analytics.etl.transform.derive_valuation_from_cost)
  fix 4  RMR GS & BO lines -> salesreturn_fact, source = 'rmr', only for the
         periods in config/source_of_truth.yaml sales_return.rmr_fallback,
         plus migration 0028's dedupe rule when a sales-return file arrives
  fix 5  Del Monte pack_size from the price list CASE PACK, fill-if-NULL
  fix 6  Del Monte brand from the product name's first token
         (config/alias_tables/delmonte_brand.csv), fill-if-NULL
  fix 7  the hidden "PANGASINAN SALES REGISTER (2)" sheet is quarantined at
         transform (hold_pending_ssm), never reaches sales_fact

THE ONE HUMAN STEP - re-signing the Transform fingerprint. A slice run stages
its files under staging_slices/<run key>/ (never staging/), writes a manifest
of every sheet it read (row count + content hash) to
transform/slices/<run key>/_manifest.json, and refuses every slice
(status refused, reason fingerprint_unsigned) until a person has approved
that exact manifest:
    python -m scripts.run_canonical_load --schema <s> --slice ... --dry-run
    python -m analytics.etl.transform_signoff --transform-dir transform/slices/<run key> \
        --decision approved --by "<name>"
    python -m scripts.run_canonical_load --schema <s> --slice ...
The dry run prints the run key and fingerprint. A changed file changes the
content hash, so an old approval never carries over to new data.

WHY THE REWRITE: the 2026-09-30 rehearsal (reports/diagnostics/
load_readiness_2026-09-30.md) found the old whole-staging/ upsert could only
load into an empty schema (the NULL-region SOH conflict crash), never removed
a month's placeholders, re-added synthetic v1 rows and duplicate quarantine
rows, reverted fixes 3 and 7, and always exited 1 on stale frozen counts.
A row count is now checked against the database inside each slice's
transaction (the ledger check) instead of against a constant.

SCHEMA SCOPING: every load transaction sets `SET LOCAL search_path TO
<schema>` - the target schema only, so a table missing from a scratch schema
fails instead of resolving to the live table (migrations keep `<schema>,
public`). Transaction-scoped, never a session-level SET, which leaks through
the :6543 pooler. `public` is refused unless --target-public is passed with
--schema public (both explicit). A load against public refuses to run while a
migration is pending; migrations reach public only through --schema-only.

MIGRATION LEDGER CHECKSUMS: a stored checksum is accepted if it equals the
sha256 of the file's LF form OR its CRLF form. Migration 0019 seeded six rows
(0001, both 0002 files, 0003, 0012, 0013) from a CRLF (core.autocrlf)
checkout, so those six rows hold CRLF hashes; the other 25 hold LF hashes,
and .gitattributes now forces *.sql to LF. Accepting either form keeps every
stored row valid without rewriting it; new rows are written in LF form.

Usage:
    python -m scripts.run_canonical_load --schema ssm_x --schema-only
    python -m scripts.run_canonical_load --schema public --target-public --schema-only
    python -m scripts.run_canonical_load --schema ssm_x --slice delmonte:sales_fact:2025-12 [--dry-run]
    python -m scripts.run_canonical_load --schema ssm_rebuild --all-slices
    python -m scripts.run_canonical_load --schema ssm_x --refresh-coverage
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import logging
import re
import sys
from collections import Counter
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from sqlalchemy import Connection, Engine, MetaData, Table, create_engine, text

from analytics.config import get_settings
from analytics.etl.load import (
    DimensionFKSpec,
)
from analytics.etl.transform import (
    DEFAULT_CONFIG_DIR,
    _SELLOUT_SOURCE_DEFECT_CATEGORY_RE,
    QUARANTINE_REASON_COLUMN,
    QUARANTINE_RULE_COLUMN,
    apply_column_map,
    coerce_is_demo_column,
    load_source_of_truth,
    natural_key_series,
    transform_fact,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
STAGING_DIR = REPO_ROOT / "staging"
TRANSFORM_DIR = REPO_ROOT / "transform"
SCHEMA_SQL = REPO_ROOT / "analytics" / "db" / "schema.sql"
MIGRATIONS_DIR = REPO_ROOT / "analytics" / "db" / "migrations"

FORBIDDEN_SCHEMAS = {"public"}  # never a valid --schema value, see _require_scratch_schema

log = logging.getLogger("run_canonical_load")


def _scratch_engine(engine: Engine, schema: str, allow_public: bool = False) -> Engine:
    """Returns an Engine wrapper that schema-qualifies every SQLAlchemy Core
    construct (Table/insert/select via autoload_with=engine) to `schema`,
    via execution_options(schema_translate_map=...). Use this for every call
    into analytics.etl.load (load_to_supabase, resolve_dimension_fk) and for
    this script's own product_dimension SELECT/UPDATE via Core constructs.
    Does NOT affect raw text() SQL — see this module's SCHEMA SCOPING note
    for why schema.sql/migrations and the backfill's raw SQL need SET LOCAL
    search_path instead, issued separately."""
    _require_scratch_schema(schema, allow_public=allow_public)
    return engine.execution_options(schema_translate_map={None: schema})


def _require_scratch_schema(schema: str, allow_public: bool = False) -> None:
    """Refuses `public` (or anything obviously not a scratch schema name) as
    a safety guard, not just a default — this script must never be pointed
    at the live schema, even by a typo. Matches the schema-safety finding
    from Phase 1 step 2a (nothing else in this repo qualifies a schema, so
    nothing reads/writes here by accident — this script is the one place
    that must stay disciplined about which schema it targets).

    allow_public (2026-09-15, Phase 1 cutover, Yuan approved): the ONE
    exception, threaded explicitly through every call site rather than a
    global switch - only main()'s own top-level check and the two
    engine-wrapping helpers it calls pass True, and only when
    --target-public was itself explicitly passed on the command line.
    _drop_scratch_schema() (the failure-path rollback) deliberately does
    NOT accept this parameter at all - see its own docstring for why."""
    if not allow_public and schema.lower() in FORBIDDEN_SCHEMAS:
        raise ValueError(
            f"--schema {schema!r} is refused. This script targets a SCRATCH schema only, "
            f"never 'public' (the live schema). Pass a distinct scratch schema name."
        )


# ---------------------------------------------------------------------------
# Fact plan — dimension-dependency order. Each entry: (fact, principal,
# canonical table, natural_key override or None to use source_of_truth.yaml's,
# amount_col for dedup conflict detection, list of DimensionFKSpec builders).
# ---------------------------------------------------------------------------

def _product_fk_spec(grain: str) -> DimensionFKSpec:
    """Shared shape for every fact that FKs to Product_Dimension — same
    natural key/columns as tests/etl/test_load.py's existing fixture, just
    parameterized on grain (sku vs category)."""
    if grain == "sku":
        # NOT the 4-column table-wide key here (bug #4, found 2026-09-15
        # cutover incident, reports/PROJECT_STATE_2026-09.md §10):
        # category_path is mutated post-load for every Unilever SKU-grain
        # row by run_category_brand_backfill() (NULL -> a real value, once,
        # unconditionally) - a natural key that includes it goes stale the
        # moment that backfill runs once, and every later resolution
        # attempt (re-running the loader, a future incremental load) stops
        # matching existing rows and silently re-inserts them as "new".
        # Confirmed this is safe to narrow to (principal, grain, sku_code)
        # ONLY for this Unilever-locked FactPlanItem (see FACT_PLAN below -
        # this spec is never invoked for Del Monte): the backup shows 0 of
        # 2,098 Unilever SKU-grain rows share a sku_code, so sku_code alone
        # already uniquely identifies the row. Del Monte's product_dimension
        # rows (loaded outside this codepath, pre-canonical-load era) used
        # to have 252 sku_codes spanning multiple category_path values -
        # CORRECTED 2026-09-17 (column-gap audit, migration 0016): those
        # extra category_path values were never real. They came from
        # scripts/generate_synthetic_dm.py:31-44, an ad-hoc script whose own
        # docstring calls category_path a "fake category" guessed from a
        # keyword heuristic on the SKU description - no Del Monte source
        # ties an individual SKU to a category at all. Migration 0016
        # deduped those 291 rows and nulled the fake category_path values,
        # so Del Monte's sku-grain rows are no longer a different story:
        # sku_code alone uniquely identifies them too now (see the new
        # table-wide partial index, migration 0016). This spec still isn't
        # invoked for Del Monte (still loaded outside this codepath), but
        # the constraint it used to be safely narrower than no longer holds
        # a real distinction. Matching partial unique index for the
        # Unilever-only case below: migration 0014, scoped to
        # principal='unilever' AND grain='sku' - conflict_index_where below
        # must repeat that predicate verbatim for Postgres to infer it.
        return DimensionFKSpec(
            fk_column="product_key",
            dimension_table="product_dimension",
            dimension_pk="product_key",
            dimension_natural_key=["principal", "grain", "sku_code"],
            df_to_dimension_columns={"principal": "principal", "sku_code": "sku_code"},
            static_values={"grain": "sku"},
            conflict_index_where="principal = 'unilever' AND grain = 'sku'",
        )
    return DimensionFKSpec(
        fk_column="product_key",
        dimension_table="product_dimension",
        dimension_pk="product_key",
        dimension_natural_key=["principal", "grain", "sku_code", "category_path"],
        df_to_dimension_columns={"principal": "principal", "category_path": "category_path"},
        static_values={"grain": "category", "sku_code": None},
    )


def _customer_fk_spec() -> DimensionFKSpec:
    """Problem 2 (2026-09-14, Yuan's ruling — extend the loader, don't
    accept the regression): live sales_fact.customer_key is ~99.9%
    populated (53,275/53,320) via an old ad-hoc path; the canonical
    FACT_PLAN entry for sales never had a dimension_fks spec for it at
    all, so scratch's sales_fact.customer_key was 0/53,109 populated -
    not a bug in resolve_dimension_fk(), just a spec that was never
    written. Customer_Dimension's real UNIQUE(customer_name, region,
    principal) is a usable natural key; all three parts are already
    real, row-sourced columns (region/principal come from
    backfill_provenance_fields(), customer_name from column_maps/
    sales_register.yaml's "Customer Name" mapping) - no static_values
    needed, same DimensionFKSpec shape already proven for
    Product_Dimension above."""
    return DimensionFKSpec(
        fk_column="customer_key",
        dimension_table="customer_dimension",
        dimension_pk="customer_key",
        dimension_natural_key=["customer_name", "region", "principal"],
        df_to_dimension_columns={
            "customer_name": "customer_name", "region": "region", "principal": "principal",
        },
    )


def _salesman_fk_spec() -> DimensionFKSpec:
    """Same problem/ruling as _customer_fk_spec() above, for
    Salesman_Dimension's UNIQUE(salesman_name) - live salesman_key is
    ~99.7% populated (53,261/53,320). Single-column natural key; the raw
    field maps to canonical `salesman` (config/column_maps/
    sales_register.yaml's "Salesman"), a different name than the
    dimension's own `salesman_name` column - df_to_dimension_columns
    exists exactly to bridge that, dimension-col-name -> df-col-name."""
    return DimensionFKSpec(
        fk_column="salesman_key",
        dimension_table="salesman_dimension",
        dimension_pk="salesman_key",
        dimension_natural_key=["salesman_name"],
        df_to_dimension_columns={"salesman_name": "salesman"},
    )


@dataclass
class FactPlanItem:
    fact: str
    principal: str
    table_name: str
    amount_col: str
    dimension_fks: list[DimensionFKSpec] = field(default_factory=list)


# Dimension-dependency order. The frozen expected_rows / expected_conflicts /
# expected_quarantined constants measured 2026-09-11..17 were retired
# 2026-09-30: they could only ever describe one snapshot of data/raw, so every
# real change printed MISMATCH and exited 1 (load_readiness_2026-09-30.md,
# check 4e). Each slice now checks its own counts against the database inside
# its transaction (scripts/load_slices.py, the ledger check), and the numbers
# travel in etl_load_event. The history of those counts is in git.
FACT_PLAN: list[FactPlanItem] = [
    FactPlanItem(
        "sales_unilever_sku_demand", "unilever", "unilever_sku_demand_fact", "quantity_sold",
        dimension_fks=[_product_fk_spec("sku")],
    ),
    FactPlanItem(
        "sales", "delmonte", "sales_fact", "net_amount",
        # No product_key (invoice-grain, DEC-02); customer_key / salesman_key are
        # real FKs (problem 2, 2026-09-14) - see _customer_fk_spec()/_salesman_fk_spec().
        dimension_fks=[_customer_fk_spec(), _salesman_fk_spec()],
    ),
    FactPlanItem("purchase", "delmonte", "purchase_fact", "net_amount"),
    FactPlanItem("sales_return", "delmonte", "salesreturn_fact", "net_amount"),
    FactPlanItem(
        "sell_out", "delmonte", "sellout_fact", "net_amount",
        dimension_fks=[_product_fk_spec("category")],
    ),
    # DM sku-grain product_key is resolved post-load by
    # resolve_delmonte_inventory_product_key(), not this FK path.
    FactPlanItem("inventory", "delmonte", "inventory_fact", "quantity_on_hand"),
]


# Canonical column -> the fact table's own column, applied before
# _project_to_table_columns(). One entry today. The column map names the raw
# "Total Sales Amt Inc. Tax" `net_amount_inc_tax` because that is what it is;
# Unilever_SKU_Demand_Fact.net_amount is where it is stored (schema.sql: the
# column was added so Unilever can get an ABC tier at all). Nothing connected
# the two, so a canonical rebuild loaded all 24,906 real rows with NULL
# revenue (found 2026-09-21, scratch vs public diff).
FACT_COLUMN_RENAMES: dict[str, dict[str, str]] = {
    "unilever_sku_demand_fact": {"net_amount_inc_tax": "net_amount"},
}


def _rename_to_table_columns(df: pd.DataFrame, table_name: str) -> pd.DataFrame:
    renames = {
        src: dst for src, dst in FACT_COLUMN_RENAMES.get(table_name, {}).items()
        if src in df.columns and dst not in df.columns
    }
    if renames:
        print(f"  [{table_name}] renaming to the table's own column names: {renames}")
    return df.rename(columns=renames)


def _project_to_table_columns(
    df: pd.DataFrame, table_name: str, engine: Engine, dimension_fks: list[DimensionFKSpec],
) -> pd.DataFrame:
    """Drops every column `df` carries that has no home on `table_name` and
    isn't needed by load_to_supabase()'s own dimension-FK resolution —
    VISIBLY (printed, not silent) — before load_to_supabase() runs. Found
    necessary 2026-09-14, first real --dry-run: transform_fact() legitimately
    produces columns a fact table never has (e.g. unilever_sku's
    `product_name`/`pack_size` belong on Product_Dimension, not
    Unilever_SKU_Demand_Fact - resolve_unilever_demand_product_metadata()
    puts them there). CORRECTED 2026-09-21: this docstring used to say
    `net_amount_inc_tax` "has no destination at all". It does -
    Unilever_SKU_Demand_Fact.net_amount was added to hold exactly that value
    (schema.sql), and projecting it out here loaded every row with NULL
    revenue. FACT_COLUMN_RENAMES now names it before this runs. Without this,
    load_to_supabase()'s own "unknown columns" anti-fabrication check (its
    docstring: "this is not silently dropped") correctly refuses to guess
    what to do with them and raises — right behavior for that function, but
    the decision of what a fact table is even supposed to hold belongs one
    layer up, here, made once per table and printed so it's auditable, not
    inferred from a caught exception.

    Dimension-FK source columns (e.g. `principal`/`sku_code` for a spec
    resolving Product_Dimension) are kept even though the fact table itself
    won't hold them under that name — load_to_supabase() needs them present
    to call resolve_dimension_fk(), and (as of 2026-09-14) already excludes
    them from its own unknown-columns check for the same reason. Passing
    the same `dimension_fks` list here keeps this function's decision
    consistent with load_to_supabase()'s, rather than guessing twice."""
    metadata = MetaData()
    table = Table(table_name, metadata, autoload_with=engine)
    table_columns = {c.name for c in table.columns}
    dimension_source_columns = {v for spec in dimension_fks for v in spec.df_to_dimension_columns.values()}
    to_drop = [
        c for c in df.columns
        if not c.startswith("_") and c not in table_columns and c not in dimension_source_columns
    ]
    if to_drop:
        print(f"  [{table_name}] projecting out columns with no home on this table: {to_drop}")
    return df.drop(columns=to_drop)


def _drop_uninsertable_quarantined_rows(
    df: pd.DataFrame, table_name: str, engine: Engine, natural_key: list[str],
) -> tuple[pd.DataFrame, int]:
    """A quarantined row (any natural_key column null) is meant to be
    "flagged, not dropped" — dedup_facts() keeps it in its output on
    purpose. But that promise runs into schema.sql's own constraints:
    found 2026-09-14, the first real load, both the hard way -
    Sales_Fact.invoice_num and Purchase_Fact.invoice_num are `NOT NULL`
    (Inventory_Fact.sku_code likewise), so a row missing that specific key
    part cannot be INSERTed at all, full stop, regardless of what this
    script wants. Fabricating a value to satisfy the constraint is exactly
    what the anti-fabrication rule forbids, so the honest resolution is:
    exclude ONLY the rows whose null key column is genuinely NOT NULL on
    the target table (checked here via real schema reflection, not
    assumed) from the INSERT — they were already counted in
    `actual_quarantined` before this runs, so they are not lost from the
    report, only from a table that structurally cannot hold them.
    SalesReturn_Fact is the counter-example that proves this isn't a
    blanket rule: both its key halves (return_slip_num, invoice_num) are
    nullable, so its 773 real quarantined rows (missing return_type, not
    either of those) load there just fine — checked per-column, not
    assumed uniform across facts."""
    metadata = MetaData()
    table = Table(table_name, metadata, autoload_with=engine)
    not_null_key_cols = [
        c for c in natural_key
        if c in df.columns and c in table.columns and not table.columns[c].nullable
    ]
    if not not_null_key_cols:
        return df, 0
    cannot_insert = df[not_null_key_cols].isna().any(axis=1)
    if cannot_insert.any():
        print(f"  [{table_name}] {int(cannot_insert.sum())} quarantined rows cannot be "
              f"inserted (NOT NULL on {not_null_key_cols}) - excluded from the INSERT, "
              f"still counted in the quarantine total above, not silently lost")
    return df.loc[~cannot_insert].copy(), int(cannot_insert.sum())


def _drop_rows_violating_other_not_null(
    df: pd.DataFrame, table_name: str, engine: Engine, natural_key: list[str],
) -> tuple[pd.DataFrame, int]:
    """Same principle as _drop_uninsertable_quarantined_rows(), but for
    NOT NULL columns OUTSIDE the natural key - found 2026-09-14, same
    load run, right after the key-column fix: Sales_Fact.net_amount is
    NOT NULL, and one is_demo=true sales_register row from the 2026-04
    Ilocos backfill had a null net_amount. Traced (not assumed) to
    scripts/generate_synthetic_backfill.py::load_real_family_template():
    it resamples straight from staging/'s raw 2025 sales_register pool,
    which still contains the signature-block junk rows (see
    SALES_REGISTER_FOOTER_CHECKS' non_numeric="net_amount" check, added
    this same session) that Transform excludes for REAL data but that the
    synthetic generator's pool was never filtered against - a real bug in
    that script, out of scope to fix/regenerate here (it writes its own
    materialized staging_synthetic/ files, a separate action from this
    load). An explicit NULL always overrides a column's DEFAULT (verified
    earlier this session), and this column has no meaningful default
    (there's no correct net_amount to invent - the anti-fabrication rule
    forbids guessing one), so the only honest fix at load time is the
    same one already applied to key columns: exclude the row, print why,
    never fabricate. Demo-only (is_demo=true) in every case observed -
    if a REAL row ever hit this it would be a genuine data-quality defect
    worth stopping to investigate, not silently dropped, so this is
    flagged distinctly per row (principal/is_demo shown) rather than
    folded into the same silent message as the key-column case."""
    metadata = MetaData()
    table = Table(table_name, metadata, autoload_with=engine)
    other_not_null_cols = [
        c for c in df.columns
        if c not in natural_key and c in table.columns and not table.columns[c].nullable
    ]
    if not other_not_null_cols:
        return df, 0
    cannot_insert = df[other_not_null_cols].isna().any(axis=1)
    if cannot_insert.any():
        bad = df.loc[cannot_insert]
        demo_counts = bad["is_demo"].value_counts().to_dict() if "is_demo" in bad.columns else {}
        print(f"  [{table_name}] {int(cannot_insert.sum())} rows have a null in a NOT NULL "
              f"non-key column {other_not_null_cols} - excluded from the INSERT "
              f"(is_demo breakdown: {demo_counts})")
    return df.loc[~cannot_insert].copy(), int(cannot_insert.sum())


def _drop_conflicting_group_rows(
    df: pd.DataFrame, table_name: str, natural_key: list[str],
) -> tuple[pd.DataFrame, int]:
    """dedup_facts() deliberately KEEPS every row of a conflicting group
    (same natural key, disagreeing amount_col) instead of picking one —
    "flagged, not resolved", a human decision (its own docstring). But
    load_to_supabase() upserts via ON CONFLICT DO UPDATE, and Postgres
    refuses outright when two rows in the SAME INSERT target the same
    conflict key ("ON CONFLICT DO UPDATE command cannot affect row a
    second time") - found 2026-09-14, purchase_fact, on real execution.

    Item 36 (2026-09-14, full sweep + diff follow-up): the original
    version of this function dropped EVERY row in a conflicting group
    uniformly, real and demo alike. That's correct for a group of 2+ REAL
    rows genuinely disagreeing (sales_fact's 1 case, INV/2024/0542 -
    decision item 23, "show don't fix" - a real human-review case). It was
    WRONG for purchase_fact: a large, older synthetic dataset
    (data/raw/Synthetic Data/PURCHASE_ORDER_*.xlsx) reuses the real
    BILL/YYYY/NNNN invoice-number scheme with low sequential numbers,
    colliding with genuine Del Monte invoices - 95 real rows (100% of
    Jan+Feb 2024, partial Mar/Apr 2025) were being dropped alongside the
    demo rows that actually caused the collision. That inverts CLAUDE.md
    rule 2 (synthetic data must never compromise real reported data): a
    real row should never lose to demo noise it didn't create.

    Fixed: within a group that contains at least one real (is_demo=false)
    row, drop only the demo rows and keep the real row(s) - the real data
    was never in question, only which invoice number the demo generator
    picked. A group with NO real rows (pure demo-vs-demo) is unaffected -
    still fully dropped, still flagged. A group of 2+ REAL rows still gets
    the original treatment (drop all, flag for human review) - keeping
    all real conflicting rows in a real-vs-real case would silently
    upsert whichever one Postgres happens to touch last, which is exactly
    what this function exists to prevent."""
    key_cols = [c for c in natural_key if c in df.columns]
    if not key_cols:
        return df, 0
    resolvable_mask = df[key_cols].notna().all(axis=1)
    resolvable = df.loc[resolvable_mask]
    if resolvable.empty:
        return df, 0
    group_keys = natural_key_series(resolvable, key_cols)
    group_sizes = resolvable.groupby(group_keys, sort=False)[key_cols[0]].transform("size")
    conflict_idx = resolvable.index[group_sizes > 1]
    if len(conflict_idx) == 0:
        return df, 0

    conf = df.loc[conflict_idx]
    has_is_demo = "is_demo" in conf.columns
    demo_dropped_idx = []
    real_kept_idx = []
    real_vs_real_dropped_idx = []
    mixed_groups = 0
    real_vs_real_groups = 0
    for _, grp in conf.groupby(natural_key_series(conf, key_cols), sort=False):
        is_demo = grp["is_demo"] if has_is_demo else pd.Series([False] * len(grp), index=grp.index)
        has_real = (is_demo != True).any()  # noqa: E712
        has_demo = (is_demo == True).any()  # noqa: E712
        if has_real and has_demo:
            mixed_groups += 1
            demo_dropped_idx.extend(grp.index[is_demo == True].tolist())  # noqa: E712
            real_kept_idx.extend(grp.index[is_demo != True].tolist())  # noqa: E712
        else:
            # pure-demo or pure-real (2+ real rows disagreeing): unchanged
            # behavior, drop the whole group.
            if has_real:
                real_vs_real_groups += 1
            real_vs_real_dropped_idx.extend(grp.index.tolist())

    dropped_idx = demo_dropped_idx + real_vs_real_dropped_idx
    if mixed_groups:
        print(f"  [{table_name}] {mixed_groups} conflicting group(s) were real rows colliding "
              f"with demo rows sharing the same key - kept the {len(real_kept_idx)} real "
              f"row(s), dropped only the {len(demo_dropped_idx)} demo row(s) (item 36 fix)")
    if real_vs_real_dropped_idx:
        n_real = int((conf.loc[real_vs_real_dropped_idx, "is_demo"] != True).sum()) if has_is_demo else 0  # noqa: E712
        print(f"  [{table_name}] {len(real_vs_real_dropped_idx)} rows across "
              f"{conf.loc[real_vs_real_dropped_idx].groupby(natural_key_series(conf.loc[real_vs_real_dropped_idx], key_cols), sort=False).ngroups} unresolved "
              f"conflicting group(s) with no real+demo mix ({real_vs_real_groups} real-vs-real, "
              f"{n_real} real rows involved) excluded from the INSERT - Postgres' ON CONFLICT "
              f"DO UPDATE cannot target the same row twice in one statement; these stay flagged "
              f"in the conflict report above for a human decision, never auto-resolved by "
              f"insert order")
    return df.drop(index=dropped_idx).copy(), len(dropped_idx)


# ---------------------------------------------------------------------------
# etl_quarantine (migration 0024) - every source row a load did not insert is
# written here with the rule that stopped it. Rows are followed by `_qid`, a
# per-fact row number stamped on the staged frame before Transform; a leading
# underscore keeps it out of the column map, the dedup comparison and the
# INSERT, the same way _src_file/_row_ordinal already travel.
# ---------------------------------------------------------------------------

QUARANTINE_TABLE = "etl_quarantine"
QID = "_qid"


def _json_safe_row(row: pd.Series) -> str:
    values = {}
    for col, value in row.items():
        if str(col).startswith("_"):
            continue
        try:
            if pd.isna(value):
                continue
        except (TypeError, ValueError):
            pass
        values[str(col)] = value
    return json.dumps(values, default=str, ensure_ascii=False)


def _quarantine_records(rows: pd.DataFrame, table_name: str, rule: str, reason) -> list[dict]:
    """`reason` is a string, or a callable(row) -> string for a per-row reason.
    slice_period / slice_region are the row's Extract provenance (_period /
    _region), carried so a slice load can tell which slice a record belongs to;
    they are not etl_quarantine columns (write_quarantine drops them)."""
    records = []
    for _, row in rows.iterrows():
        ordinal = row.get("_row_ordinal")
        src_file, src_sheet = row.get("_src_file"), row.get("_src_sheet")
        period, region = row.get("_period"), row.get("_region")
        records.append({
            "table_name": table_name,
            "rule": rule,
            "reason": reason(row) if callable(reason) else reason,
            "_src_file": src_file if pd.notna(src_file) else None,
            "_src_sheet": src_sheet if pd.notna(src_sheet) else None,
            "_row_ordinal": int(ordinal) if ordinal is not None and pd.notna(ordinal) else None,
            "is_demo": bool(row.get("is_demo") == True),  # noqa: E712
            "raw_values": _json_safe_row(row),
            "slice_period": period if isinstance(period, str) else None,
            "slice_region": region if isinstance(region, str) else None,
        })
    return records


def _transform_stage_exclusions(
    item: FactPlanItem, rule, principal_df: pd.DataFrame, mapped_df: pd.DataFrame, deduped_df: pd.DataFrame,
) -> list[dict]:
    """Rows Transform removed, classified by where they went missing: never
    reached the mapped frame (source-of-truth filter, sell-out defect merge,
    footer checks) or collapsed by dedup_facts() as an exact duplicate."""
    records: list[dict] = []
    mapped_ids = set(mapped_df[QID].dropna()) if QID in mapped_df.columns else set()
    gone = principal_df[~principal_df[QID].isin(mapped_ids)]
    if not gone.empty:
        gone_mapped, _ = apply_column_map(gone, rule.doc_type, DEFAULT_CONFIG_DIR)
        gone_mapped = coerce_is_demo_column(gone_mapped)
        role = gone_mapped["_sheet_role"] if "_sheet_role" in gone_mapped.columns else pd.Series("", index=gone_mapped.index)
        doc = gone_mapped["_doc_type"] if "_doc_type" in gone_mapped.columns else pd.Series("", index=gone_mapped.index)
        not_sot = ~role.isin(rule.system_of_record_role) | doc.isin(rule.cross_check_doc_types)
        records += _quarantine_records(
            gone_mapped[not_sot], item.table_name, "filter_source_of_truth",
            lambda r: (f"_sheet_role={r.get('_sheet_role')!r} / _doc_type={r.get('_doc_type')!r} is a cross-check "
                       f"view, not the system of record {rule.system_of_record_role}; its natural key is null or "
                       f"already present on a system-of-record sheet"),
        )
        rest = gone_mapped[~not_sot]
        merged = pd.Series(False, index=rest.index)
        if rule.doc_type == "sell_out" and "category_path" in rest.columns:
            merged = rest["category_path"].map(
                lambda v: isinstance(v, str) and bool(_SELLOUT_SOURCE_DEFECT_CATEGORY_RE.match(v.strip()))
            ).astype(bool)
        records += _quarantine_records(
            rest[merged], item.table_name, "relabel_sellout_source_defect_categories",
            "category label is the source-file defect 'False'; merged into the UNCLASSIFIED row for its "
            "region and period - amounts summed into that row, not lost",
        )
        records += _quarantine_records(
            rest[~merged], item.table_name, f"exclude_footer_rows[{rule.doc_type}]",
            "matched a footer / header / section-marker / blank-row check for this family",
        )
    kept_ids = set(deduped_df[QID].dropna()) if QID in deduped_df.columns else set()
    collapsed = mapped_df[mapped_df[QID].notna() & ~mapped_df[QID].isin(kept_ids)]
    records += _quarantine_records(
        collapsed, item.table_name, "dedup_facts",
        lambda r: ("exact duplicate on every business column of a kept row with the same natural key "
                   + str({k: r.get(k) for k in rule.natural_key})),
    )
    return records


def _loader_stage_exclusions(before: pd.DataFrame, after: pd.DataFrame, table_name: str, rule: str, reason) -> list[dict]:
    if QID not in before.columns:
        return []
    return _quarantine_records(before[~before[QID].isin(set(after[QID]))], table_name, rule, reason)


def known_duplicate_file_records() -> list[dict]:
    """Quarantine records for the rows of every file Extract skips as a confirmed byte-identical duplicate
    (analytics/etl/extract/sales_return.py KNOWN_DUPLICATES). The skip happens at file selection, so without
    this the copy's rows exist nowhere in the database. Each copy is run through the same Extract and
    Transform as the file that IS loaded, and byte-identity with that original ("<name>" without " (1)") is
    re-checked here - a copy that has drifted raises instead of being recorded as a duplicate."""
    from analytics.etl.extract._shared import process_file
    from analytics.etl.extract.sales_return import DOC_TYPE, KNOWN_DUPLICATES

    records: list[dict] = []
    for name in sorted(KNOWN_DUPLICATES):
        copy = next((REPO_ROOT / "data" / "raw").rglob(name))
        original = copy.with_name(name.replace(" (1)", ""))
        md5_copy, md5_original = (hashlib.md5(p.read_bytes()).hexdigest() for p in (copy, original))
        if md5_copy != md5_original:
            raise RuntimeError(f"{name} is no longer byte-identical to {original.name} ({md5_copy} vs {md5_original})")
        staged = pd.concat([df for df, _ in process_file(copy, DOC_TYPE).dfs], ignore_index=True)
        staged[QID] = range(len(staged))
        rows, _ = transform_fact(staged, DOC_TYPE, "delmonte", DEFAULT_CONFIG_DIR, amount_col="net_amount")
        records += _quarantine_records(
            rows, "salesreturn_fact", f"extract_known_duplicate_file[{DOC_TYPE}]",
            f"byte-identical copy (md5 {md5_copy}) of '{original.name}', whose rows are loaded; "
            f"Extract skips the copy (analytics/etl/extract/sales_return.py KNOWN_DUPLICATES)",
        )
    return records


QUARANTINE_DB_COLUMNS = ("table_name", "rule", "reason", "_src_file", "_src_sheet", "_row_ordinal", "is_demo", "raw_values")


def write_quarantine(engine: Engine | Connection, run_id: str, records: list[dict], dry_run: bool,
                     batch_size: int = 1000) -> int:
    """`engine` is the schema-scoped Engine or the slice's own Connection.
    Returns rows written."""
    if dry_run or not records:
        return 0
    table = Table(QUARANTINE_TABLE, MetaData(), autoload_with=engine)
    rows = [{**{k: r[k] for k in QUARANTINE_DB_COLUMNS}, "run_id": run_id, "raw_values": json.loads(r["raw_values"])}
            for r in records]
    with (nullcontext(engine) if isinstance(engine, Connection) else engine.begin()) as conn:
        for start in range(0, len(rows), batch_size):
            conn.execute(table.insert(), rows[start:start + batch_size])
    return len(records)


@dataclass
class PreparedFact:
    """A fact's rows after Transform and the loader's exclusions - nothing
    written yet. load_input is what a slice INSERTs; quarantine is every
    source row that will not be inserted, with its rule; transformed is the
    post-transform real frame before projection (dimension rules read
    columns the fact table does not keep, e.g. product_name)."""
    item: FactPlanItem
    natural_key: list[str]
    load_input: pd.DataFrame
    quarantine: list[dict]
    transformed: pd.DataFrame


def prepare_fact(
    item: FactPlanItem, staged: pd.DataFrame, engine: Engine | Connection,
    reference_pairs: frozenset = frozenset(), extra_known_keys: set[tuple] | None = None,
) -> PreparedFact:
    """Transform + the loader's exclusions for one fact, writing nothing
    (`engine` is used for table reflection only). `staged` is the family's
    staged rows. reference_pairs: (_src_file, _src_sheet) of sheets read only
    so that dedup decides as a whole-corpus load would (the April-2025 copy of
    the "(2)" sheet); their rows are neither loaded nor quarantined here.
    extra_known_keys: see analytics.etl.transform.rescue_cross_check_orphans."""
    rule = load_source_of_truth(item.fact, item.principal, DEFAULT_CONFIG_DIR)
    principal_df = staged[staged["_principal"] == item.principal] if "_principal" in staged.columns else staged
    principal_df = principal_df.copy()
    if "is_demo" not in principal_df.columns:
        # Real files carry no is_demo cell ("absent = real", coerce_is_demo_column).
        # Stated explicitly so a real-only slice records the same raw_values as a
        # load that also read synthetic files, where the column existed.
        principal_df["is_demo"] = False
    principal_df[QID] = range(len(principal_df))
    deduped_df, report = transform_fact(
        principal_df, item.fact, item.principal, DEFAULT_CONFIG_DIR, amount_col=item.amount_col,
        extra_known_keys=extra_known_keys,
    )

    quarantine = _transform_stage_exclusions(item, rule, principal_df, report["mapped_df"], deduped_df)
    # H1 / D12 (2026-09-22) and fix 7 (2026-09-30): rows Transform marked with a
    # ruled reason never load; they go to etl_quarantine under their own rule
    # (QUARANTINE_RULE_COLUMN, default flag_source_quarantine). After dedup, so
    # a marked row that collapsed into a kept copy is recorded once, as the
    # dedup collapse.
    if QUARANTINE_REASON_COLUMN in deduped_df.columns:
        marked = deduped_df[QUARANTINE_REASON_COLUMN].notna()
        if marked.any():
            rules = (deduped_df[QUARANTINE_RULE_COLUMN] if QUARANTINE_RULE_COLUMN in deduped_df.columns
                     else pd.Series(None, index=deduped_df.index, dtype=object))
            rules = rules.where(rules.notna(), "flag_source_quarantine")
            for rule_name, grp in deduped_df[marked].groupby(rules[marked], sort=True):
                quarantine += _quarantine_records(grp, item.table_name, rule_name, lambda r: r[QUARANTINE_REASON_COLUMN])
            print(f"  [{item.table_name}] {int(marked.sum())} row(s) quarantined by ruling: "
                  f"{dict(Counter(rules[marked]))}")
        deduped_df = deduped_df[~marked]

    # Real rows only (2026-09-30): synthetic rows live in the database, never in
    # a load - staging/'s SYNTH__ copies are stale pre-clean-pool pools.
    if "is_demo" in deduped_df.columns:
        demo = (deduped_df["is_demo"] == True).fillna(False).astype(bool)  # noqa: E712
        if demo.any():
            print(f"  [{item.table_name}] {int(demo.sum())} is_demo row(s) in the input - not loaded "
                  f"(synthetic rows are never loaded from files)")
        deduped_df = deduped_df[~demo]
    transformed = deduped_df

    load_input = _rename_to_table_columns(deduped_df, item.table_name)
    load_input = _project_to_table_columns(load_input, item.table_name, engine, item.dimension_fks)
    stage_in = load_input
    load_input, _ = _drop_uninsertable_quarantined_rows(load_input, item.table_name, engine, rule.natural_key)
    quarantine += _loader_stage_exclusions(
        stage_in, load_input, item.table_name, "_drop_uninsertable_quarantined_rows",
        lambda r: (f"natural-key column(s) {[k for k in rule.natural_key if k in r.index and pd.isna(r[k])]} are null "
                   f"and NOT NULL on {item.table_name}; no key is fabricated"),
    )
    stage_in = load_input
    load_input, _ = _drop_rows_violating_other_not_null(load_input, item.table_name, engine, rule.natural_key)
    quarantine += _loader_stage_exclusions(
        stage_in, load_input, item.table_name, "_drop_rows_violating_other_not_null",
        f"a NOT NULL non-key column of {item.table_name} is null on this row; no value is fabricated",
    )
    stage_in = load_input
    load_input, _ = _drop_conflicting_group_rows(load_input, item.table_name, rule.natural_key)
    quarantine += _loader_stage_exclusions(
        stage_in, load_input, item.table_name, "_drop_conflicting_group_rows",
        lambda r: ("shares its natural key " + str({k: r.get(k) for k in rule.natural_key})
                   + " with a row that differs on a business column (or is a demo row colliding with a real one); "
                     "needs a human decision, never resolved by insert order"),
    )

    if reference_pairs:
        def _is_ref(frame: pd.DataFrame) -> pd.Series:
            if frame.empty or "_src_file" not in frame.columns:
                return pd.Series(False, index=frame.index)
            return pd.Series([(f, s) in reference_pairs for f, s in zip(frame["_src_file"], frame["_src_sheet"])],
                             index=frame.index)
        load_input = load_input[~_is_ref(load_input)]
        transformed = transformed[~_is_ref(transformed)]
        quarantine = [r for r in quarantine if (r["_src_file"], r["_src_sheet"]) not in reference_pairs]

    print(f"  [{item.table_name}] prepared {len(load_input)} row(s) to load, {len(quarantine)} excluded source row(s): "
          f"{dict(Counter(r['rule'] for r in quarantine))}")
    return PreparedFact(item, list(rule.natural_key), load_input, quarantine, transformed)


# ---------------------------------------------------------------------------
# Category / brand backfill — runs last. Self-contained (does not reuse
# transform_ssis_soh's non-joining-only product_dimension_candidates, which
# covers a different, narrower population — see this file's own design
# notes). Reproduces the exact direct-match + keyword-fallback logic
# validated in Phase 0 (reports/PROJECT_STATE_2026-09.md §8): direct SOH
# match 79.0%, keyword rule at confidence >= 0.6 (validated out-of-sample at
# 97.4%), else UNCLASSIFIED.
# ---------------------------------------------------------------------------

_PACK_SIZE_TOKEN = re.compile(r"\d+X\d+\w*|\d+\s?(ML|G|GM|GR|KG|L|LT|PC|PCS|CS|X)\b")


def _tokenize(desc: str) -> list[str]:
    d = re.sub(r"[^A-Za-z0-9 ]", " ", str(desc).upper())
    d = _PACK_SIZE_TOKEN.sub(" ", d)
    return [t for t in d.split() if len(t) >= 3 and not t.isdigit()]


def _fit_keyword_rule(labelled: pd.DataFrame) -> dict[str, Counter]:
    """token -> Counter(category -> count), fit on every labelled (SOH-
    matched) SKU. Validated out-of-sample 2026-09-11 (70/30 split, seed 42):
    94.6% accuracy overall, 97.4% at confidence >= 0.6 (89% coverage) —
    see reports/archive/PHASE0_FOLLOWUP_CHECKS.md / PROJECT_STATE_2026-09.md §8.
    Fit on the FULL labelled set here (not a held-out split) because this is
    the production rule, not a validation run — the validation already
    happened and is cited above, not repeated at load time."""
    tok_cat: dict[str, Counter] = {}
    for _, r in labelled.iterrows():
        for t in set(_tokenize(r["article_description"])):
            tok_cat.setdefault(t, Counter())[r["category_desc"]] += 1
    return tok_cat


def _predict_category(desc: str, tok_cat: dict[str, Counter]) -> tuple[str | None, float]:
    score: Counter = Counter()
    for t in set(_tokenize(desc)):
        cc = tok_cat.get(t)
        if not cc:
            continue
        tot = sum(cc.values())
        for cat, n in cc.items():
            score[cat] += n / tot
    if not score:
        return None, 0.0
    cat, s = score.most_common(1)[0]
    total = sum(score.values())
    return cat, s / total


KEYWORD_CONFIDENCE_THRESHOLD = 0.6  # validated 2026-09-11, see _fit_keyword_rule's docstring

BRAND_ALIAS_TABLE = REPO_ROOT / "config" / "alias_tables" / "unilever_brand.csv"


# Mojibake/smart-quote apostrophes (U+FFFD, U+2019, U+2018) -> ASCII "'".
# One pattern for every product-name source: the SOH snapshot (2026-09-18)
# and the demand file's product_name (2026-09-22, two LADY'S CHOICE SKUs).
_APOSTROPHE_VARIANTS = "[�’‘]"


def _load_soh_snapshot(staging_dir: Path = STAGING_DIR) -> pd.DataFrame:
    """Most-recent SOH snapshot per sku_code — sku_code, article_description,
    category_desc. Same DEC-21 rule transform_ssis_soh.py already uses
    (_most_recent_by_sku), reproduced here independently because that
    module only exposes category info for NON-joining SKUs
    (product_dimension_candidates) — this backfill needs it for every
    Unilever SKU, joining or not. Empty when `staging_dir` has no ssis_soh
    sheets (a slice run that did not stage SOH): the category/brand rule then
    only classifies SKUs that have no category yet."""
    fs = sorted((staging_dir / "ssis_soh").glob("*.parquet"))
    if not fs:
        return pd.DataFrame(columns=["sku_code", "article_description", "category_desc", "snapshot_date"])
    soh = pd.concat(
        [pd.read_parquet(f, columns=["sku_code", "article_description", "category_desc", "snapshot_date"]) for f in fs],
        ignore_index=True,
    )
    # dropna BEFORE astype(str) - found 2026-09-14 (full sweep, class 4/6):
    # .astype(str) on a null sku_code produces the literal string "nan" or
    # "None", not a null value - grouping on that afterward would silently
    # coalesce every genuinely-missing-sku_code row (~39 known in this
    # corpus, one per snapshot - a blank/totals-adjacent source row) into
    # one fake "nan"-named SKU.
    soh = soh.dropna(subset=["sku_code"])
    soh["sku_code"] = soh["sku_code"].astype(str).str.strip()
    soh["category_desc"] = soh["category_desc"].astype(str).str.strip().replace({"": None, "nan": None})
    soh = soh.dropna(subset=["category_desc"])
    # Normalize mojibake/smart-quote apostrophes (U+FFFD, U+2019, U+2018) to
    # ASCII "'" before anything tokenizes article_description — found
    # 2026-09-18: 'LADY�S CHOICE...' (product_keys 120, 121).
    soh["article_description"] = soh["article_description"].astype(str).str.replace(
        _APOSTROPHE_VARIANTS, "'", regex=True
    )
    return soh.sort_values("snapshot_date").groupby("sku_code").last().reset_index()


def _load_brand_alias_table() -> dict[str, str]:
    if not BRAND_ALIAS_TABLE.exists():
        log.warning(
            "  %s does not exist yet — brand backfill will run WITHOUT alias "
            "normalization (mojibake variants like LADYS/LADY'S/LADY?S will "
            "NOT be merged). Build this file before relying on brand_source "
            "counts for anything reported.", BRAND_ALIAS_TABLE,
        )
        return {}
    df = pd.read_csv(BRAND_ALIAS_TABLE)
    return dict(zip(df["raw"], df["canonical"]))


def _clean_text(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    cleaned = " ".join(str(value).split())  # the MHTML source wraps names: "MASTER\r\n  CLEANSER ..."
    cleaned = re.sub(_APOSTROPHE_VARIANTS, "'", cleaned)
    return cleaned or None


def _pack_size_text(value) -> str | None:
    """Product_Dimension.pack_size is TEXT. 144.0 -> '144'; anything that is
    not a whole number is kept as the source wrote it, never rounded."""
    if value is None or pd.isna(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _clean_text(value)
    return str(int(number)) if number == int(number) else str(value).strip()


@contextmanager
def _in_schema(engine: Engine | Connection, schema: str):
    """A connection whose unqualified names resolve to `schema`. Handed a
    Connection (a slice's own transaction, scripts/load_slices.py), the work
    joins that transaction; handed an Engine, it runs in one of its own.
    SET LOCAL either way - never a session-level setting - and the target
    schema only: no `public` fallback for a table a scratch schema lacks."""
    if isinstance(engine, Connection):
        engine.execute(text("SET LOCAL search_path TO :schema").bindparams(schema=schema))
        yield engine
        return
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL search_path TO :schema").bindparams(schema=schema))
        yield conn


def _nn(value):
    """None for None/NaN, else the value - pandas turns a NULL into NaN in some columns."""
    return None if value is None or (isinstance(value, float) and pd.isna(value)) else value


def resolve_unilever_demand_product_metadata(
    engine: Engine | Connection, schema: str, dry_run: bool, staging_dir: Path = STAGING_DIR,
) -> dict[str, int]:
    """Writes product_name and pack_size from the Unilever demand file onto
    Product_Dimension (2026-09-21). transform_fact() maps both columns
    (config/column_maps/unilever_sku.yaml) and _project_to_table_columns()
    correctly keeps them off the fact table - this carries them to the
    dimension, where they belong.

    Real rows only - a synthetic file never names a real product. Most recent
    calendar_month wins when a SKU's description changes (the latest non-null
    value). The demand file is one workbook covering every month, so a slice
    run stages the whole file and this reads all of it: the result is the same
    whichever month was loaded. Set-based (2026-09-30); rows_updated counts
    rows whose value actually changed."""
    doc_dir = staging_dir / "unilever_sku"
    files = sorted(doc_dir.glob("*.parquet"))
    result = {"skus_in_demand_file": 0, "product_name_written": 0, "pack_size_written": 0, "rows_updated": 0}
    if not files:
        print("\n[Product_Dimension unilever demand metadata] no unilever_sku sheets staged - nothing written.")
        return result
    raw = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    mapped, _ = apply_column_map(raw, "unilever_sku", DEFAULT_CONFIG_DIR)
    mapped = coerce_is_demo_column(mapped)
    if "is_demo" in mapped.columns:
        mapped = mapped[mapped["is_demo"] != True]  # noqa: E712
    have = [c for c in ("product_name", "pack_size") if c in mapped.columns]
    if not have or "sku_code" not in mapped.columns:
        print("\n[Product_Dimension unilever demand metadata] no product_name/pack_size column staged - nothing written.")
        return result

    mapped = mapped.dropna(subset=["sku_code"]).copy()
    mapped["sku_code"] = mapped["sku_code"].astype(str).str.strip()
    order_col = "_period" if "_period" in mapped.columns else "sku_code"
    mapped = mapped.sort_values(order_col, kind="stable")
    rows = []
    for sku, grp in mapped.groupby("sku_code", sort=True):
        name = next((v for v in reversed([_clean_text(x) for x in grp["product_name"]]) if v), None) if "product_name" in grp else None
        pack = next((v for v in reversed([_pack_size_text(x) for x in grp["pack_size"]]) if v), None) if "pack_size" in grp else None
        rows.append({"sku_code": sku, "product_name": name, "pack_size": pack})
    result["skus_in_demand_file"] = len(rows)
    result["product_name_written"] = sum(1 for r in rows if r["product_name"])
    result["pack_size_written"] = sum(1 for r in rows if r["pack_size"])

    if not dry_run and rows:
        with _in_schema(engine, schema) as conn:
            updated = conn.execute(text("""
                UPDATE product_dimension p
                SET product_name = COALESCE(v.product_name, p.product_name),
                    pack_size = COALESCE(v.pack_size, p.pack_size)
                FROM unnest(CAST(:skus AS text[]), CAST(:names AS text[]), CAST(:packs AS text[]))
                     AS v(sku_code, product_name, pack_size)
                WHERE p.principal = 'unilever' AND p.grain = 'sku' AND p.sku_code = v.sku_code
                  AND (p.product_name IS DISTINCT FROM COALESCE(v.product_name, p.product_name)
                       OR p.pack_size IS DISTINCT FROM COALESCE(v.pack_size, p.pack_size))
            """), {"skus": [r["sku_code"] for r in rows], "names": [r["product_name"] for r in rows],
                   "packs": [r["pack_size"] for r in rows]})
            result["rows_updated"] = updated.rowcount or 0
    print(f"\n[Product_Dimension unilever demand metadata] {result}")
    return result


def run_category_brand_backfill(
    engine: Engine | Connection, schema: str, dry_run: bool, staging_dir: Path = STAGING_DIR,
) -> dict[str, int]:
    """Unilever SKU category and brand. For every Unilever SKU in
    Product_Dimension: a direct SOH match (most recent snapshot, DEC-21) sets
    category_path from the SOH CATEGORY DESC and the brand from the SOH
    description's first token; a SKU with no SOH row is UNCLASSIFIED with the
    brand from the demand file's product_name (brand_source
    'demand_first_token_rule'). The validated keyword CATEGORY rule
    (_fit_keyword_rule/_predict_category) is still not switched on - that is
    a modelling decision, not a loader fix (reports/PROJECT_STATE_2026-09.md §8).

    ORDER-INDEPENDENT since 2026-09-30, because slices arrive one at a time
    and a demand slice may land before the SOH snapshot that classifies its
    SKU (a slice run that staged no SOH passes an empty snapshot):
      - an SOH match overrides only a category this rule set itself
        (source NULL / 'unclassified' / 'direct_soh_match');
      - with no SOH row, only a SKU with no category at all is marked
        UNCLASSIFIED;
      - brand keeps COALESCE semantics (an existing brand stays), except that
        a brand this rule took from the demand file is replaced by the SOH
        description's once an SOH row exists - the same brand a load that saw
        both at once would give.
    Set-based UPDATE of the rows that change only."""
    if dry_run:
        print("\n[Product_Dimension category/brand backfill] DRY RUN: skipped (dimension rows are not "
              "written on a dry run, so there is nothing meaningful to classify).")
        return {"direct_soh_match": 0, "keyword_rule": 0, "unclassified": 0, "rows_updated": 0}
    soh = _load_soh_snapshot(staging_dir)
    alias = _load_brand_alias_table()
    soh_by_sku = soh.set_index("sku_code")

    with _in_schema(engine, schema) as conn:
        dim = conn.execute(text(
            "SELECT product_key, sku_code, product_name, category_path, category_path_source, brand, brand_source "
            "FROM product_dimension WHERE principal = 'unilever' AND grain = 'sku'"
        )).fetchall()

        # keyword_rule is seeded as a real counter, not printed as a literal: no
        # branch below increments it today (see this docstring).
        tally: dict[str, int] = {"direct_soh_match": 0, "keyword_rule": 0, "unclassified": 0}
        updates: list[dict] = []
        for product_key, sku, product_name, cat_path, cat_src, brand, brand_src in dim:
            if sku in soh_by_sku.index and cat_src in (None, "unclassified", "direct_soh_match"):
                soh_row = soh_by_sku.loc[sku]
                new_cat, new_src = soh_row["category_desc"], "direct_soh_match"
                desc, origin = soh_row["article_description"], "soh_first_token_rule"
            elif cat_path is None:
                new_cat, new_src = "UNCLASSIFIED", "unclassified"
                desc, origin = product_name, "demand_first_token_rule"
            else:
                tally[cat_src or "unclassified"] = tally.get(cat_src or "unclassified", 0) + 1
                continue

            desc = _nn(desc)
            brand_raw = str(desc).split()[0].upper() if desc and str(desc).split() else None
            token = alias.get(brand_raw, brand_raw) if brand_raw else None
            if origin == "soh_first_token_rule" and brand_src == "demand_first_token_rule" and token:
                new_brand, new_brand_src = token, origin
            else:
                new_brand = brand if brand is not None else token
                new_brand_src = brand_src if brand_src is not None else (origin if token else None)

            tally[new_src] = tally.get(new_src, 0) + 1
            log.info("  %s -> category_path=%r (%s), brand=%r", sku, new_cat, new_src, new_brand)
            if (new_cat, new_src, new_brand, new_brand_src) != (cat_path, cat_src, brand, brand_src):
                updates.append({"product_key": int(product_key), "category_path": new_cat, "category_path_source": new_src,
                                "brand": new_brand, "brand_source": new_brand_src})

        if updates:
            conn.execute(text("""
                UPDATE product_dimension p
                SET category_path = v.category_path, category_path_source = v.category_path_source,
                    brand = v.brand, brand_source = v.brand_source
                FROM unnest(CAST(:keys AS bigint[]), CAST(:cats AS text[]), CAST(:srcs AS text[]),
                            CAST(:brands AS text[]), CAST(:bsrcs AS text[]))
                     AS v(product_key, category_path, category_path_source, brand, brand_source)
                WHERE p.product_key = v.product_key
            """), {"keys": [u["product_key"] for u in updates], "cats": [u["category_path"] for u in updates],
                   "srcs": [u["category_path_source"] for u in updates], "brands": [u["brand"] for u in updates],
                   "bsrcs": [u["brand_source"] for u in updates]})

    tally["rows_updated"] = len(updates)
    print(f"\n[Product_Dimension category/brand backfill] {tally}  (keyword_rule is never applied: "
          f"see this function's docstring)")
    return tally


def tag_sellout_source_defect_categories(engine: Engine | Connection, schema: str, dry_run: bool) -> int:
    """Del Monte grain='category' side (item 40a, 2026-09-14): SellOut_Fact's
    transform step (relabel_sellout_source_defect_categories()) relabels the
    source-file-defect rows' category_path to 'UNCLASSIFIED' before load, so
    resolve_dimension_fk() creates/matches that Product_Dimension row on its
    own. It does not know category_path_source; this sets it. No other
    mechanism produces category_path='UNCLASSIFIED' for a Del Monte category
    row, so every match is this exact defect."""
    if dry_run:
        return 0
    with _in_schema(engine, schema) as conn:
        n = conn.execute(text(
            "UPDATE product_dimension SET category_path_source = 'source_file_defect' "
            "WHERE principal = 'delmonte' AND grain = 'category' "
            "AND category_path = 'UNCLASSIFIED' AND category_path_source IS NULL"
        )).rowcount or 0
    print(f"  delmonte source_file_defect (category, item 40a): {n}")
    return n


def resolve_delmonte_sku_dimension(
    engine: Engine | Connection, schema: str, dry_run: bool, staging_dir: Path = STAGING_DIR,
    transformed: pd.DataFrame | None = None,
) -> dict[str, int]:
    """Builds/refreshes delmonte sku-grain Product_Dimension rows from the ONE
    real Del Monte source that carries sku_code + description:
    inventory_sign_off's sku_description_raw, split by
    analytics.etl.transform.split_sku_description() (sell_out has no
    sku_code column - column_maps/sell_out.yaml:15; sales_register/
    sales_return are invoice-grain only). `transformed` is the inventory
    frame a slice already transformed; without it, staging_dir is read.

    category_path = NULL, no heuristic — migration 0016 corrected the prior
    generate_synthetic_dm.py-era rows ("fake category"); no real DM source
    ties an individual SKU to a category.

    New sku_codes are inserted (key: migration 0016's partial unique index on
    (principal, sku_code)); product_key is never renumbered. A sku_code whose
    product_name differs across snapshot months resolves by most-recent
    `_period` wins - ORDER-INDEPENDENT since 2026-09-30: a slice only renames
    a SKU when no later real inventory month for it exists in the table, so
    reloading an old month never overwrites a newer name.

    The 7 section-header artifact rows (a bare category label like
    "KIKKOMAN", no real SKU) never reach here: excluded upstream by
    INVENTORY_SIGN_OFF_FOOTER_CHECKS (analytics/etl/transform.py)."""
    if transformed is None:
        raw = pd.concat(
            [pd.read_parquet(f) for f in sorted((staging_dir / "inventory_sign_off").glob("*.parquet"))],
            ignore_index=True,
        )
        principal_df = raw[raw["_principal"] == "delmonte"] if "_principal" in raw.columns else raw
        transformed, _ = transform_fact(principal_df, "inventory", "delmonte", DEFAULT_CONFIG_DIR, amount_col="quantity_on_hand")
    real = transformed[transformed["is_demo"] != True] if "is_demo" in transformed.columns else transformed  # noqa: E712
    named = real.dropna(subset=["sku_code", "product_name"]).copy()

    if dry_run:
        print(f"\n[Product_Dimension delmonte sku-grain build] DRY RUN: "
              f"{named['sku_code'].nunique()} distinct real sku_codes with a product_name - nothing written.")
        return {"inserted": 0, "renamed": 0, "conflicts_logged": 0}

    named = named.sort_values("_period", kind="stable")
    conflicts_logged = 0
    for sku, grp in named.groupby("sku_code"):
        names = grp["product_name"].unique()
        if len(names) > 1:
            conflicts_logged += 1
            log.info("  %s: %d distinct product_name values across periods %s — using most recent (%r)",
                     sku, len(names), list(grp["_period"].unique()), names[-1])
    resolved = named.groupby("sku_code", as_index=False).last()[["sku_code", "product_name", "_period"]]
    params = {"skus": [str(s) for s in resolved["sku_code"]], "names": [str(n) for n in resolved["product_name"]],
              "periods": [str(p) for p in resolved["_period"]]}

    with _in_schema(engine, schema) as conn:
        inserted = conn.execute(text("""
            INSERT INTO product_dimension (principal, grain, sku_code, category_path, product_name, status)
            SELECT 'delmonte', 'sku', v.sku_code, NULL, v.product_name, 'ACTIVE'
            FROM unnest(CAST(:skus AS text[]), CAST(:names AS text[])) AS v(sku_code, product_name)
            ON CONFLICT (principal, sku_code) WHERE sku_code IS NOT NULL DO NOTHING
        """), params).rowcount or 0
        renamed = conn.execute(text("""
            UPDATE product_dimension p SET product_name = v.product_name
            FROM unnest(CAST(:skus AS text[]), CAST(:names AS text[]), CAST(:periods AS text[]))
                 AS v(sku_code, product_name, period)
            WHERE p.principal = 'delmonte' AND p.grain = 'sku' AND p.sku_code = v.sku_code
              AND p.product_name IS DISTINCT FROM v.product_name
              AND NOT EXISTS (SELECT 1 FROM inventory_fact f
                              WHERE f.principal = 'delmonte' AND NOT f.is_demo
                                AND f.sku_code = v.sku_code AND f._period > v.period)
        """), params).rowcount or 0

    result = {"skus_seen": len(resolved), "inserted": inserted, "renamed": renamed, "conflicts_logged": conflicts_logged}
    print(f"\n[Product_Dimension delmonte sku-grain build] {result}")
    return result


def resolve_delmonte_inventory_product_key(engine: Engine | Connection, schema: str, dry_run: bool) -> dict[str, int]:
    """Fixes the null Inventory_Fact.product_key for principal='delmonte'
    (2026-09 column-gap audit, reports/COLUMN_GAP_AUDIT_2026-09.md). A plain
    equality join on sku_code against Del Monte sku-grain Product_Dimension
    rows - migration 0016's partial unique index on (principal, sku_code)
    makes that join safe. Idempotent: only rows still NULL are touched.
    Unilever is never touched - asserted, not just relied on via the WHERE
    clause, per Yuan's instruction."""
    if dry_run:
        print("\n[Inventory_Fact.product_key delmonte backfill] DRY RUN: skipped.")
        return {"resolved": 0, "still_null": 0, "unilever_touched": 0}

    with _in_schema(engine, schema) as conn:
        before_unilever_null = conn.execute(text(
            "SELECT count(*) FROM inventory_fact WHERE principal = 'unilever' AND product_key IS NULL"
        )).scalar()
        resolved = conn.execute(text("""
            UPDATE inventory_fact f
            SET product_key = pd.product_key
            FROM product_dimension pd
            WHERE f.principal = 'delmonte'
              AND f.product_key IS NULL
              AND pd.principal = 'delmonte'
              AND pd.grain = 'sku'
              AND pd.sku_code = f.sku_code
        """)).rowcount or 0
        still_null = conn.execute(text(
            "SELECT count(*) FROM inventory_fact WHERE principal = 'delmonte' AND product_key IS NULL"
        )).scalar()
        after_unilever_null = conn.execute(text(
            "SELECT count(*) FROM inventory_fact WHERE principal = 'unilever' AND product_key IS NULL"
        )).scalar()

    unilever_touched = after_unilever_null - before_unilever_null
    print(f"\n[Inventory_Fact.product_key delmonte backfill] resolved {resolved}, still null {still_null} "
          f"(unmatched sku_codes, flagged not fabricated), unilever rows changed {unilever_touched}")
    if unilever_touched != 0:
        raise RuntimeError(
            f"resolve_delmonte_inventory_product_key touched {unilever_touched} Unilever "
            f"inventory_fact rows — expected 0. Aborting before this reaches public."
        )
    return {"resolved": resolved, "still_null": still_null, "unilever_touched": unilever_touched}


def resolve_unilever_inventory_product_key(
    engine: Engine | Connection, schema: str, dry_run: bool, staging_dir: Path = STAGING_DIR,
) -> dict[str, int]:
    """Runs after the ssis_soh/unilever inventory load. transform_ssis_soh()'s
    output has no product_key column, so every load leaves it unresolved for
    Unilever until this join runs (2026-09-17 column-gap audit Part B).

    First UPSERTS the SOH-only products (Article Nos with no demand history,
    DEC-22) from the real SOH source itself (Article No -> sku_code, Article
    Description -> product_name, CATEGORY DESC -> category_path, PACK SIZE ->
    pack_size), most recent snapshot per SKU. ON CONFLICT (principal, grain,
    sku_code) - migration 0014's Unilever-only partial index - DO NOTHING:
    an existing row (every demand SKU, and all 291 SOH-only rows on public)
    is never overwritten, its product_key never renumbered; on a fresh schema
    the SOH-only rows are created with whatever keys the sequence assigns,
    which is fine because everything downstream joins on sku_code. X1
    (2026-09-22): SOH "PACK SIZE" on new rows only. `staging_dir` must hold
    every SOH snapshot (a slice run stages them all under _soh_all), not just
    the slice's month, so "most recent" means the same thing on every run."""
    with _in_schema(engine, schema) as conn:
        before_delmonte_null = conn.execute(text(
            "SELECT count(*) FROM inventory_fact WHERE principal = 'delmonte' AND product_key IS NULL"
        )).scalar()
        before_dim_count = conn.execute(text(
            "SELECT count(*) FROM product_dimension WHERE principal = 'unilever' AND grain = 'sku'"
        )).scalar()
        if dry_run:
            print("\n[Inventory_Fact.product_key unilever backfill] DRY RUN: skipped.")
            return {"resolved": 0, "still_null": 0, "new_dimension_rows": 0, "delmonte_touched": 0}

        # No is_demo column at this raw staging stage — transform_ssis_soh.py
        # sets it as a constant False for every row later; there is no
        # synthetic ssis_soh variant, so every raw row here is real.
        files = sorted((staging_dir / "ssis_soh").glob("*.parquet"))
        if files:
            raw = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
            named = raw.dropna(subset=["sku_code"]).sort_values("_period", kind="stable") if "_period" in raw.columns else raw.dropna(subset=["sku_code"])
            latest = named.groupby("sku_code", as_index=False).last()
            conn.execute(text("""
                INSERT INTO product_dimension (principal, grain, sku_code, category_path, product_name, pack_size, status)
                SELECT 'unilever', 'sku', v.sku_code, v.category_path, v.product_name, v.pack_size, 'ACTIVE'
                FROM unnest(CAST(:sku_code AS text[]), CAST(:category_path AS text[]), CAST(:product_name AS text[]),
                            CAST(:pack_size AS text[])) AS v(sku_code, category_path, product_name, pack_size)
                ON CONFLICT (principal, grain, sku_code) WHERE principal = 'unilever' AND grain = 'sku'
                DO NOTHING
            """), {
                "sku_code": [str(s).strip() for s in latest["sku_code"]],
                "category_path": [_nn(v) for v in latest["category_desc"]],
                "product_name": [_nn(v) for v in latest["article_description"]],
                "pack_size": [_pack_size_text(v) for v in latest["pack_size"]],
            })
        after_dim_count = conn.execute(text(
            "SELECT count(*) FROM product_dimension WHERE principal = 'unilever' AND grain = 'sku'"
        )).scalar()
        resolved = conn.execute(text("""
            UPDATE inventory_fact f
            SET product_key = pd.product_key
            FROM product_dimension pd
            WHERE f.principal = 'unilever'
              AND f.product_key IS NULL
              AND pd.principal = 'unilever'
              AND pd.grain = 'sku'
              AND pd.sku_code = f.sku_code
        """)).rowcount or 0
        still_null = conn.execute(text(
            "SELECT count(*) FROM inventory_fact WHERE principal = 'unilever' AND product_key IS NULL"
        )).scalar()
        after_delmonte_null = conn.execute(text(
            "SELECT count(*) FROM inventory_fact WHERE principal = 'delmonte' AND product_key IS NULL"
        )).scalar()

    new_dimension_rows = after_dim_count - before_dim_count
    delmonte_touched = after_delmonte_null - before_delmonte_null
    print(f"\n[Inventory_Fact.product_key unilever backfill] new dimension rows {new_dimension_rows}, "
          f"resolved {resolved}, still null {still_null}, delmonte rows changed {delmonte_touched}")
    if delmonte_touched != 0:
        raise RuntimeError(
            f"resolve_unilever_inventory_product_key touched {delmonte_touched} Del Monte "
            f"inventory_fact rows — expected 0. Aborting before this reaches public."
        )
    return {"resolved": resolved, "still_null": still_null, "new_dimension_rows": new_dimension_rows,
            "delmonte_touched": delmonte_touched}


# --- Fixes 5 and 6 (dm_fixes batches 5-6, 2026-09-28; loader rules since 2026-09-30) ---------------------------

DM_BRAND_ALIAS = REPO_ROOT / "config" / "alias_tables" / "delmonte_brand.csv"
_DM_BRAND_SKIP = re.compile(r"^(?:[0-9A-Z]{3,4}\d{5}|\d+|-)$")
DM_PRICE_LIST_SHEET = "Sheet1"


def dm_brand(name: str | None, alias: dict[str, str]) -> str | None:
    """First word of the product name, uppercased; an embedded SKU code, bare
    number or '-' ahead of the name is skipped. Through
    config/alias_tables/delmonte_brand.csv: a blank canonical is a
    descriptive word (brand NULL). Same rule as dm_fixes batch 6."""
    for word in (name or "").upper().split():
        if not _DM_BRAND_SKIP.match(word):
            return alias.get(word, word) or None
    return None


def load_dm_price_list(staging_dir: Path) -> dict[str, str | None]:
    """sku_code -> pack size text from the price list: the 'Sheet1' of the
    2025 Del Monte inventory workbooks (PRODUCT/ SKU CODE -> CASE PACK; no
    separate price-list file exists in data/raw). Every copy must agree on
    every code, as batch 5 checked - a copy that differs stops the load."""
    copies = [pd.read_parquet(f) for f in sorted((staging_dir / "inventory_sign_off").glob(f"2025_*__{DM_PRICE_LIST_SHEET}.parquet"))]
    if not copies:
        raise RuntimeError(f"no 2025 inventory '{DM_PRICE_LIST_SHEET}' price-list sheet staged under {staging_dir.name}")
    lists = [dict(zip(c["PRODUCT/ SKU CODE"].astype(str).str.strip(), c["CASE PACK"])) for c in copies]
    if any(x != lists[0] for x in lists):
        raise RuntimeError(f"the {len(copies)} staged price-list copies disagree on code -> CASE PACK")
    return {k: _pack_size_text(v) for k, v in lists[0].items()}


def apply_dm_pack_size_rule(engine: Engine | Connection, schema: str, dry_run: bool, price: dict[str, str | None]) -> int:
    """Fix 5: Del Monte pack_size from the price list CASE PACK, on EXACT
    sku_code = PRODUCT/ SKU CODE matches only (no 5-digit-core matching).
    Fill-if-NULL: a pack_size already set (by a person, or by an earlier
    run) is never overwritten."""
    pairs = [(k, v) for k, v in price.items() if v is not None]
    if dry_run or not pairs:
        return 0
    with _in_schema(engine, schema) as conn:
        n = conn.execute(text("""
            UPDATE product_dimension p SET pack_size = v.pack_size
            FROM unnest(CAST(:codes AS text[]), CAST(:packs AS text[])) AS v(sku_code, pack_size)
            WHERE p.principal = 'delmonte' AND p.grain = 'sku' AND p.sku_code = v.sku_code AND p.pack_size IS NULL
        """), {"codes": [k for k, _ in pairs], "packs": [v for _, v in pairs]}).rowcount or 0
    print(f"  delmonte pack_size from the price list (fix 5, fill-if-NULL): {n}")
    return n


def apply_dm_brand_rule(engine: Engine | Connection, schema: str, dry_run: bool) -> int:
    """Fix 6: Del Monte brand by the product name's first-token rule, for SKUs
    with real inventory whose brand AND brand_source are both unset
    (fill-if-NULL). A descriptive first word maps to NULL and stays NULL."""
    if dry_run:
        return 0
    import csv as _csv
    with open(DM_BRAND_ALIAS, encoding="utf-8", newline="") as fh:
        alias = {r["raw"]: r["canonical"] for r in _csv.DictReader(fh)}
    with _in_schema(engine, schema) as conn:
        rows = conn.execute(text("""
            SELECT p.product_key, p.product_name FROM product_dimension p
            WHERE p.principal = 'delmonte' AND p.grain = 'sku' AND p.brand IS NULL AND p.brand_source IS NULL
              AND EXISTS (SELECT 1 FROM inventory_fact f WHERE f.product_key = p.product_key AND NOT f.is_demo)
        """)).fetchall()
        target = [(int(k), dm_brand(name, alias)) for k, name in rows]
        target = [(k, b) for k, b in target if b]
        n = 0
        if target:
            n = conn.execute(text("""
                UPDATE product_dimension p SET brand = v.brand, brand_source = 'dm_name_first_token_rule'
                FROM unnest(CAST(:keys AS bigint[]), CAST(:brands AS text[])) AS v(product_key, brand)
                WHERE p.product_key = v.product_key
            """), {"keys": [k for k, _ in target], "brands": [b for _, b in target]}).rowcount or 0
    print(f"  delmonte brand by first-token rule (fix 6, fill-if-NULL): {n} of {len(rows)} unbranded")
    return n


# ---------------------------------------------------------------------------
# Scratch schema creation
# ---------------------------------------------------------------------------

def _strip_sql_file(sql: str) -> str:
    """Removes full-comment lines (a line whose first non-whitespace chars
    are `--`) and bare `BEGIN;`/`COMMIT;` lines, line by line, returning
    the remaining real SQL joined back together.

    Line-based, not chunk-based, on purpose — an earlier version split the
    whole file on `;\\n` first and then discarded any CHUNK that happened
    to *start* with `--`. That silently dropped real statements whenever a
    comment line preceded a statement with no `;` between them (the normal
    case: every migration file has comment lines directly above the
    statement they explain, no blank/`;`-terminated line separating them).
    Caught 2026-09-14 applying migration 0011 for real: 0004_add_valuation.sql
    reduced to zero statements this way (its ALTER TABLE was glued to its
    leading two comment lines in one chunk, and the whole chunk was
    discarded because it *started* with `--`) — not previously visible
    because a static syntax check only counts chunks, it doesn't verify
    their CONTENT survived filtering. Fixed by stripping comment lines
    before any statement-boundary splitting happens at all, so a comment
    can never be glued to the statement it precedes."""
    kept = []
    for line in sql.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        if stripped.upper() in ("BEGIN;", "COMMIT;"):
            continue
        kept.append(line)
    return "\n".join(kept)


# ---------------------------------------------------------------------------
# Migration ledger (0019_schema_migrations.sql)
# ---------------------------------------------------------------------------

LEDGER_TABLE = "schema_migrations"

# --rehearse defaults (reports/SCHEMA_REORG_PLAN.md section 2, R4). Mandatory
# - no default at all - when the target is public; see main()'s validation.
DEFAULT_REHEARSE_LOCK_TIMEOUT_MS = 5000
DEFAULT_REHEARSE_STATEMENT_TIMEOUT_MS = 30000

# The ONE number that legitimately maps to two files. Both are applied, neither
# was applied twice, and renaming either would orphan its ledger row - so they
# are grandfathered rather than renumbered. Any NEW collision is a mistake and
# must fail loudly, which is what _assert_no_new_number_collision() is for.
GRANDFATHERED_DUPLICATE_NUMBERS = {"0002"}


def _migration_number(name: str) -> str:
    return name.split("_", 1)[0]


def _assert_no_new_number_collision(files: list[Path]) -> None:
    """Refuse to run if a newly added migration reuses an existing number.

    Application order is `sorted()` on the FILENAME, so two files sharing a
    number are ordered by whatever follows it - luck, not intent. That is
    tolerable for the one historical 0002 pair (they touch different tables)
    and unacceptable for anything new."""
    by_number: dict[str, list[str]] = {}
    for f in files:
        by_number.setdefault(_migration_number(f.name), []).append(f.name)
    for number, names in sorted(by_number.items()):
        if len(names) > 1 and number not in GRANDFATHERED_DUPLICATE_NUMBERS:
            raise RuntimeError(
                f"Migration number {number!r} is used by {len(names)} files: "
                f"{', '.join(sorted(names))}. Application order between them would "
                f"be decided by filename sort, not intent. Renumber the new file."
            )


def _read_ledger(engine: Engine, schema: str) -> dict[str, str | None] | None:
    """{filename: checksum} for everything already applied, or None when the
    ledger table does not exist yet (a schema predating 0019, including a
    brand-new scratch schema on its first pass)."""
    with engine.connect() as conn:
        conn.execute(text("SET LOCAL search_path TO :schema, public").bindparams(schema=schema))
        exists = conn.execute(
            text("SELECT to_regclass(:qualified)").bindparams(qualified=f'"{schema}".{LEDGER_TABLE}')
        ).scalar()
        if exists is None:
            return None
        rows = conn.execute(text(f"SELECT filename, checksum FROM {LEDGER_TABLE}")).all()
    return {r[0]: r[1] for r in rows}


def migration_checksums(path: Path) -> tuple[str, str]:
    """(LF form, CRLF form) sha256 of a migration file's bytes. The ledger
    accepts either: migration 0019 seeded six rows (0001, both 0002 files,
    0003, 0012, 0013) from a CRLF (core.autocrlf=true) checkout, so those six
    hold CRLF hashes while the other 25 hold LF hashes (verified against
    public.schema_migrations 2026-09-30). .gitattributes now pins *.sql to LF,
    so the working copy is LF everywhere; accepting both forms keeps all 31
    stored rows valid without rewriting a single one. An edit that changes
    anything besides line endings still fails both comparisons."""
    lf = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(lf).hexdigest(), hashlib.sha256(lf.replace(b"\n", b"\r\n")).hexdigest()


def pending_migrations(engine: Engine, schema: str) -> list[str]:
    """Migration files the schema's ledger has not recorded (every file when
    there is no ledger yet). Raises on a checksum that matches neither form."""
    migrations = sorted(MIGRATIONS_DIR.glob("0*.sql"))
    _assert_no_new_number_collision(migrations)
    applied = _read_ledger(engine, schema)
    pending = []
    for f in migrations:
        if applied is None or f.name not in applied:
            pending.append(f.name)
            continue
        recorded = applied[f.name]
        if recorded is not None and recorded not in migration_checksums(f):
            raise RuntimeError(
                f"{f.name} was applied with checksum {recorded} but the file on disk "
                f"now hashes to {migration_checksums(f)[0]} (LF form). A migration was edited after it was "
                f"applied. Write a new migration instead of editing an applied one."
            )
    return pending


_CREATE_SCHEMA_RE = re.compile(r"CREATE\s+SCHEMA\s+(?:IF\s+NOT\s+EXISTS\s+)?([\w\".]+)", re.IGNORECASE)
_CREATE_TABLE_RE = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([\w\".]+)", re.IGNORECASE)

# Objects a migration creates under a name that is NOT scoped under the schema
# being built: a schema of its own, or a relation/function qualified with some
# other schema. `CREATE OR REPLACE ...` is deliberately not matched - replacing
# an object that already exists is the point of it, not a collision.
_CREATE_QUALIFIED_RE = re.compile(
    r"CREATE\s+(?:TABLE|VIEW|MATERIALIZED\s+VIEW|SEQUENCE|TYPE|FUNCTION)\s+"
    r"(?:IF\s+NOT\s+EXISTS\s+)?\"?([\w]+)\"?\.\"?([\w]+)\"?",
    re.IGNORECASE,
)


def _database_wide_objects(migrations: list[Path], target_schema: str) -> list[tuple[Path, str, str]]:
    """[(migration file, what kind of thing, its name)] for every object a
    migration creates outside the schema being built. Comments are stripped
    first, so a name that only appears in a rollback note or an explanation is
    not mistaken for a statement."""
    found: list[tuple[Path, str, str]] = []
    for f in migrations:
        sql = _strip_sql_file(f.read_text(encoding="utf-8"))
        for name in _CREATE_SCHEMA_RE.findall(sql):
            name = name.replace('"', "")
            if name != target_schema:
                found.append((f, "schema", name))
        for schema, obj in _CREATE_QUALIFIED_RE.findall(sql):
            if schema != target_schema:
                found.append((f, "relation", f"{schema}.{obj}"))
    return found


def _assert_fresh_build_no_database_wide_collision(
    engine: Engine, migrations: list[Path], target_schema: str
) -> None:
    """A brand-new scratch schema (no ledger yet) replays every migration. Most
    of them create their objects unqualified, under the search_path, so they
    land inside the scratch schema and a fresh build is safe. Some do not:
    0041 creates schema `mart` and its tables by fixed name, 0046 adds
    `mart.planning_mart`, 0048 creates schema `app` and six views named
    `public.<table>`. Those names are database-wide, not scoped under the
    schema being built, so once anything has created them (live `public`'s own
    cutover, or an earlier scratch build that was never dropped) every
    subsequent fresh replay collides with it.

    This used to test one hard-coded name, `mart.sales_mart`, and so would have
    said nothing about 0048 or about the `analytics` migration the plan has
    next (reports/SCHEMA_REORG_PLAN.md section 5 group 2). It now reads what
    each migration actually creates and names whichever file is the problem,
    which is also the only version that stays correct as migrations are added.
    Without it the failure surfaces as a bare 'relation "..." already exists'
    with no indication which migration or why."""
    offenders = _database_wide_objects(migrations, target_schema)
    if not offenders:
        return
    with engine.connect() as conn:
        for f, kind, name in offenders:
            query = "SELECT to_regnamespace(:n)" if kind == "schema" else "SELECT to_regclass(:n)"
            if conn.execute(text(query).bindparams(n=name)).scalar() is None:
                continue
            raise RuntimeError(
                f"Fresh build would fail at {f.name}: {kind} '{name}' already exists. "
                f"{f.name} creates it by a fixed, database-wide name rather than one scoped "
                f"under the scratch schema being built ('{target_schema}'), so a fresh replay "
                f"always collides with whatever created it first. This script does not support "
                f"replaying that migration into a brand-new scratch schema: rehearse it with its "
                f"own script (scripts/rehearse_marts.py, scripts/rehearse_planning_mart.py) or "
                f"with --rehearse against a schema whose ledger already has it applied."
            )


# HARD GUARD (2026-10-24, docs/ROLLOVER_DESIGN.md e). A migration that names `app.`, `public.` or `mart.` explicitly
# does not obey the scratch schema's search_path: applied "to a scratch schema" it runs against the LIVE table or
# schema (0059 and 0060 altered live app.users; 0041 onward create live mart objects). A pre-flight check protects only
# when someone remembers to look, so the scratch build REFUSES: every migration it would apply is read, and any
# reference to those schemas outside the scratch schema stops the build before a single statement runs.
_LIVE_SCHEMA_REF_RE = re.compile(r'(?<![\w."])"?\b(public|app|mart)\b"?\s*\.\s*"?([A-Za-z_]\w*)', re.IGNORECASE)


def live_schema_references(files: list[Path]) -> list[tuple[str, str]]:
    """[(migration file name, 'schema.object')] for every explicit reference to public, app or mart in the SQL a
    migration actually runs (comment lines are stripped first, as the runner does)."""
    found: list[tuple[str, str]] = []
    for f in files:
        sql = _strip_sql_file(f.read_text(encoding="utf-8"))
        for schema, obj in sorted({(a.lower(), b) for a, b in _LIVE_SCHEMA_REF_RE.findall(sql)}):
            found.append((f.name, f"{schema}.{obj}"))
    return found


def assert_scratch_migrations_safe(files: list[Path], schema: str) -> None:
    """Raises SystemExit, naming the file and the reference, when any migration about to be applied to scratch schema
    `schema` names app., public. or mart. explicitly. Nothing has been applied when this runs."""
    offenders = live_schema_references(files)
    if offenders:
        first = {}
        for name, ref in offenders:
            first.setdefault(name, []).append(ref)
        lines = [f"  {name}: {', '.join(refs[:4])}{' ...' if len(refs) > 4 else ''}" for name, refs in first.items()]
        raise SystemExit(
            f"REFUSED: building or migrating scratch schema '{schema}' would apply migration(s) that name app., public. or "
            "mart. explicitly, and those statements run against the LIVE database, not the scratch schema:\n"
            + "\n".join(lines)
            + "\nApply them to public first with --schema-only on public (after a backup), then build the scratch copy, "
              "whose ledger will then have them. Nothing was applied.")


def ensure_scratch_schema(engine: Engine, schema: str, dry_run: bool, allow_public: bool = False) -> None:
    """Brings `schema` up to date through the ledger. A brand-new schema (no
    ledger) runs schema.sql and then every migration; a ledgered schema never
    re-runs schema.sql (its CREATE OR REPLACE VIEW statements are not a
    no-op on a live schema) and applies only the migrations its ledger lacks.
    Each migration and its ledger row commit in one transaction."""
    _require_scratch_schema(schema, allow_public=allow_public)
    print(f"\n[schema] ensuring '{schema}' is migrated" + (" (dry-run: SELECT-only check)" if dry_run else ""))
    if dry_run:
        print(f"  pending: {pending_migrations(engine, schema) or 'none'}")
        return

    migrations = sorted(MIGRATIONS_DIR.glob("0*.sql"))
    _assert_no_new_number_collision(migrations)
    # Read ONCE, before the loop. On a fresh schema this is None (0019 has not
    # run yet) so every file applies and 0019's backfill seeds the other 19.
    applied = _read_ledger(engine, schema)
    if not allow_public:   # a scratch build: refuse before anything runs (even the empty schema) if a pending migration reaches the live schemas
        assert_scratch_migrations_safe([f for f in migrations if applied is None or f.name not in applied], schema)
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
    if applied is None:
        _assert_fresh_build_no_database_wide_collision(engine, migrations, schema)
    files = ([SCHEMA_SQL] if applied is None else []) + migrations
    if applied is not None:
        print(f"  skipped {SCHEMA_SQL.relative_to(REPO_ROOT)} — '{schema}' already has a {LEDGER_TABLE} ledger")
    for f in files:
        is_migration = f != SCHEMA_SQL
        checksum = migration_checksums(f)[0] if is_migration else None
        if is_migration and applied is not None and f.name in applied:
            recorded = applied[f.name]
            if recorded is not None and recorded not in migration_checksums(f):
                raise RuntimeError(
                    f"{f.name} was applied with checksum {recorded} but the file on disk "
                    f"now hashes to {checksum} (LF form). A migration was edited after it was applied. "
                    f"Write a new migration instead of editing an applied one."
                )
            print(f"  skipped {f.relative_to(REPO_ROOT)} — already in {LEDGER_TABLE}")
            continue
        cleaned_sql = _strip_sql_file(f.read_text(encoding="utf-8"))
        if not cleaned_sql.strip():
            print(f"  SKIPPED {f.relative_to(REPO_ROOT)} — nothing left after stripping comments/BEGIN/COMMIT")
            continue
        with engine.begin() as conn:
            # SET LOCAL is transaction-scoped only - never leaks to another
            # session or a later transaction on this same connection.
            conn.execute(text("SET LOCAL search_path TO :schema, public").bindparams(schema=schema))
            # exec_driver_sql passes the whole multi-statement file straight to
            # psycopg2 (simple query protocol). Every literal `%` is doubled -
            # psycopg2 reads `%` as a placeholder whenever a parameters object
            # is present at all (caught 2026-09-14, migration 0011's comments).
            conn.exec_driver_sql(cleaned_sql.replace("%", "%%"))
            # Recorded in the SAME transaction as the apply, so a failed
            # migration can never leave a row claiming it succeeded. Silently
            # skipped while the ledger table does not exist yet (files before
            # 0019 on a fresh schema) - 0019's own backfill covers those.
            if is_migration and conn.execute(
                text("SELECT to_regclass(:q)").bindparams(q=f'"{schema}".{LEDGER_TABLE}')
            ).scalar() is not None:
                conn.execute(
                    text(
                        f"INSERT INTO {LEDGER_TABLE} "
                        "(filename, checksum, applied_at, applied_by, target_schema) "
                        "VALUES (:filename, :checksum, now(), :applied_by, :schema) "
                        "ON CONFLICT (filename) DO NOTHING"
                    ),
                    {"filename": f.name, "checksum": checksum,
                     "applied_by": getpass.getuser(), "schema": schema},
                )
        print(f"  applied {f.relative_to(REPO_ROOT)}")




def _verify_rehearsal(conn: Connection, pending: list[Path]) -> int:
    """Minimal, generic check that every CREATE SCHEMA / CREATE TABLE target
    named in the pending migrations now resolves inside this (uncommitted)
    transaction - catches "the SQL ran without error but didn't do what the
    file says" (e.g. a target schema name that was silently wrong). This is
    not a substitute for a migration's own dedicated rehearsal script (for
    example scripts/rehearse_marts.py, scripts/rehearse_planning_mart.py)
    when one exists for it - those compare real output, this only confirms
    the objects exist. Raises on the first object that does not resolve;
    returns the count checked."""
    checked = 0
    for f in pending:
        sql = _strip_sql_file(f.read_text(encoding="utf-8"))
        for name in _CREATE_SCHEMA_RE.findall(sql):
            name = name.replace('"', "")
            if conn.execute(text("SELECT to_regnamespace(:n)").bindparams(n=name)).scalar() is None:
                raise RuntimeError(f"{f.name}: schema {name!r} does not resolve after apply - rehearsal failed")
            checked += 1
        for name in _CREATE_TABLE_RE.findall(sql):
            name = name.replace('"', "")
            if conn.execute(text("SELECT to_regclass(:n)").bindparams(n=name)).scalar() is None:
                raise RuntimeError(f"{f.name}: table {name!r} does not resolve after apply - rehearsal failed")
            checked += 1
    return checked


def enable_server_notices() -> None:
    """Let a migration's own RAISE NOTICE reach the operator.

    SQLAlchemy's psycopg2 dialect already drains psycopg2's notice list after
    every statement and re-emits each one through the logger
    `sqlalchemy.dialects.postgresql` at INFO (sqlalchemy/dialects/postgresql/
    psycopg2.py:568-585) - which also means no caller can read the list
    afterwards, because it has already been emptied. What hides the messages
    is sqlalchemy/log.py pinning the `sqlalchemy` logger to WARN, so those
    INFO records are dropped. Raising this one logger to INFO makes them
    visible. Without it a migration that checks itself and reports with NOTICE
    (0048 does) looks exactly like a migration that checked nothing.
    """
    logging.getLogger("sqlalchemy.dialects.postgresql").setLevel(logging.INFO)


def _timeout_ms(setting: str) -> int:
    """A Postgres timeout GUC as milliseconds. Postgres normalises the unit it
    reports ('5s' asked for comes back as '5s', '5000ms' comes back as '5s'),
    so the strings cannot be compared directly - only the values can."""
    setting = setting.strip()
    for suffix, mult in (("ms", 1), ("min", 60_000), ("h", 3_600_000), ("d", 86_400_000), ("s", 1000)):
        if setting.endswith(suffix):
            return int(float(setting[: -len(suffix)]) * mult)
    return int(float(setting))


def _print_effective_timeouts(conn, lock_timeout_ms: int, statement_timeout_ms: int, when: str) -> None:
    """Print what the command line asked for beside what the transaction is
    actually running under, and name any override. A migration file's own
    SET LOCAL wins over this function's caller, and that has to be visible
    rather than inferred (asked for 2026-10-08, reviewing 0048)."""
    print(f"  [rehearse] timeouts {when}:")
    for name, requested in (("lock_timeout", lock_timeout_ms),
                            ("statement_timeout", statement_timeout_ms)):
        effective = conn.execute(text(f"SHOW {name}")).scalar()
        note = "" if _timeout_ms(effective) == requested else "   <-- OVERRIDDEN by SQL in this transaction"
        print(f"    {name:18} requested={requested}ms  "
              f"effective={effective} ({_timeout_ms(effective)}ms){note}")


def _run_check_files(conn, check_files: list[Path]) -> int:
    """Run each check file as one statement inside the rehearsal's own
    transaction and print what it returns. Returns the number of failures: a
    statement that raised, or a row whose `ok` column is not true.

    Each file runs inside its own SAVEPOINT. Postgres aborts the entire
    transaction on any error, so without one the first failing check left
    every later check reporting only "current transaction is aborted" - the
    run would hide every result after the first problem. A savepoint cannot
    commit anything; the unconditional ROLLBACK above still ends the
    transaction."""
    failures = 0
    for path in check_files:
        sql = _strip_sql_file(Path(path).read_text(encoding="utf-8"))
        print(f"\n  [check] {path}")
        savepoint = conn.begin_nested()
        try:
            result = conn.exec_driver_sql(sql.replace("%", "%%"))
        except Exception as exc:  # noqa: BLE001 - a failed check is a result, not a crash
            failures += 1
            savepoint.rollback()
            print(f"    FAILED to run: {type(exc).__name__}: {str(exc).splitlines()[0]}")
            continue
        if not result.returns_rows:
            savepoint.close()
            print("    ok (statement returned no rows)")
            continue
        rows = result.mappings().all()
        savepoint.close()
        if not rows:
            print("    ok (0 rows)")
            continue
        has_ok = "ok" in rows[0]
        for r in rows:
            bad = has_ok and r["ok"] is not True
            failures += 1 if bad else 0
            mark = "FAIL" if bad else ("PASS" if has_ok else "    ")
            print(f"    {mark} " + "  ".join(f"{k}={r[k]}" for k in r if k != "ok"))
    return failures


def rehearse_migrations(
    engine: Engine,
    schema: str,
    lock_timeout_ms: int,
    statement_timeout_ms: int,
    allow_public: bool = False,
    check_files: list[Path] | None = None,
) -> int:
    """R4 (reports/SCHEMA_REORG_PLAN.md section 2): apply this schema's
    pending migrations inside ONE transaction that is ALWAYS rolled back -
    never a commit, never a schema_migrations row. Exists so a
    reorganisation migration can be tried against live public's actual
    catalog before it is trusted to run for real; the plan's recommendation
    is R2 for the stack and R4 for the reorg migrations themselves, both
    catalog-only and millisecond-scale. lock_timeout/statement_timeout
    bound how long the transaction can hold locks on live tables: a lock it
    can't get aborts the rehearsal instead of queuing every other session
    on those tables behind it (plan's R4 risk row).

    The two timeouts are REQUESTED values, not guaranteed ones: a migration
    file may issue its own `SET LOCAL lock_timeout` (0048 does, so that
    applying it by hand in psql is bounded too), and that silently replaces
    what was asked for here. Both are therefore read back from the database -
    once after they are set, once after every file has been applied - and a
    difference is printed as an override naming the effective value, rather
    than leaving the command line looking authoritative when it is not.

    check_files: SQL files run inside this same transaction after the last
    migration and before the ROLLBACK, each exactly ONE statement (no
    splitting is attempted, so a `DO $$ ... $$` block is fine). A statement
    that returns rows has them printed; one that returns none prints `ok`. A
    returned column named `ok` that is false in any row fails the rehearsal.
    This is the only way a reorganisation migration's verification queries
    can see the moved objects at all: nothing outside this transaction can,
    because it never commits."""
    _require_scratch_schema(schema, allow_public=allow_public)
    migrations = sorted(MIGRATIONS_DIR.glob("0*.sql"))
    _assert_no_new_number_collision(migrations)
    pending_names = set(pending_migrations(engine, schema))
    pending = [f for f in migrations if f.name in pending_names]
    if not pending:
        print(f"\n[rehearse] '{schema}': nothing pending. Nothing to rehearse.")
        return 0

    banner = "!" * 70
    print(f"\n{banner}")
    print(f"!!! REHEARSE (never commits): {len(pending)} migration(s) against "
          f"'{schema}'{'  <-- LIVE' if schema == 'public' else ''}")
    print(f"!!! lock_timeout={lock_timeout_ms}ms  statement_timeout={statement_timeout_ms}ms")
    for f in pending:
        print(f"!!!   {f.relative_to(REPO_ROOT)}")
    print(banner)

    conn = engine.connect()
    try:
        # Safeguard: an autocommit connection has no transaction for ROLLBACK
        # to undo - every statement below must share one transaction.
        if conn.get_isolation_level() == "AUTOCOMMIT":
            raise RuntimeError(
                "rehearse refuses an autocommit connection: every statement must share one "
                "transaction so ROLLBACK can undo all of it as a unit."
            )
        trans = conn.begin()
        try:
            conn.execute(text("SET LOCAL search_path TO :schema, public").bindparams(schema=schema))
            conn.execute(text(f"SET LOCAL lock_timeout = '{int(lock_timeout_ms)}ms'"))
            conn.execute(text(f"SET LOCAL statement_timeout = '{int(statement_timeout_ms)}ms'"))
            _print_effective_timeouts(conn, lock_timeout_ms, statement_timeout_ms, "after SET LOCAL")
            for f in pending:
                cleaned_sql = _strip_sql_file(f.read_text(encoding="utf-8"))
                if not cleaned_sql.strip():
                    print(f"  SKIPPED {f.relative_to(REPO_ROOT)} - nothing left after stripping comments/BEGIN/COMMIT")
                    continue
                conn.exec_driver_sql(cleaned_sql.replace("%", "%%"))
                print(f"  applied (uncommitted) {f.relative_to(REPO_ROOT)}")
            _print_effective_timeouts(conn, lock_timeout_ms, statement_timeout_ms,
                                      "after applying every file")
            checked = _verify_rehearsal(conn, pending)
            print(f"  [rehearse] verified {checked} object(s) resolve in-transaction")
            if check_files:
                failures = _run_check_files(conn, check_files)
                if failures:
                    raise RuntimeError(
                        f"{failures} check(s) failed in-transaction - see the rows above. "
                        f"Rolling back (as every rehearsal does); the migration is NOT ready to apply."
                    )
        finally:
            # Unconditional: runs whether the try block succeeded, raised, or
            # was interrupted. No code path below this function can commit.
            trans.rollback()
            print(f"{banner}")
            print(f"!!! ROLLBACK complete. '{schema}' is UNCHANGED. No {LEDGER_TABLE} row written.")
            print(f"{banner}")
    finally:
        conn.close()
    return 0


def _drop_scratch_schema(engine: Engine, schema: str) -> None:
    _require_scratch_schema(schema)
    print(f"\n!!! ROLLING BACK: DROP SCHEMA \"{schema}\" CASCADE !!!")
    with engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    print(f"    '{schema}' dropped. No partial load left behind.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

# The 6 tables the canonical loader actually populates - see FACT_PLAN plus
# the separate ssis_soh path. Everything else in public (product_dimension,
# customer_dimension, salesman_dimension, supplier_dimension, date_dimension,
# the ABC/forecast/LP output tables, users, audit_log)
# is either updated in place (product_dimension, date_dimension) or never
# touched at all by --target-public - see main()'s cutover block.
CANONICAL_FACT_TABLES = [
    "sales_fact", "purchase_fact", "salesreturn_fact",
    "sellout_fact", "inventory_fact", "unilever_sku_demand_fact",
]


def _preflight_dimension_identity_check(engine: Engine) -> None:
    """Abort BEFORE any real write (even the fact-table DELETE) if
    resolving one already-known SKU against public's existing
    Product_Dimension doesn't return its existing product_key.

    Root cause this guards against (2026-09-15 cutover incident,
    reports/PROJECT_STATE_2026-09.md §10): every identity sequence on
    live was desynced - stuck at last_value=1 regardless of how much
    real data already existed (populated by ad-hoc scripts that
    explicitly set PK values, which never advances a GENERATED ALWAYS AS
    IDENTITY column's sequence - a standard, well-documented Postgres
    gotcha). resolve_dimension_fk()'s INSERT ... ON CONFLICT DO NOTHING
    then generated a fresh, non-colliding product_key for every row via
    nextval() - since that succeeds, ON CONFLICT never gets a chance to
    reject it as a natural-key duplicate, and a brand new row is
    inserted beside the real one. 1,807 Unilever SKU rows were silently
    duplicated this way before a genuine batch-level collision on a
    Del Monte category insert finally raised an error and stopped it.
    NOT a pandas/type-coercion bug - tested and disproven directly (both
    sides of the merge are `str`, byte-identical) before this was found.

    This check performs a REAL insert attempt for one known SKU, inside
    a transaction that is ALWAYS rolled back (never commits, regardless
    of outcome) - so it proves the actual behavior public would exhibit,
    not a simulation, without itself writing anything."""
    with engine.connect() as conn:
        # category_path IS NULL specifically - found 2026-09-15 while
        # testing this guard itself: an unfiltered LIMIT 1 can pick a SKU
        # whose product_dimension row already has a real category_path
        # (leftover from an older, pre-this-session ad-hoc backfill on
        # live, e.g. sku_code=20094079 -> 'ORAL CARE') - testing THAT
        # row with a hardcoded NULL category_path tests a genuinely
        # different key, not the actual incident scenario, and would
        # correctly (and misleadingly) look like a fresh insert. The
        # real incident's failure mode is specifically the
        # category_path IS NULL case (every SKU-grain row via the
        # canonical pipeline's own _product_fk_spec("sku")), so the test
        # row must match that shape exactly.
        known = conn.execute(text(
            "SELECT product_key, sku_code FROM public.product_dimension "
            "WHERE principal = 'unilever' AND grain = 'sku' AND sku_code IS NOT NULL "
            "AND category_path IS NULL LIMIT 1"
        )).fetchone()
    if known is None:
        print("\n[preflight] public.product_dimension has no existing Unilever SKU rows to "
              "test against - skipping (nothing to collide with yet, a fresh cutover target).")
        return

    expected_pk, sku_code = known
    print(f"\n[preflight] dimension-identity check: resolving known sku_code={sku_code!r} "
          f"(expected product_key={expected_pk}) against public, in a rolled-back transaction ...")

    with engine.begin() as conn:
        savepoint = conn.begin_nested()
        try:
            result = conn.execute(text("""
                INSERT INTO public.product_dimension (principal, grain, sku_code, category_path)
                VALUES ('unilever', 'sku', :sku_code, NULL)
                ON CONFLICT (principal, grain, sku_code, category_path) DO NOTHING
                RETURNING product_key
            """), {"sku_code": sku_code})
            inserted_new = result.fetchone()
            got_pk = conn.execute(text(
                "SELECT product_key FROM public.product_dimension "
                "WHERE principal='unilever' AND grain='sku' AND sku_code=:sku_code"
            ), {"sku_code": sku_code}).scalar()
        except Exception as e:
            savepoint.rollback()
            raise RuntimeError(
                f"[preflight] ABORTED before writing a single row: resolving the known SKU "
                f"{sku_code!r} raised {type(e).__name__}: {e}. This is exactly the identity-"
                f"sequence desync class of bug from the 2026-09-15 incident - fix the "
                f"sequence(s) (see reports/PROJECT_STATE_2026-09.md §10) before retrying."
            ) from e
        finally:
            if savepoint.is_active:
                savepoint.rollback()

    if inserted_new is not None or got_pk != expected_pk:
        raise RuntimeError(
            f"[preflight] ABORTED before writing a single row: resolving known SKU "
            f"{sku_code!r} returned product_key={got_pk!r} (inserted_new={inserted_new!r}), "
            f"expected the PRE-EXISTING product_key={expected_pk}. This means dimension "
            f"resolution would create a duplicate row instead of matching the existing one - "
            f"the exact failure mode from the 2026-09-15 incident. Do not proceed."
        )
    print(f"[preflight] PASSED - resolved to the pre-existing product_key={got_pk}, no new "
          f"row created. Rolled back (nothing committed by this check). Proceeding.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--schema", default="ssm_canonical", help="Target schema: a scratch schema, or 'public' with --target-public.")
    parser.add_argument(
        "--target-public", action="store_true",
        help="Explicit-only: allow --schema public. Required together with --schema public for any run "
             "against the live schema. Loads refuse while a migration is pending; migrations reach public "
             "only through --schema-only.",
    )
    parser.add_argument("--schema-only", action="store_true",
                        help="Apply pending migrations through the ledger, then exit. No loads, no data gates.")
    parser.add_argument(
        "--rehearse", action="store_true",
        help="With --schema-only: apply pending migrations inside ONE transaction that always ROLLBACKs - "
             "never commits, never writes schema_migrations. See reports/SCHEMA_REORG_PLAN.md section 2 (R4).",
    )
    parser.add_argument(
        "--lock-timeout-ms", type=int, default=None, metavar="MS",
        help=f"--rehearse only. Default {DEFAULT_REHEARSE_LOCK_TIMEOUT_MS}ms against a scratch schema; "
             f"mandatory (no default) with --schema public.",
    )
    parser.add_argument(
        "--statement-timeout-ms", type=int, default=None, metavar="MS",
        help=f"--rehearse only. Default {DEFAULT_REHEARSE_STATEMENT_TIMEOUT_MS}ms against a scratch schema; "
             f"mandatory (no default) with --schema public.",
    )
    parser.add_argument(
        "--rehearse-check", action="append", default=[], metavar="PATH", type=Path,
        help="--rehearse only, repeatable. A SQL file of exactly ONE statement, run inside the "
             "rehearsal transaction after the migrations and before the ROLLBACK, so its queries can "
             "see the uncommitted objects. A returned column named `ok` that is false fails the run.",
    )
    parser.add_argument("--slice", action="append", default=[], metavar="SPEC",
                        help="principal:table:YYYY-MM[:branch[:source]] - repeatable. See the module docstring.")
    parser.add_argument("--all-slices", action="store_true",
                        help="Full rebuild: every slice under data/raw, family-wide transform, one transaction per slice.")
    parser.add_argument("--file", action="append", default=[], metavar="PATH",
                        help="Use this raw file (under the repo) instead of discovery for the slice(s) of its family. Repeatable.")
    parser.add_argument("--allow-shrink", action="store_true",
                        help="Load a slice even if its real rows drop more than 5%% (event status warning, audit_log row).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Stage, transform and plan every slice; write only its etl_load_event row (dry_run = true).")
    parser.add_argument("--refresh-coverage", action="store_true",
                        help="Recompute etl_coverage for every principal x table x month (2021-01 .. this month).")
    parser.add_argument("--practice-auto-sign", action="store_true",
                        help="The practice copy only, refused elsewhere: the system signs this load's manifest (scripts/practice_signed_load.py).")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-SKU backfill log lines.")
    parser.add_argument("--no-fill", action="store_true",
                        help="Skip the DEC-31 fill step (scripts/fill_missing.py) that otherwise runs after every --slice / "
                             "--all-slices load.")
    args = parser.parse_args()

    modes = [bool(args.schema_only), bool(args.slice), bool(args.all_slices), bool(args.refresh_coverage)]
    if sum(modes) != 1:
        parser.error("pick exactly one of --schema-only, --slice ..., --all-slices, --refresh-coverage")
    if args.schema_only and args.dry_run:
        parser.error("--schema-only and --dry-run are mutually exclusive (schema-only always writes DDL for real).")
    if args.file and not (args.slice or args.all_slices):
        parser.error("--file only applies to --slice / --all-slices")
    if args.target_public != (args.schema == "public"):
        parser.error("--target-public and --schema public go together (both explicit, no default path leads to public).")
    if args.rehearse and not args.schema_only:
        parser.error("--rehearse only applies to --schema-only")
    if args.rehearse_check and not args.rehearse:
        parser.error("--rehearse-check only applies with --rehearse")
    for _check_path in args.rehearse_check:
        if not _check_path.is_file():
            parser.error(f"--rehearse-check: no such file: {_check_path}")
    if not args.rehearse and (args.lock_timeout_ms is not None or args.statement_timeout_ms is not None):
        parser.error("--lock-timeout-ms/--statement-timeout-ms only apply with --rehearse")
    if args.rehearse and args.target_public and (args.lock_timeout_ms is None or args.statement_timeout_ms is None):
        parser.error(
            "--rehearse --schema public requires explicit --lock-timeout-ms and --statement-timeout-ms - "
            "no silent default against the live schema."
        )
    _require_scratch_schema(args.schema, allow_public=args.target_public)

    logging.basicConfig(level=logging.WARNING if args.quiet else logging.INFO, format="%(message)s")
    if not args.quiet:
        enable_server_notices()
    print(f"=== run_canonical_load: schema='{args.schema}'  dry_run={args.dry_run}  target_public={args.target_public} ===")

    cfg = get_settings()
    engine = create_engine(cfg.supabase_db_url)

    if args.schema_only:
        if args.rehearse:
            lock_timeout_ms = args.lock_timeout_ms if args.lock_timeout_ms is not None else DEFAULT_REHEARSE_LOCK_TIMEOUT_MS
            statement_timeout_ms = (
                args.statement_timeout_ms if args.statement_timeout_ms is not None
                else DEFAULT_REHEARSE_STATEMENT_TIMEOUT_MS
            )
            return rehearse_migrations(
                engine, args.schema, lock_timeout_ms, statement_timeout_ms,
                allow_public=args.target_public, check_files=args.rehearse_check,
            )
        ensure_scratch_schema(engine, args.schema, dry_run=False, allow_public=args.target_public)
        print(f"\n--schema-only: '{args.schema}' is migrated. No loads. Exiting.")
        return 0

    # A load never applies a migration to public behind the operator's back;
    # a scratch schema is brought up to date (or created) first.
    if args.target_public:
        pending = pending_migrations(engine, args.schema)
        if pending:
            print(f"\nrefusing: migrations pending on public: {pending}. Apply them first with --schema-only.")
            return 1
    elif not args.dry_run:
        ensure_scratch_schema(engine, args.schema, dry_run=False)

    from scripts import load_slices
    return load_slices.run(engine, args)


if __name__ == "__main__":
    sys.exit(main())
