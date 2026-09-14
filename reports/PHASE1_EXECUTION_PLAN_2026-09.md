# Phase 1 — execution breakdown (verification done, build pending review)

**2026-09-09.** Scope confirmed by Yuan: **ETL fixes + canonical load into a
scratch schema. No live DB writes, no reset. Stop at the Phase 1 gate.**

Dispatch messages (`DISPATCH_MESSAGES_2026-09.md`) and the provisional decision
log (`PROJECT_STATE_2026-09.md` §6, items 17–18 + P-A/P-B/P-C) are done. This doc
is the verification sweep result + the concrete build list, for your review before
I write the loader.

---

## What the verification sweep found

### The canonical load does not exist as runnable code — it must be built

`analytics/etl/load.py` is a **library** (`load_to_supabase`, `resolve_dimension_fk`,
the two gates). Grep across `scripts/`, `scratch/`, and the drivers: **nothing
calls `load_to_supabase` except `tests/etl/test_load.py`.** `transform_driver.py`
builds a classification manifest and **discards** the transformed frames
(`report["mapped_df"]` never leaves `_classify_fact_principal`). So there is no
code path from raw files to DB rows for the six base facts. The live DB's demand /
sales / inventory / sellout rows came from ad-hoc `scratch/` scripts (only
`ssis_soh` still has its scratch trio committed; the rest are gone).

**Phase 1d = write that orchestrator.** ~250–350 lines, new file
`scripts/run_canonical_load.py` (or `analytics/etl/load_driver.py`).

### Fresh manifest state (staging Aug-20, transform Aug-20 — Phase 0 did not regenerate them; data/raw unchanged since)

| | staged | reject |
|---|---|---|
| `staging/_manifest.json` (Extract) | 1,590 | **0** |
| `transform/_manifest.json` (Transform) | 669 | **921** |

**The 921 transform rejects break down as:**

| count | doc_type | reason | disposition |
|---|---|---|---|
| 661 | `ssis_summary` | `natural_key: null` for `sales.unilever` | **dead mapping — remove it** (Phase 0: ssis_summary has no product grain, no fact destination, 0 real DB rows). Reclassifies as clean `demoted`. |
| 144 | `ssis_summary` | unrecognized `_principal` | same fix clears these |
| 49 | `purchase_order` | dedup conflict on `(invoice_num, principal, region)` | **real — needs resolution** (1b) |
| 44 | `rmr_gs_bo` | dedup conflict on `(return_slip_num, principal, region, return_type)` | **real** (1b) |
| 11 | `inventory_sign_off` | dedup conflict on `(sku_code, snapshot_date, region)` | **real** (1a) |
| 7 | `sell_out` | dedup conflict on `(category_path, region, _period)` | **real** (1a) |
| 5 | `sales_register` | dedup conflict on `(invoice_num, principal, region)` | **real** (1a) |

**Loadable today (promoted sheets):** sales_register 214, sell_out 129,
inventory_sign_off 126, purchase_order 87, unilever_sku 31.

---

## Build list

### 1a — column-map gaps

| Item | Finding | Action |
|---|---|---|
| `sell_out.category_path` "unmapped" (ARCHITECTURE.md:197) | **STALE.** `sell_out.yaml` maps `category_path` from `__col0__`; transform promotes 129 sell_out sheets with no unmapped-canonical block; live `sellout_fact_real` has 98 categories populated. | Close the note as stale in Phase 5. No code change. |
| `inventory_sign_off` 3rd header shape (ARCHITECTURE.md:196) | Not yet reproduced — 126 promoted, 6 demoted, 11 conflicts, **0 blocked/unknown** in the current manifest. The "3rd shape" may already be handled or may not be in `data/raw/`. | Re-run Extract+Transform fresh; if any `inventory_sign_off` sheet blocks on shape, extend `inventory_sign_off.yaml` + `transform._classify_inventory_sku_shape`. Else close as stale. |
| `sales_register` multi-vocab collision (ARCHITECTURE.md:195) | 214 promoted, only 5 conflicts. No mass blocking. | Add a mixed-era fixture test to `tests/etl/`; confirm `_coalesce_duplicate_columns` covers all 3 eras. Fix only if the test fails. |
| **7 sell_out + 5 sales_register + 11 inventory conflicts** | Real same-key rows disagreeing on the amount column. | Inspect each conflicting group (script, read-only); resolve by either a natural-key fix (missing discriminator column) or a documented "keep-latest / sum" rule in `dedup_facts`. Log each. |

### 1b — orphaned families + system-of-record

| Item | Finding | Action |
|---|---|---|
| `ssis_summary` → `sales.unilever` | Dead: `natural_key: null`, 805 rejects, 0 real rows, no product grain. | **Remove the `sales.unilever` block** from `source_of_truth.yaml` (keep `ssis_summary` as a `cross_check_doc_types` entry only). Update `schema.sql` `Sales_Fact` comment. 805 rejects → demoted. |
| `sales_return` doc_type (8th family, 68 sheets) | **No `source_of_truth.yaml` owner** — `_doc_type_owners` maps the `sales_return:` section to doc_type `rmr_gs_bo`, so all 68 `sales_return` sheets are demoted. | Decide system-of-record for `SalesReturn_Fact`. **Recommend `sales_return`** (fuller 2023–2025 family) over `rmr_gs_bo` (Oct/Nov-2025 only). Add its `source_of_truth.yaml` entry + column map; resolve the 44 `rmr_gs_bo` conflicts or retire that path. |
| `rmr_gs_bo` 44 conflicts | Real dedup conflicts on the return key. | If `sales_return` becomes SoR, `rmr_gs_bo` drops to cross-check and the conflicts stop mattering. Otherwise resolve. |
| `purchase_order` 49 conflicts | Real — same `(invoice_num, principal, region)` with different `net_amount`. | Inspect; likely needs a line-item or date discriminator in the key, or a documented aggregation. Feeds `Purchase_Fact` (353 real Del Monte rows today). |
| `ssis_soh` not in `FAMILY_PARSERS` | Confirmed — `analytics/etl/extract/ssis_soh.py` + `transform_ssis_soh.py` exist, run only via `scratch/run_ssis_soh_*.py`. | **Sanction as a separate sanctioned driver** (`scripts/run_ssis_soh_pipeline.py`) with its own manifest, OR wire into `driver.py`/`transform_driver.py`. Recommend the former — its grain (snapshot) and transform differ enough that folding it into the generic fact driver adds risk. The canonical loader calls both. |
| `SalesReturn_Fact` `return_type`-NULL-in-UNIQUE gap (schema.sql:257-273) | Postgres `UNIQUE` treats NULL≠NULL → rows with null `return_type` silently not deduped. | Migration `0011`: `COALESCE(return_type,'UNKNOWN')` in the constraint or a `NOT NULL DEFAULT`. |

### 1c — category + brand propagation (enables D1/D2/D4/P1)

| Item | Action |
|---|---|
| `Product_Dimension.category_path` NULL for 1,807 UL demand SKUs | Migration `0011` + loader step: for each UL demand SKU, `category_path` = most-recent SOH snapshot `CATEGORY DESC` (DEC-21). **Direct match ceiling 79.0%** (verified). Then description-keyword rule **at confidence ≥ 0.6** (validated OOS: 94.6% overall, 97.4% at ≥0.6) for the rest. Then `UNCLASSIFIED` (0.2% of revenue, 0 Tier A — immaterial). Keyword table committed as a fixture, regenerated at load. |
| `Product_Dimension.brand` written by no code | Loader step: populate `brand` from SOH `Article Description` brand-token rule (or migration). Document the token list as a committed fixture. |
| `Inventory_Fact.quantity_on_hand` unit contract | Add `-- UNIT: CASES` schema comment; audit `dashboard.py:254`, trapped-capital calc, PR4 all multiply by `pack_size`. (Consumer audit only — no data change.) |

### 1d — canonical load into a SCRATCH schema

1. **New `scripts/run_canonical_load.py`:**
   - create/refresh a Postgres schema `ssm_canonical` by executing `schema.sql`
     (+ migrations 0001–0011) with `search_path` set to it — never touches
     `public`.
   - for each `(fact, principal)` in `source_of_truth.yaml`: `transform_fact` →
     `clean_pipeline` → build `DimensionFKSpec`(s) → `load_to_supabase(...,
     manifest_path=staging/_manifest.json, transform_dir=transform/)`.
   - `ssis_soh` path: `transform_ssis_soh` → `Inventory_Fact` load + the
     `Product_Dimension` category/brand backfill frame.
   - both gates must pass. `check_reject_rate_gate` currently trivially passes
     (Extract reject list empty) — **that is not evidence of transform quality**;
     the real check is the transform manifest reject count going to ~116 (real
     conflicts only) and then to 0 as 1a/1b land, plus the scratch-vs-live diff.
2. **`transform_signoff.py --decision approved --by "Yuan"`** to create
   `transform/_signoff.json` (never existed).
3. **Diff `ssm_canonical` vs `public` row-by-row** per table; investigate every
   delta; write `reports/SCRATCH_VS_LIVE_DIFF.md`.
4. **Stop.** Cutover is a separate, deliberate decision — not part of this phase.

### 1e — Del-Monte-readiness

Every loader step takes `principal`; no `WHERE principal='unilever'` in the
loader. Del Monte column maps (`sell_out` ✅, `purchase_order` ✅, `sales_return`
❓, `inventory_sign_off` ✅) — log `sales_return` Del Monte coverage. DEC-03
Jan-2025 taxonomy break: loader loads both eras with an `era` marker; bridge/split
ruling stays open (decision item 16). Test the Del Monte path against the 1,539
real sell-out rows in `ssm_canonical`, then leave unpopulated.

---

## Proposed order (each a reviewable commit-sized chunk)

1. `source_of_truth.yaml` — remove dead `sales.unilever`; add `sales_return` SoR entry (**1b**)
2. Conflict-inspection script + resolutions for the 116 real conflicts (**1a/1b**)
3. `sales_return` column map + `SalesReturn_Fact` key fix → migration `0011` (**1b**)
4. Migration `0011` — category_path + brand columns/backfill, SOH unit comment, return_type key (**1c**)
5. `scripts/run_ssis_soh_pipeline.py` — sanctioned SOH driver (**1b**)
6. `scripts/run_canonical_load.py` — the orchestrator (**1d**)
7. Scratch-schema load run + both gates + `SCRATCH_VS_LIVE_DIFF.md` (**1d**)
8. Del Monte path smoke test (**1e**)
9. **GATE** — review the diff, decide cutover separately

**No live DB writes in any step. Steps 1–5 are code/config only; 6–8 write only to
the `ssm_canonical` scratch schema.**

---

# PROGRESS LOG

## Schema-safety confirmation for `ssm_canonical` (2026-09-09) — CLEAR

Grepped the whole repo for schema qualification / `search_path` / `schema=` /
`schema_translate_map` / `CREATE SCHEMA`:

- **No code sets a schema or `search_path`.** Every table reference in `backend/`
  and `analytics/` is unqualified (`SELECT ... FROM abc_classification`), resolving
  against the connection's default `search_path` = `public`.
- Connections: `backend/deps.py` `create_engine(db_url, pool_pre_ping=True)`,
  scripts use `psycopg2.connect(SUPABASE_DB_URL)` — no `options=-csearch_path`
  anywhere, none in `.env`.
- `information_schema` references (2) are in report `.md` files, not code.

**Conclusion:** nothing can read or write `ssm_canonical` accidentally. **Rule for
the loader:** it must set `search_path` to `ssm_canonical` **per-session only**
(connection `options` or `SET LOCAL`) — never `ALTER ROLE/DATABASE ... SET
search_path` (that would leak to every other connection).

## The 116 dedup conflicts — pattern per family (read-only analysis, before any resolution)

Ran `transform_fact` per `(fact, principal)`, regrouped `mapped_df` on the natural
key, classified every amount-conflict group. **The five families have five
different root causes — they need five different fixes.**

### `purchase_order` — 274 groups — **BROKEN KEY COMPONENT (not real duplicates)**
`BILL/2024/0001` appears once for the Ilocos site and once for the Pangasinan
site — **genuinely different purchase invoices** sharing a bill number across the
two regional sites. They collide because the key's `region` = the literal string
`'False'` for both. Root cause: `purchase_order.yaml` maps `region` from a
raw town/municipality column that is half-blank (values seen: `pangasinan 909`,
`False 719`, `'False' 387`, `ilocos 438`, then a long tail of town names). The
clean site-level split is in `_region` (`pangasinan 1859 / ilocos 844`) but
`backfill_provenance_fields` only fills *nulls*, and the mapped column has literal
`'False'` strings, so provenance never wins.
**Fix:** drop the bogus `region` mapping from `purchase_order.yaml` → `_region`
populates `region` cleanly → `BILL/2024/0001` becomes 2 distinct keys. Most of the
274 dissolve. Zero data invented.

