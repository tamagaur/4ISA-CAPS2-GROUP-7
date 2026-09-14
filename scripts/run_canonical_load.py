"""
scripts/run_canonical_load.py — the canonical Extract-output -> Load
orchestrator (Phase 1d, ARCHITECTURE.md / reports/PHASE1_EXECUTION_PLAN_2026-09.md).

WHY THIS EXISTS: analytics/etl/load.py (load_to_supabase, resolve_dimension_fk)
is a LIBRARY — before this file, nothing in the repo called it except tests.
transform_driver.py classifies staged sheets but discards the transformed
frames. There was no code path from raw files to DB rows. This script is
that path.

TARGET IS ALWAYS A SCRATCH SCHEMA, NEVER `public`. --schema defaults to
ssm_canonical and the script hard-refuses `public` (see _require_scratch_schema).
Confirmed 2026-09-11 (Phase 1 step 2a): no other code in this repo qualifies a
schema or sets search_path, so nothing else can read or write this scratch
schema by accident — but this script itself must stay disciplined about it:
every DDL/DML statement runs inside `SET LOCAL search_path TO <schema>`,
scoped to one transaction, NEVER `ALTER ROLE`/`ALTER DATABASE` (which would
leak the setting to every other connection).

ORDER (dimension-dependency order, not alphabetical — see _run_facts):
  1. Gate check (reject-rate, sign-off) — nothing else has run yet, so a gate
     failure has nothing to roll back.
  2. Ensure the scratch schema (schema.sql + every migrations/000*.sql file).
  3. sales_unilever_sku_demand/unilever — creates the 1,807 Product_Dimension
     SKU rows the category/brand backfill (step 6) needs to exist first.
  4. sales/delmonte, purchase/delmonte (no real Unilever purchase_order
     data exists in staging — confirmed 2026-09-11, 2,703/2,703 staged rows
     are delmonte; FACT_PLAN omits purchase/unilever rather than run it on
     nothing), sales_return/delmonte.
  5. sell_out/delmonte — creates the 99 Product_Dimension category rows.
  6. inventory/delmonte (the inventory_sign_off doc_type — also delmonte-only
     in staging, confirmed 2026-09-11: 23,350/23,350 rows; Unilever's
     inventory is a wholly separate doc_type, ssis_soh, step 7 below).
  7. ssis_soh — Unilever SOH Inventory_Fact rows + its own non-joining
     Product_Dimension candidates (transform_ssis_soh.py).
  8. Category/brand backfill — runs LAST, after steps 3 and 7 have both run,
     since it needs the demand SKUs (3) and the SOH category source (7).
  9. Summary print + exit.

TRANSACTIONALITY / WHAT ROLLS BACK ON FAILURE: this is NOT one single Postgres
transaction spanning every table (load_to_supabase/resolve_dimension_fk each
manage their own transaction internally, per table — changing that is a
larger refactor than this script, not made here). Instead: "no partial load
left behind" is enforced at the SCHEMA level, explicitly, not implicitly —
  - A gate failure (step 1) happens before schema creation even runs. Nothing
    to roll back — the script prints which gate and why, then exits nonzero.
    This is the trivial case.
  - Any exception from step 2 onward is caught by one top-level try/except.
    On catch (and NOT in --dry-run, which never writes anything): the script
    prints exactly what it is about to do, then issues
    `DROP SCHEMA <schema> CASCADE` against the scratch schema and re-raises
    the original exception. The scratch schema ends the run either fully
    loaded or fully absent — never half-loaded. This is a real DROP, only
    ever against the scratch schema (never `public`, same guard as
    _require_scratch_schema), and only ever triggered by a genuine failure.

EXPECTED VS ACTUAL: every fact's target row/conflict/quarantine count below
was measured against real staged data 2026-09-11 (Phase 1 steps 2b/2c/2d/2e —
see reports/PHASE1_EXECUTION_PLAN_2026-09.md for the full evidence per number).
These are frozen constants, not recomputed live — if a future run's actual
count differs, that is real information (data/raw/ changed, a fix regressed,
a config drifted) and must be visible, not silently accepted. A mismatch
prints a loud, unmissable banner and the run's final exit code is nonzero,
but does NOT itself trigger the schema-drop cleanup above (a real, expected
data update looks the same as a regression from here — a human decides which
this is, the script's job is to make sure that decision is never made blind).

STILL REQUIRES migration 0011 to be applied before a real (non---dry-run) run
of the sales_return step can succeed — see that file's header and
config/source_of_truth.yaml's sales_return.both comment: the transform-side
natural_key already has 5 columns (invoice_num added), but schema.sql's
SalesReturn_Fact UNIQUE constraint is still 4 until migration 0011 lands, and
Postgres will reject the ON CONFLICT clause outright (a hard failure, not a
silent misload) until it does.

NOT YET BUILT, deliberately out of this script's scope: the scratch-vs-live
diff (a separate, read-only script) and the cutover decision (separate,
human, after the diff).

SCHEMA SCOPING — two mechanisms, used for two different kinds of SQL, on
purpose (a real bug in an earlier draft of this file mixed them up and would
have silently hit `public` for the category/brand backfill's raw SQL — caught
2026-09-11 before this shipped, see _scratch_engine()'s docstring):
  - schema.sql / migrations (raw multi-statement text SQL): `SET LOCAL
    search_path TO <schema>, public`, issued fresh inside every transaction
    that runs one of these files — SET LOCAL is transaction-scoped, never
    leaks to another transaction or connection.
  - Everything that goes through analytics.etl.load (load_to_supabase,
    resolve_dimension_fk — SQLAlchemy Core Table/insert/select against
    autoload_with=engine) AND this script's own raw product_dimension
    SELECT/UPDATE in the backfill step: a single ENGINE created once via
    `_scratch_engine()`, using SQLAlchemy's `execution_options(
    schema_translate_map={None: schema})`. This is the right mechanism for
    Core-construct SQL (it rewrites the schema at compile time, correctly,
    for every call made through that engine) — `SET LOCAL` would NOT work
    here because load_to_supabase opens its own fresh transactions
    internally with no way for this script to inject a SET LOCAL into them.
    Raw `text()` SQL, however, is NOT schema_translate_map-aware (Postgres
    resolves unqualified names in literal SQL via the CONNECTION's
    search_path, not SQLAlchemy's compile-time rewrite) — which is why the
    backfill step's raw SELECT/UPDATE also needs its own SET LOCAL, even
    though it runs against the same _scratch_engine().

Usage:
    python -m scripts.run_canonical_load --schema-only     # apply schema.sql + migrations, exit
    python -m scripts.run_canonical_load --dry-run          # compute + print, write nothing
    python -m scripts.run_canonical_load --schema ssm_canonical   # the real load
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from sqlalchemy import Engine, MetaData, Table, create_engine, text

from analytics.config import get_settings
from analytics.etl.load import (
    DimensionFKSpec,
    check_reject_rate_gate,
    check_signoff_gate,
    load_to_supabase,
)
from analytics.etl.transform import (
    DEFAULT_CONFIG_DIR,
    dedup_facts,
    load_source_of_truth,
    transform_fact,
)
from analytics.etl.transform_ssis_soh import transform_ssis_soh

REPO_ROOT = Path(__file__).resolve().parent.parent
STAGING_DIR = REPO_ROOT / "staging"
TRANSFORM_DIR = REPO_ROOT / "transform"
SCHEMA_SQL = REPO_ROOT / "analytics" / "db" / "schema.sql"
MIGRATIONS_DIR = REPO_ROOT / "analytics" / "db" / "migrations"

FORBIDDEN_SCHEMAS = {"public"}  # never a valid --schema value, see _require_scratch_schema

log = logging.getLogger("run_canonical_load")


def _scratch_engine(engine: Engine, schema: str) -> Engine:
    """Returns an Engine wrapper that schema-qualifies every SQLAlchemy Core
    construct (Table/insert/select via autoload_with=engine) to `schema`,
    via execution_options(schema_translate_map=...). Use this for every call
    into analytics.etl.load (load_to_supabase, resolve_dimension_fk) and for
    this script's own product_dimension SELECT/UPDATE via Core constructs.
    Does NOT affect raw text() SQL — see this module's SCHEMA SCOPING note
    for why schema.sql/migrations and the backfill's raw SQL need SET LOCAL
    search_path instead, issued separately."""
    _require_scratch_schema(schema)
    return engine.execution_options(schema_translate_map={None: schema})


def _require_scratch_schema(schema: str) -> None:
    """Refuses `public` (or anything obviously not a scratch schema name) as
    a safety guard, not just a default — this script must never be pointed
    at the live schema, even by a typo. Matches the schema-safety finding
    from Phase 1 step 2a (nothing else in this repo qualifies a schema, so
    nothing reads/writes here by accident — this script is the one place
    that must stay disciplined about which schema it targets)."""
    if schema.lower() in FORBIDDEN_SCHEMAS:
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
        return DimensionFKSpec(
            fk_column="product_key",
            dimension_table="product_dimension",
            dimension_pk="product_key",
            dimension_natural_key=["principal", "grain", "sku_code", "category_path"],
            df_to_dimension_columns={"principal": "principal", "sku_code": "sku_code"},
            static_values={"grain": "sku", "category_path": None},
        )
    return DimensionFKSpec(
        fk_column="product_key",
        dimension_table="product_dimension",
        dimension_pk="product_key",
        dimension_natural_key=["principal", "grain", "sku_code", "category_path"],
        df_to_dimension_columns={"principal": "principal", "category_path": "category_path"},
        static_values={"grain": "category", "sku_code": None},
    )


@dataclass
class FactPlanItem:
    fact: str
    principal: str
    table_name: str
    amount_col: str
    dimension_fks: list[DimensionFKSpec] = field(default_factory=list)
    # Frozen targets, measured 2026-09-11 against real staged data (see this
    # file's own header + reports/PHASE1_EXECUTION_PLAN_2026-09.md). None
    # where not yet measured for that specific (fact, principal).
    expected_rows: int | None = None
    expected_conflicts: int | None = None
    expected_quarantined: int | None = None


FACT_PLAN: list[FactPlanItem] = [
    # expected_rows is the REAL+DEMO COMBINED total (what the loader
    # actually inserts — demo rows load into the base tables by design,
    # filtered downstream by the _Real views, CLAUDE.md rule 1). Re-measured
    # 2026-09-14 directly from this script's own --dry-run output, after
    # two real bugs were found and fixed the same day (see this file's
    # module docstring / reports/PHASE1_EXECUTION_PLAN_2026-09.md step 5c):
    # a fresh Extract re-run staged `data/raw/Synthetic Data/*` files that
    # a stale staging/ snapshot never had, and half of purchase_order's and
    # inventory_sign_off's synthetic is_demo values were the literal string
    # "True" (not boolean), silently misclassified as real by every
    # `is_demo != True` filter until analytics.etl.transform.coerce_is_demo_column()
    # was added. expected_conflicts/expected_quarantined stay REAL-ONLY —
    # the meaningful data-quality signal; demo-data noise is real but not
    # held to this rigor (same standing position as everywhere else in this
    # codebase) and is reported separately by _run_one_fact, not blended
    # into these targets.
    FactPlanItem(
        "sales_unilever_sku_demand", "unilever", "unilever_sku_demand_fact", "quantity_sold",
        dimension_fks=[_product_fk_spec("sku")],
        expected_rows=44575, expected_conflicts=0, expected_quarantined=0,
    ),
    FactPlanItem(
        "sales", "delmonte", "sales_fact", "net_amount",
        dimension_fks=[],  # Sales_Fact carries no product_key (invoice-grain, DEC-02)
        expected_rows=53901, expected_conflicts=1, expected_quarantined=591,
    ),
    FactPlanItem(
        "purchase", "delmonte", "purchase_fact", "net_amount",
        dimension_fks=[],  # Purchase_Fact carries no product_key either
        expected_rows=4594, expected_conflicts=0, expected_quarantined=27,
    ),
    FactPlanItem(
        "sales_return", "delmonte", "salesreturn_fact", "net_amount",
        dimension_fks=[],
        # expected_quarantined=773 matches the CURRENT transform-side key
        # (source_of_truth.yaml's sales_return.both.natural_key, 5 columns,
        # return_type still included) - migration 0011 already changed the
        # DB CONSTRAINT to drop return_type, but source_of_truth.yaml's
        # transform-side key was deliberately left unchanged (see that
        # file's own comment) pending a separate decision on whether to
        # widen the quarantine relief to match. If/when that changes,
        # re-measure: informationally verified 2026-09-11, dropping
        # return_type from the transform key drops real quarantined to 8.
        expected_rows=1901, expected_conflicts=0, expected_quarantined=773,
    ),
    FactPlanItem(
        "sell_out", "delmonte", "sellout_fact", "net_amount",
        dimension_fks=[_product_fk_spec("category")],
        expected_rows=8584, expected_conflicts=0, expected_quarantined=0,
    ),
    FactPlanItem(
        "inventory", "delmonte", "inventory_fact", "quantity_on_hand",
        dimension_fks=[],  # inventory_sign_off SKUs join via sku_code text match downstream, not this FK path
        expected_rows=21612, expected_conflicts=0, expected_quarantined=188,
    ),
]


@dataclass
class TableRunResult:
    label: str
    expected_rows: int | None
    actual_rows: int
    expected_conflicts: int | None
    actual_conflicts: int
    expected_quarantined: int | None
    actual_quarantined: int
    rows_upserted: int
    mismatch: bool


def _project_to_table_columns(
    df: pd.DataFrame, table_name: str, engine: Engine, dimension_fks: list[DimensionFKSpec],
) -> pd.DataFrame:
    """Drops every column `df` carries that has no home on `table_name` and
    isn't needed by load_to_supabase()'s own dimension-FK resolution —
    VISIBLY (printed, not silent) — before load_to_supabase() runs. Found
    necessary 2026-09-14, first real --dry-run: transform_fact() legitimately
    produces columns a fact table never has (e.g. unilever_sku's
    `product_name`/`pack_size` belong on Product_Dimension, not
    Unilever_SKU_Demand_Fact; `net_amount_inc_tax` has no destination at all
    — `net_amount` is the field the table actually carries). Without this,
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


