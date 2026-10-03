"""
analytics.etl.slice_validation - the slice loader's checks that run BEFORE any
row is deleted (scripts/load_slices.write_slice, right after the shrink guard).

Bands come from config/validation_bands.yaml (measured on public 2026-09-30 and
committed before any drill ran); this module only applies them, the same way
they were measured:

  slice unit   (month, site): sales rows by lineage of _src_file/_src_sheet,
               every other family by its month column and region
  reference    median of the same site's up to 6 immediately preceding months
               with rows, only when at least 3 exist
  peso         sum(amount) / reference            outside [min, max]  -> warn
  unit_price   sum(amount)/sum(qty) / reference   outside the band widened by
               `widen`                                                -> refuse
  known_sku    share of the slice's distinct sku_codes already present in an
               earlier month of the table (same principal)  below min -> refuse
               (a month the band file excludes, with its reason   -> warn)
  types        an amount/qty value that does not parse as a number    -> refuse
  history      fewer than 3 prior months                              -> warn
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable

import pandas as pd
import yaml
from sqlalchemy import Connection, text

from analytics.etl.extract._shared import REPO_ROOT, infer_sheet_period, infer_sheet_region

BANDS_FILE = REPO_ROOT / "config" / "validation_bands.yaml"
ALLOWLIST_FILE = REPO_ROOT / "config" / "checksum_allowlist.yaml"
MIN_PRIOR, MAX_PRIOR = 3, 6   # the measurement's own reference rule (validation_bands.yaml header)


@dataclass(frozen=True)
class Measure:
    table: str
    principal: str
    amount: str
    qty: str | None
    month_col: str
    where: str = ""               # extra predicate on the table (salesreturn source)
    lineage: bool = False         # sales: month/site from _src_file/_src_sheet
    has_site: bool = True


MEASURES = {
    "sales_register": Measure("sales_fact", "delmonte", "net_amount", "quantity_cases", "_period", lineage=True),
    "purchase_order": Measure("purchase_fact", "delmonte", "net_amount", None, "_period"),
    "sales_return": Measure("salesreturn_fact", "delmonte", "net_amount", "quantity_cases", "_period", "AND source IS NULL"),
    "rmr_gs_bo": Measure("salesreturn_fact", "delmonte", "net_amount", None, "_period", "AND source = 'rmr'"),
    "sell_out": Measure("sellout_fact", "delmonte", "net_amount", "quantity", "_period"),
    "unilever_sku": Measure("unilever_sku_demand_fact", "unilever", "net_amount", "quantity_sold", "calendar_month",
                            has_site=False),
    "inventory_sign_off": Measure("inventory_fact", "delmonte", "valuation", "quantity_on_hand", "_period"),
    "ssis_soh": Measure("inventory_fact", "unilever", "valuation", "quantity_on_hand", "_period", has_site=False),
}


@dataclass(frozen=True)
class Finding:
    check: str        # types | peso | unit_price | known_sku | history
    severity: str     # refuse | warn
    detail: str


@lru_cache(maxsize=None)
def load_bands(path: Path = BANDS_FILE) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _num(v) -> float | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _principal_filter(m: Measure) -> str:
    return "" if m.table in ("unilever_sku_demand_fact",) else f"AND principal = '{m.principal}'"


def history(conn: Connection, family: str,
            lineage: Callable[[str, str], tuple[str, str]] | None = None) -> dict[tuple[str, str | None], tuple[float, float, float]]:
    """(month, site) -> (sum amount, sum amount where qty is not null, sum qty)
    over the table's real rows - the same aggregate the bands were measured on.
    Sales rows take (month, site) from `lineage` (the loader's own)."""
    m = MEASURES[family]
    qty = m.qty or "NULL::numeric"
    pf = _principal_filter(m)
    if m.lineage:
        sql = (f"SELECT _src_file, _src_sheet, sum({m.amount}), sum({m.amount}) FILTER (WHERE {qty} IS NOT NULL), "
               f"sum({qty}) FROM {m.table} WHERE NOT is_demo {pf} {m.where} GROUP BY 1, 2")
    else:
        site = "region" if m.has_site else "NULL"
        sql = (f"SELECT {m.month_col}, {site}, sum({m.amount}), sum({m.amount}) FILTER (WHERE {qty} IS NOT NULL), "
               f"sum({qty}) FROM {m.table} WHERE NOT is_demo {pf} {m.where} GROUP BY 1, 2")
    out: dict = {}
    for a, b, amt, pamt, q in conn.execute(text(sql)).all():
        if m.lineage:
            key = lineage(a, b) if lineage else (infer_sheet_period(REPO_ROOT / a, b), infer_sheet_region(REPO_ROOT / a, b))
        else:
            key = (a, b)
        t = out.setdefault(key, [0.0, 0.0, 0.0])
        t[0] += float(amt or 0)
        t[1] += float(pamt or 0)
        t[2] += float(q or 0)
    return {k: tuple(v) for k, v in out.items()}


def earlier_skus(conn: Connection, family: str, month: str) -> set[str]:
    m = MEASURES[family]
    rows = conn.execute(text(f"SELECT DISTINCT sku_code FROM {m.table} WHERE NOT is_demo {_principal_filter(m)} "
                             f"AND {m.month_col} < :m"), {"m": month}).scalars().all()
    return set(rows)


def _earlier_month_count(hist: dict, month: str, site) -> int:
    return len({mm for (mm, s) in hist if s == site and mm < month})


def check_types(family: str, rows: pd.DataFrame) -> list[Finding]:
    m = MEASURES[family]
    out = []
    for col in (m.amount, m.qty):
        if col is None or col not in rows.columns:
            continue
        vals = rows[col]
        bad = [v for v in vals if v is not None and not (isinstance(v, float) and pd.isna(v)) and _num(v) is None]
        if bad:
            out.append(Finding("types", "refuse", f"{col}: {len(bad)} value(s) are not numbers, e.g. {bad[0]!r}"))
    return out


def validate_rows(family: str, rows: pd.DataFrame, slices: pd.DataFrame, hist: dict,
                  sku_lookup: Callable[[str], set[str]] | None = None, bands: dict | None = None) -> list[Finding]:
    """Every check for one slice's prepared rows. `slices` is row_slices()
    (month, site per row); `hist` is history() read in the slice's own
    transaction; `sku_lookup(month)` returns the SKUs of earlier months."""
    bands = bands or load_bands()
    band = bands["families"].get(family) or {}
    widen = float(bands["widen"])
    m = MEASURES[family]
    findings = check_types(family, rows)
    if rows.empty or findings:
        return findings
    df = pd.DataFrame({"month": slices["month"].astype(str).values, "site": slices["site"].values,
                       "amt": [_num(v) or 0.0 for v in rows[m.amount]]}, index=rows.index)
    df["qty"] = [_num(v) for v in rows[m.qty]] if m.qty and m.qty in rows.columns else None
    if not m.has_site:
        df["site"] = None
    for (month, site), g in df.groupby(["month", "site"], dropna=False, sort=True):
        site = None if pd.isna(site) else site
        where = f"{month}" + (f" {site}" if site else "")
        prior = sorted(((mm, v) for (mm, s), v in hist.items() if s == site and mm < month), reverse=True)[:MAX_PRIOR]
        if len(prior) < MIN_PRIOR:
            findings.append(Finding("history", "warn", f"{where}: {len(prior)} prior month(s), bands need {MIN_PRIOR} - "
                                                      f"peso and unit-price checks not run"))
        else:
            ref = statistics.median(v[0] for _, v in prior)
            ratio = g["amt"].sum() / ref if ref else None
            pb = band.get("peso")
            if pb and ratio is not None and not (pb["min"] <= ratio <= pb["max"]):
                findings.append(Finding("peso", "warn", f"{where}: peso total {g['amt'].sum():,.2f} is {ratio:.3f}x the "
                                                        f"prior-months median; measured band {pb['min']}-{pb['max']}"))
            ub = band.get("unit_price")
            if ub:
                lo, hi = ub["min"] * (1 - widen), ub["max"] * (1 + widen)
                priced = [v[1] / v[2] for _, v in prior if v[2]]
                have = g[g["qty"].notna()] if "qty" in g and g["qty"].notna().any() else None
                if have is None or not have["qty"].sum():
                    findings.append(Finding("unit_price", "refuse", f"{where}: no quantities, so no unit price - every "
                                                                    f"measured month of this family had them"))
                elif len(priced) >= MIN_PRIOR:
                    r = (have["amt"].sum() / have["qty"].sum()) / statistics.median(priced)
                    if not (lo <= r <= hi):
                        findings.append(Finding("unit_price", "refuse", f"{where}: unit price is {r:.4f}x the prior-months "
                                                                        f"median; allowed {lo:.4f}-{hi:.4f} (measured "
                                                                        f"{ub['min']}-{ub['max']}, widened {widen:.0%})"))
        kb = band.get("known_sku")
        if kb and sku_lookup is not None and "sku_code" in rows.columns:
            codes = set(rows.loc[g.index, "sku_code"].dropna().astype(str))
            earlier_months = {mm for (mm, _s) in hist if mm < month}
            if len(earlier_months) < MIN_PRIOR:
                findings.append(Finding("history", "warn", f"{where}: {len(earlier_months)} earlier month(s) - "
                                                          f"known-SKU check not run"))
            elif codes:
                share = len(codes & sku_lookup(month)) / len(codes)
                if share < kb["min"]:
                    sev = "warn" if month in (kb.get("excluded_months") or []) else "refuse"
                    findings.append(Finding("known_sku", sev, f"{where}: {share:.1%} of {len(codes)} SKU codes seen in "
                                                             f"earlier months; floor {kb['min']:.1%}"
                                                             + (" (month excluded from the band, see bands file)"
                                                                if sev == "warn" else "")))
    return findings


# --- totals row -------------------------------------------------------------------------------------------------

@lru_cache(maxsize=None)
def _allowlist(path: Path = ALLOWLIST_FILE) -> dict[tuple[str, str], str]:
    entries = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("sheets") or []
    return {(e["sha256"], e["sheet"]): e["reason"] for e in entries}


@lru_cache(maxsize=None)
def file_sha256(path: Path) -> str:
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def checksum_allowed(path: Path, sheet: str) -> str | None:
    """The recorded source-problem reason when this exact file (by content
    hash) and sheet are on config/checksum_allowlist.yaml, else None."""
    return _allowlist().get((file_sha256(Path(path)), sheet))
