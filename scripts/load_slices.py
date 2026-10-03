"""
scripts/load_slices.py - the slice loop behind `run_canonical_load --slice /
--all-slices / --refresh-coverage`. The design (what a slice is, what one
transaction does, the fingerprint sign-off) is in run_canonical_load's module
docstring; this module is the mechanics:

  discovery   data/raw files per family (never data/raw/Synthetic Data), by
              the extract's own doc-type and period inference
  extract     one file at a time into staging_slices/<run key>/ - staging/ is
              never rewritten
  manifest    every staged sheet (row count + content hash) ->
              transform/slices/<run key>/_manifest.json; unsigned = refused
  prepare     Transform + the loader's exclusions, nothing written
              (run_canonical_load.prepare_fact; RMR and SOH have their own)
  write       one transaction per slice: delete owned real rows, DEC-29
              synthetic removal, quarantine replace, plain INSERT, dimension
              rules, ledger check, etl_coverage, etl_load_event, audit_log

Why sales_fact is special: its region column is the customer's town and its
_period is the invoice month (analytics.etl.transform.period_from_invoice_date),
so a sales row's slice is read from its lineage - infer_sheet_period /
infer_sheet_region on _src_file / _src_sheet, the same functions Extract used.
Every other table stores the workbook month in _period and the branch in
region.
"""
from __future__ import annotations

import getpass
import hashlib
import json
import re
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Callable

import pandas as pd
import yaml
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError

from analytics.etl.extract._shared import (
    REPO_ROOT,
    infer_sheet_period,
    infer_sheet_region,
    process_file,
    select_source_files,
    write_staging_table,
)
from analytics.etl import slice_validation as sv
from analytics.etl.extract import layout as lay
from analytics.etl.extract.sales_return import KNOWN_DUPLICATES
from analytics.etl.load import check_signoff_gate, load_to_supabase
from analytics.etl.transform import DEFAULT_CONFIG_DIR, FAKE_BOOKING_SHEET, apply_column_map
from analytics.etl.transform_signoff import compute_manifest_fingerprint
from profiling.profile_files import infer_period
from scripts import run_canonical_load as rcl

RAW_DIR = REPO_ROOT / "data" / "raw"
SYNTHETIC_DIR = RAW_DIR / "Synthetic Data"
SLICE_STAGING = REPO_ROOT / "staging_slices"
SLICE_TRANSFORM = REPO_ROOT / "transform" / "slices"
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
SITES = ("ilocos", "pangasinan")
SEP = "\x1f"  # chr(31): joins _src_file and _src_sheet into one comparable text value
SHRINK_FLOOR = 0.95  # a slice whose real rows would drop below 95% of what it holds now is refused
COVERAGE_START = "2021-01"
AUDIT_ACTOR = "system:etl_loader"  # audit_log.user_email is NOT NULL (0003); the OS user goes in user_name

# The "(2)" sheet is identical in six 2025 sales workbooks; a whole-corpus load
# keeps April's copy (first in file order) and records the other five as
# dedup_facts. A slice that reads one of the later workbooks also reads April's
# copy as a reference, so it decides the same way (see prepare_fact).
KEPT_COPY_MONTH = "2025-04"


@dataclass(frozen=True)
class Family:
    key: str                          # the extract doc_type; also etl_load_event.source
    principal: str
    table: str
    fact: str | None                  # run_canonical_load.FACT_PLAN fact; None = own prepare (RMR, SOH)
    month_col: str = "_period"
    source_value: str | None = None   # salesreturn_fact.source
    has_sites: bool = True


FAMILIES = [
    Family("unilever_sku", "unilever", "unilever_sku_demand_fact", "sales_unilever_sku_demand",
           month_col="calendar_month", has_sites=False),
    Family("sales_register", "delmonte", "sales_fact", "sales"),
    Family("purchase_order", "delmonte", "purchase_fact", "purchase"),
    Family("sales_return", "delmonte", "salesreturn_fact", "sales_return"),
    Family("rmr_gs_bo", "delmonte", "salesreturn_fact", None, source_value="rmr"),
    Family("sell_out", "delmonte", "sellout_fact", "sell_out"),
    Family("inventory_sign_off", "delmonte", "inventory_fact", "inventory"),
    Family("ssis_soh", "unilever", "inventory_fact", None, has_sites=False),
]
FAMILY_ORDER = {f.key: i for i, f in enumerate(FAMILIES)}
ITEMS = {(i.fact, i.principal): i for i in rcl.FACT_PLAN}

# principal x table -> the branches a complete month has (coverage 'partial' when one is missing).
# Unilever purchases/returns and Del Monte product sales have no SSM source; their months are filled by the
# DEC-31 fill step (scripts/fill_missing.py) and tracked here as derived / synthetic / missing.
COVERAGE = {
    ("delmonte", "sales_fact"): SITES,
    ("delmonte", "purchase_fact"): SITES,
    ("delmonte", "salesreturn_fact"): SITES,
    ("delmonte", "sellout_fact"): SITES,
    ("delmonte", "inventory_fact"): SITES,
    ("unilever", "unilever_sku_demand_fact"): ("la_union",),
    ("unilever", "inventory_fact"): (),
    ("unilever", "purchase_fact"): (),
    ("unilever", "salesreturn_fact"): (),
    ("delmonte", "sku_demand_fill"): (),
}
# A (principal, fact table) whose months the fill step estimates in a table of its own: when real rows for the
# month load, the estimate goes in the same transaction (DEC-31: real data wins).
DERIVED_FOR = {("unilever", "purchase_fact"): "derived_receipt_fact"}
NO_SITE_TABLES = {"sku_demand_fill"}  # no region column: a fill-only table, never real rows


@dataclass(frozen=True)
class Slice:
    family: Family
    month: str
    site: str | None = None  # None = every branch in the month's files

    @property
    def key(self) -> str:
        f = self.family
        return f"{f.principal}:{f.table}:{self.month}:{self.site or '*'}:{f.key}"


class Refused(Exception):
    def __init__(self, reason: str, detail: str):
        super().__init__(detail)
        self.reason, self.detail = reason, detail


class Unchanged(Exception):
    """The slice's new rows equal what it held: roll back, write nothing."""


PK = {"unilever_sku_demand_fact": "demand_key", "sales_fact": "sales_key", "purchase_fact": "purchase_key",
      "salesreturn_fact": "return_key", "sellout_fact": "sellout_key", "inventory_fact": "inventory_key"}
QUARANTINE_VOLATILE = "- 'quarantine_key' - 'run_id' - 'quarantined_at'"
DIMENSION_TABLES = {"product_dimension": "product_key", "customer_dimension": "customer_key",
                    "salesman_dimension": "salesman_key"}


def _multiset(values) -> dict:
    out: dict[str, int] = {}
    for v in values:
        k = json.dumps(v, sort_keys=True, default=str)
        out[k] = out.get(k, 0) + 1
    return out


def _dimension_fingerprints(conn: Connection) -> dict:
    return {t: conn.execute(text(f"SELECT count(*), md5(COALESCE(string_agg(md5(x::text), '' ORDER BY x.{k}), '')) "
                                 f"FROM {t} x")).one() for t, k in DIMENSION_TABLES.items()}


def parse_spec(spec: str) -> Slice:
    """principal:table:YYYY-MM[:branch[:source]]; branch '*' or empty = all."""
    parts = spec.strip().split(":")
    if not 3 <= len(parts) <= 5:
        raise ValueError(f"slice {spec!r}: expected principal:table:YYYY-MM[:branch[:source]]")
    principal, table, month = (p.strip() for p in parts[:3])
    site = parts[3].strip().lower() if len(parts) > 3 and parts[3].strip() not in ("", "*") else None
    source = parts[4].strip() if len(parts) > 4 and parts[4].strip() else None
    if not MONTH_RE.match(month):
        raise ValueError(f"slice {spec!r}: month must be YYYY-MM")
    cands = [f for f in FAMILIES if f.principal == principal and f.table == table]
    if source:
        cands = [f for f in cands if source in (f.key, f.source_value)]
    elif len(cands) > 1:
        cands = [f for f in cands if f.source_value is None]
    if len(cands) != 1:
        raise ValueError(f"slice {spec!r}: no single loadable family for {principal}/{table}/{source or '-'}")
    fam = cands[0]
    if site is not None and (not fam.has_sites or site not in SITES):
        raise ValueError(f"slice {spec!r}: branch {site!r} not valid for {fam.key} (branches: {SITES if fam.has_sites else 'none'})")
    return Slice(fam, month, site)


@lru_cache(maxsize=None)
def _path_lineage(src_file: str, src_sheet: str) -> tuple[str, str]:
    path = REPO_ROOT / (src_file or "")
    return infer_sheet_period(path, src_sheet or ""), infer_sheet_region(path, src_sheet or "")


# repo-relative path -> month, for a file whose path names no month and whose
# invoice dates gave one (layout guard; filled by layout_of()).
CONTENT_MONTHS: dict[str, str] = {}


def lineage(src_file: str, src_sheet: str) -> tuple[str, str]:
    """(workbook month, branch) of a stored row, by the extract's own
    inference; a file whose path names no month takes its invoice dates' month."""
    month, site = _path_lineage(src_file, src_sheet)
    if month == "unknown":
        month = CONTENT_MONTHS.get(src_file or "", month)
    return month, site


def _matches(month: str, site: str | None, sl: Slice) -> bool:
    return month == sl.month and (sl.site is None or site == sl.site)


def rmr_allowed_periods() -> list[str]:
    rules = yaml.safe_load((DEFAULT_CONFIG_DIR / "source_of_truth.yaml").read_text(encoding="utf-8"))
    return [str(p) for p in rules["sales_return"]["both"]["rmr_fallback"]["allowed_periods"]]


