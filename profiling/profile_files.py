"""SSM ETL discovery — profiling pass (Phase 3A pre-parser reconnaissance).

READ-ONLY on data/raw/. Writes only under profiling/ and config/.
Re-running produces identical, diffable output (files walked in sorted order,
all inference is deterministic pure functions over the actual cell grids).

Usage: python profiling/profile_files.py
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from reader import read_workbook  # noqa: E402
from detect import (  # noqa: E402
    trim_grid, detect_header, infer_dtype, infer_grain,
    infer_principal_from_content, contains_magnolia, is_blank,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
PROFILING_DIR = REPO_ROOT / "profiling"
SHEET_PROFILES_DIR = PROFILING_DIR / "sheet_profiles"

# The repo lives under OneDrive; sustained sequential reads on large xlsx
# files there degrade badly mid-file (observed: linear cost for the first
# ~3500 rows of a sheet, then a 100x+ slowdown cliff), consistent with
# OneDrive's sync/cloud-file filter driver throttling long-held file
# handles. Read from a local mirror instead — set SSM_RAW_MIRROR to point
# at one (see profiling/README note); falls back to the OneDrive path.
RAW_DIR = Path(os.environ.get("SSM_RAW_MIRROR", "")) if os.environ.get("SSM_RAW_MIRROR") else REPO_ROOT / "data" / "raw"
LOGICAL_RAW_DIR = REPO_ROOT / "data" / "raw"

# The repo lives under a OneDrive-synced folder. Writing hundreds of small
# JSON files there triggers per-file cloud-sync overhead that compounds
# and throttles the run. Stage writes on local (non-synced) disk, then
# bulk-copy into profiling/sheet_profiles/ once at the end.
STAGING_DIR = Path(tempfile.gettempdir()) / "ssm_etl_profiling_staging"

# Hard wall-clock ceiling per file, enforced by killing the worker
# subprocess. Generously above the ~20-70s worst case observed for the
# largest legitimate SSIS files even under the pathological slowdown.
PER_FILE_TIMEOUT_SECONDS = 180

MONTHS = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "sept": "09", "october": "10", "november": "11",
    "december": "12", "decmber": "12", "jan": "01", "feb": "02", "mar": "03",
    "apr": "04", "jun": "06", "jul": "07", "aug": "08", "oct": "10", "nov": "11", "dec": "12",
}

DOC_TYPE_PATTERNS = [
    ("rmr_gs_bo", re.compile(r"rmr.*gs.*bo|gs\s*&\s*bo", re.I)),
    ("sales_return", re.compile(r"sale[s]?\s*return", re.I)),
    ("sell_out", re.compile(r"sell\s*out", re.I)),
    ("inventory_sign_off", re.compile(r"inventory|sign\s*off", re.I)),
    ("purchase_order", re.compile(r"purchase|_po\b|\bpo\b", re.I)),
    ("sales_register", re.compile(r"sale[s]?\s*regist(er)?|daily\s*sales\s*report", re.I)),
    ("ssis_summary", re.compile(r"ssis", re.I)),
    ("price_list", re.compile(r"pricelist|price\s*list", re.I)),
    ("unilever_sku", re.compile(r"la.union.*sku|sku.*la.union", re.I)),
]

REGION_PATTERNS = [
    ("pangasinan", re.compile(r"pangasinan|pang\b|pang\.", re.I)),
    ("ilocos", re.compile(r"ilocos", re.I)),
    ("la_union", re.compile(r"la.union", re.I)),
]


def sanitize_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)


def normalize_dedup_key(filename: str) -> str:
    """Strip 'Copy of', trailing ' (1)'/'_1' style suffixes for dedup grouping."""
    stem = Path(filename).stem
    stem = re.sub(r"^copy of\s+", "", stem, flags=re.I)
    stem = re.sub(r"\s*\(\d+\)\s*$", "", stem)
    stem = re.sub(r"[_\s]\d+$", "", stem)
    stem = re.sub(r"\s+", " ", stem).strip().lower()
    return stem


# MM.DD.YYYY, as seen in daily-report filenames ("DAILY SALES REPORT
# 07.31.2025.xlsx") and in per-day sheet names within them ("07.08.2025").
# Extract's period tagging reuses this for sheet names too (see
# analytics/etl/extract/_shared.py::infer_sheet_period) rather than
# duplicating the pattern.
MM_DD_YYYY_RE = re.compile(r"\b(\d{2})\.(\d{2})\.(20\d{2})\b")


def infer_period(path: Path) -> str | None:
    """Extract YYYY-MM from filename/folder path. Returns None if not found."""
    text = " ".join(p.name for p in [path] + list(path.parents[:3])).lower()
    year_match = re.search(r"20\d{2}", text)
    year = year_match.group(0) if year_match else None
    month = None
    for name, num in MONTHS.items():
        if re.search(rf"\b{name}\b", text):
            month = num
            break
    if not month:
        mm_match = re.search(r"report\s*-\s*(\d{2})\.(\d{4})", text)
        if mm_match:
            month, year = mm_match.group(1), mm_match.group(2)
    if not month:
        mdy_match = MM_DD_YYYY_RE.search(text)
        if mdy_match:
            month, _day, year = mdy_match.groups()
    if year and month:
        return f"{year}-{month}"
    return None


def infer_doc_type(path: Path) -> str:
    name = path.name
    for doc_type, pattern in DOC_TYPE_PATTERNS:
        if pattern.search(name):
            return doc_type
    return "unknown"


def infer_regions(path: Path) -> list[str]:
    text = str(path)
    found = []
    for region, pattern in REGION_PATTERNS:
        if pattern.search(text):
            found.append(region)
    return found or ["unknown"]


def infer_principal_from_path(path: Path) -> str:
    text = str(path).lower()
    if "unilever" in text:
        return "unilever"
    if "del monte" in text or "delmonte" in text or "dm " in text:
        return "delmonte"
    return "ambiguous"


def header_signature(header_row: list) -> str:
    tokens = sorted(
        str(h).strip().lower() for h in header_row if not is_blank(h)
    )
    joined = "|".join(tokens)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:12], tokens


def profile_sheet(file_rel: str, sheet_name: str, raw_rows: list, real_format: str, truncated: bool = False) -> dict:
    trimmed = trim_grid(raw_rows)
    hd = detect_header(trimmed)

    if hd.header_row_index < 0 or not trimmed:
        return {
            "file": file_rel, "sheet": sheet_name, "real_format": real_format,
            "header_row_index": None, "header_confidence": 0.0,
            "junk_ranges": [], "raw_columns": [], "dtypes": {}, "null_pct": {},
            "distinct_count": {}, "samples": {}, "grain": "unknown",
            "usable_row_count": 0, "header_signature": None, "principal_guess": "ambiguous",
            "principal_evidence": [], "magnolia_flag": False, "read_truncated": truncated,
        }

    header_row = trimmed[hd.header_row_index]
    data_rows = trimmed[hd.header_row_index + 1:]
    header_labels = [str(h).strip() if not is_blank(h) else f"__col{i}__" for i, h in enumerate(header_row)]

    dtypes, null_pct, distinct_count, samples = {}, {}, {}, {}
    for i, col_name in enumerate(header_labels):
        col_vals = [r[i] for r in data_rows if len(r) > i]
        dtypes[col_name] = infer_dtype(col_vals)
        n = len(col_vals)
        null_pct[col_name] = round(100 * sum(1 for v in col_vals if is_blank(v)) / n, 2) if n else 100.0
        distinct_vals = set(str(v) for v in col_vals if not is_blank(v))
        distinct_count[col_name] = len(distinct_vals)
        samples[col_name] = list(distinct_vals)[:5]

    grain = infer_grain(header_row, data_rows)
    principal_guess, principal_evidence = infer_principal_from_content(header_row, data_rows)
    sig_hash, sig_tokens = header_signature(header_row)
    magnolia = contains_magnolia(trimmed)

    usable_rows = sum(1 for r in data_rows if any(not is_blank(v) for v in r))

    return {
        "file": file_rel, "sheet": sheet_name, "real_format": real_format,
        "header_row_index": hd.header_row_index, "header_confidence": hd.confidence,
        "junk_ranges": hd.junk_ranges, "raw_columns": header_labels,
        "dtypes": dtypes, "null_pct": null_pct, "distinct_count": distinct_count,
        "samples": samples, "grain": grain, "usable_row_count": usable_rows,
        "header_signature": sig_hash, "header_tokens": sig_tokens,
        "principal_guess": principal_guess, "principal_evidence": principal_evidence,
        "magnolia_flag": magnolia, "read_truncated": truncated,
    }


def main():
    if STAGING_DIR.exists():
        shutil.rmtree(STAGING_DIR)
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    (REPO_ROOT / "config" / "column_maps").mkdir(parents=True, exist_ok=True)
    (REPO_ROOT / "config" / "alias_tables").mkdir(parents=True, exist_ok=True)

    all_files = sorted(RAW_DIR.rglob("*"))
    all_files = [f for f in all_files if f.is_file() and f.name != ".gitkeep"]

    inventory_rows = []
    all_sheet_profiles = []
    dedup_groups = defaultdict(list)

    for f in all_files:
        rel = (LOGICAL_RAW_DIR / f.relative_to(RAW_DIR)).relative_to(REPO_ROOT).as_posix()
        dedup_key = normalize_dedup_key(f.name)
        dedup_groups[dedup_key].append(rel)

    worker_script = Path(__file__).parent / "profile_one_file.py"
    worker_out_dir = STAGING_DIR / "_worker_out"
    worker_out_dir.mkdir(parents=True, exist_ok=True)

    for idx, f in enumerate(all_files):
        rel = (LOGICAL_RAW_DIR / f.relative_to(RAW_DIR)).relative_to(REPO_ROOT).as_posix()
        size_kb = round(f.stat().st_size / 1024, 1)
        print(f"[{idx + 1}/{len(all_files)}] {rel}", flush=True)
        dedup_key = normalize_dedup_key(f.name)
        dup_group = dedup_key if len(dedup_groups[dedup_key]) > 1 else ""

        # Each file is profiled in a fresh subprocess: isolates any
        # cross-file state degradation (observed but not root-caused —
        # a file that's fast standalone can become pathologically slow
        # deep into a long single-process loop) and gives a hard
        # wall-clock kill switch via subprocess timeout.
        out_json = worker_out_dir / f"{idx}.json"
        try:
            subprocess.run(
                [sys.executable, str(worker_script), str(f), str(out_json)],
                timeout=PER_FILE_TIMEOUT_SECONDS, check=True,
                capture_output=True, text=True,
            )
        except subprocess.TimeoutExpired:
            inventory_rows.append({
                "path": rel, "real_format": "unknown", "size_kb": size_kb,
                "sheet_count": 0, "principal": "ambiguous", "regions": "",
                "period": infer_period(f) or "", "doc_type": infer_doc_type(f),
                "duplicate_group": dup_group, "magnolia_flag": "magnolia" in str(f).lower(),
                "read_error": f"worker timed out after {PER_FILE_TIMEOUT_SECONDS}s",
            })
            continue
        except subprocess.CalledProcessError as e:
            inventory_rows.append({
                "path": rel, "real_format": "unknown", "size_kb": size_kb,
                "sheet_count": 0, "principal": "ambiguous", "regions": "",
                "period": infer_period(f) or "", "doc_type": infer_doc_type(f),
                "duplicate_group": dup_group, "magnolia_flag": "magnolia" in str(f).lower(),
                "read_error": f"worker crashed: {e.stderr[-500:] if e.stderr else e}",
            })
            continue

        result = json.loads(out_json.read_text(encoding="utf-8"))
        out_json.unlink()
        inv = result["inventory"]
        inv["duplicate_group"] = dup_group
        inventory_rows.append(inv)

        for prof in result["sheets"]:
            all_sheet_profiles.append(prof)
            out_name = sanitize_filename(f"{Path(rel).stem}__{prof['sheet']}") + ".json"
            with open(STAGING_DIR / out_name, "w", encoding="utf-8") as out:
                json.dump(prof, out, indent=2, default=str, ensure_ascii=False)

    SHEET_PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    for existing in SHEET_PROFILES_DIR.glob("*.json"):
        existing.unlink()
    for staged in STAGING_DIR.glob("*.json"):
        shutil.copy2(staged, SHEET_PROFILES_DIR / staged.name)
    shutil.rmtree(STAGING_DIR, ignore_errors=True)
    print(f"Copied {len(list(SHEET_PROFILES_DIR.glob('*.json')))} staged profiles into profiling/sheet_profiles/")

    fieldnames = ["path", "real_format", "size_kb", "sheet_count", "principal",
                  "regions", "period", "doc_type", "duplicate_group", "magnolia_flag", "read_error"]
    with open(PROFILING_DIR / "file_inventory.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in inventory_rows:
            row.setdefault("read_error", "")
            writer.writerow(row)

    print(f"Wrote {len(inventory_rows)} rows to profiling/file_inventory.csv")
    print(f"Wrote {len(all_sheet_profiles)} sheet profiles to profiling/sheet_profiles/")

    # Summary
    by_format = defaultdict(int)
    by_principal = defaultdict(int)
    ambiguous, magnolia_hits, dup_hits = 0, 0, 0
    for row in inventory_rows:
        by_format[row["real_format"]] += 1
        by_principal[row["principal"]] += 1
        if row["principal"] == "ambiguous":
            ambiguous += 1
        if row["magnolia_flag"]:
            magnolia_hits += 1
        if row["duplicate_group"]:
            dup_hits += 1

    print("\n--- Summary ---")
    print("By real_format:", dict(by_format))
    print("By principal:", dict(by_principal))
    print(f"Ambiguous-principal files: {ambiguous}")
    print(f"Magnolia-flagged files: {magnolia_hits}")
    print(f"Files in a duplicate group: {dup_hits}")

    return inventory_rows, all_sheet_profiles


if __name__ == "__main__":
    main()
