# Synthetic Staging Conversion — SSM Decision Support Dashboard

Branch `kelvin-etl`. Companion to `reports/SYNTHETIC_DATA_AUDIT.md` (prior audit, findings accepted as-is, not re-derived) and `reports/STAGING_CONTRACT.md` (Phase 0). This file covers Phase 1 (diagnosis + implemented fix) so far; Phases 2-6 not started.

## PHASE 1 — Two blocking field gaps: diagnosis, fix, validation

### 1a. `sell_out` `category_path` — already fixed, closed

Root cause (historical, pre-session): `apply_column_map()`'s old skip condition was `col.startswith("_")`, which also matched Extract's `__col0__`/`__col1__` placeholder names (they start with `_` too), silently excluding them from column-map lookup. `category_path` never appeared post-Transform for any real sell_out sheet.

**Commit `ca8ee33`** (already merged into `kelvin-etl`, `transform.py:175`) changed the skip condition to exact membership in `PROVENANCE_COLUMNS`. Verified directly against all 34 real staged files: `category_path` now appears post-map in **34/34 files**, **0 null values across all 1,573 real rows**. No further work needed.

### 1b. `inventory_sign_off` `sku_code` — four real shapes, not two

Phase 0's "col0-only vs col0+col1" premise undercounted. Verified against all 41 real staged files:

| Shape | Files | Structure |
|---|---|---|
| A | 25 | `__col0__` only — combined `"CODE DESCRIPTION"` string |
| B | 13 | `__col0__` = redundant bare-numeric SKU suffix (ignorable); `__col1__` = the real combined `"CODE DESCRIPTION"` string |
| C | 2 | Real labeled headers `ITEM CODE` / `ITEM DESCRIPTION` — no split needed |
| D | 1 | `DELMONTE_INVENTORY_SIGN_OFF_..._AUGUST_2023__PANGASINAN-ACTUAL.parquet` — `__col1__` has description text but the alpha SKU prefix is absent from the source entirely (173/173 rows checked, 0 contain a `9Dxx#####`-style prefix anywhere). Not a parsing failure — the code genuinely isn't in this file. |

The existing `_SKU_CODE_RE` (`transform.py:309`, inside the already-existing `split_sku_description()`) already handles Shapes A/B's combined-string format correctly at 395/398 (99.2%) of real distinct values, with the only 3 failures being non-product banner/corruption rows (`'#REF!'`, `'WH/Stock'`, `'IS-WH/Stock'`) it correctly refuses rather than guesses at. The gap was routing, not parsing: `config/column_maps/inventory_sign_off.yaml` only ever mapped `__col1__` → `sku_description_raw` (Shape B's path); `__col0__` (Shape A, 25/41 real files, 92/92 synthetic files) was never routed anywhere, so `split_sku_description()` never ran on it — every Shape A row produced `sku_code = NULL`.

### Fix implemented — shape-aware dispatch in `transform.py`