def rmr_roles() -> list[str]:
    rules = yaml.safe_load((DEFAULT_CONFIG_DIR / "source_of_truth.yaml").read_text(encoding="utf-8"))
    return list(rules["sales_return"]["both"]["rmr_fallback"]["system_of_record_role"])


# --- discovery + extract ----------------------------------------------------------------------------------------

# Layout guard (2026-09-30): what a file is comes from its content
# (analytics/etl/extract/layout.py - sheet names + the required headers of
# config/column_maps/*.yaml); the file name is a hint only. A file that cannot
# be identified, or has no month, is refused with an event - never skipped,
# never matched to every slice, never replaced by another file.
LAYOUT_CACHE = SLICE_STAGING / "_layout_cache.json"
_layout_cache: dict | None = None
SOH_FILE_FAMILY = "ssis_summary"   # the SSIS workbook family the ssis_soh slices read


@dataclass(frozen=True)
class Problem:
    """Why a file cannot load: an etl_load_event reason code and its detail."""
    file: str
    reason: str
    detail: str


def layout_of(path: Path) -> lay.FileLayout:
    """layout.identify() through a cache (staging_slices/_layout_cache.json)
    keyed by the file's size and mtime and by the signature config's
    fingerprint - a cold run reads every file's header rows (~1 minute)."""
    global _layout_cache
    if _layout_cache is None:
        fp = lay.config_fingerprint()
        try:
            _layout_cache = json.loads(LAYOUT_CACHE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _layout_cache = {}
        if _layout_cache.get("config") != fp:
            _layout_cache = {"config": fp, "files": {}}
    rel = path.resolve().relative_to(REPO_ROOT).as_posix()
    st = path.stat()
    key = f"{rel}|{st.st_size}|{st.st_mtime_ns}"
    hit = _layout_cache["files"].get(key)
    fl = lay.from_json(path, hit) if hit else lay.identify(path)
    if not hit:
        _layout_cache["files"][key] = lay.to_json(fl)
        LAYOUT_CACHE.parent.mkdir(parents=True, exist_ok=True)
        LAYOUT_CACHE.write_text(json.dumps(_layout_cache), encoding="utf-8")
    if fl.month_source == "invoice_dates":
        CONTENT_MONTHS[rel] = fl.month
    return fl


def discover() -> dict[Path, lay.FileLayout]:
    """Every real raw file (never data/raw/Synthetic Data), identified by content."""
    return {f: layout_of(f) for f in select_source_files(RAW_DIR) if SYNTHETIC_DIR not in f.parents}


def family_files(fam: Family) -> list[Path]:
    """Real raw files whose content is this family (the byte-identical
    April-2023 sales-return copy never - its rows are recorded by
    run_canonical_load.known_duplicate_file_records instead)."""
    files = [f for f, fl in discover().items() if fl.ok and fl.family == fam.key]
    if fam.key == "sales_return":
        files = [f for f in files if f.name not in KNOWN_DUPLICATES]
    return files


def file_month(path: Path) -> str | None:
    """The path's month, else the invoice dates' (layout.identify). None for a
    file whose rows carry their own month (unilever_sku) or that has none."""
    return layout_of(path).month


def slice_files(pool: list[Path], fam: Family, month: str) -> list[Path]:
    """The pool's files for one month. A file with no month is never matched to
    a slice, except a family whose rows carry their own month."""
    per_row = fam.key in lay.PER_ROW_MONTH_FAMILIES
    return [f for f in pool if file_month(f) == month or (per_row and layout_of(f).month_source == "rows")]


def _file_family(fl: lay.FileLayout) -> str:
    fam = fl.family or fl.hint
    return "ssis_soh" if fam == SOH_FILE_FAMILY else fam


def bad_files_for(fam: Family, month: str) -> list[tuple[Path, lay.FileLayout]]:
    """Discovered files of this family (by content, or by name when content
    could not say) and month that could not be identified cleanly."""
    return [(f, fl) for f, fl in discover().items()
            if not fl.ok and _file_family(fl) == fam.key and (fl.month or infer_period(f)) == month]


def extract_files(files: list[Path], doc_type: str, staging: Path, done: set[Path]) -> list[Problem]:
    """Stage each file once (process_file + write_staging_table, the same two
    calls the full extract driver makes), header rows from the file's verified
    layout. Returns problems: layout (a sheet could not be read as this family)
    and totals (a sheet's own totals row disagrees with the sum of its rows and
    the file is not on config/checksum_allowlist.yaml)."""
    problems = []
    for f in files:
        if f in done:
            continue
        done.add(f)
        res = process_file(f, doc_type, layout=layout_of(f))
        if res.file_reject is not None:
            problems.append(Problem(f.name, "layout_changed", res.file_reject.reason))
            continue
        if not res.dfs:
            problems.append(Problem(f.name, "layout_changed", "no sheet could be staged"))
            continue
        for o in res.outcomes:
            if o.checksum_status == "mismatch" and sv.checksum_allowed(f, o.src_sheet) is None:
                problems.append(Problem(f.name, "validation_failed", (
                    f"sheet {o.src_sheet!r}: its totals row says {o.checksum_column} = {o.checksum_expected:,.2f}, "
                    f"its rows sum to {o.checksum_got:,.2f} (not on config/checksum_allowlist.yaml)")))
        for df, outcome in res.dfs:
            write_staging_table(df, outcome.doc_type, outcome.src_file, outcome.src_sheet, staging)
    return problems


def extract_soh(staging: Path, months: set[str] | None) -> list[Problem]:
    """SOH is extracted across every SSIS workbook at once (rule R2 keeps the
    first file per snapshot date, ssis_soh.py), then filtered: per month under
    _soh_<month>/ssis_soh, and every snapshot under _soh_all/ssis_soh for the
    dimension rules. months=None (full rebuild) stages everything under
    ssis_soh directly."""
    from analytics.etl.extract.ssis_soh import parse_ssis_soh
    result = parse_ssis_soh(files=[f for f, fl in discover().items() if (fl.family or fl.hint) == SOH_FILE_FAMILY])
    for df, rel, sheet_name, _snapshot in result.dfs:
        if months is None:
            write_staging_table(df, "ssis_soh", rel, sheet_name, staging)
            continue
        write_staging_table(df, "ssis_soh", rel, sheet_name, staging / "_soh_all")
        period = str(df["_period"].iloc[0]) if len(df) else None
        if period in months:
            write_staging_table(df, "ssis_soh", rel, sheet_name, staging / f"_soh_{period}")
    return [Problem(Path(r.src_file).name, "layout_changed", r.reason) for r in result.file_rejects]


def read_staged(staging: Path, doc_type: str) -> pd.DataFrame:
    files = sorted((staging / doc_type).glob("*.parquet"))
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True) if files else pd.DataFrame()


def stage_sales_reference(staging: Path, input_files: list[Path]) -> frozenset:
    """April-2025's copy of the "(2)" sheet, staged beside a later 2025
    workbook's copy so dedup keeps April's and records the later one as a
    duplicate - what a whole-corpus load does. Nothing when April itself is in
    the input or the input has no such sheet."""
    staged = read_staged(staging, "sales_register")
    if staged.empty or FAKE_BOOKING_SHEET not in set(staged["_src_sheet"]):
        return frozenset()
    if any(file_month(f) == KEPT_COPY_MONTH for f in input_files):
        return frozenset()
    april = [f for f in family_files(FAMILIES[1]) if file_month(f) == KEPT_COPY_MONTH]
    if len(april) != 1:
        raise RuntimeError(f"expected one {KEPT_COPY_MONTH} sales workbook for the '{FAKE_BOOKING_SHEET}' reference, found {len(april)}")
    pairs = set()
    for df, outcome in process_file(april[0], "sales_register", layout=layout_of(april[0])).dfs:
        if outcome.src_sheet == FAKE_BOOKING_SHEET:
            write_staging_table(df, outcome.doc_type, outcome.src_file, outcome.src_sheet, staging)
            pairs.add((outcome.src_file, outcome.src_sheet))
    return frozenset(pairs)


def stage_price_list(staging: Path) -> Path:
    """The 2025 inventory workbooks' Sheet1 (the price list, fix 5), under
    _price_list/ so it never mixes with the slice's own inventory rows."""
    out = staging / "_price_list"
    inv = next(f for f in FAMILIES if f.key == "inventory_sign_off")
    for f in family_files(inv):
        if (file_month(f) or "").startswith("2025"):
            for df, outcome in process_file(f, "inventory_sign_off", layout=layout_of(f)).dfs:
                if outcome.src_sheet == rcl.DM_PRICE_LIST_SHEET:
                    write_staging_table(df, outcome.doc_type, outcome.src_file, outcome.src_sheet, out)
    return out


# --- manifest + sign-off ----------------------------------------------------------------------------------------

def frame_hash(df: pd.DataFrame) -> str:
    df = df[sorted(df.columns)].astype(str)
    return hashlib.sha256(pd.util.hash_pandas_object(df, index=False).values.tobytes()).hexdigest()