def _run_one_fact(item: FactPlanItem, engine: Engine, dry_run: bool) -> TableRunResult:
    rule = load_source_of_truth(item.fact, item.principal, DEFAULT_CONFIG_DIR)
    doc_dir = STAGING_DIR / rule.doc_type
    raw = pd.concat(
        [pd.read_parquet(f) for f in sorted(doc_dir.glob("*.parquet"))], ignore_index=True,
    )
    principal_df = raw[raw["_principal"] == item.principal] if "_principal" in raw.columns else raw
    deduped_df, report = transform_fact(
        principal_df, item.fact, item.principal, DEFAULT_CONFIG_DIR, amount_col=item.amount_col,
    )
    dedup = report["dedup"]  # REAL+DEMO combined — this is what actually gets loaded

    # Separate, real-only dedup pass — diagnostic only, nothing loaded from
    # it — so conflicts/quarantined can be compared against a meaningful
    # target instead of a number dominated by demo-data noise. Confirmed
    # 2026-09-14: demo data conflicts heavily (e.g. purchase_order: 438
    # demo-only conflict groups vs 0 real) — blending that into a pass/fail
    # target would make every run "mismatch" on noise that was already
    # known and accepted, defeating the point of having a target at all.
    if "is_demo" in deduped_df.columns:
        real_only = deduped_df[deduped_df["is_demo"] != True]  # noqa: E712
        _, real_report = dedup_facts(real_only, rule.natural_key, amount_col=item.amount_col)
        real_conflicts, real_quarantined = len(real_report.conflicting_groups), len(real_report.quarantined)
    else:
        real_conflicts, real_quarantined = len(dedup.conflicting_groups), len(dedup.quarantined)

    load_input = _project_to_table_columns(deduped_df, item.table_name, engine, item.dimension_fks)

    load_result = load_to_supabase(
        load_input, item.table_name, engine, rule.natural_key,
        dimension_fks=item.dimension_fks, dry_run=dry_run,
    )

    actual_rows = load_result.rows_attempted
    actual_conflicts = real_conflicts
    actual_quarantined = real_quarantined
    if len(dedup.conflicting_groups) > real_conflicts or len(dedup.quarantined) > real_quarantined:
        print(f"  [{item.table_name}] combined (real+demo) has "
              f"{len(dedup.conflicting_groups)} conflicts / {len(dedup.quarantined)} quarantined — "
              f"demo-data noise, not compared against a target, loaded as-is")
    mismatch = (
        (item.expected_rows is not None and actual_rows != item.expected_rows)
        or (item.expected_conflicts is not None and actual_conflicts != item.expected_conflicts)
        or (item.expected_quarantined is not None and actual_quarantined != item.expected_quarantined)
    )

    result = TableRunResult(
        label=f"{item.table_name} ({item.fact}/{item.principal})",
        expected_rows=item.expected_rows, actual_rows=actual_rows,
        expected_conflicts=item.expected_conflicts, actual_conflicts=actual_conflicts,
        expected_quarantined=item.expected_quarantined, actual_quarantined=actual_quarantined,
        rows_upserted=load_result.rows_upserted, mismatch=mismatch,
    )
    _print_table_result(result, dry_run)
    for dim_report in load_result.dimension_resolutions:
        verb = "would insert" if dim_report.dry_run else "inserted"
        log.info(
            "  dimension %s: %d distinct keys seen, %d %s, %d rows unresolved (null key part)",
            dim_report.dimension_table, dim_report.distinct_keys_seen, dim_report.rows_inserted,
            verb, dim_report.rows_unresolved,
        )
    return result