Per your decision, **not** a second YAML alias (confirmed collision risk: Shape B files have both `__col0__` and `__col1__` non-null simultaneously; adding `__col0__` as a `sku_description_raw` alias would make `_coalesce_duplicate_columns()`'s first-non-null-wins logic silently pick `__col0__`'s bare numeric fragment over `__col1__`'s real value for every Shape B row, while flooding `duplicate_column_conflicts` with false positives).

Added to `analytics/etl/transform.py`:
- `_classify_inventory_sku_shape(group)` — classifies one `(_src_file, _src_sheet)` sheet's shape from its own post-column-map data (Shape C: `ITEM CODE` present; Shape B/D: `sku_description_raw` present — note this checks the *already-renamed* field, since `apply_column_map()` runs first and `__col1__` no longer exists under that name by the time this runs — distinguished from each other by content match-rate against the alpha-prefix pattern; Shape A: only `__col0__` present).
- `route_inventory_sku_shapes(df)` — groups by `(_src_file, _src_sheet)` (**per sheet, not per file**, per your instruction — confirmed necessary: every 2025-era workbook carries a third `"Sheet1"` alongside the two region-named sheets, though see the correction below), tags every row with `_inventory_sku_shape`, and routes Shape A's `__col0__` into `sku_description_raw` (only for Shape A rows — Shape B's existing YAML-driven `__col1__` mapping is untouched, exactly as instructed).
- Wired into `transform_fact()`: routing runs first, then `split_sku_description()` (now correctly fed for Shape A too), then Shape C gets a direct `ITEM CODE`/`ITEM DESCRIPTION` → `sku_code`/`product_name` copy (bypassing the regex, since it's already labeled), then a new `sku_code_status` column (`"matched"` / `"unmatched"` / `"direct"` / `"source_gap"`) is set so a Shape D row is explicitly distinguishable from an ordinary regex refusal.

**Correction to my own Phase 1 finding**: the "third `Sheet1`, still Shape A" observation was accurate about `staging/`'s raw contents, but that sheet's `_sheet_role` is `"scratch"` (it's a SKU pricelist/master-data export, not an inventory count — confirmed by its real columns: `CATEGORY`, `PRODUCT/ SKU CODE`, `DESCRIPTION`, `BASE UNIT`, `SKU BARCODE`, price columns), so `filter_source_of_truth()` already excludes it before any fact-level processing runs (`source_of_truth.yaml`'s `inventory_sign_off` entry requires `system_of_record_role: data`). It never reaches shape classification in production. Not a bug to fix — just a correction to how I described that finding.

### Validation — real staged data only, via the actual `transform_fact("inventory", "delmonte")` call

Total real rows after `filter_source_of_truth()` (data-role only): **5,591** (of 7,019 raw staged rows — the excluded 1,428 are the 6 real `"scratch"`-role pricelist sheets above, correctly filtered before this ever runs).

Shape breakdown: `{A: 2910, B: 2097, C: 411, D: 173}` — sums to 5,591 exactly, zero `UNKNOWN`.

**`sku_code` non-null rate per shape, before vs. after:**

| Shape | n | Before | After |
|---|---|---|---|
| A | 2,910 | 0.0% | **99.3%** (2,889/2,910) |
| B | 2,097 | 98.8% | 98.8% (2,072/2,097) — **unchanged** |
| C | 411 | 0.0% | **100%** (411/411) |
| D | 173 | 0.0% | 0.0% (correctly stays null) |

Matches your expectation exactly: Shape A went from 0% to near-100%.

**Shape B regression check: 0/2,097 rows changed value.** Confirmed row-by-row (`sku_code` before vs. after, exact string comparison) — Shape B was already routing correctly and nothing about it changed.

**`duplicate_column_conflicts`, before vs. after: identical.**
```
[{'canonical': 'pieces', 'conflicting_row_count': 223},
 {'canonical': 'pieces_breakdown', 'conflicting_row_count': 156},
 {'canonical': 'cases_breakdown', 'conflicting_row_count': 155}]
```
Same 3 entries, same counts, both runs — these are pre-existing, unrelated to SKU splitting (packaging/quantity vocabulary conflicts). No new conflicts introduced by the shape dispatch.

**All 395/398 previously-successful splits still succeed** — re-verified directly against the post-fix pipeline's `sku_description_raw` values for Shape A+B combined: 398 distinct real values, 395 successful, exactly the same 3 refusals (`'#REF!'`, `'WH/Stock'`, `'IS-WH/Stock'`), preserved as refusals, not silently passed or guessed.

`sku_code_status` distribution across all 5,591 real rows: `matched=4,961`, `direct=411` (Shape C), `source_gap=173` (Shape D), `unmatched=46` (34 non-null banner/corruption refusals — `'Total'` ×29, `'DESCRIPTION'` ×1, `'#REF!'` ×2, `'WH/Stock'` ×1, `'IS-WH/Stock'` ×1 — plus 12 rows where the source cell was genuinely blank).

Test suite: **32/32 `tests/etl/test_transform.py` pass** after the change.

### Logged for Phase 6 (not acted on)

`DELMONTE_INVENTORY_SIGN_OFF_PANGASINAN_ILOCOS__AUGUST_2023__PANGASINAN-ACTUAL.xlsx` is Shape D — 173/173 rows missing the alpha SKU prefix at source. This is data loss in SSM's own export, not our pipeline. To include in the eventual Phase 6 client re-delivery request list.

### Addendum — accounting for the 21 Shape A rows that didn't split

All 21 are the same class of banner/summary/corruption row already established, not an unhandled pattern:

| Value | Count | Row(s) |
|---|---|---|
| `"Total"` | 17 | row 0 of 17 different real sheets — the per-sheet summary banner |
| `"WH/Stock"` | 1 | row 0, `JANUARY_2023_INVENTORY_SANSAN_PANGASINAN_ILOCOS__PANGASINAN_INVENTORY_SIGNOFF.parquet` |
| `"IS-WH/Stock"` | 1 | row 0, `MARCH_2023_INVENTORY_SANSAN_PANGASINAN_ILOCOS__ILOCOS_INVENTORY_SIGNOF_.parquet` |
| `"#REF!"` | 2 | rows 145–146, `JUNE_2023_INVENTORY_SANSAN_PANGASINAN_ILOCOS__PANGASINAN_INVENTORY_SIGNOFF.parquet` |

17+1+1+2 = 21, exact. Closed — no unhandled pattern, the regex correctly refuses all of them.

### Phase 1 fix — committed

Commit `7e3dfe9`, isolated to `analytics/etl/transform.py` alone (`git status` confirmed only that file was staged). Message frames it explicitly as a real-data pipeline fix (Shape A files producing `sku_code=NULL` for 25/41 real files), independent of the synthetic-data work below.

---

## PHASE 2 — Converter (`scripts/convert_synthetic_to_staging.py`), quarantined to `staging_synthetic/`

Writes only to `staging_synthetic/` — confirmed `staging/` untouched (`git status -- staging/` empty after the run). Read-only on `data/raw/`.

### Finding, reported separately as instructed: the `profile_files.py` doc-type regex bug

`DOC_TYPE_PATTERNS`' `sales_register` pattern (`sale[s]?\s*regist(er)?|daily\s*sales\s*report`) and `sell_out` pattern (`sell\s*out`) both require **whitespace** between the two words via `\s*`/`\s`. The synthetic filenames use an underscore there (`SALES_REGISTER_...`, `SELL_OUT_...`), and `\s` doesn't match `_` (a word character) — same root-cause class of bug as the `PANG_` region-inference fix earlier this session. Confirmed directly: `infer_doc_type(Path("SALES_REGISTER_2021-01_ILOCOS.xlsx"))` and `infer_doc_type(Path("SELL_OUT_2021-01_ILOCOS.xlsx"))` both return `"unknown"`. `INVENTORY_SIGN_OFF_*`/`PURCHASE_ORDER_*` are unaffected — their patterns match via a plain substring alternative (`"inventory"`, `"purchase"`) with no `\s` in the way. **Not fixed** — the converter uses its own explicit `DOC_TYPE_PREFIX_MAP` instead, exactly as instructed.

### Files converted / skipped

**374/374 converted, 0 skipped.** Every file matched the `<PREFIX>_<YYYY-MM>_<REGION>.xlsx` naming pattern the explicit map depends on.

| doc_type | files | rows |
|---|---|---|
| sales_register | 86 | 33,438 |
| sell_out | 92 | 5,386 |
| inventory_sign_off | 92 | 14,662 |
| purchase_order | 104 | 1,909 |

### `inventory_sign_off` shape distribution after era-faithful conversion

**Shape A: 78 files, 12,408 rows** (periods 2021-01 through 2025-02). **Shape B: 14 files, 2,254 rows** (periods 2025-05 through 2026-03 — the synthetic corpus has no 2025-03/04 files, so the first actual Shape B period present is 2025-05, not the 2025-03 cutover itself; cutover logic is period-based, not file-presence-based, so this is just a gap in which months exist, not a converter issue). Verified the Shape B numeric-fragment convention directly against a converted file — e.g. `"DMC43196 DM Four Seasons Blend Juice 155g Tray"` → `__col0__="43196"`, `__col1__="DMC43196 DM Four Seasons Blend Juice 155g Tray"` — matches the real convention derived in Phase 1b (trailing digits of the leading code token). No Shape C or D synthesized, per instruction.

### Provenance repairs applied

- **`_src_file`**: replaced with `data/raw/Synthetic Data/<actual filename>` for every row — a real, existing path. Previously pointed at fabricated stems from a wrong era (e.g. a 2021-01 file carrying `_src_file="PANGASINAN_ILOCOS_JANUARY_2023_SELL_OUT"`).
- **`_period`**: replaced with the period parsed from the filename, so it agrees with the repaired `_src_file` by construction.
- **`_src_sheet`**: also repaired, to the file's actual (single, real) sheet name (e.g. `"Sales Register"`) — not explicitly named in the instruction alongside `_src_file`/`_period`, but the baked-in values showed the identical wholesale-copy problem (e.g. pointing at `"ILOCOS SALES REGISTER"`, a real anchor-row sheet name that doesn't match this file at all), and `Transform`'s `groupby(["_src_file","_src_sheet"])` logic needs this pair internally consistent. Flagging the extension beyond your explicit list here for visibility.
- **`_region`**: cross-checked against the filename-derived region and overwritten to agree (no disagreements found in this run, but the check is real, not assumed).
- **`_sheet_role`**: set explicitly from `source_of_truth.yaml`'s `system_of_record_role` (`"data"` for all four doc_types) rather than trusted from the baked-in value. Baked-in values were independently re-confirmed identical to the set value for every row in this run (matches the earlier finding: 374/374 files already baked in `"data"` correctly) — nothing was silently changed, but the code path no longer trusts it.
- **`is_demo`**: preserved as `True` on every row, untouched.