def build_manifest(run_key: str, staging: Path, slices: list[str], references: frozenset,
                   problems: list[Problem]) -> dict:
    """Every staged sheet the run read, with row count and content hash, in
    the {"staged": [...], "reject": [...]} shape transform_signoff reads."""
    staged = []
    for f in sorted(staging.rglob("*.parquet"), key=lambda p: p.relative_to(staging).as_posix()):
        df = pd.read_parquet(f)
        first = df.iloc[0] if len(df) else {}
        pair = (first.get("_src_file"), first.get("_src_sheet")) if len(df) else (None, None)
        staged.append({
            "src_file": pair[0], "src_sheet": pair[1], "doc_type": f.parent.name,
            "staged_as": f.relative_to(staging).as_posix(), "period": first.get("_period") if len(df) else None,
            "region": first.get("_region") if len(df) else None, "row_count": int(len(df)),
            "content_sha256": frame_hash(df), "checksum_status": "promoted",
            "reason": "reference only - read, not loaded" if pair in references else None,
            "header_row": int(first.get("_header_row")) if len(df) else None,
            "totals_check": _totals_check(first) if len(df) else None,
        })
    reject = [{"src_file": p.file, "src_sheet": None, "checksum_status": "blocked", "reason": f"{p.reason}: {p.detail}"}
              for p in problems]
    return {"run_key": run_key, "slices": sorted(slices), "staged": staged, "reject": reject, "quantity_issues": {}}


def _totals_check(first) -> str | None:
    """The extract's totals-row verdict for the reviewer: pass / mismatch /
    unverified, or allowlisted (a recorded source problem)."""
    status = first.get("_checksum_status")
    if status == "mismatch" and sv.checksum_allowed(REPO_ROOT / first["_src_file"], first["_src_sheet"]):
        return "allowlisted"
    return status


def unsigned_reason(transform_dir: Path) -> str | None:
    try:
        check_signoff_gate(transform_dir)
        return None
    except RuntimeError as e:
        msg = str(e)
        if "stale" in msg:
            return "the recorded sign-off is for a different manifest (files changed since approval)"
        if "no " in msg and "found" in msg:
            return "no sign-off recorded for this manifest"
        return "the recorded sign-off is not 'approved'"


# --- prepare ----------------------------------------------------------------------------------------------------

@dataclass
class Prepared:
    rows: pd.DataFrame
    records: list[dict]
    natural_key: list[str]
    dimension_fks: list = field(default_factory=list)
    transformed: pd.DataFrame | None = None


RMR_KEY = ["_src_file", "_src_sheet", "_row_ordinal", "invoice_date", "customer_name", "net_amount"]
RMR_NO_SLIP_REASON = ("RMR GS & BO line with no Return Slip #: the dedupe rule against a later sales-return file keys on the slip "
                      "(migration 0028), so the line is held rather than loaded; it also appears on the export's ONE PAGER")


def prepare_rmr(staged: pd.DataFrame, periods: list[str]) -> Prepared:
    """Fix 4, the same rows dm_fixes batch 4 wrote: the GS and BO sheets (the
    ONE PAGER is their union and is not loaded) of the listed periods. A line
    is a row with a parsable Invoice Date and a numeric Net Amount - the rest
    are each sheet's TOTAL, 'Prepared by' and signature rows, which batch 4
    did not record either. A line with no Return Slip # is quarantined."""
    empty = Prepared(pd.DataFrame(), [], RMR_KEY)
    if staged.empty:
        return empty
    raw = staged[staged["_period"].isin(periods) & staged["_sheet_role"].isin(rmr_roles())]
    if raw.empty:
        return empty
    mapped, _ = apply_column_map(raw, "rmr_gs_bo", DEFAULT_CONFIG_DIR)
    amount = pd.to_numeric(mapped["net_amount"], errors="coerce")
    date = pd.to_datetime(mapped["invoice_date"], errors="coerce")
    lines = mapped[amount.notna() & date.notna()].copy()
    lines["net_amount"], lines["invoice_date"] = amount[lines.index], date[lines.index].dt.date
    bad_type = int((lines["return_type"].astype(str).str.upper() != lines["_sheet_role"].str.upper()).sum())
    bad_month = int((lines["invoice_date"].map(lambda x: x.strftime("%Y-%m")) != lines["_period"]).sum())
    if bad_type or bad_month:
        raise RuntimeError(f"RMR lines: {bad_type} Return Type differs from its sheet, {bad_month} invoice month differs from the export month")
    slip, no_slip = lines[lines["return_slip_num"].notna()], lines[lines["return_slip_num"].isna()]
    rows = pd.DataFrame({
        "return_slip_num": slip["return_slip_num"].values, "invoice_num": None,
        "return_type": slip["return_type"].astype(str).str.upper().values, "return_date": None, "principal": "delmonte",
        "region": slip["_region"].values, "net_amount": slip["net_amount"].values, "bo_units": None,
        "_src_file": slip["_src_file"].values, "_src_sheet": slip["_src_sheet"].values, "_period": slip["_period"].values,
        "is_demo": False, "quantity_cases": None, "quantity_pieces": None, "source": "rmr",
        "_row_ordinal": slip["_row_ordinal"].astype(int).values, "invoice_date": slip["invoice_date"].values,
        "customer_name": slip["customer_name"].values,
    })
    records = [{
        "table_name": "salesreturn_fact", "rule": "rmr_line_without_return_slip", "reason": RMR_NO_SLIP_REASON,
        "_src_file": r["_src_file"], "_src_sheet": r["_src_sheet"], "_row_ordinal": int(r["_row_ordinal"]),
        "is_demo": False, "raw_values": rcl._json_safe_row(r), "slice_period": r["_period"], "slice_region": r["_region"],
    } for _, r in no_slip.iterrows()]
    print(f"  [salesreturn_fact/rmr] prepared {len(rows)} line(s), {len(records)} without a Return Slip # quarantined")
    return Prepared(rows, records, RMR_KEY)


def prepare_soh(soh_dir: Path, engine: Engine) -> Prepared:
    """Unilever SOH (transform_ssis_soh), the same exclusions the loader
    applied before: the per-snapshot totals row (null sku_code) and
    conflicting (sku_code, snapshot_date) groups."""
    from analytics.etl.transform_ssis_soh import transform_ssis_soh
    if not list((soh_dir / "ssis_soh").glob("*.parquet")):
        return Prepared(pd.DataFrame(), [], ["sku_code", "snapshot_date", "region"])
    res = transform_ssis_soh(staging_dir=soh_dir, real_sku_codes=None)
    df = rcl._project_to_table_columns(res.inventory_fact_df, "inventory_fact", engine, [])
    before = df
    df, _ = rcl._drop_conflicting_group_rows(df, "inventory_fact", ["sku_code", "snapshot_date"])
    records = rcl._quarantine_records(
        res.rejected_rows, "inventory_fact", "transform_ssis_soh",
        "null sku_code: the per-snapshot totals row in the sheet body, not a SKU",
    ) + rcl._quarantine_records(
        before.loc[before.index.difference(df.index)], "inventory_fact", "_drop_conflicting_group_rows",
        "shares (sku_code, snapshot_date) with a row that differs on a business column",
    )
    print(f"  [inventory_fact/ssis_soh] prepared {len(df)} row(s), {len(records)} excluded source row(s)")
    return Prepared(df, records, ["sku_code", "snapshot_date", "region"])


def prepare(fam: Family, staged: pd.DataFrame, engine: Engine | Connection, soh_dir: Path | None = None,
            references: frozenset = frozenset(), extra_known_keys: set | None = None,
            months: set[str] | None = None) -> Prepared:
    if fam.key == "ssis_soh":
        return prepare_soh(soh_dir, engine)
    if fam.key == "rmr_gs_bo":
        return prepare_rmr(staged, rmr_allowed_periods())
    item = ITEMS[(fam.fact, fam.principal)]
    if staged.empty:
        return Prepared(pd.DataFrame(), [], [], item.dimension_fks)
    p = rcl.prepare_fact(item, staged, engine, reference_pairs=references, extra_known_keys=extra_known_keys)
    records = p.quarantine
    if fam.key == "sales_return" and (months is None or any(
            file_month(REPO_ROOT / "data" / "raw" / n) == m for n in KNOWN_DUPLICATES for m in months)):
        records = records + rcl.known_duplicate_file_records()
    return Prepared(p.load_input, records, p.natural_key, item.dimension_fks, p.transformed)


def row_slices(fam: Family, df: pd.DataFrame) -> pd.DataFrame:
    """(month, site) of every prepared row."""
    if df.empty:
        return pd.DataFrame({"month": [], "site": []})
    if fam.key == "sales_register":
        ls = [lineage(f, s) for f, s in zip(df["_src_file"], df["_src_sheet"])]
        return pd.DataFrame({"month": [m for m, _ in ls], "site": [s for _, s in ls]}, index=df.index)
    if fam.key == "unilever_sku":
        return pd.DataFrame({"month": df["calendar_month"].astype(str), "site": "la_union"}, index=df.index)
    if fam.key == "ssis_soh":
        return pd.DataFrame({"month": df["_period"].astype(str), "site": None}, index=df.index)
    return pd.DataFrame({"month": df["_period"].astype(str), "site": df["region"]}, index=df.index)


def record_slice(fam: Family, rec: dict) -> tuple[str, str | None]:
    if fam.key == "sales_register":
        return lineage(rec["_src_file"] or "", rec["_src_sheet"] or "")
    month, site = rec.get("slice_period"), rec.get("slice_region")
    if not month or not MONTH_RE.match(str(month)):
        month = lineage(rec["_src_file"] or "", rec["_src_sheet"] or "")[0]
    if fam.key == "unilever_sku":
        site = "la_union"
    elif fam.key == "ssis_soh":
        site = None
    elif site not in SITES:
        site = lineage(rec["_src_file"] or "", rec["_src_sheet"] or "")[1]
    return month, site


# --- database side ----------------------------------------------------------------------------------------------

@dataclass
class RunContext:
    engine: Engine
    schema: str
    run_id: str
    run_by: str
    dry_run: bool
    allow_shrink: bool
    target_public: bool
    staging: Path
    soh_dir: Path | None = None
    price_list: dict | None = None
    events: list = field(default_factory=list)