### `rmr_gs_bo` — 225 groups — **MOOT (now cross-check) + dtype artifact**
`return_slip_num 39308` appears 3× with **identical** net_amount, untaxed,
discount, balance — only `invoice_date` and `_row_ordinal` differ (same slip
re-listed across monthly snapshots). Half the "conflict" is a **dtype artifact**:
`Decimal('88.57')` vs the string `'88.57'` count as distinct in `nunique`.
**Fix:** none needed — `rmr_gs_bo` is demoted to cross-check as of step 1. For
`sales_return` (the new SoR) the loader coerces `net_amount` to numeric before
dedup so the Decimal-vs-str artifact can't occur, and a slip repeated verbatim
across months is a true duplicate (safe collapse).

### `sales_return` — 14 conflict sheets — **same-slip-different-month + 11 header rows**
Same pattern as rmr_gs_bo (fuller data). Plus **11 rows literally carrying
`Return Type == "Return Type"`** — an unstripped header row — and 27 rows with a
null Return Slip #. **Fix:** numeric coercion before dedup; drop the 11 header
rows (`Return Type` not in `{GS, BO, NULL}`) at transform; null-key rows load with
`fk NULL`, never guessed.

### `inventory_sign_off` — 127 groups — **NEEDS A DISCRIMINATOR (possibly real multi-line)**
`9DMC57604 / 2026-04-01 / pangasinan` has **4 rows**, quantities 0.67 / 36 / 24.9 /
29, each with its own cost, valuation, `cases`, `pieces`. These look like **4
separate stock lines for one SKU in one snapshot** — different bins or a
good/damaged/near-expiry split (the sheet has `NEAR EXPIRY/ EXPIRED`, `DAMAGED`,
`VARIANCE` columns). The mapped frame also has header-recovery garbage column
names (`'68649'`, `'2902.08...'`) — likely the "3rd header shape" from 1a.
**Fix:** NOT decided — needs the raw sheets inspected to see whether a
bin/condition column separates the lines (→ add to key) or the source genuinely
double-lists (→ sum, documented). **Bring findings before applying a rule.**

### `sell_out` — 16 groups — **MULTI-SHEET DOUBLE-COUNT**
`CULINARY / pangasinan / 2026-08` has 4 rows: `2.35M`, `2.24M`, **`14.87M`**,
`2.41M`. The 14.87M row looks like a month total sitting alongside 3 partials;
others look like the same category on 2 sheets of one workbook. Only `quantity`
and `_row_ordinal` differ. `exclude_sell_out_total_rows` catches `category_path ==
"Total"` but not this.
**Fix:** NOT decided — needs the source sheet of each conflicting row identified
(is one a different `_sheet_role`? a sub-total row?). **Bring findings first.**

### `sales_register` — 28 groups — **GENUINE INVOICE-NUMBER REUSE**
`INV/2024/0542 / delmonte / SANTA MARIA` = two completely different invoices
(different customer, salesman, date, branch) sharing a number. 28 of 56,968 rows
(0.05%). `invoice_date` + `return_slip_num` splits ~half; the rest have no
discriminator.
**Fix:** add `invoice_date` to the key where it separates; for the residual with
no discriminator, keep both rows flagged (never silently pick one). Migration 0011
candidate. Low volume.

**Summary:** 2 of 5 are clean config fixes (`purchase_order` broken region;
`rmr_gs_bo` moot). 1 is a transform hygiene fix (`sales_return` coercion + header
rows). **2 (`inventory_sign_off`, `sell_out`) need the raw sheets inspected before
any rule — reporting those next, not applying anything.**

## Step 1 — DONE & VERIFIED (2026-09-09)

**`config/source_of_truth.yaml`:**
- Removed the dead `sales.unilever → ssis_summary (natural_key: null)` block;
  replaced with a documented "EXCLUDED — no fact destination" comment block.
  `_doc_type_owners` now returns `None` for `ssis_summary` → its ~805 sheets
  classify as clean `demoted`, not `blocked`.
- `sales_return.both`: `doc_type` `rmr_gs_bo` → **`sales_return`**;
  `system_of_record_role: [gs, bo, data]`; `cross_check_doc_types: [rmr_gs_bo]`.
  `rmr_gs_bo` now `None`-owner → demoted (cross-check only).

**`config/column_maps/sales_return.yaml`** — new. Maps `return_slip_num`,
`invoice_num`, `return_type`, `net_amount`, `is_demo`. Deliberately does **not**
map `region` (→ `_region` provenance, site-level) or `return_date` (no real return
date column — flagged).

**Transform manifest rebuilt** (`transform/_manifest.pre_phase1_20260909.json` =
backup):

| | before step 1 | after step 1 |
|---|---|---|
| blocked | ~805 | **0** |
| conflict (reject) | 116 sheets / 921 total reject | **86 sheets** |
| promoted | — | 720 |
| demoted | — | 902 |

Remaining 86 rejects, all genuine dedup conflicts:
purchase_order 49, sales_return 14, inventory_sign_off 11, sell_out 7,
sales_register 5.

## Next

- **Step 2a:** inspect the raw `inventory_sign_off` and `sell_out` sheets behind
  their conflicts; report the pattern; get a resolution rule approved.
- **Step 2b:** apply the `purchase_order` region fix + `sales_return` coercion.
- Then steps 3–8 per the build list.

---

# STEP 2a — raw-row findings (2026-09-11, read-only, no rule applied)

## CORRECTION to the previous conflict-pattern table

The `inventory_sign_off` and `sell_out` conflict examples shown earlier were
**not filtered by `is_demo`.** Re-run with `is_demo != True` excluded:

| family | conflict groups (unfiltered) | conflict groups (real only) |
|---|---|---|
| `inventory_sign_off` | 127 | **3** |
| `sell_out` | 16 | **0** |
| `purchase_order` | 274 | 73 |
| `sales_register` | 28 | 27 |
| `sales_return` | 20 (post header-fix) | 20 |

**`sell_out` has zero real conflicts.** The 16 I reported are entirely synthetic
(the `9DMC57604`/`CULINARY`-style examples I showed you were `GENERATED_BACKFILL_*`
rows, `is_demo=True`). Nothing to resolve for `sell_out` — the earlier "multi-sheet
double-count" hypothesis was wrong because the underlying rows weren't real.

**`inventory_sign_off`'s real pattern is also different from what I reported.**
The `9DMC57604 / 2026-04 / pangasinan` 4-line example was **100% synthetic**
(`_src_file = GENERATED_BACKFILL_inventory_sign_off_2026-04_pangasinan`,
`is_demo=True` on all 4 rows) — not a real bin/condition split. See below for
what the 3 real conflict groups actually are.

## `inventory_sign_off` — 3 real conflict groups, all `sku_code = NULL`

```
key=(NaN, 2023-06-01, pangasinan)  rows=3
key=(NaN, 2023-08-01, ilocos)      rows=13
key=(NaN, 2023-08-01, pangasinan)  rows=173
```
All three keys have **`sku_code = NaN`** — these are rows where
`transform.split_sku_description()` (per its own docstring,
`analytics/etl/transform.py`) could not parse a SKU code from the source row and
correctly left it null. The bug is in `dedup_facts` (`transform.py:668-702`):
`groupby(natural_key, dropna=False)` treats every `NaN` sku_code as **the same
key** — so **173 distinct, unrelated unparseable rows** for 2023-08 Pangasinan get
lumped into one "conflict group" and reported as if they were 173 versions of one
SKU. They are not. Checked for silent data loss: none of these 3 groups have a
single repeated `quantity_on_hand` value, so `dedup_facts`' "true duplicate, safe
to collapse" branch never fires here — no rows were silently dropped. But the
**design gap is real**: a null-natural-key row should never be grouped with other
null-natural-key rows at all (matching Postgres UNIQUE's own NULL≠NULL semantics,
and the "never fabricate a key" principle already used elsewhere in this
codebase — e.g. `load.py`'s `resolve_dimension_fk` leaves `fk_column` NULL rather
than guess). **Not fixed here — flagging for step 2b, no rule proposed yet** since
I have not seen why these specific 219 real rows (33 (snapshot,region) groups
across 2023-01→2025-12, real is_demo≠True) failed to parse a SKU code — that needs
the raw sheets for the 2023-08 Pangasinan file specifically (173 of the 219 sit
there), not yet opened.

## `sell_out` — 0 real conflicts. Nothing to do.

## `purchase_order` live-DB check (item 1 below) confirms this family's conflicts ARE real — see next section.

---

## 1. `purchase_order` region defect — checked in the LIVE DB, confirmed present

**`purchase_fact` (real rows, `is_demo=false`), live query:**

| region | rows | % of 353 |
|---|---|---|
| `'False'` (literal string) | **223** | **63.2%** |
| pangasinan | 90 | 25.5% |
| ilocos | 40 | 11.3% |

**This is a live data defect already in the DB — not only a staging-collision
artifact.** 223 of the 353 real `Purchase_Fact` rows carry a region value of the
literal string `'False'`, which is neither a real site nor a real town.

**Root cause, cited:**
- `config/column_maps/purchase_order.yaml:43-44` maps `region: ["Town Display"]`.
- The raw "Town Display" cells for these rows contain **the literal text
  `FALSE`** (confirmed: two distinct-typed variants in the staged parquet, a
  Python `bool` `False` (719 raw rows) and the string `'False'` (387 raw rows) —
  likely an unresolved Excel formula in the source workbook, not something this
  pipeline introduced). 1,320 rows are genuine `NaN` (correctly recoverable) and
  27 are `None`.
- `analytics/etl/transform.py:210-248` (`backfill_provenance_fields`) only
  overwrites a value that is truly null (`.notna()`); a literal `False`/`'False'`
  is not null, so the clean site-level `_region` provenance tag (`pangasinan 1859
  / ilocos 844`, confirmed clean) never gets the chance to fill it.
- The site split **is** recoverable — every purchase sheet is literally named
  `ILOCOS PURCHASE` / `PANGASINAN PURCHASE` (`_src_sheet`, feeding `_region`).

**Distinct from `sales_register`'s region:** `sales_register.yaml:30-33` also maps
`region` from `"Town Display"/"AREA"/"Area"`, and live `Sales_Fact` real rows are
41.8% site-level (pangasinan 5,748 + ilocos 1,745 of 17,947) / 58.2% real town
names (`BAGUIO CITY`, `CITY OF URDANETA`, ...). This is **not the same defect** —
`transform.py:229-234`'s own docstring documents this as intentional (real
per-row town granularity distinguishes same-day/same-invoice-number rows) and no
literal `'False'` was found there. **Separately noticed, not yet explained:** 2 of
the 27 real `sales_register` conflict groups have `region='13'` (a 2-digit
numeric string, not a town) — UNVERIFIED root cause, not investigated further
yet; flagging, not fixing.

**No rule applied.** This needs your call: is the fix "drop the `region` mapping
from `purchase_order.yaml` entirely, let `_region` fill it" (my read of the
evidence — nothing legitimate is lost, the raw column carries no real signal for
this family, unlike sales_register's towns), or something else?

---

## 2. `sales_return` — dropped-column confirmation, grain confirmation, expected count