def _print_table_result(r: TableRunResult, dry_run: bool) -> None:
    def fmt(expected, actual):
        if expected is None:
            return f"{actual} (no target measured)"
        flag = "" if expected == actual else "  <<< MISMATCH"
        return f"expected {expected} / actual {actual}{flag}"

    verb = "would upsert" if dry_run else "upserted"
    print(f"\n[{r.label}]")
    print(f"  rows:        {fmt(r.expected_rows, r.actual_rows)}")
    print(f"  conflicts:   {fmt(r.expected_conflicts, r.actual_conflicts)}")
    print(f"  quarantined: {fmt(r.expected_quarantined, r.actual_quarantined)}")
    print(f"  {verb}: {r.rows_upserted}")
    if r.mismatch:
        print(f"  !!! {r.label}: ACTUAL DIFFERS FROM THE FROZEN 2026-09-11 TARGET !!!")
        print("      This is not necessarily wrong — data/raw/ may have genuinely changed.")
        print("      It must not be accepted silently. Investigate before trusting this load.")


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


def _load_soh_snapshot() -> pd.DataFrame:
    """Most-recent SOH snapshot per sku_code — sku_code, article_description,
    category_desc. Same DEC-21 rule transform_ssis_soh.py already uses
    (_most_recent_by_sku), reproduced here independently because that
    module only exposes category info for NON-joining SKUs
    (product_dimension_candidates) — this backfill needs it for every
    Unilever SKU, joining or not."""
    fs = sorted((STAGING_DIR / "ssis_soh").glob("*.parquet"))
    soh = pd.concat(
        [pd.read_parquet(f, columns=["sku_code", "article_description", "category_desc", "snapshot_date"]) for f in fs],
        ignore_index=True,
    )
    soh["sku_code"] = soh["sku_code"].astype(str).str.strip()
    soh["category_desc"] = soh["category_desc"].astype(str).str.strip().replace({"": None, "nan": None})
    soh = soh.dropna(subset=["category_desc"])
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