def _scope(conn: Connection, schema: str, read_only: bool = False) -> None:
    if read_only:
        conn.execute(text("SET TRANSACTION READ ONLY"))
    # The target schema ONLY - no `public` fallback: a table missing from a scratch
    # schema must fail, never resolve to the live table of the same name.
    conn.execute(text("SET LOCAL search_path TO :schema").bindparams(schema=schema))


def owned(conn: Connection, sl: Slice) -> tuple[str, dict]:
    """SQL predicate for the REAL rows a slice owns in its fact table."""
    fam, params = sl.family, {"m": sl.month}
    if fam.key == "sales_register":
        pairs = conn.execute(text(
            "SELECT DISTINCT _src_file, _src_sheet FROM sales_fact WHERE NOT is_demo AND principal = 'delmonte'")).all()
        params["owned"] = [f"{f}{SEP}{s}" for f, s in pairs if _matches(*lineage(f, s), sl)]
        return ("NOT is_demo AND principal = 'delmonte' "
                "AND _src_file || chr(31) || _src_sheet = ANY(CAST(:owned AS text[]))"), params
    if fam.key == "unilever_sku":
        return "NOT is_demo AND calendar_month = :m", params
    if fam.key == "ssis_soh":
        return "NOT is_demo AND principal = 'unilever' AND _period = :m", params
    where = f"NOT is_demo AND principal = '{fam.principal}' AND _period = :m"
    if fam.table == "salesreturn_fact":
        where += " AND source = 'rmr'" if fam.source_value == "rmr" else " AND source IS NULL"
    if sl.site:
        where += " AND region = :site"
        params["site"] = sl.site
    return where, params


def synthetic_where(fam: Family) -> str:
    """DEC-29: a table-month's synthetic rows go when its real rows arrive -
    per table-month, not per branch (a synthetic Del Monte sales row carries no
    branch at all: its region is a town and its _src_file names no site)."""
    if fam.table == "unilever_sku_demand_fact":
        return "is_demo AND calendar_month = :m"
    return f"is_demo AND principal = '{fam.principal}' AND _period = :m"


def remove_derived(conn: Connection, principal: str, table: str, month: str) -> int:
    """DEC-31: real rows for a month replace that month's estimate (derived_receipt_fact for Unilever purchases).
    No-op for a table with no estimate, or a schema without migration 0038."""
    dt = DERIVED_FOR.get((principal, table))
    if dt is None or conn.execute(text("SELECT to_regclass(:t)"), {"t": dt}).scalar() is None:
        return 0
    return conn.execute(text(f"DELETE FROM {dt} WHERE principal = :p AND _period = :m"), {"p": principal, "m": month}).rowcount


def _quarantine_where(table: str, ordinals: list[int] | None) -> str:
    w = "table_name = :qt AND _src_file || chr(31) || _src_sheet = ANY(CAST(:qpairs AS text[]))"
    return w + (" AND _row_ordinal = ANY(CAST(:qords AS bigint[]))" if ordinals is not None else "")


def carry_conflict_groups(conn: Connection, table: str, natural_key: list[str], rows: pd.DataFrame,
                          own_pairs: set) -> tuple[pd.DataFrame, list[dict]]:
    """A key that another slice's row already holds in etl_quarantine as a
    conflicting group (real rows disagreeing, never resolved by insert order)
    is held here too - the whole-corpus load would have held both."""
    if rows.empty or not natural_key or any(k not in rows.columns for k in natural_key):
        return rows, []
    held = conn.execute(text(
        "SELECT raw_values, _src_file, _src_sheet FROM etl_quarantine "
        "WHERE table_name = :t AND rule = '_drop_conflicting_group_rows' AND NOT is_demo"), {"t": table}).all()
    keys = {tuple(str(rv.get(k)).strip() for k in natural_key) for rv, f, s in held
            if (f, s) not in own_pairs and all(rv.get(k) is not None for k in natural_key)}
    if not keys:
        return rows, []
    hit = rows[natural_key].astype(str).apply(lambda r: tuple(v.strip() for v in r), axis=1).isin(keys)
    if not hit.any():
        return rows, []
    recs = rcl._quarantine_records(
        rows[hit], table, "_drop_conflicting_group_rows",
        "shares its natural key with a row another slice already holds as a conflicting group; "
        "needs a human decision, never resolved by insert order")
    return rows[~hit], recs


def rmr_dedupe_decisions(rmr: pd.DataFrame, sr: pd.DataFrame) -> tuple[list[int], list[tuple[int, int]]]:
    """Migration 0028's rule, for when a proper sales-return file arrives for
    an RMR period: an RMR row matching a sales-return row on (principal,
    region, return_slip_num, return_type) is deleted when the amounts agree;
    when they differ, both go to etl_quarantine and neither is kept. Returns
    (rmr return_keys to delete, [(rmr return_key, sales-return return_key)]
    to quarantine). Pure - the SQL around it is rmr_dedupe()."""
    delete, mismatch = [], []
    if rmr.empty or sr.empty:
        return delete, mismatch
    key = ["principal", "region", "return_slip_num", "return_type"]
    norm = lambda d: d.assign(**{k: d[k].astype(str).str.strip().str.upper() for k in key})  # noqa: E731
    m = norm(rmr).merge(norm(sr), on=key, suffixes=("_rmr", "_sr"))
    for _, r in m.iterrows():
        a, b = r["net_amount_rmr"], r["net_amount_sr"]
        same = (pd.isna(a) and pd.isna(b)) or (pd.notna(a) and pd.notna(b) and round(float(a), 2) == round(float(b), 2))
        if same:
            delete.append(int(r["return_key_rmr"]))
        else:
            mismatch.append((int(r["return_key_rmr"]), int(r["return_key_sr"])))
    return sorted(set(delete)), mismatch


def rmr_dedupe(conn: Connection, month: str, run_id: str) -> dict:
    cols = "return_key, principal, region, return_slip_num, return_type, net_amount"
    rmr = pd.DataFrame(conn.execute(text(f"SELECT {cols} FROM salesreturn_fact WHERE source = 'rmr' AND NOT is_demo AND _period = :m"),
                                    {"m": month}).mappings().all())
    sr = pd.DataFrame(conn.execute(text(f"SELECT {cols} FROM salesreturn_fact WHERE source IS NULL AND NOT is_demo AND _period = :m"),
                                   {"m": month}).mappings().all())
    delete, mismatch = rmr_dedupe_decisions(rmr, sr)
    out = {"rmr_deleted": 0, "mismatch_pairs": len(mismatch), "sales_return_deleted": 0, "quarantined": 0}
    if delete:
        out["rmr_deleted"] = conn.execute(text("DELETE FROM salesreturn_fact WHERE return_key = ANY(CAST(:k AS bigint[]))"),
                                          {"k": delete}).rowcount
    if mismatch:
        keys = sorted({k for pair in mismatch for k in pair})
        out["quarantined"] = conn.execute(text("""
            INSERT INTO etl_quarantine (run_id, table_name, rule, reason, _src_file, _src_sheet, _row_ordinal, is_demo, raw_values)
            SELECT :run_id, 'salesreturn_fact', 'rmr_dedupe_amount_mismatch',
                   'RMR line and sales-return line share principal, region, Return Slip # and Return Type but differ on '
                   || 'net_amount (migration 0028 dedupe rule): both held for review, neither kept',
                   _src_file, _src_sheet, _row_ordinal, false, to_jsonb(s) - 'return_key'
            FROM salesreturn_fact s WHERE return_key = ANY(CAST(:k AS bigint[]))
        """), {"run_id": run_id, "k": keys}).rowcount
        n = conn.execute(text("DELETE FROM salesreturn_fact WHERE return_key = ANY(CAST(:k AS bigint[])) AND source IS NULL"),
                         {"k": keys}).rowcount
        out["sales_return_deleted"] = n
        out["rmr_deleted"] += conn.execute(text("DELETE FROM salesreturn_fact WHERE return_key = ANY(CAST(:k AS bigint[])) AND source = 'rmr'"),
                                           {"k": keys}).rowcount
    if any(out.values()):
        print(f"  [salesreturn_fact] migration 0028 RMR dedupe for {month}: {out}")
    return out


def would_shrink(before: int, after: int) -> bool:
    """The shrink guard: a slice holding real rows may not lose more than 5% of them."""
    return before > 0 and after < SHRINK_FLOOR * before


def coverage_status(real: int, synthetic: int, real_sites: set, expected: tuple, derived: int = 0) -> str:
    if real:
        return "partial" if expected and not set(expected) <= set(real_sites) else "real"
    if derived:
        return "derived"
    return "synthetic" if synthetic else "missing"


def month_range(start: str, end: str) -> list[str]:
    return [p.strftime("%Y-%m") for p in pd.period_range(start, end, freq="M")]


