# SOH Sheet Profile — Step 1 Discovery

Scope: `data/raw/SSIS/**` and `data/raw/Unilever/**` (106 raw files scanned:
39 under SSIS/, 67 under Unilever/ — one of which,
`UnileverLaUnionSalesperSKU2023to2026.xls`, is not an ssis_summary file and
was excluded). No extractor, YAML, or migration was written. This is a
read-only discovery pass using a throwaway script
(`scratch/profile_soh.py`), reusing the existing header-detection logic
from `profiling/detect.py` and `profiling/reader.py` so results are
consistent with how the rest of the corpus is profiled. `profiling/` and
`staging/ssis_summary/` were NOT trusted as ground truth for this report —
`profiling/file_inventory.csv` references a `data/raw/SANSAN MARKETING_*`
folder layout that no longer exists in this working tree, so it's stale.
Everything below was computed fresh against the current raw files.

**102 of 106 files contain a sheet whose name matches `SOH`.** The 4 that
don't are 3 early-2021 Unilever files (`SSIS MONTHLY SALES REPORT (FEB.
01-28, 2021)`, `... (JAN. 01-31, 2021)`, `... (MARCH 01-31,2021)`) whose
inventory sheets are named `INVENTORY` / `STOCK CARD(...)` instead — the
`SOH` naming convention only starts appearing from the April 2021 file
onward — plus the La Union file (different source entirely, no SOH sheet).

---

## a/b. Full file list, row counts, header stability

All 102 SOH sheets reduce to **9 distinct header signatures**. All 9 are
supersets of the confirmed 14-column list — nothing drops a column that's
actually load-bearing, but the tail columns are unstable in both name and
presence.

| # | Sheets | Header (as found) |
|---|---|---|
| 1 | 27 | Storage Location, Article No, Article Description, PACK SIZE, Stock Quantity (CS/PC), Stock Value, PO Qty, Open SO Quantity, Balance Quantity, **Last Purchase Price(GSV/CS)**, Status, CATEGORY DESC, Sales Route, Batch, Hierarchy Node, Blocked Stock(CS/PC), Sales Route Description |
| 2 | 25 | Storage Location, Article No, Article Description, PACK SIZE, Stock Quantity (CS/PC), Stock Value, PO Qty, Open SO Quantity, Balance Quantity, **Last Purchase Price(GSV/CS)**, Status, CATEGORY DESC, Blocked Stock(CS/PC), Batch — *(exactly the confirmed 14-column list, no extras)* |
| 3 | 21 | Storage Location, Article No, Article Description, PACK SIZE, Stock Quantity (CS/PC), Stock Value, PO Qty, Open SO Quantity, Balance Quantity, **MOVING AVERAGE PRICE(CS)**, Status, CATEGORY DESC, Sales Route, Batch, Hierarchy Node, Blocked Stock(CS/PC), Sales Route Description |
| 4 | 8 | Storage Location, Article No, Article Description, PACK SIZE, Stock Quantity (CS/PC), Stock Value, PO Qty, Open SO Quantity, Balance Quantity, **MOVING AVERAGE PRICE(CS)**, Status, CATEGORY DESC, Sales Route, Batch |
| 5 | 7 | ...same as #4 plus **Hierarchy Node** |
| 6 | 6 | Storage Location, Article No, Article Description, PACK SIZE, Stock Quantity (CS/PC), Stock Value, PO Qty, Open SO Quantity, Balance Quantity, **Last Purchase Price(GSV/CS)**, Status, CATEGORY DESC, Sales Route, Batch |
| 7 | 4 | ...same as #4 minus **Batch** |
| 8 | 2 | ...same as #4 plus a trailing unlabeled `__col14__` (SSIS MONTHLY JUNE 2021 / the duplicate Unilever copy of it — genuinely blank extra column in the source) |
| 9 | 2 | 3 leading unlabeled columns (`__col0__`,`__col1__`,`__col2__`) then the full 20-col list (Unilever APRIL 2023 / MAY 2023 "SOH" sheets) — verified this is 3 truly blank leading columns before `Storage Location`, not a header-detection misread; row 0 is still the real header row |

**Deviations from the 14 confirmed columns, quoted verbatim:**
- Extra, present in most files: `Sales Route`, `Hierarchy Node`, `Sales Route Description` — always blank or low-value ("VALUATED", route codes), never populated with anything the confirmed 14 columns don't already carry.
- **Price column split (confirmed):** `Last Purchase Price(GSV/CS)` appears in files from **Jan 2023 onward** (57 sheets); `MOVING AVERAGE PRICE(CS)` appears in **2021–Dec 2022** files (35 sheets — note the pricing methodology changed, not just the label; these are not simply a renamed column and should not be silently unioned as one field).
- `Blocked Stock(CS/PC)` is **missing** from 24 files, scattered across both eras (not a clean cutover) — e.g. all of 2024's `SOH(JANUARY 2, 2025)` / `SOH(DECEMBER 2, 2024)` and most of 2025 lack it, while most of 2024's other months have it.
- `Batch` is missing from 2 files only (`SSIS FEBRUARY.2022`, `SSIS MARCH.2022`, and their Unilever duplicates).

Full per-file table (file · sheet name · populated data rows · header count) is in `scratch/soh_file_table.tsv` (not committed; regenerate via `scratch/profile_soh.py` if needed).

---

## c. Dedupe by snapshot date

Parsed the raw snapshot-date token out of each `SOH(...)` sheet name (no normalization ruling applied yet — this is exactly why Step 1 stops here). **38 distinct dates have more than one file.**

**Verdict: yes, `data/raw/SSIS/` and `data/raw/Unilever/` are the same months twice.** For all 37 of the 38 multi-file dates that have exactly 2 files, one from each folder, row counts and Article No sets are **byte-identical** between the SSIS/ copy and the Unilever/ copy. Concretely:

- SSIS/ contains 2021, 2022, 2024, 2025, 2026 files.
- Unilever/ contains 2021 (7 files), 2022 (7 files), and a complete monthly run 2023–2025.
- Every SSIS/2021, SSIS/2022, SSIS/2024, SSIS/2025 file has an exact duplicate in Unilever/ (same row count, same Article No set) — confirmed for **37 date-pairs**.
- **Unilever/2023 (12 months) is NOT duplicated anywhere in SSIS/** — SSIS/ has no 2023 folder at all. This is the one place Unilever/ has data SSIS/ doesn't.
- **SSIS/2026 (3 files) is NOT duplicated anywhere in Unilever/** — Unilever/ has no 2026 files. This is the one place SSIS/ has data Unilever/ doesn't.
- A handful of pairs (`2021-01-30` vs `2022-02-03`-style near-misses) look like the same underlying export with a slightly different snapshot-date label between the two copies (e.g. `JANUARY.2022.xlsx` labels its SOH sheet `FEB.3,2022` while nothing in Unilever/ parses to exactly that token, likely due to a stray period/space in the source label) — flagged in the raw JSON as `SSIS-only` / `Unilever-only` dates, worth a manual spot-check rather than assuming they're independent snapshots.

**One real anomaly:** the `2021-06-30` group has **4 files but 2 distinct payloads** — `SSIS MONTHLY JUNE 2021.xlsx` (952 rows) and `SSIS MONTHLY JULY 2021.xlsx` (904 rows) both carry a SOH sheet literally labeled `SOH(JUNE 30, 2021)`, with different data. One of these is almost certainly mislabeled by the source (a "beginning of July" snapshot mislabeled as June 30, or vice versa) — needs a ruling, not an assumption, before either is picked as canonical for 2021-06-30.

**One likely source-data typo worth flagging:** `SSIS DECEMBER 2025.xlsx`'s SOH sheet is labeled `SOH(JANUARY 05, 2025)` — the year should almost certainly be **2026** (a December-2025 snapshot's month-end SOH can't be dated January 2025, a year in the past). Its Unilever/ duplicate carries the identical mislabel. This affects the sort order if snapshot_date is taken from the label at face value.

---

## d. Stock Quantity (CS/PC) format

Checked all populated values across all 102 sheets (not just samples). **Always the `cases/pieces` slash format** (`CS/PC`), e.g. `4/1`, `0/143`, `191/1`. No bare integers, no blanks (blank cells are excluded from the row already by header-alignment), and **no negatives found anywhere in the corpus**.

---

## e. Article No join rate vs. real Unilever sku_code universe

Join universe: `staging/unilever_sku/UnileverLaUnionSalesperSKU2023to2026__sheet1.parquet` (`Product` column), the only confirmed real, non-synthetic Unilever SKU-code source per CLAUDE.md — **1,807 distinct codes**.

**The join rate is not flat — it trends sharply upward over time, from ~53% in early 2021 to ~96% in 2025.** The user-supplied figure of 686/716 (≈96%) reflects the *current* state (matches `SSIS SEPTEMBER 2025`, 686/715 populated Article Nos exactly), not the historical average. Aggregated across all 102 sheet-instances (including the SSIS/Unilever duplicate pairs): **61,449 / 76,920 ≈ 79.9%**.

| Period | Join rate |
|---|---|
| 2021 (all months) | 51–65% |
| 2022 | 66–80% |
| 2023 | 80–90% |
| 2024 | 90–94% |
| 2025–2026 | 88–96% |

This looks like La Union's SKU roster (2023–2026 coverage per its filename) simply not covering the wider, older SSIS SKU universe — non-matches concentrate in codes with the `20xxxxxx` / `21xxxxxx` prefix pattern (older/legacy article numbering) alongside plenty of `6xxxxxxx`/`67xxxxxx`/`68xxxxxx`/`69xxxxxx` codes that don't appear in La Union at all in any period. Non-matching samples:

- `SSIS SEPTEMBER 2025` (2025-09, 96% join): `68736088, 68562180, 64406387, 64406389, 69664189, 64803599, 64898713, 64975221, 64898710, 64975191, 64357125, 64865070, 69668179, 68130755, 68777823, 64890453, 68565222, 68565208, 64356058, 64888791, 64876002, 64876146, 67010161, 62681033, 65064577, 68541083, 68582337, 63914556, 64882229` (29 of 30 shown — file has only 30 non-matches total)
- `SSIS MONTHLY JANUARY-JUNE 2021` (2021-01, 53% join): `20248034, 21147708, 67842079, 67088660, 21058471, 67604474, 67136166, 67842077, 67064977, 67634846, 67633691, 67633693, 67064981, 67488443, 67424017, 67666681, 67424000, 67556620, 67556622, 67060705, 67556636, 67782910, 67782906, 67065022, 67099164, 67065020, 67149590, 67149586, 67149588, 67321277`

Full non-match lists per file (30-ish each) are in `scratch/soh_profile_raw.json` under `article_nonmatch_sample`.

---

## f. CATEGORY DESC vocabulary

**20 distinct values across the whole corpus, not 12.** All are clean, real category names (no near-duplicate casing/whitespace variants found) — this vocabulary looks stable across eras, unlike Del Monte's; every category present in 2021 files is also present in 2025 files.

| Rows | CATEGORY DESC |
|---|---|
| 15,659 | HAIR CARE |
| 13,420 | FABRIC CLEANING |
| 11,266 | SKIN CARE |
| 8,562 | DEODORANTS & FRAGRANCES |
| 6,568 | SKIN CLEANSING |
| 4,627 | DRESSINGS |
| 4,370 | FABRIC ENHANCERS |
| 4,306 | SCRATCH COOKING AIDS |
| 2,615 | ORAL CARE |
| 2,081 | HOME & HYGIENE |
| 1,426 | CONDIMENTS |
| 1,285 | COOKING AIDS |
| 244 | OTHER FOODS |
| 151 | TEA |
| 151 | OTHER NUTRITION |
| 100 | BEVERAGES |
| 28 | SNACKING |
| 27 | MINI MEALS |
| 24 | NON CORPORATE PERSONAL CARE CATEGORY |
| 10 | HEALTHY SNACKING |

(Row counts are summed across all 102 sheet-instances, i.e. include the SSIS/Unilever duplicate pairs counted twice — halve roughly for a true per-snapshot estimate once the dedupe rule is set.)

---

## g. Storage Location

**Single value everywhere: `SALE`.** No other Storage Location value appears in any file, any era. This column carries no discriminating information in this corpus.

---

## Open questions for your ruling before Step 2

1. **Dedupe rule**: SSIS/ and Unilever/ are the same 37 months twice, byte-identical — which folder is canonical, or do we key strictly on parsed snapshot_date and ignore folder? Unilever/2023 and SSIS/2026 are each folder's unique contribution and must both be kept.
2. **`2021-06-30` conflict**: two genuinely different payloads share the same sheet label — need a source ruling (or drop one) before it's safe to load either as canonical for that date.
3. **`SSIS DECEMBER 2025` → `SOH(JANUARY 05, 2025)` mislabel**: treat as `2026-01-05`, or flag/exclude?
4. **Price column semantics**: `Last Purchase Price(GSV/CS)` (2023+) vs `MOVING AVERAGE PRICE(CS)` (2021–2022) — same target field with an era-based rename, or two different metrics that shouldn't be unioned into one column? (Same shape of question CLAUDE.md already flags for this split.)
5. **Snapshot-date normalization**: sheet-name date tokens are inconsistently formatted (`MARCH1,2022` vs `MARCH 01, 2025` vs `Oct. 30, 2021`) — confirms a normalizer is needed; fine to build in Step 2 once the above are settled.