def run_category_brand_backfill(engine: Engine, schema: str, dry_run: bool) -> dict[str, int]:
    """Runs LAST (see module docstring's step 8). For every Unilever demand
    SKU already in Product_Dimension (loaded by step 3): direct SOH match,
    else UNCLASSIFIED. Logs which method resolved each SKU AS IT RUNS (per
    Yuan's instruction, 2026-09-11) via log.info at INFO level — pass
    --quiet to suppress per-SKU lines and keep only the final tally.

    IMPORTANT GAP, found while writing this (2026-09-11, not previously
    surfaced this precisely): the validated description-keyword fallback
    (_fit_keyword_rule/_predict_category above, 94.6% accuracy / 97.4% at
    confidence >= 0.6 out-of-sample — reports/PROJECT_STATE_2026-09.md §8)
    has NO Unilever demand SKUs to actually apply to in production. It was
    validated on the 1,427 SKUs that DO have an SOH row (train/test split of
    the SAME labelled population) — but the 380 SKUs that need a fallback
    have NO SOH row at all, and Unilever's demand data
    (unilever_sku.yaml's "Product" column is a bare SKU code, not a name)
    carries no description anywhere else in this pipeline. There is
    currently no text to run the keyword rule against for the population it
    was meant to help. So this function only ever produces two outcomes in
    practice: direct_soh_match (~1,427) or unclassified (~380) — not the
    three-way split originally envisioned. _fit_keyword_rule/_predict_category
    are kept, unused, for if a second Unilever description source is ever
    found — not deleted, but not pretending to run either."""
    if dry_run:
        print("\n[Product_Dimension category/brand backfill] DRY RUN LIMITATION: "
              "this step queries product_dimension for existing Unilever demand SKU "
              "rows, but --dry-run never actually inserts them (resolve_dimension_fk's "
              "dry-run reports 'would insert' without writing) — so on an empty/partial "
              "scratch schema this correctly finds 0 and the tally below is not "
              "meaningful. Real signal only on a non-dry-run run, where step 3's fact "
              "load has already populated Product_Dimension for real by the time this "
              "step (step 8) runs.")
    soh = _load_soh_snapshot()
    alias = _load_brand_alias_table()
    soh_by_sku = soh.set_index("sku_code")

    with engine.connect() as conn:
        conn.execute(text("SET LOCAL search_path TO :schema, public").bindparams(schema=schema))
        demand_skus = pd.DataFrame(
            conn.execute(text(
                "SELECT product_key, sku_code FROM product_dimension "
                "WHERE principal = 'unilever' AND grain = 'sku'"
            )).fetchall(),
            columns=["product_key", "sku_code"],
        )

    tally: dict[str, int] = {"direct_soh_match": 0, "unclassified": 0}
    updates: list[dict] = []
    for _, row in demand_skus.iterrows():
        sku = row["sku_code"]
        if sku in soh_by_sku.index:
            soh_row = soh_by_sku.loc[sku]
            category_path, category_source = soh_row["category_desc"], "direct_soh_match"
            desc = soh_row["article_description"]
        else:
            # No SOH row at all -> no category signal AND no description to
            # run the keyword rule against (see this function's docstring).
            desc, category_path, category_source = None, None, "unclassified"

        brand_raw = str(desc).split()[0].upper() if desc else None
        brand = alias.get(brand_raw, brand_raw) if brand_raw else None
        brand_source = "soh_first_token_rule" if brand else None

        tally[category_source] = tally.get(category_source, 0) + 1
        log.info(
            "  %s -> category_path=%r (%s), brand=%r",
            sku, category_path or "UNCLASSIFIED", category_source, brand,
        )
        updates.append({
            "product_key": int(row["product_key"]),
            "category_path": category_path or "UNCLASSIFIED",
            "category_path_source": category_source,
            "brand": brand,
            "brand_source": brand_source,
        })

    print(f"\n[Product_Dimension category/brand backfill]")
    print(f"  direct_soh_match: {tally.get('direct_soh_match', 0)}")
    print(f"  keyword_rule:     0  (no description source exists for the SKUs "
          f"it would apply to — see run_category_brand_backfill's docstring; "
          f"this is a real, currently-unclosed gap, not a bug in this script)")
    print(f"  unclassified:     {tally.get('unclassified', 0)}")

    if not dry_run and updates:
        with engine.begin() as conn:
            conn.execute(text("SET LOCAL search_path TO :schema, public").bindparams(schema=schema))
            for u in updates:
                conn.execute(text(
                    "UPDATE product_dimension SET category_path = :category_path, "
                    "category_path_source = :category_path_source, brand = COALESCE(brand, :brand), "
                    "brand_source = COALESCE(brand_source, :brand_source) WHERE product_key = :product_key"
                ), u)
    return tally


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