def coverage_rows(conn: Connection, principal: str, table: str, months: set[str] | None) -> list[dict]:
    """etl_coverage rows for one principal x table: real / synthetic / partial /
    missing per month. Branches of real rows by lineage for sales_fact, by the
    region column elsewhere (where it is the branch)."""
    expected = COVERAGE[(principal, table)]
    mcol = "calendar_month" if table == "unilever_sku_demand_fact" else "_period"
    pcond = "TRUE" if table == "unilever_sku_demand_fact" else "principal = :p"
    mfilter = "" if months is None else f" AND {mcol} = ANY(CAST(:ms AS text[]))"
    params = {"p": principal, "ms": sorted(months or [])}
    counts: dict[str, list[int]] = {}
    for m, demo, n in conn.execute(text(f"SELECT {mcol}, is_demo, count(*) FROM {table} WHERE {pcond}{mfilter} GROUP BY 1, 2"), params):
        counts.setdefault(m, [0, 0])[1 if demo else 0] += n
    derived: dict[str, int] = {}
    if (principal, table) in DERIVED_FOR:
        dt = DERIVED_FOR[(principal, table)]
        derived = dict(conn.execute(text(f"SELECT _period, count(*) FROM {dt} WHERE principal = :p{mfilter.replace(mcol, '_period')} "
                                         f"GROUP BY 1"), params).all())
    sites: dict[str, set] = {}
    if table in NO_SITE_TABLES:
        pass
    elif table == "sales_fact":
        q = f"SELECT {mcol}, _src_file, _src_sheet FROM sales_fact WHERE NOT is_demo AND {pcond}{mfilter} GROUP BY 1, 2, 3"
        for m, f, s in conn.execute(text(q), params):
            sites.setdefault(m, set()).add(lineage(f, s)[1])
    else:
        q = f"SELECT {mcol}, region FROM {table} WHERE NOT is_demo AND {pcond}{mfilter} GROUP BY 1, 2"
        for m, r in conn.execute(text(q), params):
            if r is not None:
                sites.setdefault(m, set()).add(r)
    month_list = sorted(months) if months is not None else month_range(COVERAGE_START, datetime.now(timezone.utc).strftime("%Y-%m"))
    out = []
    for m in month_list:
        if not MONTH_RE.match(str(m)):
            continue
        real, demo = counts.get(m, [0, 0])
        real_sites = sorted(sites.get(m, set()))
        status = coverage_status(real, demo, set(real_sites), expected, derived.get(m, 0))
        out.append({"principal": principal, "table_name": table, "month": m, "status": status, "real_rows": real,
                    "synthetic_rows": demo, "derived_rows": derived.get(m, 0), "real_sites": real_sites,
                    "expected_sites": list(expected)})
    return out


def upsert_coverage(conn: Connection, rows: list[dict], event_key: int | None, only_changed: bool = False) -> int:
    """One statement for any number of months (a row-by-row executemany costs one
    pooler round trip per month). only_changed: leave a row whose counts and
    status are already the same untouched (the fill step's no-op run writes nothing).
    Returns the number of rows written."""
    if not rows:
        return 0
    col = lambda k: [r[k] for r in rows]  # noqa: E731
    changed_only = ("WHERE (etl_coverage.status, etl_coverage.real_rows, etl_coverage.synthetic_rows, etl_coverage.derived_rows, "
                    "etl_coverage.real_sites, etl_coverage.expected_sites) IS DISTINCT FROM (EXCLUDED.status, EXCLUDED.real_rows, "
                    "EXCLUDED.synthetic_rows, EXCLUDED.derived_rows, EXCLUDED.real_sites, EXCLUDED.expected_sites)") if only_changed else ""
    return conn.execute(text(f"""
        INSERT INTO etl_coverage (principal, table_name, month, status, real_rows, synthetic_rows, derived_rows, real_sites,
                                  expected_sites, last_load_event_key, refreshed_at)
        SELECT v.principal, v.table_name, v.month, v.status, v.real_rows, v.synthetic_rows, v.derived_rows,
               string_to_array(v.real_sites, chr(31)), string_to_array(v.expected_sites, chr(31)), CAST(:event_key AS bigint), now()
        FROM unnest(CAST(:principal AS text[]), CAST(:table_name AS text[]), CAST(:month AS text[]), CAST(:status AS text[]),
                    CAST(:real_rows AS int[]), CAST(:synthetic_rows AS int[]), CAST(:derived_rows AS int[]), CAST(:real_sites AS text[]),
                    CAST(:expected_sites AS text[]))
             AS v(principal, table_name, month, status, real_rows, synthetic_rows, derived_rows, real_sites, expected_sites)
        ON CONFLICT (principal, table_name, month) DO UPDATE SET
            status = EXCLUDED.status, real_rows = EXCLUDED.real_rows, synthetic_rows = EXCLUDED.synthetic_rows,
            derived_rows = EXCLUDED.derived_rows, real_sites = EXCLUDED.real_sites, expected_sites = EXCLUDED.expected_sites,
            last_load_event_key = COALESCE(EXCLUDED.last_load_event_key, etl_coverage.last_load_event_key),
            refreshed_at = now()
        {changed_only}
    """), {"principal": col("principal"), "table_name": col("table_name"), "month": col("month"), "status": col("status"),
           "real_rows": col("real_rows"), "synthetic_rows": col("synthetic_rows"),
           "derived_rows": [r.get("derived_rows", 0) for r in rows],
           "real_sites": [SEP.join(r["real_sites"]) for r in rows], "expected_sites": [SEP.join(r["expected_sites"]) for r in rows],
           "event_key": event_key}).rowcount


def refresh_all_coverage(conn: Connection) -> dict[str, int]:
    tally: dict[str, int] = {}
    for principal, table in COVERAGE:
        rows = coverage_rows(conn, principal, table, None)
        upsert_coverage(conn, rows, None)
        for r in rows:
            tally[r["status"]] = tally.get(r["status"], 0) + 1
    return tally


def new_event(ctx: RunContext, sl: Slice, files: list[str], started: datetime) -> dict:
    return {
        "run_id": ctx.run_id, "slice": sl.key, "principal": sl.family.principal, "table_name": sl.family.table,
        "month": sl.month, "site": sl.site, "source": sl.family.key, "status": "loaded", "reason": None, "detail": None,
        "files": sorted({Path(f).name for f in files}), "real_rows_before": 0, "real_rows_removed": 0,
        "real_rows_added": 0, "real_rows_after": 0, "synthetic_rows_removed": 0, "quarantine_rows_removed": 0,
        "quarantine_rows_added": 0, "allow_shrink": ctx.allow_shrink, "dry_run": ctx.dry_run, "run_by": ctx.run_by,
        "started_at": started,
    }


def insert_event(conn: Connection, ev: dict) -> int:
    return conn.execute(text("""
        INSERT INTO etl_load_event (run_id, slice, principal, table_name, month, site, source, status, reason, detail,
            files, real_rows_before, real_rows_removed, real_rows_added, real_rows_after, synthetic_rows_removed,
            quarantine_rows_removed, quarantine_rows_added, allow_shrink, dry_run, run_by, started_at)
        VALUES (:run_id, :slice, :principal, :table_name, :month, :site, :source, :status, :reason, :detail,
            CAST(:files AS text[]), :real_rows_before, :real_rows_removed, :real_rows_added, :real_rows_after,
            :synthetic_rows_removed, :quarantine_rows_removed, :quarantine_rows_added, :allow_shrink, :dry_run,
            :run_by, :started_at)
        RETURNING load_event_key
    """), ev).scalar()


def write_audit(conn: Connection, ev: dict, shrink_used: bool) -> None:
    if ev["dry_run"]:
        return
    details = (f"{ev['slice']} status={ev['status']}" + (f" reason={ev['reason']}" if ev["reason"] else "")
               + f" real -{ev['real_rows_removed']}/+{ev['real_rows_added']} synthetic -{ev['synthetic_rows_removed']}"
               + f" quarantine -{ev['quarantine_rows_removed']}/+{ev['quarantine_rows_added']} run_id={ev['run_id']}")
    rows = [{"a": "data_load", "d": details}]
    if shrink_used:
        rows.append({"a": "data_load_allow_shrink", "d": f"--allow-shrink used: {details}"})
    conn.execute(text("INSERT INTO audit_log (user_email, user_name, role, action, details) "
                      "VALUES (:e, :n, 'etl', :a, :d)"), [{"e": AUDIT_ACTOR, "n": ev["run_by"], **r} for r in rows])


def record_standalone(ctx: RunContext, ev: dict) -> None:
    """A refused (or dry-run) slice's event, in its own transaction - the
    slice's own transaction was rolled back, or never wrote."""
    try:
        with ctx.engine.begin() as conn:
            _scope(conn, ctx.schema)
            if conn.execute(text("SELECT to_regclass('etl_load_event')")).scalar() is None:
                print(f"  (no etl_load_event table in '{ctx.schema}' - migration 0033 not applied; event not recorded)")
                return
            ev["load_event_key"] = insert_event(conn, ev)
            write_audit(conn, ev, shrink_used=False)
    finally:
        ctx.events.append(ev)


def record_file_event(ctx: RunContext, path: Path, fl: lay.FileLayout) -> dict:
    """A file the loader cannot place in a slice - unrecognised content, a
    layout the family's signature refuses, or no month - refused on its own
    (slice 'file:<name>'; principal / table / month only where the file says
    them). Never a silent skip."""
    fam = next((f for f in FAMILIES if f.key == _file_family(fl)), None)
    month = fl.month or infer_period(path)
    ev = {
        "run_id": ctx.run_id, "slice": f"file:{path.name}", "principal": fam.principal if fam else None,
        "table_name": fam.table if fam else None, "month": month if fam else None, "site": None,
        "source": fl.family or fl.hint, "status": "refused", "reason": fl.reason, "detail": (fl.problem or "")[:500],
        "files": [path.name], "real_rows_before": 0, "real_rows_removed": 0, "real_rows_added": 0,
        "real_rows_after": 0, "synthetic_rows_removed": 0, "quarantine_rows_removed": 0, "quarantine_rows_added": 0,
        "allow_shrink": ctx.allow_shrink, "dry_run": ctx.dry_run, "run_by": ctx.run_by,
        "started_at": datetime.now(timezone.utc),
    }
    print(f"\n--- file {path.name}: refused ({fl.reason}) {fl.problem}")
    record_standalone(ctx, ev)
    return ev


