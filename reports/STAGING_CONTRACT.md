# Staging Contract — What Transform Actually Expects From `staging/`

Read-only discovery pass. Branch `kelvin-etl`. Every claim below cites the file/line I actually opened or the exact command I ran to verify it.

## 0a. Real Parquet schema per doc_type

One real file loaded per doc_type via `pandas.read_parquet()`:

| doc_type | file loaded | shape |
|---|---|---|
| sales_register | `staging/sales_register/2024_JANUARY_SALES_REGISTER__ILOCOS_SALES_REGISTER.parquet` | 163 rows × 30 cols |
| sell_out | `staging/sell_out/2024_JANUARY_SELL_OUT__ILOCOS_SELL_OUT.parquet` | 69 rows × 18 cols |
| inventory_sign_off | `staging/inventory_sign_off/2024_JANUARY_INVENTORY_SIGN_OFF__ILOCOS_SIGN_OFF_INVENTORY.parquet` | 131 rows × 25 cols |
| purchase_order | `staging/purchase_order/2024_JANUARY_PURCHASES__ILOCOS_PURCHASE.parquet` | 11 rows × 30 cols |

**Column order and dtypes (exactly as read):**

`sales_register` (30 cols) — 15 raw business columns (unmapped, Extract's raw header text) followed by the 15 provenance columns:
```
Invoice Date(object) Salesman(object) Town Display(object) Branch Code(object) Customer Name(object)
Invoice Num(object) REFNBR(object) Untaxed Amount(object) Discount Rate(object) Dscount Amount(object)
Tax(object) Net Amount(object) Balance(object) Posted(object) Return Slip #(object)
_src_file(object) _src_sheet(object) _header_row(int64) _row_ordinal(int64) _principal(object)
_region(object) _period(object) _doc_type(object) _sheet_role(object) _grain(object)
_checksum_status(object) _checksum_column(object) _checksum_expected(float64) _checksum_got(float64) _checksum_diff(float64)
```
Note the real raw header is `Dscount Amount` (typo, missing "i") in this January-2024 file, not `Discount Amount` — column-map matching is case/whitespace-normalized but this is a literal spelling variant; confirms real header vocabulary is genuinely inconsistent file-to-file, not just casing.

`sell_out` (18 cols) — only 3 raw business columns:
```
__col0__(object) Total Without Tax(object) Product Quantity(float64)
_src_file _src_sheet _header_row _row_ordinal _principal _region _period _doc_type _sheet_role _grain
_checksum_status _checksum_column _checksum_expected(object) _checksum_got(object) _checksum_diff(object)
```
`__col0__` is the unlabeled category-path column (row 0 of real data literally contains the string `"Total"` — the banner row `exclude_sell_out_total_rows()` now strips at Transform time, still present here since staging is pre-Transform). Checksum columns are `object` dtype here (all-`None` in this file → pandas infers `object`, not `float64` — dtype is data-dependent, not a schema guarantee; see Phase 2 note below).

`inventory_sign_off` (25 cols) — 9 raw business columns in *this* file:
```
__col0__(object) Quantity(float64) Cost(object) Valuation(object) Valuation with VAT(object)
CAS(int64) PCS(int64) PKG(float64) in PCS(int64) in Cases(float64)
_src_file ... (15 provenance columns, same as above)
```
**Column-count is NOT stable across all real inventory_sign_off files** — checked all 41 real staged files directly: 15/41 have both `__col0__` and `__col1__` (26 cols total), 26/41 have only `__col0__` (25 cols, as in the sampled file). This era split matters for Phase 1b.

`purchase_order` (30 cols) — same 15 raw business columns as `sales_register` (this doc_type shares Sales Register's column vocabulary, confirmed identical field set) + same 15 provenance columns.

**Sample rows** — 3 real rows per doc_type were printed and visually confirmed to carry real-looking Ilocos/Pangasinan business data (real customer names like "K'KOS", "*NOR LEE'S BAKERY"; real salesman "JOENATHAN ARIZABAL"; real invoice numbers `INV/2024/0368`; real inventory SKU strings like `"9DBL58403 DM 100% PA Juice w/ Vit ACE 202 6-Pack"` combining a code and description in one field). Full row dumps not reproduced here for length; re-run is trivial (`pd.read_parquet(path).head(3)`).

## 0b. Exact record shape of a `staging/_manifest.json` entry

`staging/_manifest.json` top-level keys: `{"reject": [...], "staged": [...]}` (verified: `json.load()` → `list(m.keys())`).

One `staged` entry, every field with its type (verified against `m["staged"][0]`):

| field | type | example |
|---|---|---|
| `checksum_column` | `str` | `"Net Amount"` |
| `checksum_diff` | `float \| None` | `None` |
| `checksum_expected` | `float \| None` | `None` |
| `checksum_got` | `float \| None` | `None` |
| `checksum_status` | `str` | `"unverified"` |
| `columns` | `list[str]` | `["Invoice Date", "Salesman", "AREA", ...]` (raw header names, unmapped) |
| `doc_type` | `str` | `"sales_register"` |
| `grain` | `str` | `"invoice"` |
| `period` | `str` | `"2025-11"` |
| `principal` | `str` | `"delmonte"` |
| `region` | `str` | `"ilocos"` |
| `row_count` | `int` | `405` |
| `sheet_role` | `str` | `"one_pager"` |
| `src_file` | `str` | `"data/raw/Del Monte/DAILY REPORT - NOVEMBER 2025/..."` |
| `src_sheet` | `str` | `"ONE PAGER"` |

**Important naming mismatch to carry into Phase 2**: manifest keys are **unprefixed** (`src_file`, `doc_type`, `region`...) while the Parquet files' own provenance columns are **`_`-prefixed** (`_src_file`, `_doc_type`, `_region`...). These are two independently-shaped records describing the same fact — a converter must not confuse manifest-key-casing with column-casing.

**Which fields Transform actually reads: none.** See 0c — `transform_driver.py` never opens `staging/_manifest.json` at all. The manifest is Extract's own output/audit artifact, consumed only by `analytics/etl/load.py` (for the DEC-12 reject-rate gate — `load.py:222`, `load.py:262`) and by `analytics/etl/_review.py`'s HTML viewer, not by Transform.

## 0c. How Transform discovers files — directory glob, not the manifest (cited)

`analytics/etl/transform_driver.py::build_transform_manifest()`, lines 233–238:
```python
for doc_dir in sorted(p for p in staging_dir.iterdir() if p.is_dir() and p.name != "_rejects"):
    doc_type = doc_dir.name
    parquet_files = sorted(doc_dir.glob("*.parquet"))
    if not parquet_files:
        continue
    df = pd.concat([pd.read_parquet(f) for f in parquet_files], ignore_index=True)
```
This is the **only** place Transform loads staged data. It iterates `staging_dir`'s subdirectories directly, globs `*.parquet` inside each, and concatenates them with `pd.read_parquet()`. Confirmed via `grep -rn "staging.*_manifest\.json\|json.load.*manifest" analytics/etl/transform_driver.py analytics/etl/transform.py` — zero matches in either file.

**Direct consequence for the plan: an unmanifested Parquet file dropped into `staging/<doc_type>/` is NOT invisible — it is picked up automatically**, indistinguishably from a real Extract-produced file, purely because it's a `.parquet` file sitting in the right directory. `staging/_manifest.json` plays no gating role for Transform. (It does matter for `load.py`'s reject-rate gate later, per 0b above — but that's a Load-stage concern, out of scope this session per your hard rule 5.)

## 0d. Real file naming convention inside `staging/<doc_type>/`

Defined in `analytics/etl/extract/_shared.py::write_staging_table()`, lines 631–638:
```python
def write_staging_table(df, doc_type, rel_path, sheet_name, staging_dir):
    out_dir = staging_dir / doc_type
    file_stem = sanitize_filename(Path(rel_path).stem)
    sheet_stem = sanitize_filename(sheet_name)
    out_path = out_dir / f"{file_stem}__{sheet_stem}.parquet"
```
Pattern: **`<sanitized source-filename-stem>__<sanitized sheet-name>.parquet`**, double-underscore separator, one Parquet file per (source file, sheet) pair. `sanitize_filename()` (`profiling/profile_files.py:93-94`, imported into `_shared.py` at line 39): `re.sub(r"[^A-Za-z0-9_.-]+", "_", name)` — collapses any run of non-alphanumeric/`._-` characters (including spaces) into a single underscore.

Confirmed against real directory listings, e.g. `staging/sales_register/2024_JANUARY_SALES_REGISTER__ILOCOS_SALES_REGISTER.parquet` — the source file was `2024 JANUARY SALES REGISTER.xlsx`, sheet `ILOCOS SALES REGISTER`.

## 0e. `PROVENANCE_COLUMNS` — content and actual read/ignore status

Defined `analytics/etl/extract/_shared.py:47-51`, 15 entries:
```python
PROVENANCE_COLUMNS = [
    "_src_file", "_src_sheet", "_header_row", "_row_ordinal", "_principal",
    "_region", "_period", "_doc_type", "_sheet_role", "_grain",
    "_checksum_status", "_checksum_column", "_checksum_expected", "_checksum_got", "_checksum_diff",
]
```

Checked every one of the 15 for real usage in `analytics/etl/transform.py` and `analytics/etl/transform_driver.py` beyond the list definition itself:

| column | read by Transform logic? | where |
|---|---|---|
| `_src_file` | **yes** — grouping key, conflict/leftover tracking | `transform_driver.py:93,173,193,262` |
| `_src_sheet` | **yes** — same as above | `transform_driver.py:93,173,193,262` |
| `_principal` | **yes** — the master per-principal filter | `transform_driver.py:150`: `principal_df = df[df["_principal"] == principal]` |
| `_sheet_role` | **yes** — gates promoted vs. demoted (DEC-04) | `transform.py:557` (`filter_source_of_truth`), `transform_driver.py:200-205` |
| `_doc_type` | **yes** — `cross_check_doc_types` exclusion | `transform.py:555-556` |
| `_period` | **yes**, but only conditionally — feeds `inventory_sign_off`'s synthetic `snapshot_date` | `transform.py:685-686` |
| `_grain` | copied into the output record, **not** used in any conditional | `transform_driver.py:106` |
| `_region` | **not read by any conditional in transform.py/transform_driver.py** — passed through, and separately re-derived into the canonical `region` field by `backfill_provenance_fields()` if the mapped column is missing, but the raw `_region` value itself gates nothing | grep shows only doc/comment references |
| `_header_row` | **ignored** — appears only in the `PROVENANCE_COLUMNS` list itself | transform.py:49 only |
| `_row_ordinal` | **ignored** — same | transform.py:49 only |
| `_checksum_status` | **ignored** — same | transform.py:51 only |
| `_checksum_column` | **ignored** — same | transform.py:51 only |
| `_checksum_expected` | **ignored** — same | transform.py:51 only |
| `_checksum_got` | **ignored** — same | transform.py:51 only |
| `_checksum_diff` | **ignored** — same | transform.py:51 only |

**Bottom line for Phase 2**: the columns that must be *correct* for a converted synthetic row to classify the same way a real row does are `_src_file`/`_src_sheet` (uniqueness/tracking only, don't need to point at a real file for Transform to run — see Phase 1's separability question, not re-litigated here), `_principal` (must be exactly `"delmonte"` or `"unilever"`, lowercase), `_sheet_role` (must be a real system-of-record role for the target fact, per `source_of_truth.yaml`), and `_doc_type` (must be an exact match to a `source_of_truth.yaml`-declared doc_type, or a declared `cross_check_doc_types` value). The remaining 10 provenance columns can be structurally present (Transform will not crash without them being *correct*, only if `apply_column_map()` needs `_sheet_role` present — see `filter_source_of_truth()`'s explicit `KeyError` at transform.py:552-553) but their *values* don't influence any Transform decision.