**Confirmed: I did NOT drop `region`.** `config/column_maps/sales_return.yaml`
deliberately does not map it so `backfill_provenance_fields` fills it from the
clean `_region` tag (verified: staged `sales_return` regions are `pangasinan
1262 / ilocos 669` — no `'False'`, no towns; this family doesn't have the
`purchase_order` defect). **`SalesReturn_Fact` rows carry real site-level
`region`** — the fact table's grain is `return_slip_num × principal × region ×
return_type`, not collapsed to principal×month. D5 (the BO value/count trend,
decision item 18) is reported at **principal × month** as a reporting/aggregation
choice on top of this — the fact table itself is finer.

**`return_date` IS genuinely unrecoverable — confirmed, not a convenience
choice.** Checked all raw columns across all 68 staged `sales_return` files:
`['Invoice Date', 'Salesman', 'Town Display', 'Branch Code', 'Customer Name',
'Invoice Num', 'REFNBR', 'Untaxed Amount', 'Discount Rate', 'Discount Amount',
'Tax', 'Net Amount', 'Balance', 'Posted', 'Return Slip #', 'Return Type', 'Total
CAS', 'Total PCS', 'is_demo']`. Zero columns with "Return" and "Date" in the name.
The only date is `Invoice Date` (1,928/1,931 populated) — the **original sale's**
date, not the return event's date; its month matches the file's own `_period` tag
in 1,900/1,928 real+demo rows (98.5%), consistent with it being the wrong field to
use. `_period` (the report month) is the finest real temporal grain that exists
in this source family — this is a source-data limit, not an implementation
shortcut.

**Columns confirmed dropped** (present in `mapped_df`, no home in
`SalesReturn_Fact`, will be projected out by the loader): `Invoice Date,
Salesman, Town Display, Branch Code, Customer Name, REFNBR, Untaxed Amount,
Discount Rate, Discount Amount, Tax, Balance, Posted, Total CAS, Total PCS`.
**Columns kept:** `return_slip_num, invoice_num, return_type, net_amount,
is_demo` + provenance-filled `region, principal, _period, _src_file, _src_sheet`.

**Expected row count — measured, not assumed:**

| step | rows |
|---|---|
| staged total (`sales_return`, all) | 1,931 |
| minus `is_demo=True` (synthetic) | −525 → **1,406 real** |
| minus header-artifact rows among the real set (`Return Type == "Return Type"`, literal) | −7 → **1,399** |
| dedup on real+clean: true-duplicate collapses | **0** (none — every duplicate-sized group is a real amount conflict) |
| rows sitting in unresolved conflict groups (20 groups) | 61 |
| **defensible load count today** | **1,399 − 61 = 1,338** |

**Not yet resolved, so not in the 1,338:** the 20 conflict groups (61 rows,
sample: slip `11272` ilocos has two different amounts `35.31` vs `304.46` — a
genuine disagreement, not a dtype artifact; numeric-coercion of `net_amount` was
tested and did not change the conflict count) and **27 real rows with a null
`return_slip_num`.** On the null-slip rows: `dedup_facts`'
`groupby(natural_key, dropna=False)` groups them by the same NULL≠NULL mismatch
described above for `inventory_sign_off` — the 27 collapse into 4 pandas groups by
`(principal, region, return_type)`, which is **not** how Postgres' `UNIQUE` would
treat them (each NULL-key row is distinct there). This is the same structural gap
as the inventory finding — flagging, not fixing yet.

**So: 1,338 is the current floor, not the final target.** The final number
depends on how the 20 conflicts and 27 null-slip rows are resolved — no rule
applied, per your instruction.

---

# STEP 2a, round 2 (2026-09-11) — downstream check, dropna proposal, raw rows

All read-only. No code changed, no writes. Report only, per instruction.

## 1. `purchase_fact.region` downstream check — NOT consumed anywhere today

Grepped `backend/routers/*.py`, `backend/schemas/*.py`, `analytics/optimization/`,
`scripts/run_lp.py`, `analytics/classification/*.py`, `frontend/src/` for any
`region` reference tied to purchase/received/allocation:

- `backend/routers/dashboard.py:389-398` (`_received_by_period`) selects
  `SUM(net_amount)` from `Purchase_Fact_Real`, grouped by `_period` only — no
  `region` in the query.
- `backend/routers/bo_monitoring.py:67-96` selects `SUM(net_amount)` from
  `purchase_fact_real` — no `region` column, no `region` filter.
- `backend/schemas/bo_monitoring.py:26` declares `BOMonitoringItem.region`, but
  the router that fills it (`bo_monitoring.py`) never selects a `region` column at
  all — that field is presently dead regardless of this defect, and it mirrors
  `SalesReturn_Fact`/BO grain, not `Purchase_Fact`.
- No router, schema, or `frontend/src/` file filters or displays purchase data by
  region. `frontend/src/components/Charts.jsx`'s one "region" hit is a chart
  shading term, unrelated.

**Verdict: the 63.2% defect is real and live in the column, but nothing on the
dashboard or in any analysis currently reads it — it is not producing a visibly
wrong number today.** It is a latent data-integrity issue (the column is wrong
for its own sake, and would corrupt anything built on it later — e.g. a future
per-site trapped-capital breakdown), not an active one. Flagging this distinction
per your instruction rather than either alarming or dismissing it.

**Fix, cleared to apply:** drop the `region: ["Town Display"]` mapping from
`config/column_maps/purchase_order.yaml:43-44` so `backfill_provenance_fields`
fills `region` from the clean `_region` tag. This is a config-only change
(one YAML block removed), re-run through Transform (writes only to `transform/`),
no live DB write. **Not yet applied — waiting for your go given the "fix it" in
your message doesn't yet have a diff in front of you. Say the word and I'll make
the edit + re-run Transform to confirm the live-DB-shaped 223 'False' rows would
resolve to their real site.**

## `sales_register` region='13'/'14' — root cause found, not a region at all

Traced both rows to source: `Invoice Date = "TOTAL"`, `Salesman`/`Customer Name`
= blank, raw `"AREA"` column = the literal digits `"13"`/`"14"`. Full raw rows
(`data/raw/Del Monte/DAILY REPORT - OCTOBER 2025/...SALES REGISTER.xlsx`, sheets
`1011-13`/`1016`/`1025`, last row of each daily sheet):

```
Invoice Date=TOTAL  Salesman=None  Customer Name=None  AREA=14  NET VALUE=282418.62  DISCOUNT=10254.51  TAX=33890.25  AMOUNT=316308.87
Invoice Date=TOTAL  Salesman=None  Customer Name=None  AREA=14  NET VALUE=83058.67   DISCOUNT=669.67    TAX=9967.05   AMOUNT=93025.72
Invoice Date=TOTAL  Salesman=None  Customer Name=None  AREA=13  NET VALUE=24373.25   DISCOUNT=66.25     TAX=2924.79   AMOUNT=27298.04
Invoice Date=TOTAL  Salesman=None  Customer Name=None  AREA=13  NET VALUE=124181.06  DISCOUNT=3040.78   TAX=14901.69  AMOUNT=139082.75
```

**These are per-sheet TOTAL/footer rows** (one per daily sheet, `invoice_num` is
also null on all of them — matches the earlier `(nan, 'delmonte', '13')` conflict
key) — almost certainly a line-item count ("14 invoices, ₱316,308.87") landing in
the AREA/region column position, not a region. This is the same class of defect
`sell_out.exclude_sell_out_total_rows` (`transform.py:711-736`) already exists to
handle for `sell_out` — **`sales_register` has no equivalent TOTAL-row filter.**
Not fixed here (out of the two items you asked me to fix this round); logging for
the `sales_register` conflict resolution alongside the 25 real invoice-number-reuse
conflicts already known there.

---

## 2. `dropna=False` grouping defect — one root cause, proposal (NOT applied)

Confirmed the same defect drives both the inventory "173-row conflict" and the
sales_return null-slip rows:

**Root cause:** `dedup_facts()` (`analytics/etl/transform.py:668-702`) does
`df.groupby(natural_key, dropna=False)`. Pandas groups every row with a fully
null key together as **one group** — the opposite of Postgres' own `UNIQUE`
semantics, where `NULL <> NULL` means every null-key row is already distinct.
Anywhere a natural key can legitimately be null (an unparseable SKU, a return
with no slip number), this silently treats unrelated rows as if they share an
identity.

**Proposal (design only — no code written yet):**

1. Before `groupby`, split `df` on whether **every** natural-key column is
   non-null (`resolvable_mask`, same name/shape as `load.py::build_dimension_key_frame`'s
   existing mask — matching precedent, not a new concept).
2. **Resolvable rows** (full key present): unchanged — existing
   dedup/true-duplicate/conflict logic runs exactly as today.
3. **Unresolvable rows** (any key column null): **never grouped with each
   other.** Each becomes its own entry in a new `DedupReport.quarantined: list[dict]`
   field — `{row identity (src_file/src_sheet/row_ordinal), which key column(s)
   were null}`. Not deduped, not flagged as a false "conflict," not silently
   dropped — visible on its own, the same anti-fabrication posture `load.py`
   already applies one stage later.
4. Callers (`transform_fact`, `transform_driver.py::_classify_fact_principal`)
   would report quarantined rows as their own manifest category (distinct from
   `conflict`) rather than folding them into `reject`/`blocked` alongside real
   multi-row conflicts, which is what currently mislabels the inventory 173-row
   group and sales_return's null-slip rows as "conflicts."

**Separately, not part of this proposal:** the sales_return "Good Stock"/"Bad
Stock" rows found below (item 4) aren't a null-key edge case at all — they carry
no data (`net_amount` is null too) and should be **excluded before dedup even
runs**, the same way `exclude_sell_out_total_rows` excludes sell_out's Total
rows. That's a second, unrelated fix — flagging it here because it surfaced in
the same investigation, not folding it into the quarantine proposal.

**Waiting for your sign-off on this proposal before touching `dedup_facts`.**

---

## 3. `inventory_sign_off` — the raw 2023-08 Pangasinan sheet

Source: `data/raw/Del Monte/MONTHLY REPORT - AUGUST 2023/DELMONTE_INVENTORY SIGN
OFF_PANGASINAN & ILOCOS _AUGUST 2023.xlsx`, sheet `PANGASINAN-ACTUAL` — **the
entire 173-row sheet**, not a subset. Every one of the 173 rows already carries
`sku_code_status = 'source_gap'` (an existing classification from
`transform.route_inventory_sku_shapes` / `_classify_inventory_sku_shape`).

Full non-null raw columns for this sheet: `Quantity, Cost, Valuation, Valuation
with VAT, CAS, PCS, PKG, in PCS, in Cases, In Pcs, In Cases`. **Sample rows:**

```
Quantity=6123.25  Cost=5626419.38  Valuation=5626419.38  CAS=6059.0  PCS=1387.0  in PCS=120240.0
Quantity=-16.75    Cost=-10032.08   Valuation=-10032.08    CAS=-17.0   PCS=-18.0   PKG=24.0
Quantity=128.25    Cost=72456.12    Valuation=72456.12     CAS=128.0   PCS=1.0     PKG=4.0
```

**No product code, description, category, or barcode column exists anywhere in
this sheet** — confirmed by listing every non-null raw column across all 173
rows, not a sample. This is a genuinely different (and apparently earlier, 2023-08
only) export shape that never carried a per-row product identifier at all — not a
parsing failure on this pipeline's part. `transform.py` already recognizes this
shape and correctly tags it `source_gap` rather than guessing a SKU.

**So the finding narrows to exactly the `dropna=False` bug above**: these 173
rows are real, distinct stock-value lines (note the first row's magnitude —
6,123 cases, ₱5.6M — looks like it might itself be a subtotal, and the negative
row is a real adjustment/variance line) that legitimately have no natural key and
should each be quarantined individually, not lumped into one 173-way "conflict."
No further rule proposed — this is exactly item 2's fix, applied to a concrete
case. Not applying anything until item 2 is approved.

---

## 4. `sales_return` — all 20 real conflict groups, shown in full

Two distinct patterns, confirmed against every row (not a sample):

### Pattern A — 18 of 20 groups (36 rows): genuine return-slip-number reuse

The **same `return_slip_num` was assigned to two different real returns** —
different `invoice_num`, different `Invoice Date` (sometimes different months
entirely), different amount. Every single pair has a distinct `invoice_num` — no
exceptions found. Examples (full row detail; all 18 follow this shape):

```
slip=11272   ilocos      INV/2023/2546  2023-12-29  ₱35.31   |  INV/2023/2545  2023-12-29  ₱304.46
slip=38687   ilocos      INV/2023/2438  2023-12-18  ₱26.32   |  INV/2023/2437  2023-12-18  ₱23.54
slip=RMR37154 pangasinan INV/2023/1293  2023-02-28  ₱2516.02 |  INV/2023/1536  2023-03-10  ₱390.15   ← different months
slip=RMR      pangasinan INV/2025/9004  2025-12-23  ₱1062.90 |  INV/2025/2092  2025-03-26  ₱1472.16  ← "RMR" alone, 9 months apart
```
(Full list of all 18 keys: `11272, 38687, 38710, RMR, RMR116605, RMR13322,
RMR18607, RMR24015, RMR35285, RMR37154, RMR38566, RMR38652, RMR38654, RMR39283,
RMR40348, RMR44653, RMR44707, RMR47954`.)

`invoice_num` cleanly discriminates every one of these 18 pairs — no case where
`invoice_num` is also shared.

### Pattern B — 2 of 20 groups (25 rows): NOT real data — section-header rows + a few swept-in real rows

`key=(NULL, 'delmonte', 'ilocos', NULL)` (14 rows) and
`key=(NULL, 'delmonte', 'pangasinan', NULL)` (11 rows). Most rows in both groups
have `Invoice Date` literally equal to the strings **`"Good Stock"` / `"Bad
Stock"`**, with `invoice_num`, `net_amount`, and `return_slip_num` all null —
these are **section-header rows** inside `data`-shaped sheets (marking where the
GS/BO sub-listing starts), not returns, staged as if they were data rows. Sample:

```
region=ilocos      return_slip_num=None  invoice_num=None  net_amount=None  Invoice Date=None       (src: 2025 APRIL SALES RETURN, sheet "ILOCOS BO")
region=ilocos      return_slip_num=None  invoice_num=None  net_amount=None  Invoice Date=Bad Stock   (src: 2025 APRIL SALES RETURN, sheet "ILOCOS BO")
region=ilocos      return_slip_num=None  invoice_num=None  net_amount=None  Invoice Date=Good Stock  (src: 2025 APRIL SALES RETURN, sheet "ILOCOS GS")
region=pangasinan  return_slip_num=None  invoice_num=INV/2023/4844  net_amount=1341.60  Invoice Date=2023-08-09  (src: AUGUST 2023 SALES RETURN)
```
A handful of rows in these same two groups (4 of 25) ARE real returns with a real
`invoice_num` and `net_amount` — they only lack a `return_slip_num`, and got
grouped with the header-artifact rows purely by the `dropna=False` bug.

**No rule applied.** Per your instruction, this is the pattern, not a
resolution. Two separate fixes are implied by the two patterns (Pattern A needs a
stated collision rule — e.g. widen the key with `invoice_num`, or keep both rows
flagged; Pattern B's header rows need an exclusion filter before dedup, and its
4 genuine null-slip rows need the item-2 quarantine treatment) — your call on
each, not proposed here.

---

# STEP 2b — all four fixes applied (2026-09-11)

Writes to `config/`, `analytics/etl/transform.py`, and `transform/` only. **No DB
writes.** Each fix verified against real data before/after; expected outcomes
stated before running, per standing rule 5.

## 1. `purchase_order` region — DONE

Dropped `region: ["Town Display"]` from `config/column_maps/purchase_order.yaml:43`
(replaced with a comment explaining why). Expected: `region` becomes exactly
`{pangasinan: 1859, ilocos: 844}` (matches `_region`'s 100% population). **Measured
exactly that, zero deviation.**

| | before | after |
|---|---|---|
| mapped rows | 2,703 | 2,703 |
| `region='False'`-ish | 1,106 | **0** |
| distinct region values | pangasinan/ilocos/False×2/40+ towns | **pangasinan, ilocos only** |
| `purchase_order` conflict sheets (manifest) | 49 | **0** |
| transform manifest total reject | 86 | **37** |

**Live DB note logged, not touched:** the 223/353 real `purchase_fact` rows
already carrying `region='False'` are unchanged — this fix is forward-only.
Logged as decision item 19 in `PROJECT_STATE_2026-09.md` §6, tagged for the
Phase 1d scratch-vs-live diff, not fixed in place.

## 2. `sales_register` TOTAL/footer rows — DONE

**Counted first, not just the 2 that collided:** 181 raw / **177 post-mapping**
rows across the whole `sales_register` family are TOTAL or signature-line footer
rows (163 real + 14 demo), not the 2 that happened to produce a visible
`region='13'/'14'` conflict. Added `exclude_sales_register_total_rows()`
(`analytics/etl/transform.py`, mirrors `exclude_sell_out_total_rows`), wired into
`transform_fact` for `doc_type == "sales_register"`.

**Caught and fixed before finalizing:** an early version matched "TOTAL" as a
substring against `customer_name` too, which wrongly excluded 21 real rows for
an actual customer named "TOTAL ABANAO...". Fixed to match each footer token
against exactly one specific column (`invoice_date` for "TOTAL"/"Prepared by:",
`customer_name` for "Checked by:", `tax_amount` for "Noted by:") — verified that
customer's 21 rows now survive.

| | before | after |
|---|---|---|
| mapped rows (Del Monte) | 56,968 | 56,791 (−177) |
| `region ∈ {'13','14'}` | 4 | **0** |
| real conflict groups | 4 (some footer, some genuine) | **1** (`INV/2024/0542` — genuine invoice-number reuse, unaffected by this fix, not in scope today) |

**Unilever La Union file — checked, clean.** Scanned all 24,906 real
`unilever_sku` rows for the same footer tokens (`TOTAL`, `PREPARED BY`,
`CHECKED BY`, `NOTED BY`, `GRAND TOTAL`, `SUB TOTAL`) across every column: **zero
hits.** Also checked for null `Product`/`Calendar Month` and anomalously short
`Product` values: zero. **The 24,906-row demand series is not affected — this
was a `sales_register`(Del Monte invoice)-only defect.**

**Regression caught and fixed before shipping:** the first version of this
function raised `KeyError` when none of its 3 target columns were present,
which broke `tests/etl/test_transform_driver.py`'s minimal `sales_register`
fixture (a legitimate frame with only `REFERENCE #`/`AMOUNT`/`Area`). Changed to
pass the frame through unchanged (nothing to exclude) instead of raising —
`exclude_sell_out_total_rows`'s raise stays as-is because `category_path` is that
fact's one load-bearing discriminator; `sales_register`'s three columns are
ordinary attributes whose absence doesn't signal a mapping failure the same way.

## 3. `dropna=False` quarantine — DONE, as proposed

`dedup_facts()` now splits `resolvable` (every natural-key column non-null) from
`unresolvable` (any null) **before** grouping. Unresolvable rows are never
grouped with each other — each is reported individually in the new
`DedupReport.quarantined` list (`{null_key_columns, _src_file, _src_sheet,
_row_ordinal}`), matching `load.py::build_dimension_key_frame`'s existing
`resolvable_mask` precedent. **Design choice, stated for review:** quarantined
rows stay in the returned DataFrame (not dropped) — same "flag, never drop"
posture `resolve_dimension_fk` already uses one stage later; a caller/loader can
still choose to load them with a NULL key column.

**Expected vs measured (real rows only), stated before running:**

| family | expected quarantine | measured | conflict groups: before → after |
|---|---|---|---|
| `inventory_sign_off` (delmonte) | ~219 (the null-`sku_code` rows) | **219** | 3 → **0** |
| `sales_register` (delmonte) | ~591 (null-`invoice_num`, post footer-fix) | **591** | 3 real (incl. footer noise) → **1** (the genuine reuse) |
| `sales_return` (delmonte) | not pre-estimated (depends on fix 4's key widening) | **776** — see §4 | 20 → **0** |

Both pre-stated expectations matched exactly. `purchase_order` and `sell_out`
unaffected (0 real conflicts either way already).

**Regression check:** ran `pytest tests/etl/` (129 tests) before and after all
four fixes. **3 pre-existing failures found, unrelated to today's work** —
`tests/etl/test_transform.py::test_transform_fact_raises_on_unconfirmed_natural_key`,
`test_load_source_of_truth_exposes_none_natural_key`, and
`tests/etl/test_transform_driver.py::test_build_transform_manifest_classifies_promoted_demoted_conflict_blocked`
all assert the pre-step-1 `sales.unilever → ssis_summary (natural_key: null,
status: blocked)` behavior that step 1 (2026-09-09, this Phase) deliberately
changed to "demoted." These tests were never updated after that fix — a gap from
the earlier step, not introduced today. **Not fixed here** (out of today's
approved scope) — flagging for a follow-up. One genuine regression from today's
own work was caught and fixed (§2's `KeyError` above) before it reached this
report; final run is 3 failed / 125 passed (was 4 failed / 124 passed before any
of today's fixes touched anything, i.e. the 3 remaining were already failing
before step 2b started).

## 4. `sales_return` conflicts — both patterns fixed

**Pattern A (18 groups/36 rows) — `invoice_num` added to the natural key.**
`config/source_of_truth.yaml`'s `sales_return.both.natural_key` widened to
`[return_slip_num, principal, region, return_type, invoice_num]`. Verified: real
conflict groups **20 → 0**.

**Not yet fixed at Load — flagged, blocks Phase 1d for this fact:**
`schema.sql`'s `SalesReturn_Fact` `UNIQUE` constraint is still the original 4
columns (no `invoice_num`). Widening only the YAML key changes what
`dedup_facts()` reports during Transform; it does not change the DB constraint
`load_to_supabase()`'s `ON CONFLICT` clause targets. Passing a 5-column
`natural_key` against a 4-column DB constraint will make Postgres reject the
`ON CONFLICT` clause outright (a hard failure, not a silent misload) until
migration 0011 adds a matching unique index — already flagged as a migration
candidate in the same YAML comment.

**Pattern B — "Good Stock"/"Bad Stock" section headers rejected at transform.**
New `exclude_sales_return_header_rows()` (`analytics/etl/transform.py`), mirrors
the sell_out/sales_register pattern: drops rows where raw `Return Type ==
"Return Type"` (unstripped header) or raw `Invoice Date ∈ {"Good Stock", "Bad
Stock"}` (section markers, no real data). **16 rows excluded** (all real, 0
demo) before dedup runs. The 4 genuine null-slip returns that were mixed into
Pattern B now go through fix 3's quarantine individually, not grouped.

**One unresolved finding worth your attention, not part of what was approved
today:** of the 776 quarantined `sales_return` rows, **765 are quarantined
solely because `return_type` is null** — the pre-2025 `data`-shaped sheets
never populated it (a structural property of ~55% of the real corpus, not an
anomaly). This is the exact gap `schema.sql`'s own comment on `SalesReturn_Fact`
already flags (NULL≠NULL under strict `UNIQUE` semantics) and proposes fixing
with `COALESCE(return_type, '')` instead. Today's quarantine fix applies the
strict-null reading as approved; whether the pre-2025 shape should instead use
a `COALESCE` policy (so two same-slip pre-2025 rows *would* still dedupe/conflict
against each other) is a real design question this now makes visible — **not
decided or applied, flagging for your call.**

## Revised expected `SalesReturn_Fact` count — against the 1,338 floor

| step | rows |
|---|---|
| staged total (all) | 1,931 |
| minus `is_demo=True` | −525 → 1,406 real |
| minus header/section-marker rows (fix 4, all real) | −16 → **1,390** |
| dedup: true-duplicate collapses | −5 → **1,385** |
| — of which cleanly resolved (full 5-part key) | 609 |
| — of which quarantined (null `return_type`, mostly pre-2025; kept, not dropped) | 776 |
| — unresolved conflicts | **0** |
| **Revised defensible count** | **1,385** |

**1,385, up from the 1,338 floor** (+47) — and now **zero unresolved conflicts**,
versus 61 rows held out before. The composition changed materially: the earlier
1,338 excluded 61 real conflict rows outright; today's 1,385 includes all real,
non-junk rows, with 776 of them explicitly flagged (not hidden) as carrying an
incomplete key pending the `return_type`/`COALESCE` decision above, and the whole
fact blocked at actual Load by the schema.sql constraint gap noted in Pattern A.
**1,385 is real-and-accounted-for, not yet load-clean.**

---

# STEP 2c (2026-09-11) — item 21 tested, migration 0011 listed, tests fixed

## Item 21 — `return_type` in the key: tested both options against real data

**Bug caught first, before results could be trusted:** `exclude_sales_return_header_rows()` (§4 above) checked the raw column name `"Return Type"` for the header-artifact match — but `apply_column_map` runs before this function (see `transform_fact`) and had already renamed it to canonical `return_type`. `"Return Type" in df.columns` was therefore always `False`, so that check silently did nothing. All 7 real header rows (and 4 demo) leaked through and were still showing up as false collisions when I started this test. **Fixed**: now checks the canonical `return_type`/`return_slip_num`/`invoice_num` columns (three redundant checks, since a header row repeats its own header text in every column) instead of the pre-rename raw name. Verified: excluded count went from 16 (all real, the bug's output) to the correct **27** (23 real + 4 demo).

**schema.sql's existing comment on this** (`schema.sql:250-266`, quoted in full):
> "OPEN ITEM (2026-08, flagged not fixed): return_type is now nullable (see above), and this key includes it. Postgres UNIQUE treats NULL as distinct from NULL, so two real rows sharing the same (return_slip_num, principal, region) with return_type both NULL (the pre-2025 shapes, which never populate return_type) would NOT be caught as duplicates by this constraint... Likely low-impact in practice (return_slip_num itself appears to already be unique per region in the pre-2025 shapes... **but not verified against real data**). If this needs closing, the fix is a unique expression index on (return_slip_num, principal, region, COALESCE(return_type, ''))."

Note this comment predates `sales_return` becoming the system of record — it also says invoice_num "never exists as a producible column at all" (true for the old `rmr_gs_bo` source, false for `sales_return`, which has it on 1,912/1,931 rows).

**Both options tested against the real, clean (header/marker-excluded) 1,383-row corpus:**

| option | key | colliding groups | rows |
|---|---|---|---|
| (a) drop `return_type` | `(return_slip_num, principal, region, invoice_num)` | **1** | **3** |
| (b) `COALESCE(return_type, '')` | `(return_slip_num, principal, region, COALESCE(return_type,''), invoice_num)` | **1** | **3** |

**Identical result — (a) and (b) are empirically indistinguishable on this data.** `return_type` never discriminates a real pair beyond what `invoice_num` already does; COALESCE-ing it adds no protection `invoice_num` doesn't already provide.

**The one collision, shown in full — not a real duplicate:**
```
key=(NULL, 'delmonte', 'ilocos', NULL)  3 rows, ALL fields null except region:
  return_slip_num=None invoice_num=None return_type=None net_amount=None Invoice Date=None  (APRIL 2025 SALES RETURN, sheet "ILOCOS BO")
  return_slip_num=None invoice_num=None return_type=None net_amount=None Invoice Date=None  (JUNE  2025 SALES RETURN, sheet "ILOCOS BO")
  return_slip_num=None invoice_num=None return_type=None net_amount=None Invoice Date=None  (MARCH 2025 SALES RETURN, sheet "ILOCOS BO")
```
Every field is null — no return_slip_num, no invoice_num, no amount, no date. These are **genuinely blank rows** (a third kind of non-data artifact, distinct from the header rows and the Good/Bad Stock section markers already excluded) — not two returns competing for one identity. **New finding, not yet fixed**: `exclude_sales_return_header_rows()` doesn't catch these (they have no signal to match on beyond "everything is null"); a follow-up filter (e.g. drop rows where `net_amount` and `return_slip_num` and `invoice_num` are all null) would need to be added. Not applied — flagging only.

**Your read is confirmed against the data: `return_slip_num` + `invoice_num` already identify a return; `return_type` adds nothing on real data once `invoice_num` is in the key.** Not applied yet (source_of_truth.yaml keeps the 5-column key from §4, which already includes `invoice_num` — `return_type` stays in it too since removing it requires the migration-0011 DDL change to actually take effect at Load; the transform-side natural_key list and the DB constraint must move together or Transform will report clean while Load still fails). **Recommendation for the migration: drop `return_type` from the DB `UNIQUE` constraint** (simpler than an expression index, and COALESCE adds no verified value) — your call.

## Migration 0011 — full contents, for your review as one unit (NOT written)

| # | Change | Type | Evidence / source |
|---|---|---|---|
| 1 | `SalesReturn_Fact.UNIQUE` constraint: `(return_slip_num, principal, region, return_type)` → **`(return_slip_num, principal, region, invoice_num)`** (drop `return_type`, add `invoice_num`) | DDL | §4 + item 21 above — empirically verified equivalent to COALESCE, simpler DDL. Must land together with `source_of_truth.yaml`'s already-widened transform key (decision item 20) or Load hard-fails on `ON CONFLICT` mismatch. |
| 2 | `Product_Dimension.category_path` backfill for 1,807 Unilever demand SKUs | Data (UPDATE, not DDL — column already exists) | Direct SOH match 79.0% (1,427 SKUs) + description-keyword fallback ≥0.6 confidence (validated OOS 97.4% accurate) + `UNCLASSIFIED` for the rest (0.2% of revenue, 0 Tier A — immaterial). Plan doc §1c. |
| 3 | `Product_Dimension.brand` backfill, made reproducible | Data (UPDATE) | SOH `article_description` first-token rule + a committed alias table (`config/alias_tables/unilever_brand.csv`, not yet built — handles mojibake variants like LADYS/LADY'S/LADY?S). Currently populated by no code at all. Plan doc §1c, `PROJECT_STATE_2026-09.md` §8. |
| 4 | `Inventory_Fact.quantity_on_hand` — add a `-- UNIT: CASES` schema comment | DDL comment only, no data change | `transform_ssis_soh.py:226` loads it from `stock_qty_cases`; no explicit unit marker exists today. Plan doc §1c. |
| 5 | **NOT included — decide if it belongs**: `purchase_fact.region` — 223/353 live rows still carry `'False'` | N/A | Decision item 19. The transform-side mapping is already fixed forward (§1 above); a fresh canonical load naturally produces clean rows, so this likely needs **no migration DDL/UPDATE at all** — just the Phase 1d scratch-vs-live diff explaining the delta. Listed here so it isn't silently forgotten, not because it's DDL. |
| — | **Considered, NOT included**: an exclusion for `sales_return`'s 3 fully-blank rows (item 21 above) | Transform code, not migration | This is a `transform.py` fix (extend `exclude_sales_return_header_rows` or a new function), not a schema change — noted here only so it isn't lost. |

**Open, unresolved, NOT part of this migration:** `sales_register`'s 1 remaining real conflict (`INV/2024/0542`, genuine invoice-number reuse across two different customers) has no rule yet — not decided today, so nothing to migrate for it.

## Tests fixed — 3/3, all traced to step 1

Root cause confirmed for all three: they asserted the **pre-step-1** behavior of
`source_of_truth.yaml`'s `sales.unilever` entry (`natural_key: null` →
`transform_fact` raises `ValueError`, `transform_driver` classifies `blocked`).
Step 1 (2026-09-09) removed that entry entirely (dead mapping, 0 real rows,
`ssis_summary` has no product grain — `PROJECT_STATE_2026-09.md` §8). Updated to
assert the current, correct, intentional behavior instead of the removed one:

- `tests/etl/test_transform.py::test_transform_fact_raises_on_unconfirmed_natural_key`
  → renamed `test_transform_fact_raises_on_missing_source_of_truth_entry`, now
  expects `KeyError` (no rule found) rather than `ValueError` (natural_key is
  null) — `load_source_of_truth` raises before `transform_fact` ever reaches the
  null-key check, since there's no entry to find at all now.
- `test_load_source_of_truth_exposes_none_natural_key` →
  `test_load_source_of_truth_raises_for_removed_sales_unilever_entry`, now
  expects `KeyError` from `load_source_of_truth("sales", "unilever")`.
- `tests/etl/test_transform_driver.py::test_build_transform_manifest_classifies_promoted_demoted_conflict_blocked`
  — `fileD/raw_sheet` (an `ssis_summary` fixture) now expects `"demoted"` /
  `"never a fact's primary source"` instead of `"blocked"` /
  `"natural_key unconfirmed"`, matching `_doc_type_owners()`'s real current output
  (verified: `owner("ssis_summary") is None`).

**Full suite: `pytest tests/etl/` — 128 passed, 0 failed** (was 4 failed/124 passed
before step 2b started; 3 failed/125 passed after step 2b's own regression was
fixed; now 0/128 after these 3 fixes).

## What's still blocking the canonical load into `ssm_canonical`

| # | Blocker | Status |
|---|---|---|
| 1 | **No loader exists.** `scripts/run_canonical_load.py` (or equivalent) — the Extract→Transform→signoff→Load orchestrator — has never been written. `load_to_supabase`/`resolve_dimension_fk` are library functions called by nothing but tests. | Not started |
| 2 | `ssm_canonical` schema doesn't exist in Supabase yet | Not created |
| 3 | `transform/_signoff.json` doesn't exist — `transform_signoff.py --decision approved --by <name>` never run | Not run |
| 4 | Migration 0011 (table above) — not written | Not written, listed for your review this turn |
| 5 | `ssis_soh` driver still not wired as its own sanctioned pipeline (`scripts/run_ssis_soh_pipeline.py`) — approved direction 2026-09-09, not built | Not built |
| 6 | `Product_Dimension.category_path`/`brand` backfill logic — not implemented (migration item 2/3 above) | Not implemented |
| 7 | `sales_register`'s 1 remaining real conflict (`INV/2024/0542`) — no resolution rule decided | Open, undecided |
| 8 | `sales_return`'s 3 fully-blank rows (item 21) — no exclusion filter yet | Open, flagged only |
| 9 | `inventory_sign_off` "3rd header shape" (ARCHITECTURE.md:196) — flagged in step 1's verification sweep as "not yet reproduced against current staging"; still unresolved either way | Open, low priority |

**Everything real-data-defect-shaped that step 2 could find without a migration or
a loader is now fixed.** The remaining path is genuinely a build phase (items
1–6), plus two small open decisions (7–8) and one unverified-but-probably-moot
item (9).

---

# STEP 2d (2026-09-11) — the three open decisions cleared

## Decision 22 — sales_return's 3 blank rows: CLOSED, filtered

Added a third check to `exclude_sales_return_header_rows()`: `return_slip_num`,
`invoice_num`, AND `net_amount` all null on the same row (all three required, not
any one — a real return that's merely missing its slip number must still reach
`dedup_facts()`'s quarantine, not get silently dropped here). Verified before
running: expected 3 real rows excluded, no others. **Measured exactly 3** — real
input to dedup 1,383 → **1,380**, quarantined 776 → **773**, conflict groups
stayed **0**. `pytest tests/etl/` re-run: **128 passed, 0 failed.**

**Bonus, run once migration 0011's key lands** (informational, not applied — no
DB write): re-tested `dedup_facts` with `return_type` already dropped from the
key, against the same 1,380-row real corpus: **quarantined drops from 773 to
8**, conflict groups stay 0. Those 8 are genuine returns missing only
`return_slip_num` or `invoice_num` — a small, honest residual, not a systemic
gap. This is the number to expect once the migration + a fresh loader run land:
**`SalesReturn_Fact` = 1,380 real rows, 0 conflicts, 8 quarantined (flagged,
not hidden).**

## Decision 23 — sales_register's one genuine conflict: shown in full

```
invoice_num=INV/2024/0542  region=SANTA MARIA  principal=delmonte
  Row 1: 2024-02-24  Joenathan Arizabal  branch L12E-000861  *ELLISE CONVENIENCE STORE   ₱1,069.08  Posted=Yes  Balance=0.00
         (ILOCOS SALES REGISTER, 2024 FEBRUARY SALES REGISTER.xlsx)
  Row 2: 2024-01-24  Benjamin Aquino     branch L12F-001973  SAYO TEA                     ₱1,580.82  Posted=No   Balance=1,580.82
         (PANGASINAN SALES REGISTER, 2024 JANUARY SALES REGISTER.xlsx)
```
Two completely different transactions — different date (different **month**,
Jan vs Feb), different customer, different salesman, different branch, different
amount — that happen to share the literal invoice number `INV/2024/0542` across
Del Monte's Ilocos and Pangasinan sales-register books. `invoice_date` alone
would separate them cleanly (same shape as the `sales_return` Pattern-A fix, just
one pair instead of eighteen). **Not fixed** — you asked to see it, not resolve
it; **not included in migration 0011** (out of its approved scope today). If you
want the same treatment (`invoice_date` added to `Sales_Fact`'s key), say so and
it's a one-line `source_of_truth.yaml` change + a matching migration-0012-or-added-
to-0011 DDL change, same pattern as today's `sales_return` fix.

## Decision 24 — inventory "3rd header shape": verified MOOT, `ARCHITECTURE.md` closed

Checked directly rather than left unverified: real `inventory_sign_off` rows
split `matched` 4,961 / **`direct` (shape C — `ITEM CODE`/`ITEM DESCRIPTION`) 411**
/ `source_gap` 173 / `unmatched` 46, out of 5,591 real rows (99.2% accounted for
cleanly). Shape C **is** handled — not by `column_maps/inventory_sign_off.yaml`
(still true it never references `PRODUCT/ SKU CODE`/`ITEM CODE`/etc.), but by
`transform.route_inventory_sku_shapes()` (`transform.py:784-798`, direct
`ITEM CODE`→`sku_code` copy), built after `ARCHITECTURE.md:196`'s note was
written. **`ARCHITECTURE.md:196` closed as stale** (edited in place, dated).

**New finding while verifying (not part of what was asked, not fixed):** the 46
`unmatched` rows are all `sku_description_raw == "Total"` — a per-sheet
TOTAL/footer row, exactly the same defect class already fixed in `sales_register`
/ `sales_return` / `sell_out`, just not yet for `inventory_sign_off`. Flagged in
`ARCHITECTURE.md`'s edit and here; not applied.

---

# STEP 3 — Migration 0011 (drafted, NOT applied)

Files written (config/DDL text only — **no DB connection made, nothing executed**):
- `analytics/db/migrations/0011_sales_return_key_and_category_brand.sql` (new)
- `analytics/db/schema.sql` — updated in place to match (house convention: 0009/0010
  both document their live changes directly in `schema.sql`, not just the migration
  file), so a from-scratch build matches what this migration produces.

**Four changes, per your approval:**

1. **`SalesReturn_Fact` key**: `DROP CONSTRAINT` the old 4-column unique (name
   confirmed **live**, read-only query: `salesreturn_fact_return_slip_num_
   principal_region_return_ty_key`), `ADD CONSTRAINT` the new
   `(return_slip_num, principal, region, invoice_num)`.
2. **`Product_Dimension.category_path_source`** (new column, `TEXT CHECK IN
   ('direct_soh_match', 'keyword_rule', 'unclassified')`, nullable) — your
   addition. `COMMENT ON COLUMN` spells out exactly what each value means and
   when NULL applies (not yet processed, vs. `'unclassified'` = processed,
   genuinely couldn't classify — `category_path` itself is the literal string
   `'UNCLASSIFIED'` in that case, per Phase 0's design, never NULL).
3. **`Product_Dimension.brand_source`** (new column, `TEXT CHECK IN
   ('soh_first_token_rule')`, nullable) — your addition, one value today
   (room to grow if a fallback rule is ever added, matching category's shape).
4. **`Inventory_Fact.quantity_on_hand`** — `COMMENT ON COLUMN` only, `UNIT:
   CASES`, no data/type change.

**Deliberately DDL-only, no inline backfill SQL** — matches migration 0010's own
precedent (its header comment explicitly says a 44,575-row UPDATE "isn't
reviewable or practical as a giant VALUES list", delegates to
`scratch/backfill_0010.py`). Here, the category_path/brand backfill logic
belongs in the **loader** (§4 below, not yet written) since it's a repeatable
Load-time step, not a one-time script — it needs to run every time
`sales_unilever_sku_demand` + `ssis_soh` are loaded, not once.

**Full file content, both the migration and the `schema.sql` diff, are in the
repo now for your review** — not reproduced in full here to keep this report
readable; open `analytics/db/migrations/0011_sales_return_key_and_category_brand.sql`
directly. Rollback block included at the bottom (commented out, matching house
style), not run.

---

# STEP 4 — `scripts/run_canonical_load.py` design (for review, NOT written)

## What it calls, in order

1. **Parse args**: `--schema` (default `ssm_canonical`; hard-refuses `public` —
   a safety guard, not just a default), `--dry-run` (compute + print everything,
   skip the actual `INSERT`/`ALTER` calls — lets this be tested safely without
   writing anywhere), `--staging-dir`/`--transform-dir`/`--config-dir` (default
   to the real paths, overridable for tests).
2. **Gate check — once, at the top, before anything else runs:**
   `check_reject_rate_gate(staging/_manifest.json)` then
   `check_signoff_gate(transform/)`. Both raise on failure (existing behavior in
   `load.py`) — **the script does not catch these**; an uncaught exception here
   is the correct behavior (per-table `try/except` would risk a half-loaded
   schema on a gate that should have blocked everything). Printed before the
   raise: which gate, the measured rate/decision, the threshold.
3. **Ensure the scratch schema exists**: `CREATE SCHEMA IF NOT EXISTS
   <schema>;` then execute `schema.sql` followed by every
   `analytics/db/migrations/000*.sql` file **in filename order**, all inside
   one transaction per file, with `SET LOCAL search_path TO <schema>` issued
   at the start of **each** transaction (never `ALTER ROLE/DATABASE` — session-
   scoped only, matching the schema-safety finding from step 2a: nothing else
   in this codebase qualifies a schema, so this must not leak). If `--schema
   ssm_canonical` already has these objects (a re-run), every statement is
   `IF NOT EXISTS`/idempotent by the existing migration convention — safe to
   re-run.
4. **Per `(fact, principal)` in `source_of_truth.yaml`** (the 7 real
   combinations with a non-null natural key today: `sales/delmonte`,
   `sales_unilever_sku_demand/unilever`, `sales_return/delmonte`,
   `purchase/delmonte`, `purchase/unilever` if it ever has rows,
   `inventory/delmonte`, `inventory/unilever`, `sell_out/delmonte`), in this
   fixed order (dimension-dependency order, not alphabetical):
   1. `sales_unilever_sku_demand/unilever` first — creates the 1,807
      `Product_Dimension` SKU rows everything else's category/brand backfill
      (step 6) needs to exist first.
   2. `sales/delmonte`, `purchase/*`, `sales_return/delmonte` — no dimension
      ordering constraint among these three, run in any order.
   3. `sell_out/delmonte` — creates the 99 `Product_Dimension` category rows.
   4. `inventory/*` (the `inventory_sign_off` doc_type path).

   For each: `transform_fact()` → `clean_pipeline()` (same call shape
   `transform_driver.py` already uses) → build the fact's `DimensionFKSpec`(s)
   (same shape as `tests/etl/test_load.py`'s existing fixtures — e.g.
   `fk_column="product_key", dimension_table="product_dimension",
   dimension_natural_key=["principal","grain","sku_code","category_path"],
   df_to_dimension_columns={...}, static_values={...}`) → `load_to_supabase()`
   **without** re-passing `manifest_path`/`transform_dir` (the gates already ran
   once in step 2 — no need to re-check per table).
5. **`ssis_soh` path** (separate — its own Extract/Transform, not
   `source_of_truth.yaml`-driven): `transform_ssis_soh`'s transform function →
   `Inventory_Fact` rows for Unilever SOH (same `load_to_supabase` call shape)
   **plus** the category-source frame step 6 needs (most-recent snapshot
   `CATEGORY DESC` per SKU).
6. **Category/brand backfill** (migration 0011's new columns; runs **last**,
   after steps 4.1 and 5 have created every `Product_Dimension` row it needs to
   update): for each of the 1,807 Unilever demand SKUs — direct SOH match (79%,
   `category_path_source='direct_soh_match'`) → else the validated
   keyword rule at confidence ≥0.6 (`category_path_source='keyword_rule'`) →
   else `category_path='UNCLASSIFIED'`
   (`category_path_source='unclassified'`). Same shape for `brand`
   (`brand_source='soh_first_token_rule'`), using the alias table (not yet
   built — `config/alias_tables/unilever_brand.csv`, a **separate small
   deliverable**, needed before this step can run for real). Implemented as
   `UPDATE`s against `Product_Dimension`, batched, via SQLAlchemy — not
   `load_to_supabase` (that function upserts *fact* rows on a natural key; this
   is a dimension-row `UPDATE` by `product_key`, a different shape, closer to
   `resolve_dimension_fk`'s pattern than a fresh insert).
7. **Print the summary** (see below) and exit 0. On `--dry-run`, steps 3–6 run
   their full logic (including the real DB reads `resolve_dimension_fk` needs
   for the "does this dimension row already exist" check) but every `INSERT`/
   `UPDATE`/`ALTER` is skipped and replaced with the row count it *would* have
   written — this needs `load_to_supabase`/`resolve_dimension_fk` to accept a
   dry-run flag too, which they don't today (a small, additive change to
   `analytics/etl/load.py`, not yet made).

## What it does on gate failure

Nothing loads. The gate check (step 2) is the very first thing that touches the
DB-bound path at all — schema creation (step 3) doesn't even run. Matches
`load.py`'s own existing raise-based design; this script adds no new gate logic,
it just calls the two that already exist, once, before anything else.

## What it prints

- Which schema it's targeting, `--dry-run` or not, at the very top (so a stray
  run against the wrong schema is visible immediately, not discovered later).
- Gate results (reject rate measured/threshold, signoff decision/decided-by/at).
- Per `(fact, principal)`: rows attempted, rows upserted, dimension rows
  resolved/inserted, `DedupReport` conflict-group and quarantined-row counts
  (so a conflict or a large quarantine count is visible in the run log, not
  only in a separate report someone has to remember to check).
- Category/brand backfill: counts per `*_source` value (`direct_soh_match` /
  `keyword_rule` / `unclassified` — directly queryable afterward too, but
  printed at load time so the split is visible without a follow-up query).
- A final one-line summary table: fact → row count, and a reminder to run the
  scratch-vs-live diff next (not part of this script — a separate step, per the
  plan).

## Explicitly NOT in this script's scope

- The scratch-vs-live diff (separate step, reads both schemas, writes nothing).
- The cutover decision (separate, human, after the diff).
- `sales_register`'s one remaining conflict and `inventory_sign_off`'s 46
  TOTAL-row leak (decisions 23/24's "new, not fixed" note) — the loader runs
  against `transform_fact()`'s current output either way; those rows load
  as-is (the conflict as 2 flagged, un-deduped rows per `dedup_facts`'
  existing "keep all, flag" behavior; the 46 TOTAL rows as genuine
  `sku_code=NULL` "unmatched" — no fabricated data either way, just not yet
  cleaned).

**Not written yet — this is the design for your review, per your instruction.**

---

# STEP 5 (2026-09-11/12) — conflict reconciled, footer rows consolidated, loader written

## 1. The "22 vs 0" reconciliation — both numbers are correct, they answer different questions

**Not stale.** `transform/_manifest.json` was rebuilt multiple times today; 22 is
current. The manifest's 22 = **total conflict SHEETS across real+demo combined**
(what `transform_driver.py` — and, critically, the new loader — actually
processes, since demo rows are approved data that still loads into the base
tables per `CLAUDE.md` rule 1). My "0 conflicts" claims were **real-data-only**
(is_demo filtered) — true, but I should have said "0 real conflicts" every time,
not bare "0 conflicts." Full breakdown, real vs demo vs combined, measured fresh:

| family | FULL (real+demo) groups | REAL groups | DEMO groups |
|---|---|---|---|
| `inventory_sign_off` | 114 | **0** | 114 |
| `sales_register` | 2 | 1 (`INV/2024/0542`, genuine) | 1 |
| `sell_out` | 16 | **0** | 16 |
| `sales_return` | 0 | 0 | 0 |
| `purchase_order` | 0 | 0 | 0 |

**133 of the manifest's underlying conflict groups (114+16+1+2) are demo-row
artifacts** — synthetic data colliding with itself, not a real data-quality
problem. `sales_register`'s 2 groups split 1 real (already known,
`INV/2024/0542`) + 1 demo. **The "zero real conflicts" premise holds.** The
premise that matters for the canonical load — "zero conflicts **among real
business data**" — is unchanged and still true. What's now explicit: the loader
will still encounter ~132 demo-driven conflict groups when it processes the full
corpus, and will apply the exact same `dedup_facts` "keep all, flag" treatment
to them as to real data — no special-casing demo rows, matching this codebase's
existing design (same tables, `is_demo` flag, not a separate code path).
**Every reference to "conflicts" from here on states real vs demo vs combined —
never a bare number again.**

## 2. Footer-row exclusion consolidated — one function, four families

`exclude_sell_out_total_rows` / `exclude_sales_register_total_rows` /
`exclude_sales_return_header_rows` **replaced** with one shared
`exclude_footer_rows(df, checks: list[FooterRowCheck], label, required=True)`
(`analytics/etl/transform.py`) + four committed check-list constants
(`SELL_OUT_FOOTER_CHECKS`, `SALES_REGISTER_FOOTER_CHECKS`,
`SALES_RETURN_FOOTER_CHECKS`, `INVENTORY_SIGN_OFF_FOOTER_CHECKS`). A
`FooterRowCheck` is either a `(column, token, mode)` match or an `all_null=[...]`
joint check. `required=False` preserves `sales_register`'s already-established
leniency (pass through unchanged if none of its columns are present — a
legitimately thin frame, not a broken one); the other three keep the original
strict "raise if nothing to check against" behavior.

**`inventory_sign_off` — the 4th family, now fixed too.** Its exclusion must run
**after** `route_inventory_sku_shapes()`/`split_sku_description()` (unlike the
other three, which run right after `backfill_provenance_fields()`) —
`sku_description_raw` only exists as one canonical name across both the 2023
and 2025 header shapes once that step has run.

**Investigated before writing a rule, not assumed:** of the 46 real "unmatched"
rows, only **29** are `sku_description_raw == "Total"`. Checked the rest before
extending the fix — **2** are `"#REF!"` (a broken Excel formula reference, zero
real data — safe to add). The remaining **15** (12 null `sku_description_raw`, 1
`"DESCRIPTION"`, 2 `"WH/Stock"`/`"IS-WH/Stock"`) **all carry real
`quantity_on_hand`/`cost`/`valuation` data** — one is ~2,535 cases / ₱2.6M,
large enough to look like a section subtotal, not noise. **Not excluded** —
forcing them into "junk" without understanding what they are risks dropping
real inventory data, the anti-fabrication failure in the other direction. Left
as `sku_code_status='unmatched'`, flagged. `ARCHITECTURE.md:196` updated to
reflect the true 29+2 vs 15 split (was previously stated, based on only a
3-row sample, as if all 46 were the same "Total" pattern).

**Row counts affected, real rows only, before vs after (today's cumulative
work, not just this consolidation step):**

| family | real rows before any footer fix | real excluded | real after |
|---|---|---|---|
| `sell_out` | 1,573 | 34 | 1,539 |
| `sales_register` | 21,593 | 163 | 21,430 |
| `sales_return` | 1,406 | 26 | 1,380 |
| `inventory_sign_off` | 5,591 | 31 (29 Total + 2 #REF!) | 5,560 |

`pytest tests/etl/`: **128 passed, 0 failed** (verified after the consolidation,
again after the inventory `#REF!` addition, again after the `load.py` dry-run
changes below — three separate confirmed runs, not one assumed to cover
everything).

## 3. Migration 0011 — approved as written, not applied

No further changes made to the migration file itself. It will run as part of
the loader's schema-creation step (below), on your explicit go for an actual
(non-dry-run) invocation.

## 4. `scripts/run_canonical_load.py` — written, per the approved design + 3 requirements

**Written, syntax-verified (AST parse), import-verified (all real modules,
including the corrected `analytics.config.get_settings()` — the design doc
said `load_config()`, which doesn't exist; caught before shipping), and
`FACT_PLAN` cross-checked against `source_of_truth.yaml`'s real rules — all 6
entries resolve with the expected `doc_type`/`natural_key`.
`python -m scripts.run_canonical_load --help` and `--schema public --dry-run`
both verified to exit cleanly / refuse correctly **without opening a DB
connection** (confirmed: the `public`-schema guard raises before
`get_settings()`/`create_engine()` ever runs). No `--dry-run` or real run has
been executed — that needs your explicit go, and even `--dry-run` still opens
a live connection (to introspect table shapes) — see the file's own
docstring on what dry-run does and doesn't skip.**

**Requirement 1 — gate failure aborts transactionally, what rolls back:**
Not one giant spanning Postgres transaction (would need a deeper refactor of
`load_to_supabase`/`resolve_dimension_fk` to accept a caller-supplied
connection — not done). Instead, explicit and schema-scoped: a gate failure
happens **before** schema creation runs — nothing to roll back, trivial case.
Any exception from schema creation onward is caught by one top-level
`try/except`; on catch (and never in `--dry-run`), the script prints exactly
what it's about to do and issues `DROP SCHEMA "<schema>" CASCADE`, then
re-raises. The scratch schema ends every failed run **either fully loaded or
fully absent, never half-loaded.** Stated explicitly in the script's own
module docstring, not just here.

**Requirement 2 — expected vs actual, printed per table:** `FactPlanItem`
carries frozen `expected_rows`/`expected_conflicts`/`expected_quarantined`,
measured against real staged data **today** (not recomputed live — a stale
target is itself information). Every table prints
`expected N / actual M  <<< MISMATCH` when they differ, plus a loud banner.
A mismatch does **not** trigger the schema-drop cleanup (a real, legitimate
data update looks identical to a regression from inside the script — a human
decides which, the script's job is only to make sure that decision is never
made blind) — it sets the run's final exit code nonzero instead.

**Requirement 3 — per-SKU backfill method logging:** `run_category_brand_backfill`
calls `log.info()` for every SKU as it's resolved (`sku -> category_path
(method), brand`), not just an end tally — default-on, `--quiet` suppresses it
down to the final tally only.

**Requirement 4 — `--dry-run` added to `load.py`:** `resolve_dimension_fk` and
`load_to_supabase` both gained a `dry_run: bool = False` parameter.
`resolve_dimension_fk`'s dry-run still issues a real, read-only SELECT to
resolve FKs for dimension rows that already exist; a row needing a genuinely
new dimension row gets `fk=NULL` and is counted in `rows_inserted` as "would
insert" — never a fabricated key. `load_to_supabase`'s dry-run does real
column-validation/table-introspection against the live schema, then returns
before the actual `INSERT`/`UPDATE`. `tests/etl/test_load.py`: 18 passed after
these additions, no regression.

**Two real problems caught and fixed before this was reported as done, not
after:**

1. **A schema-scoping bug** — the category/brand backfill's raw SQL
   (`SELECT`/`UPDATE product_dimension`) was written using
   `execution_options(schema_translate_map=...)`, which does **not** apply to
   raw `text()` SQL (Postgres resolves unqualified names in literal SQL via
   the connection's `search_path`, not SQLAlchemy's compile-time rewrite) —
   it would have silently targeted `public` instead of the scratch schema.
   Fixed: `load_to_supabase`/`resolve_dimension_fk` calls now go through a
   `schema_translate_map`'d engine (correct for their SQLAlchemy Core
   `Table(autoload_with=...)` constructs); this script's own raw SQL uses
   `SET LOCAL search_path` instead (correct for raw text). Documented as its
   own "SCHEMA SCOPING" section in the script's module docstring so this
   distinction isn't lost again.
2. **The validated keyword-rule fallback has nothing to apply to, in
   production, today.** Found while wiring the backfill step, not previously
   stated this precisely: the description-keyword rule (94.6% / 97.4%
   out-of-sample accuracy, Phase 0) was validated on the 1,427 SKUs that
   already have an SOH row — but the 380 SKUs it was meant to help have **no
   SOH row and no description anywhere else in the pipeline**
   (`unilever_sku.yaml`'s `"Product"` column is a bare SKU code, confirmed,
   not a name). There is no text to run the rule against for the population
   that needs it. **`category_path_source` will show only `direct_soh_match`
   (~1,427) and `unclassified` (~380) in a real run — `keyword_rule` will be
   0**, not the 3-way split originally designed. The fitting/prediction code
   is kept (for if a second Unilever description source is ever found) but
   is honestly not wired to run. This doesn't change Phase 0's finding that
   the 380 SKUs are immaterial (0.2% of revenue, 0 Tier A) — but it does mean
   `category_path_source='keyword_rule'` should not be expected to appear.

**Still open before an actual run can succeed:** migration 0011 must be
applied (this session did not apply it — no DB writes); `config/alias_tables/
unilever_brand.csv` does not exist yet (the backfill runs without brand-alias
normalization until it does, with a printed warning, not a silent gap).

---

## What's left, in order

1. Your go to apply migration 0011 (or run it inside the loader's own schema
   creation step — either way, still scratch-schema only).
2. Build `config/alias_tables/unilever_brand.csv`.
3. Your go for an actual `--dry-run` invocation (opens a live connection,
   writes nothing) to confirm the design holds against real Supabase, before
   any real (write) run.
4. Your go for a real scratch-schema run.
5. The scratch-vs-live diff (separate, not yet written).
6. The cutover decision.

**No DB writes were made this turn.** Stopping here for your review.

---

# Decision item 28 — the 15 real `inventory_sign_off` "unmatched" rows, logged

Not fixed (right call, per Yuan). Logged with full traceable identifiers, not
left only in prose, so they're findable in the source workbook by anyone —
`sku_code` is null for all 15 (that's exactly the problem), so file/sheet/row
is the only real identifier.

**Pattern A — 13 rows, all one file, one sheet, contiguous rows.** File
`data/raw/Del Monte/MONTHLY REPORT - AUGUST 2023/DELMONTE_INVENTORY SIGN
OFF_PANGASINAN & ILOCOS _AUGUST 2023.xlsx`, sheet `ILOCOS-ACTUAL`:

| `_row_ordinal` | `sku_description_raw` | `snapshot_date` | `region` | `quantity_on_hand` | `cost` |
|---|---|---|---|---|---|
| 0 | `"DESCRIPTION"` | 2023-08-01 | ilocos | 2,597.85 | ₱2,625,357.08 |
| 143 | `None` | 2023-08-01 | ilocos | 15.13 | ₱10,213.76 |
| 144 | `None` | 2023-08-01 | ilocos | 17.25 | ₱11,648.75 |
| 145 | `None` | 2023-08-01 | ilocos | 36.70 | ₱44,315.25 |
| 146 | `None` | 2023-08-01 | ilocos | 8.68 | ₱13,147.86 |
| 147 | `None` | 2023-08-01 | ilocos | 8.52 | ₱13,086.21 |
| 148 | `None` | 2023-08-01 | ilocos | 14.00 | ₱14,344.96 |
| 149 | `None` | 2023-08-01 | ilocos | 0.25 | ₱198.70 |
| 150 | `None` | 2023-08-01 | ilocos | 6.38 | ₱5,066.91 |
| 151 | `None` | 2023-08-01 | ilocos | 1.00 | ₱911.14 |
| 152 | `None` | 2023-08-01 | ilocos | 0.92 | ₱835.21 |
| 153 | `None` | 2023-08-01 | ilocos | 0.79 | ₱721.32 |
| 154 | `None` | 2023-08-01 | ilocos | 0.79 | ₱435.98 |

Row 0 (`"DESCRIPTION"`, the single large row — 2,598 cases / ₱2.6M) is likely a
section header or subtotal at the top of a second block within this sheet; rows
143–154 (consecutive, small realistic per-line quantities/costs) look like a
genuine but description-less block of real stock lines directly below it — two
different things sharing one `sku_description_raw=NULL`/`"DESCRIPTION"` pattern,
not necessarily one phenomenon. Needs the raw Excel sheet opened at these exact
rows to resolve, not guessed from the staged parquet.

**Pattern B — 2 rows, different files, each the first row of its sheet:**

| `sku_description_raw` | `snapshot_date` | `region` | `quantity_on_hand` | `cost` | `_src_file` | `_src_sheet` | `_row_ordinal` |
|---|---|---|---|---|---|---|---|
| `"WH/Stock"` | 2023-01-01 | pangasinan | 4,739.93 | ₱5,943,931.32 | `JANUARY_2023_INVENTORY_SANSAN_PANGASINAN&ILOCOS.xlsx` | `PANGASINAN INVENTORY SIGNOFF` | 0 |
| `"IS-WH/Stock"` | 2023-03-01 | ilocos | 1,994.78 | ₱2,176,536.00 | `MARCH_2023_INVENTORY_SANSAN_PANGASINAN&ILOCOS.xlsx` | `ILOCOS INVENTORY SIGNOF` | 0 |

Both are row 0 of their sheet, both large magnitude (warehouse-level, not
per-SKU scale) — read as warehouse-wide subtotal rows, but not confirmed against
the raw source.

**Status: open, not fixed, not guessed.** `sku_code_status='unmatched'` stays as
the honest flag. Whoever picks this up next should open the two source
workbooks at the cells above before writing any exclusion rule — the anti-
fabrication risk here runs the opposite direction from the TOTAL-row fix
(dropping real inventory data), so it needs eyes on the actual sheet, not
another pattern-match from staged parquet.

---

# STEP 5c (2026-09-14) — sequence executed: schema-only → dry-run → 6/6 reconciled. No fact data written.

Per Yuan's "go, apply migration 0011, build the alias table, run --dry-run,
report." Full sequence run, several real bugs found and fixed along the way —
reported in the order found, not smoothed over.

## 0. Plan doc correction (Yuan's note 1)

`yeah-thats-rigth-so-virtual-hollerith.md`'s Phase 1d verification line updated:
was "direct ≥79% + fallback (reported separately) + UNCLASSIFIED", now **"79.0%
direct + 21.0% UNCLASSIFIED, full stop — no fallback tier in production"** (the
keyword rule is built/validated but inert — decision item 27). 380 SKUs get
`category_path = 'UNCLASSIFIED'` (a real string, never NULL) and
`category_path_source = 'unclassified'` — confirmed in the migration and the
loader code.

## 1. The 15 inventory rows (Yuan's note 2) — logged with full identifiers

Done as decision item 28, both in `PROJECT_STATE_2026-09.md` §6 and as a full
table (file/sheet/row_ordinal, `sku_code` doesn't exist for these rows) earlier
in this document. Not fixed — correctly left open, needs the source workbooks
opened.

## 2. `config/alias_tables/unilever_brand.csv` — built from real evidence, 9 entries

Every entry backed by an actual description sample (not guessed) — see the CSV's
own `evidence` column. **LADYS/LADY'S/LADY'S → LADY'S**, **POND'S → PONDS**,
**SRF → SURF**, **BRZ → BREEZE**, **REX → REXONA**, **CLOSE → CLOSEUP**, **CREAM
→ CREAMSILK**, **DR.KAUFMAN → DR.KAUFMANN**.

**Three tokens explicitly checked and NOT merged** (a judgment call, stated, not
buried):
- **MASTER** ("MASTER FW ACNE FIGHT...", SKIN CARE) — no merge target found,
  kept as its own brand.
- **BABY** ("BABY DOVE SHAMPOO...") — this is "Baby Dove," a real Dove sub-line,
  not a spelling variant of DOVE. The alias table normalizes STRING variants of
  one intended brand, not brand-family/taxonomy decisions — merging it into
  DOVE would blend baby-care revenue into adult skin/hair-care reporting, a
  substantive choice, not a typo fix. Left as `BABY`.
- **BF** ("BF MYMGC DOY+CANNEDGDS...", CONDIMENTS, 1 row) — possibly an
  abbreviation of BESTFOODS, but unconfirmed and only 1 row. Not guessed.

## 3. Sign-off recorded — attributed to Yuan Kyle, per your explicit answer

The M2 sign-off gate (`check_signoff_gate`) blocks even `--dry-run` —
`transform/_signoff.json` didn't exist. Asked who the recorded name should be
(a real, permanent audit-trail decision, not implicit in "go"); you answered
"Yuan Kyle." Recorded via `transform_signoff.py --decision approved --by "Yuan
Kyle"`, re-recorded twice more as the manifest changed under the bug fixes
below (each time with full notes — see `transform/_signoff.json`).

## 4. The row-count reconciliation — resolved, not a bug

`transform_signoff.py` flagged "Row-count reconciliation vs Extract: MISMATCH"
before any of the above. Investigated rather than ignored: `staging/_manifest.json`
was last written **before** `data/raw/Synthetic Data/*` files were staged (a
separate, out-of-band synthetic-data-generation step that writes directly into
`staging/`, never through `extract.driver`). A fresh `python -m
analytics.etl.extract.driver` re-run (0 rejects, confirmed deterministic —
byte-identical `staging/` output on a repeat run) refreshed the real-file count;
`transform_driver` still sees more because it globs `staging/` directly,
picking up the synthetic files too. **This mismatch is expected and by design**
— Extract's manifest only ever tracked `data/raw/`-sourced files. Not fixed
(nothing to fix), documented in the sign-off notes so the next person doesn't
re-investigate it as new.

## 5. THE is_demo string/bool bug — found via that same Extract refresh, fixed

The fresh Extract run staged the Synthetic Data files for the first time this
session (a stale `staging/` snapshot simply hadn't had them before). That
surfaced something serious: **`purchase_order` conflict sheets jumped 0→110,
`invoice_num` values like `BILL/2021/0001` appeared in what my `is_demo != True`
filters were treating as REAL rows** — but CLAUDE.md is explicit that Del Monte
real data starts 2023, not 2021.

**Root cause, verified against raw parquet dtypes, not guessed:** every checked
cell in `data/raw/Synthetic Data/PURCHASE_ORDER_*.xlsx` and
`.../INVENTORY_SIGN_OFF_*.xlsx` carries `is_demo` as the literal **string**
`"True"`, not a real boolean — confirmed exactly two forms across both
families, `('True', str)` and `(np.True_, bool)`, roughly half and half. Since
Python/pandas `'True' != True` evaluates `True` (different types), **every
`df['is_demo'] != True` filter in this codebase and every scratchpad analysis
this session was silently counting these synthetic rows as real** — 1,909
`purchase_order` rows and 14,662 `inventory_sign_off` rows. `sales_register`
and `sell_out`'s synthetic rows were checked and are NOT affected (clean
boolean throughout).

**Fixed:** `analytics/etl/transform.py::coerce_is_demo_column()` (new),
wired into `transform_fact()` right after `apply_column_map()` — coerces any
case-insensitive `"true"`/`"1"`/`"yes"` string to real boolean `True`, wired in
Transform (not patched per call site) so no future analysis can reproduce the
bug by filtering before this runs.

**Re-verified, not just fixed-and-trusted:** with the coercion in place,
`purchase_order` and `inventory_sign_off`'s real-only row/conflict/quarantine
counts came back to **exactly** the numbers already computed earlier in Phase
1 (526/0/27 and 5,359/0/188) — the earlier work was correct all along, it had
simply been computed against a `staging/` snapshot that never had the buggy
files staged yet. This was the first time a complete, fresh Extract run
combined with the full real-data filter had actually been exercised together —
worth having found before any DB write, not after.

`pytest tests/etl/`: 128 passed after this fix.

## 6. `--schema-only` — applied migration 0011 for real, to the scratch schema. Two more bugs found and fixed en route.

**First attempt failed**, cleanly: `ALTER TABLE ... ADD COLUMN ... category_path_source`
succeeded, but the very next `COMMENT ON COLUMN` (which has a literal `%` in
its text — "~79% of Unilever demand SKUs") raised `UndefinedColumn`. Root
cause: `sqlalchemy.text()` treats a literal `%` as a psycopg2 paramstyle
placeholder and corrupts execution. **The rollback fired exactly as designed**
— printed what it was doing, issued `DROP SCHEMA "ssm_canonical" CASCADE`,
confirmed clean.

**Fixed (attempt 2):** switched to `conn.exec_driver_sql()` (bypasses
SQLAlchemy's bind-parameter layer). **Still failed**, differently: the very
FIRST file (`schema.sql`) now failed with `TypeError: immutabledict is not a
sequence` — `exec_driver_sql` still passes an (empty) parameters object to
psycopg2, which still tries to interpret any `%` in the query. Root cause of
where the `%` came from this time: my own chunk-based SQL splitter discarded
any WHOLE chunk that *started* with `--`, which silently dropped `0004_add_valuation.sql`'s
real `ALTER TABLE` entirely (glued to two leading comment lines with no `;`
between them, so the whole chunk got thrown away — invisible to my earlier
*static* check, which only counted chunks, not their survival). Separately,
`schema.sql` has a literal `%` inside a **trailing inline comment** on one
line (`discount_rate_label TEXT, -- ... 'LESS 2%' ...`) that a whole-line
comment stripper doesn't catch.

**Fixed properly (attempt 3):** rewrote the stripper to work **line by line**
(`_strip_sql_file()`, removes every line whose first non-whitespace characters
are `--`, plus bare `BEGIN;`/`COMMIT;` lines) instead of chunk-by-chunk, and
escape every literal `%` as `%%` (psycopg2's own documented escape) right
before `exec_driver_sql()`. **Third attempt succeeded.** Verified for real,
read-only, against the live scratch schema (not just "no exception raised"):
25 tables exist, `product_dimension.category_path_source`/`brand_source`
columns exist, `salesreturn_fact`'s new 4-column `UNIQUE(return_slip_num,
principal, region, invoice_num)` constraint exists,
`inventory_fact.quantity_on_hand`'s comment is set to the exact text from the
migration.

**One cosmetic issue found, not fixed:** `salesreturn_fact` now carries **two**
identical unique constraints (schema.sql's own bare `UNIQUE(...)` already had
the new 4-column definition baked in — from documenting migration 0011 in
schema.sql per house convention — so migration 0011's `DROP` + `ADD` ends up
adding a second, differently-named constraint with the same definition on a
from-scratch build). Harmless (Postgres allows it), but untidy — flagged for a
follow-up cleanup, not fixed now.

## 7. `--dry-run` — two more real gaps found and fixed, then 6/6 reconciled cleanly

**First real dry-run attempt failed** on the very first table:
`unilever_sku_demand_fact` — `transform_fact()`'s output legitimately carries
columns (`product_name`, `pack_size`, `principal`, ...) that table doesn't
have (some belong on `Product_Dimension`, `principal` is only needed to
*resolve* the Product_Dimension FK, not stored on this fact table at all).
`load_to_supabase()`'s own "unknown columns" anti-fabrication check correctly
refused to guess and raised — the caller (this loader) never actually
projected down to real table columns before calling it, a gap flagged all the
way back in the very first Phase 1 investigation and never implemented until
now.

**Fixed:** new `_project_to_table_columns()` in the loader — reflects the real
target table, drops anything with no home there (printed, not silent), while
`analytics/etl/load.py::load_to_supabase()` was also given a small, additive
fix: its unknown-columns check now excludes `dimension_fks`' own source
columns (needed for `resolve_dimension_fk()`, never meant to land on the fact
table) — both changes needed together, verified against `tests/etl/test_load.py`
(18 passed, no regression).

**Second issue, once the first was fixed:** every table showed `<<< MISMATCH`
against the frozen targets — because those targets were **real-only** numbers
(correctly computed earlier in Phase 1), but the loader **correctly loads
real+demo combined** (demo data is approved, loads into base tables, filtered
downstream by `_Real` views — CLAUDE.md rule 1). The targets were measuring the
wrong thing, not the load being wrong. **Fixed:** `FACT_PLAN`'s
`expected_rows` updated to the real+demo combined totals (44,575 / 53,901 /
4,594 / 1,901 / 8,584 / 21,612); `expected_conflicts`/`expected_quarantined`
stay **real-only** (the meaningful data-quality signal — demo-data conflict
noise, confirmed heavy for `purchase_order` 438 and `inventory_sign_off` 114
demo-only conflict groups, is computed separately via a second
`dedup_facts()` pass and printed as its own line, never blended into a
pass/fail target).

## 8. Final `--dry-run` — the full expected-vs-actual table, per Yuan's note 3

Every fact table, before authorizing anything:

| table | rows: expected / actual | conflicts (real-only): expected / actual | quarantined (real-only): expected / actual |
|---|---|---|---|
| `unilever_sku_demand_fact` | 44,575 / 44,575 | 0 / 0 | 0 / 0 |
| `sales_fact` | 53,901 / 53,901 | 1 / 1 | 591 / 591 |
| `purchase_fact` | 4,594 / 4,594 | 0 / 0 | 27 / 27 |
| `salesreturn_fact` | 1,901 / 1,901 | 0 / 0 | 773 / 773 |
| `sellout_fact` | 8,584 / 8,584 | 0 / 0 | 0 / 0 |
| `inventory_fact` (inventory_sign_off) | 21,612 / 21,612 | 0 / 0 | 188 / 188 |
| `inventory_fact` (ssis_soh/unilever) | 27,282 / 27,282 | — | — |

**Zero mismatches. Demo-data conflict noise reported separately, not blended
in:** `sales_fact` +1 demo conflict, `purchase_fact` +456, `salesreturn_fact`
+0, `sellout_fact` +16, `inventory_fact` +114 — all printed during the run,
none affecting the pass/fail comparison above.

**Category/brand backfill:** correctly shows 0/0/0 in dry-run — `Product_Dimension`
is genuinely empty at this point (dry-run never inserts dimension rows), so
there's nothing to query yet. A printed note explains this is a known dry-run
limitation, not a bug — real signal only on an actual load, where the fact
loads (step 3) populate `Product_Dimension` before the backfill (step 8) runs.

**Confirmed clean via a direct read-only query, not just "dry-run said 0
written":** `ssm_canonical`'s 7 fact/dimension tables all show **0 rows**.
Schema structure exists (from `--schema-only`); zero data anywhere.

## What's still open before a real load

- The `salesreturn_fact` duplicate-constraint cosmetic issue (§6).
- `sales_return`'s transform-key `return_type` decision (deferred, §5c item in
  `FACT_PLAN`'s own comment) — real quarantined would drop from 773 to 8 if the
  transform-side key is widened to match the DB constraint change already applied.
- The keyword-rule fallback truly has nothing to run on (§ earlier in this doc)
  — `category_path_source` will show `direct_soh_match`/`unclassified` only.

**No DB writes beyond the approved sequence** (`--schema-only`'s DDL, both
scratch-schema-only). `pytest tests/etl/`: 128 passed, final run. Stopping here
for your review of the table above before the real load.