def _apply_warnings(ev: dict, warns: list[tuple[str, str]]) -> None:
    """Warnings never block a load; they make it visible. A slice already
    partial / shrink_allowed keeps that reason and gains the text."""
    if not warns:
        return
    said = "; ".join(d for _, d in warns)
    if ev["status"] == "loaded":
        ev.update(status="warning", reason=warns[0][0])
    ev["detail"] = (((ev["detail"] + " | ") if ev["detail"] else "") + said)[:500]


def validate(conn: Connection, sl: Slice, rows: pd.DataFrame) -> list[sv.Finding]:
    """The pre-delete checks (analytics/etl/slice_validation.py, bands from
    config/validation_bands.yaml), history read inside the slice's own
    transaction."""
    fam = sl.family
    if rows.empty or fam.key not in sv.MEASURES:
        return []
    hist = sv.history(conn, fam.key, lineage=lineage)
    return sv.validate_rows(fam.key, rows, row_slices(fam, rows), hist,
                            sku_lookup=lambda m: sv.earlier_skus(conn, fam.key, m))


def _bind(sql: str, params: dict) -> dict:
    """Only the parameters a statement names (text() gets exactly its own binds)."""
    return {k: v for k, v in params.items() if re.search(":" + re.escape(k) + r"(?![A-Za-z0-9_])", sql)}


def _run(conn: Connection, sql: str, params: dict):
    return conn.execute(text(sql), _bind(sql, params))


def _count(conn: Connection, table: str, where: str, params: dict) -> int:
    return _run(conn, f"SELECT count(*) FROM {table} WHERE {where}", params).scalar()


def write_slice(ctx: RunContext, sl: Slice, prep_rows: pd.DataFrame, records: list[dict], prep: Prepared,
                files: list[str], input_pairs: set, ordinals: list[int] | None,
                dims: Callable[[Connection], None] | None, refusal: Refused | None = None,
                warnings: list[tuple[str, str]] | None = None) -> dict:
    """One slice, one transaction. Returns its etl_load_event row. Everything
    that can refuse the slice runs before its first DELETE: the shrink guard,
    then the validation bands. `warnings` ((reason, detail), e.g. a header the
    column map does not know) make the event a warning, never a refusal."""
    fam, started = sl.family, datetime.now(timezone.utc)
    ev = new_event(ctx, sl, files, started)
    warns = list(warnings or [])
    if refusal is not None:
        ev.update(status="refused", reason=refusal.reason, detail=refusal.detail[:500])
        record_standalone(ctx, ev)
        return ev
    rows, shrink_used = prep_rows, False
    record_pairs = {(r["_src_file"], r["_src_sheet"]) for r in records}
    qpairs = sorted(f"{f}{SEP}{s}" for f, s in (input_pairs | record_pairs) if f is not None and s is not None)
    try:
        # A dry run plans inside one READ ONLY transaction that is never
        # committed (connect() rolls back on exit); a real run commits or rolls
        # back as one unit.
        with (ctx.engine.connect() if ctx.dry_run else ctx.engine.begin()) as conn:
            _scope(conn, ctx.schema, read_only=ctx.dry_run)
            where, params = owned(conn, sl)
            owned_pairs = set(tuple(p.split(SEP)) for p in params.get("owned", []))
            if owned_pairs:
                qpairs = sorted(set(qpairs) | {f"{f}{SEP}{s}" for f, s in owned_pairs})
            qparams = {"qt": fam.table, "qpairs": qpairs, "qords": ordinals}
            before = _count(conn, fam.table, where, params)
            ev["real_rows_before"] = before
            if would_shrink(before, len(rows)):
                if not ctx.allow_shrink:
                    raise Refused("shrink_guard", f"real rows would drop from {before} to {len(rows)} "
                                                  f"(more than {100 - SHRINK_FLOOR * 100:.0f}%); pass --allow-shrink to load anyway")
                shrink_used = True
            findings = validate(conn, sl, rows)
            refuse = [x for x in findings if x.severity == "refuse"]
            if refuse:
                raise Refused("validation_failed", "; ".join(f"{x.check}: {x.detail}" for x in refuse))
            warns += [("validation_warning", f"{x.check}: {x.detail}") for x in findings]
            if ctx.dry_run:
                ev.update(real_rows_removed=before, real_rows_added=len(rows), real_rows_after=len(rows),
                          synthetic_rows_removed=_count(conn, fam.table, synthetic_where(fam), params) if len(rows) else 0,
                          quarantine_rows_removed=_count(conn, "etl_quarantine", _quarantine_where(fam.table, ordinals), qparams),
                          quarantine_rows_added=len(records), detail="dry run: nothing written")
                if shrink_used:
                    ev.update(status="warning", reason="shrink_allowed")
                _apply_warnings(ev, warns)
                record_standalone(ctx, ev)
                return ev

            dims_before = _dimension_fingerprints(conn)
            t, qw = fam.table, _quarantine_where(fam.table, ordinals)
            deleted = _run(conn, f"DELETE FROM {t} WHERE {where} RETURNING {fam.month_col}, to_jsonb({t}) - '{PK[t]}'",
                           params).all()
            gone = [m for m, _ in deleted]
            ev["real_rows_removed"] = len(gone)
            if len(rows):
                ev["synthetic_rows_removed"] = _run(conn, f"DELETE FROM {t} WHERE {synthetic_where(fam)}", params).rowcount
                ev["synthetic_rows_removed"] += remove_derived(conn, fam.principal, fam.table, sl.month)
            q_deleted = _run(conn, f"DELETE FROM etl_quarantine WHERE {qw} RETURNING to_jsonb(etl_quarantine) {QUARANTINE_VOLATILE}",
                             qparams).scalars().all()
            ev["quarantine_rows_removed"] = len(q_deleted)

            rows, carried = carry_conflict_groups(conn, fam.table, prep.natural_key, rows, input_pairs | owned_pairs)
            records = records + carried
            if len(rows):
                load_to_supabase(rows, fam.table, conn, prep.natural_key, dimension_fks=prep.dimension_fks,
                                 on_conflict_update=False)
            ev["real_rows_added"] = len(rows)
            ev["quarantine_rows_added"] = rcl.write_quarantine(conn, ctx.run_id, records, False)
            if dims is not None:
                dims(conn)
            dedupe = {"sales_return_deleted": 0, "quarantined": 0}
            if fam.key == "sales_return" and sl.month in rmr_allowed_periods() and len(rows):
                dedupe = rmr_dedupe(conn, sl.month, ctx.run_id)

            # Ledger check: the table holds exactly what this event will say.
            where2, params2 = owned(conn, sl)
            after = _count(conn, fam.table, where2, params2)
            ev["real_rows_after"] = after
            expected_after = before - ev["real_rows_removed"] + ev["real_rows_added"] - dedupe["sales_return_deleted"]
            q_after = _count(conn, "etl_quarantine", _quarantine_where(fam.table, ordinals), qparams)
            # The 0028 dedupe may add held rows under this slice's sheets (the
            # sales-return side of a mismatch); its RMR side sits under RMR sheets.
            expected_q = ev["quarantine_rows_added"] + dedupe["quarantined"]
            if after != expected_after:
                raise Refused("row_balance", f"real rows after {after} != before {before} - removed "
                                             f"{ev['real_rows_removed']} + added {ev['real_rows_added']}")
            if q_after < ev["quarantine_rows_added"] or q_after > expected_q:
                raise Refused("row_balance", f"quarantine rows for the slice's sheets {q_after} != added {ev['quarantine_rows_added']}")

            # Idempotence: the same file loaded twice commits nothing the second time.
            if (ev["synthetic_rows_removed"] == 0
                    and _multiset(j for _, j in deleted) == _multiset(
                        _run(conn, f"SELECT to_jsonb({t}) - '{PK[t]}' FROM {t} WHERE {where2}", params2).scalars().all())
                    and _multiset(q_deleted) == _multiset(
                        _run(conn, f"SELECT to_jsonb(etl_quarantine) {QUARANTINE_VOLATILE} FROM etl_quarantine WHERE {qw}",
                             qparams).scalars().all())
                    and _dimension_fingerprints(conn) == dims_before):
                raise Unchanged()

            months = {sl.month} | {str(m) for m in gone if m} | (
                {str(m) for m in rows[fam.month_col].dropna()} if len(rows) and fam.month_col in rows.columns else set())
            cov = coverage_rows(conn, fam.principal, fam.table, months)
            mine = next((r for r in cov if r["month"] == sl.month), None)
            if mine and mine["status"] == "partial":
                missing = sorted(set(mine["expected_sites"]) - set(mine["real_sites"]))
                ev.update(status="partial", reason="partial_month", detail=f"no real rows for branch(es): {', '.join(missing)}")
            elif shrink_used:
                ev.update(status="warning", reason="shrink_allowed", detail=f"--allow-shrink: real rows {before} -> {after}")
            _apply_warnings(ev, warns)
            ev["load_event_key"] = insert_event(conn, ev)
            upsert_coverage(conn, cov, ev["load_event_key"])
            write_audit(conn, ev, shrink_used)
        ctx.events.append(ev)
        return ev
    except Unchanged:
        ev.update(status="loaded", reason=None, detail="unchanged: the files' rows equal the slice's rows; nothing written",
                  real_rows_removed=0, real_rows_added=0, real_rows_after=ev["real_rows_before"],
                  synthetic_rows_removed=0, quarantine_rows_removed=0, quarantine_rows_added=0)
        _apply_warnings(ev, warns)
    except Refused as r:
        ev.update(status="refused", reason=r.reason, detail=r.detail[:500], real_rows_removed=0, real_rows_added=0,
                  real_rows_after=ev["real_rows_before"], synthetic_rows_removed=0, quarantine_rows_removed=0,
                  quarantine_rows_added=0)
    except DBAPIError as e:
        code = getattr(e.orig, "pgcode", None)
        constraint = getattr(getattr(e.orig, "diag", None), "constraint_name", None)
        reason = "key_conflict_other_slice" if code == "23505" else "error"
        ev.update(status="refused", reason=reason, real_rows_removed=0, real_rows_added=0,
                  real_rows_after=ev["real_rows_before"], synthetic_rows_removed=0, quarantine_rows_removed=0,
                  quarantine_rows_added=0,
                  detail=(f"a key already held by another slice (constraint {constraint})" if code == "23505"
                          else f"{type(e.orig).__name__}: {str(e.orig).splitlines()[0][:300]}"))
    except Exception as e:  # noqa: BLE001 - recorded as a refusal, then re-raised below
        ev.update(status="refused", reason="error", detail=f"{type(e).__name__}: {str(e).splitlines()[0][:300] if str(e) else ''}",
                  real_rows_removed=0, real_rows_added=0, real_rows_after=ev["real_rows_before"],
                  synthetic_rows_removed=0, quarantine_rows_removed=0, quarantine_rows_added=0)
        record_standalone(ctx, ev)
        raise
    record_standalone(ctx, ev)
    return ev