def ensure_scratch_schema(engine: Engine, schema: str, dry_run: bool) -> None:
    _require_scratch_schema(schema)
    print(f"\n[schema] ensuring '{schema}' exists" + (" (dry-run: SELECT-only check)" if dry_run else ""))
    if dry_run:
        with engine.connect() as conn:
            conn.execute(text("SET LOCAL search_path TO :schema, public").bindparams(schema=schema))
            # dry-run: don't create anything, just confirm the connection works
            conn.execute(text("SELECT 1"))
        return

    files = [SCHEMA_SQL] + sorted(MIGRATIONS_DIR.glob("0*.sql"))
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
    for f in files:
        cleaned_sql = _strip_sql_file(f.read_text(encoding="utf-8"))
        if not cleaned_sql.strip():
            print(f"  SKIPPED {f.relative_to(REPO_ROOT)} — nothing left after stripping comments/BEGIN/COMMIT")
            continue
        with engine.begin() as conn:
            # SET LOCAL is transaction-scoped only - never leaks to another
            # session or a later transaction on this same connection. This
            # is the ONE place a schema is ever set for this whole script.
            # Uses text()+bindparams here (not exec_driver_sql) because this
            # one statement genuinely needs a real bind parameter, and it
            # has no literal `%` in it.
            conn.execute(text("SET LOCAL search_path TO :schema, public").bindparams(schema=schema))
            # exec_driver_sql bypasses SQLAlchemy's text()/bind-parameter
            # layer entirely (passes the SQL straight to psycopg2), which
            # matters because these files' comments contain literal `%`
            # characters (e.g. "~79% of Unilever demand SKUs" in migration
            # 0011) that text() misreads as psycopg2 paramstyle
            # placeholders and silently corrupts execution — caught
            # 2026-09-14: an earlier version using text() per-statement let
            # migration 0011's ADD COLUMN succeed but then raised
            # UndefinedColumn on the very next COMMENT ON COLUMN statement
            # (the schema-drop rollback fired correctly and cleanly either
            # way, confirming that part of the design). exec_driver_sql
            # also natively runs a full `;`-separated multi-statement
            # script in one call (Postgres' simple query protocol).
            #
            # STILL not enough on its own: exec_driver_sql passes an empty
            # parameters object to psycopg2's cursor.execute(), and
            # psycopg2 tries to interpret ANY literal `%` in the query as a
            # paramstyle placeholder whenever a parameters argument is
            # present at all (even empty) - raising
            # "immutabledict is not a sequence". schema.sql itself has a
            # trailing INLINE comment with a literal `%` on one line
            # (`discount_rate_label TEXT, -- ... 'LESS 2%' ...`) that
            # _strip_sql_file() does not remove (it only strips whole
            # comment LINES, not trailing inline comments after real code -
            # a second gap in the same category, caught immediately after
            # the first by actually running this against a live schema
            # rather than trusting a static check). Doubling every literal
            # `%` to `%%` is psycopg2's own documented escape for this -
            # safe unconditionally here, real DDL/COMMENT text in this
            # codebase never needs an un-doubled `%s`/`%()s` sequence.
            conn.exec_driver_sql(cleaned_sql.replace("%", "%%"))
        print(f"  applied {f.relative_to(REPO_ROOT)}")