### Schema mismatches found (reported, not silently coerced or fabricated)

| doc_type | files affected | deviation |
|---|---|---|
| `sales_register` | 86/86 (all) | Missing `Town Display` / `Branch Code` in every file, **regardless of period** — real data only lacks these pre-2024 (confirmed against real staging: real `sales_register` transitions to including them from 2024-01). Synthetic 2024/2025-period files should have them and don't. |
| `purchase_order` | 104/104 (all, opposite direction — not caught by the "missing column" check, found by direct era comparison) | **Has** `Town Display`/`Branch Code` in every file, including pre-2024 periods. Real `purchase_order` has the identical 2024-01 cutover as `sales_register` (verified directly against `staging/purchase_order/*.parquet`: 2023 real files lack both columns, 2024+ real files have them) — synthetic never varies, so pre-2024 synthetic purchase_order rows carry two columns real data of that era never had. |
| `sell_out` | 92/92 (all) | Missing `CASE` — an optional real column present in some 2025+ real exports (`column_maps/sell_out.yaml`'s own comment: "only present in newer (2025+) exports"). Lower severity — it's optional in real data too, not a required field for any era. |
| `inventory_sign_off` | 92/92 (all) | Missing `"in PCS"` — a real business column, though itself only "confirmed header, most 2023 exports" per `column_maps/inventory_sign_off.yaml`'s own note (i.e., not universal in real data either). No synthetic file has it at all. |

None of these were fixed — fabricating values for a column a synthetic row was never given would violate the anti-fabrication rule the same as any other invented data. Reported for your review.

### Manifest fragment

`staging_synthetic/_manifest_fragment.json` — `{"staged": [...374 entries...], "reject": []}`, same field shape as `staging/_manifest.json`'s real entries (`checksum_column`, `checksum_diff`, `checksum_expected`, `checksum_got`, `checksum_status`, `columns`, `doc_type`, `grain`, `period`, `principal`, `region`, `row_count`, `sheet_role`, `src_file`, `src_sheet`). Not merged into `staging/_manifest.json`.

---

## PHASE 3 (partial) — Schema-deviation resolution: sales_register Town Display / Branch Code

Ruling accepted: NULL-filling was rejected (empty regional dashboard tiles); values must be drawn from real co-occurring pairs, not a random cross-product.

**Derivation** (`scripts/convert_synthetic_to_staging.py::derive_town_branch_map()`, reads `staging/sales_register/*.parquet` only): grouped real `(Town Display, Branch Code)` by `_region`, weight = real row count per pair. **87 distinct real Town Display values, 1,345 distinct real Branch Codes, 1,351 distinct real co-occurring pairs.** Checked region separability first: only 2 of 87 town names (`"SAN NICOLAS"`, `"SANTA MARIA"`) appear in both regions — plausibly the same common Filipino place name existing independently in both provinces, not a data artifact — so region-scoped sampling is safe. Per-region breakdown:

| Region | Real rows | Distinct real pairs |
|---|---|---|
| ilocos | 2,562 | 480 |
| pangasinan | 8,629 | 871 |

Full map written to `reports/town_branch_cooccurrence.json` (every real pair + its real weight, per region).

**Distribution method**: each synthetic row gets one pair, sampled with replacement from its region's real pairs, weighted by real frequency (so busy real branches stay busy in the synthetic data, matching real skew rather than spreading rows evenly across all pairs) — never a `Town Display` paired with a `Branch Code` it doesn't really co-occur with. Deterministic: seeded per-file from a stable hash of the filename (`sha256(filename)[:8]` as the RNG seed), not a global sequential generator, so output doesn't depend on file-processing order and is reproducible on re-run.

**Verification**: re-derived the full set of `(Town Display, Branch Code)` pairs actually assigned across all 33,438 synthetic rows and checked every one against the real set — **0 invented pairs** (1,341 distinct pairs used, all 1,341 are real). 87/87 real town names used; 1,335/1,345 real branch codes used.

Converter re-run: `"missing real business column(s)"` note count dropped from 270 files to 184 (exactly the 86 `sales_register` files that no longer trigger it — `sell_out` and `inventory_sign_off`'s separate, still-open deviations account for the remaining 184).

---

## PHASE 3 — Remaining schema-deviation resolutions (b, c, d) + salesman/negative fixes (3a, 3b)

### b) `purchase_order` Town Display / Branch Code — messier than a clean cutover, confirmed

Checked every real file individually rather than assuming a boundary:

| Period | Both regions | Columns present? |
|---|---|---|
| 2023-09, 2023-11, 2023-12 | ilocos + pangasinan | **Absent entirely** |
| 2024-01 onward | ilocos + pangasinan | **Present**, mostly 0% null... |
| **2025-09 ilocos specifically** | — | **Present but 100% NULL** (27/27 rows) — a genuine one-off real source gap, same class as `inventory_sign_off`'s Shape D |

Real null rate among rows where the column exists: **27/414 = 6.52%**, entirely attributable to that single 2025-09-Ilocos file. You were right that it's messier than a clean cutover — but the messiness is a presence-vs-population distinction, not an irregular cutover date: the column-*existence* boundary is a clean 2024-01 (verified, not assumed), and the 2025-09-Ilocos anomaly is a separate, one-off, 100%-null gap layered on top of that clean boundary — not synthesized (a single real one-off file, like inventory's Shape D, isn't a recurring template).

**Applied**: dropped `Town Display`/`Branch Code` from all synthetic `purchase_order` files with period < `2024-01` (66/104 files). 2024-01+ files keep both columns, populated (matching real's ~93.5% non-null rate in that window). Verified directly: `SYNTH__PURCHASE_ORDER_2023-01_ILOCOS.parquet` no longer has them; `SYNTH__PURCHASE_ORDER_2024-03_ILOCOS.parquet` still does.

### c) `sell_out` `CASE` — neither of the two framings offered; left absent

Investigated the real relationship to `Product Quantity` directly: it is **not a per-row ratio** of Product Quantity (the 20 real non-null rows show ratios ranging 0.0 to 1.24 with no fixed relationship). It is instead a **constant keyed to a completely different category vocabulary**: `CASE` only ever appears on rows labeled `"Total"`, `"FRUITS"`, `"CULINARY"`, `"BEVERAGE"`, `"INNOVATION"` — a coarse 5-category summary structure found in exactly 4/34 real files (20/1,573 real rows) — and those 5 labels never overlap with the fine-grained `category_path` vocabulary (e.g. `"/DISPENSER JUICE/DISPENSER JUICE"`) every synthetic row and the other 30/34 real files actually use. Real overall null rate: **98.73%** (20/1,573).

Populating `CASE` on synthetic rows would mean inventing a relationship between two structurally incompatible real row shapes that synthetic data doesn't represent at all — not a deterministic conversion, not a samplable ratio, and not something to force-fit. **Left absent (100% null)**, which is arguably a closer match to the real 98.73% null rate than adding the column would produce. Documented in code rather than silently skipped.

### d) `inventory_sign_off` `in PCS` — derivable, applied within its real presence window only

Derived formula: **`in PCS = in Cases × PKG`**, confirmed on **1,193/1,211 (98.5%)** real rows carrying all three columns (the 18 mismatches are `in Cases = 0` edge cases, not representative of the general rule). Real presence itself is narrow — only 8/41 real files, all within **2023-08, 2023-09, 2023-12, 2024-01** (matches `column_maps/inventory_sign_off.yaml`'s own note: "confirmed header, most 2023 exports"). Real overall null rate across all 7,019 real rows: **82.62%**.

Applied the formula only within that real presence window, per your "if real data leaves a column mostly null, synthetic should too" instruction. **In practice this has zero effect on the current synthetic corpus**: the 92 synthetic `inventory_sign_off` files' periods don't overlap the 2023-08/09/12/2024-01 window at all (closest synthetic periods are 2023-07, 2023-10, 2023-11). The derivation is implemented and correct (verified the formula itself against real data), but 0/92 converted files end up with `in PCS` populated — reporting this rather than silently claiming it "worked."

### 3a) Salesman names — remapped, region-scoping preserved

**33 real distinct Salesman names** loaded from `staging/sales_register/*.parquet`. Checked region-scoping first, same question as Town Display: **30/33 real names appear in exactly one region**; 3 (`"ADMIN SALES"`, `"ELYSSA L. MASON"`, `"ENCODER"`) appear in both.

Synthetic data has 9 distinct names; checked each one's region(s) directly — **already internally region-scoped one-name-per-region**, except `"OFFICE SALES"` (the one already-real name), which correctly appears in both regions in synthetic data too, matching its real behavior. The other 8 are invented and were remapped 1:1 onto that region's real single-region roster, both sides sorted alphabetically for a fully deterministic (non-random) assignment:

| Invented | Region | Remapped to (real) |
|---|---|---|
| EDWIN TABUCOL | ilocos | BARBI LABRADOR |
| MARISSA GALLARDO | ilocos | CARLON DAHILIG |
| RODEL BUMANGLAG | ilocos | FREDERICK C. GUZON |
| ARNEL SORIANO | pangasinan | ANNA MARIE MANAPSAL |
| ELMER CASTANEDA | pangasinan | ANNET QUIEN COSI |
| GRACE PALAGANAS | pangasinan | BENJAMIN AQUINO |
| JOVIT MANANSALA | pangasinan | CORFEL PARAS |
| NOEL DE VERA | pangasinan | DERICK PRIDAS |

Written to `reports/salesman_remap.json`. Applied and verified: converted synthetic output's distinct `Salesman` values are now exactly `{ANNA MARIE MANAPSAL, ANNET QUIEN COSI, BARBI LABRADOR, BENJAMIN AQUINO, CARLON DAHILIG, CORFEL PARAS, DERICK PRIDAS, FREDERICK C. GUZON, OFFICE SALES}` — all real, all region-correct.

### 3b) Sell Out negative quantities — exact rate measured, real magnitudes sampled

**Exact real negative rate: 33/1,539 non-`"Total"` rows = 2.1442%** (not the audit's approximate ~2.1%). `"Total"` banner rows were excluded from both the eligible pool and the rate's denominator — a summary-row aggregate isn't independently eligible to roll negative. Magnitude distribution of the 33 real values: right-skewed, mean -1.17, median -0.42, min -8.5 (largest real negative), max -0.042 (closest to zero) — sampled directly from this exact real list (with replacement), never a fitted/parametric distribution, so every injected value is one SSM's own export actually reported.

**Applied and verified**: synthetic negative rate came out to **115/5,294 non-`"Total"` rows = 2.1723%** — close to the 2.1442% target but not exact, because **9 rows in the original synthetic generation were already negative before my injection ran at all** (confirmed directly against the raw `.xlsx` files, pre-conversion — an artifact of whatever process generated the synthetic data, not something this converter introduced). My injection's eligible pool doesn't exclude already-negative rows, so there's some harmless overlap rather than a clean additive count. Reporting this rather than tuning it to land exactly on target.

### 3c) Net Amount duplicate clustering — target discrepancy flagged, resolved with my own verified figure

**Could not reproduce 44.14% from real data under any definition tried against `staging/sales_register/*.parquet`:**

| Definition | Result |
|---|---|
| Standard: rows whose value repeats elsewhere / all non-null rows | **52.5316%** (9,815/18,684) |
| String-exact instead of numeric-coerced | 52.5316% (identical here) |
| Denominator = all rows including null Net Amount | 41.2101% |
| Ilocos region only | 25.4934% |
| Pangasinan region only | 58.1902% |

None match 44.14%. Used the standard rows-basis definition (**52.5316%**) as the real target instead, since it's the one I can directly cite (file path, exact counts) and reproduce on demand — flagged here rather than silently substituted.

**Empirical resampling, no parametric fit**: built the full real Net Amount multiset (18,684 non-null values, natural frequency preserved) from `staging/sales_register/*.parquet`. For each synthetic file, overwrote a fraction of rows' Net Amount values with values drawn (with replacement) directly from that real multiset — every injected value is one SSM's own export actually reported, never a fitted/generated number. Calibrated the injection fraction by empirical search against the full 33,438-row synthetic corpus (no closed-form relationship between draw fraction and resulting collision rate, so found it by trying candidates): 0.60→50.91%, 0.61→51.82%, **0.62→52.87%**, 0.63→53.71%. Locked in **62%**, not tuned further.

**Achieved, verified against the actual converted output**: **52.754%** synthetic duplicate rate (was 0.64%) against a **52.532%** target — **gap +0.223pp**. Row count preserved exactly (33,438, unchanged). `staging/` confirmed untouched throughout.

**One implementation issue worth flagging**: the first attempt formatted injected values as `"1234.56"`-style strings, assuming synthetic Net Amount cells were strings (based on an earlier openpyxl spot-check). That crashed `to_parquet()` — `pandas.read_excel()` actually auto-parses this column to plain `float` for most files, inconsistently with openpyxl's raw-cell string reads, and mixing `str` and `float` in one column is exactly what pyarrow correctly refuses to write. Fixed by detecting each file's actual existing type before choosing whether to inject a formatted string or a plain float, rather than assuming one convention across all 86 files.

---

*Phase 3 (items a/b/c/d, 3a, 3b, 3c) complete. Phases 4-6 not started.*