# --- dimension rules per family ---------------------------------------------------------------------------------

def dims_for(ctx: RunContext, fam: Family, prep: Prepared) -> Callable[[Connection | Engine], None] | None:
    s = ctx.schema
    if fam.key == "unilever_sku":
        def run(bind):
            rcl.resolve_unilever_demand_product_metadata(bind, s, False, staging_dir=ctx.staging)
            rcl.run_category_brand_backfill(bind, s, False, staging_dir=ctx.soh_dir or ctx.staging)
        return run
    if fam.key == "ssis_soh":
        def run(bind):
            rcl.resolve_unilever_inventory_product_key(bind, s, False, staging_dir=ctx.soh_dir or ctx.staging)
            rcl.run_category_brand_backfill(bind, s, False, staging_dir=ctx.soh_dir or ctx.staging)
        return run
    if fam.key == "inventory_sign_off":
        def run(bind):
            rcl.resolve_delmonte_sku_dimension(bind, s, False, transformed=prep.transformed)
            rcl.resolve_delmonte_inventory_product_key(bind, s, False)
            rcl.apply_dm_pack_size_rule(bind, s, False, ctx.price_list or {})
            rcl.apply_dm_brand_rule(bind, s, False)
        return run
    if fam.key == "sell_out":
        return lambda bind: rcl.tag_sellout_source_defect_categories(bind, s, False)
    return None


# --- orchestration ----------------------------------------------------------------------------------------------

def _run_key(slices: list[Slice], files: list[Path], all_slices: bool) -> str:
    h = hashlib.sha1(json.dumps([sorted(s.key for s in slices), sorted(str(f) for f in files), all_slices]).encode()).hexdigest()[:8]
    if all_slices:
        return f"all_{h}"
    base = "__".join(re.sub(r"[^A-Za-z0-9-]+", "_", s.key.replace("*", "all")) for s in sorted(slices, key=lambda s: s.key))
    return f"{base[:80]}_{h}"


def _sign_hint(transform_dir: Path) -> str:
    rel = transform_dir.relative_to(REPO_ROOT).as_posix()
    return f'python -m analytics.etl.transform_signoff --transform-dir {rel} --decision approved --by "<name>"'


def _seed_date_dimension(ctx: RunContext) -> None:
    with ctx.engine.connect() as conn:
        _scope(conn, ctx.schema, read_only=True)
        n = conn.execute(text("SELECT count(*) FROM date_dimension")).scalar()
    if n == 0 and not ctx.dry_run:
        from analytics.db.seed_date_dim import upsert_date_dimension
        _, validation = upsert_date_dimension(rcl._scratch_engine(ctx.engine, ctx.schema, allow_public=ctx.target_public))
        print(f"[date_dimension] seeded {validation.row_count} calendar days")