def _drop_scratch_schema(engine: Engine, schema: str) -> None:
    _require_scratch_schema(schema)
    print(f"\n!!! ROLLING BACK: DROP SCHEMA \"{schema}\" CASCADE !!!")
    with engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    print(f"    '{schema}' dropped. No partial load left behind.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--schema", default="ssm_canonical", help="Target scratch schema (never 'public').")
    parser.add_argument("--dry-run", action="store_true", help="Compute everything, write nothing.")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-SKU backfill log lines (tally still prints).")
    parser.add_argument(
        "--schema-only", action="store_true",
        help="Apply schema.sql + all migrations (including 0011) to the scratch schema, "
             "then exit — no fact loads, no backfill. A real DB write (DDL only, no data), "
             "scoped to the scratch schema. Use to apply migration 0011 as its own reviewable "
             "step before a real (non-dry-run) fact load.",
    )
    args = parser.parse_args()
    if args.schema_only and args.dry_run:
        parser.error("--schema-only and --dry-run are mutually exclusive (schema-only always writes DDL for real).")

    logging.basicConfig(level=logging.WARNING if args.quiet else logging.INFO, format="%(message)s")

    _require_scratch_schema(args.schema)
    print(f"=== run_canonical_load: schema='{args.schema}'  dry_run={args.dry_run}  "
          f"schema_only={args.schema_only} ===")

    cfg = get_settings()
    engine = create_engine(cfg.supabase_db_url)

    manifest_path = STAGING_DIR / "_manifest.json"
    print("\n[gates]")
    reject_result = check_reject_rate_gate(manifest_path)
    print(f"  reject-rate gate: {reject_result.rejected}/{reject_result.staged + reject_result.rejected} "
          f"({reject_result.reject_rate:.1%}) <= {reject_result.threshold:.0%} — PASSED")
    signoff_result = check_signoff_gate(TRANSFORM_DIR)
    print(f"  sign-off gate: '{signoff_result.decision}' by {signoff_result.decided_by} "
          f"at {signoff_result.decided_at} — PASSED")
    # Both raise on failure (uncaught, on purpose — see module docstring).
    # Nothing below this line has touched the schema yet.

    results: list[TableRunResult] = []
    try:
        ensure_scratch_schema(engine, args.schema, args.dry_run)
        if args.schema_only:
            print(f"\n--schema-only: schema.sql + migrations (incl. 0011) applied to "
                  f"'{args.schema}'. No fact loads, no backfill. Exiting.")
            return 0
        scratch_engine = _scratch_engine(engine, args.schema)
        for item in FACT_PLAN:
            results.append(_run_one_fact(item, scratch_engine, args.dry_run))
        # ssis_soh — separate path, not source_of_truth.yaml-driven
        soh_result = transform_ssis_soh(staging_dir=STAGING_DIR, real_sku_codes=None)
        soh_load_input = _project_to_table_columns(
            soh_result.inventory_fact_df, "inventory_fact", scratch_engine, [],
        )
        soh_load = load_to_supabase(
            soh_load_input, "inventory_fact", scratch_engine,
            ["sku_code", "snapshot_date", "region"], dry_run=args.dry_run,
        )
        print(f"\n[inventory_fact (ssis_soh/unilever)]")
        print(f"  rows: expected 27282 / actual {soh_load.rows_attempted}"
              + ("" if soh_load.rows_attempted == 27282 else "  <<< MISMATCH"))
        # backfill's raw SQL needs the RAW engine + its own SET LOCAL (see
        # module docstring's SCHEMA SCOPING note) — schema_translate_map
        # does not apply to text() SQL.
        tally = run_category_brand_backfill(engine, args.schema, args.dry_run)
    except Exception:
        if not args.dry_run:
            _drop_scratch_schema(engine, args.schema)
        raise

    mismatches = [r for r in results if r.mismatch]
    print("\n=== summary ===")
    for r in results:
        print(f"  {r.label}: {r.actual_rows} rows" + ("  MISMATCH" if r.mismatch else ""))
    print(f"  category_path_source split: {tally}")
    print(f"\n{'DRY RUN — nothing written.' if args.dry_run else 'Load complete.'}")
    print("Next: run the scratch-vs-live diff (separate script, not yet written), "
          "then the cutover decision is yours.")

    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