def _stage_and_sign(ctx: RunContext, slices: list[Slice], files_by_family: dict[str, list[Path]],
                    soh_months: set[str] | None, all_slices: bool) -> tuple[str | None, list[Problem], frozenset]:
    """Extract every input file, add references, write the manifest. Returns
    (why unsigned or None, layout problems, reference pairs)."""
    shutil.rmtree(ctx.staging, ignore_errors=True)
    ctx.staging.mkdir(parents=True)
    done: set[Path] = set()
    problems: list[Problem] = []
    for key, files in files_by_family.items():
        problems += extract_files(files, key, ctx.staging, done)
    references = frozenset()
    if "sales_register" in files_by_family and not all_slices:
        references = stage_sales_reference(ctx.staging, files_by_family["sales_register"])
    if any(s.family.key == "ssis_soh" for s in slices) or (all_slices and soh_months is None):
        problems += extract_soh(ctx.staging, soh_months)
        ctx.soh_dir = ctx.staging if soh_months is None else ctx.staging / "_soh_all"
    if any(s.family.key == "inventory_sign_off" for s in slices) or all_slices:
        price_dir = ctx.staging if all_slices else stage_price_list(ctx.staging)
        ctx.price_list = rcl.load_dm_price_list(price_dir)
    run_key = ctx.staging.name
    manifest = build_manifest(run_key, ctx.staging, [s.key for s in slices], references, problems)
    transform_dir = SLICE_TRANSFORM / run_key
    transform_dir.mkdir(parents=True, exist_ok=True)
    (transform_dir / "_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True, default=str), encoding="utf-8")
    fp = compute_manifest_fingerprint(json.loads(json.dumps(manifest, default=str)))
    print(f"\n[manifest] run key {run_key}: {len(manifest['staged'])} staged sheet(s), fingerprint {fp}")
    unsigned = unsigned_reason(transform_dir)
    if unsigned:
        print(f"[sign-off] NOT SIGNED - {unsigned}. After reviewing transform/slices/{run_key}/_manifest.json:\n"
              f"    {_sign_hint(transform_dir)}")
    else:
        print("[sign-off] approved for this exact manifest")
    return unsigned, problems, references


def _summary(ctx: RunContext) -> int:
    print("\n=== slice summary ===")
    for ev in ctx.events:
        print(f"  {ev['slice']:<60} {ev['status']:<8} {ev['reason'] or '':<24} "
              f"real {ev['real_rows_before']}->{ev['real_rows_after']} (-{ev['real_rows_removed']}/+{ev['real_rows_added']}) "
              f"synthetic -{ev['synthetic_rows_removed']} quarantine -{ev['quarantine_rows_removed']}/+{ev['quarantine_rows_added']}")
    refused = [ev for ev in ctx.events if ev["status"] == "refused"]
    print(f"\n{len(ctx.events)} slice(s), {len(refused)} refused. run_id={ctx.run_id}"
          + ("  (DRY RUN - only etl_load_event rows written)" if ctx.dry_run else ""))
    return 1 if refused else 0


def run(engine: Engine, args) -> int:
    run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    ctx = RunContext(engine=engine, schema=args.schema, run_id=run_id, run_by=getpass.getuser(), dry_run=args.dry_run,
                     allow_shrink=args.allow_shrink, target_public=args.target_public, staging=SLICE_STAGING)
    if args.refresh_coverage:
        with engine.begin() as conn:
            _scope(conn, ctx.schema)
            tally = refresh_all_coverage(conn)
        print(f"[etl_coverage] refreshed: {tally}")
        return 0
    if args.target_public and not args.dry_run:
        rcl._preflight_dimension_identity_check(engine)
    overrides = [Path(f).resolve() for f in args.file]
    for f in overrides:
        if not f.is_file() or REPO_ROOT not in f.parents:
            raise SystemExit(f"--file {f.name}: must be an existing file under the repository")
    code = run_full(ctx, overrides) if args.all_slices else run_incremental(ctx, [parse_spec(s) for s in args.slice], overrides)
    # DEC-31: the fill step re-runs after every load - after a refused slice too (it fills only cells with no
    # real rows, and removes fills from cells that have them). Never on a dry run.
    if not ctx.dry_run and not getattr(args, "no_fill", False):
        from scripts import fill_missing
        fill_missing.run_step(engine, ctx.schema, run_by=ctx.run_by, trigger=f"load_slices run_id={run_id}",
                              allow_public=ctx.target_public)
    return code


def run_incremental(ctx: RunContext, slices: list[Slice], overrides: list[Path]) -> int:
    slices = sorted(set(slices), key=lambda s: (FAMILY_ORDER[s.family.key], s.month, s.site or ""))
    ctx.staging = SLICE_STAGING / _run_key(slices, overrides, False)
    refusals: dict[Slice, Refused] = {}
    files_by_slice: dict[Slice, list[Path]] = {}
    files_by_family: dict[str, list[Path]] = {}
    # --file: identified by content like any other file. One that cannot be
    # identified refuses the whole run - loading the on-disk file in its place
    # would load something other than what was asked for.
    given = {f: layout_of(f) for f in overrides}
    bad_given = [(f, fl) for f, fl in given.items() if not fl.ok]
    attributed: set[Path] = set()
    for sl in slices:
        fam = sl.family
        if bad_given:
            f, fl = bad_given[0]
            refusals[sl] = Refused(fl.reason, f"--file {f.name}: {fl.problem} - refusing rather than loading another "
                                              f"file in its place")
            continue
        if fam.key == "rmr_gs_bo" and sl.month not in rmr_allowed_periods():
            refusals[sl] = Refused("period_not_allowed", f"RMR lines load only for {rmr_allowed_periods()} "
                                                         f"(config/source_of_truth.yaml sales_return.rmr_fallback)")
            continue
        mine = [f for f, fl in given.items() if fl.family == fam.key]
        bad = [] if mine else bad_files_for(fam, sl.month)
        attributed |= {f for f, _ in bad}
        if bad:
            f, fl = bad[0]
            refusals[sl] = Refused(fl.reason, "; ".join(f"{g.name}: {gl.problem}" for g, gl in bad)[:500])
            continue
        if fam.key == "ssis_soh":
            # SOH is extracted across every SSIS workbook at once; these are the
            # month's workbooks, for the event and for problem matching.
            files_by_slice[sl] = [f for f, fl in discover().items()
                                  if (fl.family or fl.hint) == SOH_FILE_FAMILY and (fl.month or infer_period(f)) == sl.month]
            continue
        chosen = slice_files(mine or family_files(fam), fam, sl.month)
        if not chosen:
            refusals[sl] = Refused("missing_file", f"no {fam.key} file for {sl.month}"
                                                   + (" among the --file inputs" if mine else " under data/raw"))
            continue
        files_by_slice[sl] = chosen
        files_by_family.setdefault(fam.key, [])
        files_by_family[fam.key] += [f for f in chosen if f not in files_by_family[fam.key]]
    for f, fl in list(given.items()) + [(f, fl) for f, fl in discover().items() if f not in given]:
        if not fl.ok and f not in attributed:
            record_file_event(ctx, f, fl)

    soh_months = {s.month for s in slices if s.family.key == "ssis_soh"}
    unsigned, problems, references = _stage_and_sign(ctx, slices, files_by_family, soh_months, False)
    _seed_date_dimension(ctx)

    for sl in slices:
        fam = sl.family
        files = files_by_slice.get(sl, [])
        refusal = refusals.get(sl)
        if refusal is None and unsigned and not ctx.dry_run:
            refusal = Refused("fingerprint_unsigned", unsigned)
        names = {f.name for f in files}
        mine = sorted((p for p in problems if p.file in names), key=lambda p: p.reason != "layout_changed")
        if refusal is None and mine:
            refusal = Refused(mine[0].reason, "; ".join(f"{p.file}: {p.detail}" for p in mine)[:500])
        # headers no alias or ignored-list knows: loaded, and said so
        warns = [("unmapped_column", f"{f.name}: header(s) the column map does not know, not loaded: "
                                     f"{', '.join(layout_of(f).unmapped)}") for f in files if layout_of(f).unmapped]
        print(f"\n--- slice {sl.key} ---")
        if refusal is not None:
            write_slice(ctx, sl, pd.DataFrame(), [], Prepared(pd.DataFrame(), [], []), [str(f) for f in files],
                        set(), None, None, refusal=refusal)
            continue

        soh_dir = ctx.staging / f"_soh_{sl.month}" if fam.key == "ssis_soh" else None
        staged = pd.DataFrame() if fam.key == "ssis_soh" else read_staged(ctx.staging, fam.key)
        ordinals = None
        if not staged.empty:
            rel = {f.relative_to(REPO_ROOT).as_posix() for f in files}
            ref = pd.Series([(f, s) in references for f, s in zip(staged["_src_file"], staged["_src_sheet"])], index=staged.index)
            keep = staged["_src_file"].isin(rel)
            if fam.key == "unilever_sku":
                keep &= staged["_period"] == sl.month
            if sl.site:
                keep &= staged["_region"] == sl.site
            staged = staged[keep | ref]
            if fam.key == "unilever_sku":
                ordinals = sorted(int(o) for o in staged["_row_ordinal"])
        input_pairs = set()
        if not staged.empty:
            input_pairs = {(f, s) for f, s in zip(staged["_src_file"], staged["_src_sheet"])} - set(references)
        elif fam.key == "ssis_soh":
            soh = read_staged(soh_dir, "ssis_soh")
            input_pairs = {(f, s) for f, s in zip(soh["_src_file"], soh["_src_sheet"])} if not soh.empty else set()

        extra = None
        if fam.key == "sales_register":
            with ctx.engine.connect() as conn:
                _scope(conn, ctx.schema, read_only=True)
                _, params = owned(conn, sl)
                own = set(params["owned"])
                rule_key = rcl.load_source_of_truth("sales", "delmonte").natural_key
                extra = {tuple(str(v).strip() for v in r[:-2]) for r in conn.execute(text(
                    f"SELECT {', '.join(rule_key)}, _src_file, _src_sheet FROM sales_fact WHERE NOT is_demo")).all()
                    if f"{r[-2]}{SEP}{r[-1]}" not in own}
        try:
            prep = prepare(fam, staged, ctx.engine, soh_dir=soh_dir, references=references, extra_known_keys=extra,
                           months={sl.month})
        except Exception as e:  # noqa: BLE001 - a prepare failure refuses this slice only
            write_slice(ctx, sl, pd.DataFrame(), [], Prepared(pd.DataFrame(), [], []), [str(f) for f in files], set(), None,
                        None, refusal=Refused("error", f"prepare failed: {type(e).__name__}: {str(e).splitlines()[0][:300] if str(e) else ''}"))
            continue
        # The known-duplicate file's records cover both branches of its month;
        # a branch slice keeps its own.
        prep.records = [r for r in prep.records if not (r["rule"].startswith("extract_known_duplicate_file")
                                                        and not _matches(*record_slice(fam, r), sl))]
        attr = row_slices(fam, prep.rows)
        stray = int((~attr.apply(lambda r: _matches(r["month"], r["site"], sl), axis=1)).sum()) if len(attr) else 0
        stray += sum(1 for r in prep.records if not _matches(*record_slice(fam, r), sl))
        if stray:
            write_slice(ctx, sl, pd.DataFrame(), [], prep, [str(f) for f in files], input_pairs, ordinals, None,
                        refusal=Refused("error", f"{stray} prepared row(s) belong to another slice's month/branch"))
            continue
        write_slice(ctx, sl, prep.rows, prep.records, prep, [str(f) for f in files], input_pairs, ordinals,
                    dims_for(ctx, fam, prep), warnings=warns)
    return _summary(ctx)


def run_full(ctx: RunContext, overrides: list[Path]) -> int:
    """--all-slices: every family transformed as a whole, then written one
    transaction per (family, month) slice; each family's dimension rules run
    once after its slices, in their own transaction."""
    ctx.staging = SLICE_STAGING / _run_key([], overrides, True)
    files_by_family = {}
    given = {f: layout_of(f) for f in overrides}
    unplaced = [(f, fl) for f, fl in list(given.items()) + list(discover().items()) if not fl.ok]
    if unplaced:
        for f, fl in unplaced:
            record_file_event(ctx, f, fl)
        print(f"\nrefusing the whole rebuild: {len(unplaced)} file(s) could not be identified - {[f.name for f, _ in unplaced]}")
        return 1
    for fam in FAMILIES:
        if fam.key == "ssis_soh":
            continue
        pool = [f for f, fl in given.items() if fl.family == fam.key] or family_files(fam)
        if fam.key == "rmr_gs_bo":
            pool = [f for f in pool if file_month(f) in rmr_allowed_periods()]
        files_by_family[fam.key] = pool
    unsigned, problems, _ = _stage_and_sign(ctx, [], files_by_family, None, True)
    if unsigned and not ctx.dry_run:
        print("\nrefusing the whole rebuild: fingerprint not signed (no slice events are written for an unsigned full rebuild)")
        return 1
    if problems:
        print(f"\nrefusing the whole rebuild: file problems {[f'{p.file}: {p.reason}: {p.detail}' for p in problems]}")
        return 1
    _seed_date_dimension(ctx)

    for fam in FAMILIES:
        staged = pd.DataFrame() if fam.key == "ssis_soh" else read_staged(ctx.staging, fam.key)
        print(f"\n=== family {fam.key} ===")
        prep = prepare(fam, staged, ctx.engine, soh_dir=ctx.staging)
        attr = row_slices(fam, prep.rows)
        rec_attr = [record_slice(fam, r) for r in prep.records]
        stg_month = (staged["_period"].astype(str) if not staged.empty else pd.Series(dtype=str))
        months = sorted({m for m in attr["month"] if MONTH_RE.match(str(m))} | {m for m, _ in rec_attr if MONTH_RE.match(str(m))})
        bad = int((~attr["month"].astype(str).str.match(MONTH_RE.pattern)).sum()) if len(attr) else 0
        if bad:
            print(f"  !!! {bad} row(s) with no month - not loaded (a gap to investigate, never guessed)")
        files = {fam.key: [str(f) for f in files_by_family.get(fam.key, [])]}
        for m in months:
            sl = Slice(fam, m, None)
            rows_m = prep.rows[attr["month"] == m] if len(attr) else prep.rows
            recs_m = [r for r, (rm, _) in zip(prep.records, rec_attr) if rm == m]
            if fam.key == "ssis_soh":
                soh = read_staged(ctx.staging, "ssis_soh")
                sel = soh[soh["_period"].astype(str) == m]
                pairs = {(f, s) for f, s in zip(sel["_src_file"], sel["_src_sheet"])}
            elif staged.empty:
                pairs = set()
            else:
                sel = staged[stg_month == m] if fam.key != "unilever_sku" else staged
                pairs = {(f, s) for f, s in zip(sel["_src_file"], sel["_src_sheet"])}
            ordinals = (sorted(int(o) for o in staged.loc[stg_month == m, "_row_ordinal"])
                        if fam.key == "unilever_sku" and not staged.empty else None)
            src_files = sorted({f for f, _ in pairs} | {r["_src_file"] for r in recs_m if r["_src_file"]})
            print(f"\n--- slice {sl.key} ---")
            write_slice(ctx, sl, rows_m, recs_m, prep, src_files or files[fam.key], pairs, ordinals, None)
        dims = dims_for(ctx, fam, prep)
        if dims is not None and not ctx.dry_run:
            dims(ctx.engine)
    return _summary(ctx)
