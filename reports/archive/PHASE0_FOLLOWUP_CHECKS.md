# Phase 0 follow-up — five checks  (read-only, 2026-09-09)

No code changed, no DB writes. Findings only.

---

## 1. `ssis_summary` and `purchase_order` — do they reach a fact table?

### `check_reject_rate_gate` measures **SHEETS/FILES, not rows** — and reads the **Extract** manifest, not the transform one

`analytics/etl/load.py::compute_reject_rate`:
```python
staged   = len(manifest.get("staged", []))
rejected = len(manifest.get("reject", []))
total    = staged + rejected
reject_rate = (rejected / total) if total else 0.0
```
`check_reject_rate_gate` loads **`staging/_manifest.json`**, whose `reject` list is
*"unreadable files, no detectable header/data, Magnolia-quarantined content"* only
(`compute_reject_rate` docstring) — **checksum mismatches and dedup/natural-key
blocks are deliberately excluded.**

`staging/_manifest.json` `reject = []` → **0 rejects → the gate passes trivially
today.** The 805 `ssis_summary` blocks and 921 total rejects live in
`transform/_manifest.json` — a *different* manifest the gate never reads. So the
premise that `ssis_summary` "counts against the reject gate" is **incorrect**;
marking it excluded won't change the gate.

### `ssis_summary` — no product grain, no fact destination, no real rows

**Column map** (`config/column_maps/ssis_summary.yaml`): `salesman, calendar_day,
reason_code, outlet_code, outlet_name, gsv, discount_amount, net_amount, vat,
net_amount_inc_tax, remarks`. **No SKU / article / product / item column.**

**Staged parquet** — 805 sheets by `_sheet_role`:

| role | sheets | rows | product identifier? |
|---|---|---|---|
| `raw_data` | 105 | 624,886 | **none** — outlet × day sales value |
| `per_customer_summary` | 150 | 635,813 | **none** — same columns |
| `invoice_reg` | 102 | 602,389 | **none** — value columns only |
| `data` (B.O SUMMARY sheets) | 311 | 80,115 | a `CATEGORY` col, but it's RMR bad-order category, not product |
| `scratch` | 135 | 2,420 | junk (`Not assigned`, `INVOICE`) |
| `bo` (2020–21 "BO INVENTORY" sheets) | 2 | 4,064 | **`Product Code` + `Item category`** — the only ones |

**1,863,088 of 1,949,687 rows (95.6%) are product-less outlet/day/invoice sales
value.** Only 2 sheets (4,064 rows, Nov-2020→Mar-2021, pre-project-window) carry a
real product code.

- **(a) Is any fact sourced from it?** `config/source_of_truth.yaml` declares
  `sales.unilever → {doc_type: ssis_summary, system_of_record_role: raw_data,
  natural_key: null}`. But `natural_key: null` makes `transform_fact` refuse to
  run for it, **and** `Sales_Fact` carries `CHECK (principal = 'delmonte')`
  (DEC-10) so it structurally cannot hold Unilever rows. **No fact is actually
  sourced from it — the `source_of_truth.yaml` entry is a dead declaration.**
- **(b) Any real DB row traceable to it?** **No.** Queried every fact for real
  rows from an `ssis_summary`-style source (RAW DATA / SALES PER CUSTOMER /
  INVOICE REG sheets): `sales_fact` 0, `sellout_fact` 0, `purchase_fact` 0. (The
  `inventory_fact` rows that superficially match are from **SOH / inventory
  sign-off sheets** that live inside the same SSIS workbooks — `_doc_type =
  ssis_soh` / `inventory_sign_off`, loaded via `scratch/run_ssis_soh_load.py` —
  not the `ssis_summary` sales grain.)
- **(c) Correct treatment:** an explicit *"excluded — no fact destination"*
  marker in `config/source_of_truth.yaml` (replace the dead `natural_key: null`
  `sales.unilever` entry, or add an `excluded: true` / reason field). Value: it
  makes the "we deliberately do not load 1.95M rows of product-less outlet sales"
  decision **auditable**, and stops `transform_driver` re-classifying 805 sheets
  as `blocked` every run. It does **not** affect the reject-rate gate. Separately
  worth a one-line note: the `bo` role (2 sheets) + the B.O SUMMARY `data` role
  could feed a **category/account-grain BO monitoring** view — not a fact table.

### `purchase_order` — reaches `Purchase_Fact`, thinly

- `source_of_truth.yaml`: `purchase.both → {doc_type: purchase_order,
  natural_key: [invoice_num, principal, region]}` — **Purchase_Fact is sourced
  from it.**
- **Real rows traceable: yes.** All 353 real `purchase_fact` rows come from
  `data/raw/Del Monte/MONTHLY REPORT - .../…PURCHASE ORDER.xlsx` (and `…PURCHASES.xlsx`),
  sheets `PANGASINAN PURCHASE` / `ILOCOS PURCHASE`. 10 months, Del Monte only.
- The **49 transform rejects** are dedup conflicts (`invoice_num` collisions
  across the multi-vocab eras). Those sheets' rows didn't load, but the family
  overall reaches the fact table. `units_received` is 0/353 populated (relevant
  to the D5 rate — see Phase 0).

---

## 2. `category_path` direct-match ceiling — **measured: 79.0%, not 90%**

Joined the 39 staged `ssis_soh` parquet files (27,321 rows, 1,718 distinct
`sku_code`, **all 1,718 carry a non-null `category_desc`**, 18 distinct category
values) against the 1,807 real Unilever demand SKUs:

| Path | Count | % of 1,807 |
|---|---|---|
| **(A) direct `category_desc` match** (SKU has a SOH row) | **1,427** | **79.0 %** |
| (B) in SOH but `category_desc` NULL | 0 | 0.0 % |
| (C) **no SOH row at all** | **380** | 21.0 % |

**Proposed verification bar (reported separately, never blended):**
- **Direct match: ≥ 79 %** (1,427 SKUs) — the actual ceiling of the SOH path.
- **Fallback: whatever the brand→category rule recovers of the 380** — reported
  as its own number, e.g. "fallback recovered 240 / 380".
- **Remainder** (fails both): an explicit `UNCLASSIFIED` bucket — **not NULL**
  (NULL is indistinguishable from "not yet processed") and **not silently
  excluded** — so D1/D2/D4 can show an "Unclassified" slice and its size is
  visible. Target: `UNCLASSIFIED` < ~8 % of demand SKUs (~140), reviewed by hand
  before the Phase 1 gate.

The 18 real category values: BEVERAGES, CONDIMENTS, COOKING AIDS, DEODORANTS &
FRAGRANCES, DRESSINGS, FABRIC CLEANING, FABRIC ENHANCERS, HAIR CARE, HEALTHY
SNACKING, HOME & HYGIENE, MINI MEALS, NON CORPORATE PERSONAL CARE CATEGORY, ORAL
CARE, OTHER FOODS, OTHER NUTRITION, SCRATCH COOKING AIDS, SKIN CARE, SKIN
CLEANSING.

---

## 3. brand→category fallback — **the mapping is NOT 1:1, and `brand` has no validation data**

### (a) Making `brand` reproducible from a committed rule

`Product_Dimension.brand` is written by no code (Phase 0). The SOH staged parquet
carries `article_description` per SKU (e.g. `"SURF POWDER ROSE FRESH L 288X65G"`).
A committed rule would be:
```
brand = first whitespace-delimited token of article_description, upper-cased,
        then normalised through a small committed alias table
        (LADYS / LADY'S / LADY?S  ->  LADY'S ;  handle the mojibake).
```
Written into `Product_Dimension.brand` during the SOH→dimension step (Phase 1c),
with the alias table under `config/alias_tables/unilever_brand.csv`. Documented,
re-derivable.

**But:** the first-token rule already produced **3 variants of one brand**
(`LADYS`, `LADY'S`, `LADY?S` — encoding damage in `article_description`) in this
check. The alias table is mandatory, not optional.

### (b) Is brand→category 1:1? — **No.**

Derived brand from SOH `article_description`, crossed with `category_desc`:

- 35 distinct derived brands. **9 (26 %) span more than one category:**

| Brand | Categories it spans |
|---|---|
| KNORR | COOKING AIDS · HEALTHY SNACKING · MINI MEALS · SCRATCH COOKING AIDS |
| BESTFOODS | CONDIMENTS · DRESSINGS · OTHER FOODS · OTHER NUTRITION |
| LADY'S | CONDIMENTS · DRESSINGS · (OTHER FOODS · OTHER NUTRITION) |
| DOVE | DEODORANTS & FRAGRANCES · HAIR CARE · SKIN CLEANSING |
| BABY (Dove Baby) | HAIR CARE · SKIN CARE · SKIN CLEANSING |
| SURF | FABRIC CLEANING · FABRIC ENHANCERS |
| AXE | DEODORANTS & FRAGRANCES · SKIN CLEANSING |

- Only **26 / 35 brands are cleanly 1:1.** And the multi-category brands include
  **SURF and KNORR — the two largest by revenue** (~half the portfolio).

### (c) The proposal

- **`Product_Dimension.brand` and `Product_Dimension.category_path` are disjoint
  in the current DB** — the 291 SKUs with `category_path` are SOH-only (no
  demand, no brand); the 1,807 with `brand` are demand SKUs (no category). **Zero
  overlap** — there is no existing data to validate a brand→category mapping
  against. It can only be validated against the SOH `article_description`↔
  `category_desc` pairing itself.
- Because brand→category is not 1:1 for the biggest brands, a **flat brand→category
  fallback is not defensible.** Options for the 380 SKUs with no SOH row:
  1. **Sub-brand / description-token rule** — match on more of `article_description`
     (e.g. `"SURF ... FABRIC CONDITIONER" → FABRIC ENHANCERS` vs `"SURF POWDER" →
     FABRIC CLEANING`), built as a committed keyword→category table from the
     1,427 SKUs that *do* have both a description and a category. This is the
     honest fallback — it uses the same signal the direct path uses, just applied
     to SKUs whose SOH row is missing.
  2. For any SKU where the token rule is ambiguous or the brand is one of the 9
     multi-category brands with no disambiguating keyword → **`UNCLASSIFIED`**.
  3. **Never** assign a category from a bare brand for SURF/KNORR/DOVE/BESTFOODS/
     LADY'S/AXE/BABY without a keyword confirmation.
- **Fallback for SKUs that fail both paths:** an explicit **`UNCLASSIFIED`**
  category value (a real string, not NULL), included in D1/D2/D4 as its own
  slice. D1 (category ABC) and D4 (decomposition) run on it like any other
  category; D2 (SKU-within-category) treats `UNCLASSIFIED` as one bucket. Its size
  is a Phase 1 gate metric.

---

## 4. `unilever_sku` row delta — **not coincidence; the 30 extra sheets ARE the demo rows**

The 31 staged `unilever_sku` sheets:

| Sheets | Source | Rows |
|---|---|---|
| **1 real** | `UnileverLaUnionSalesperSKU2023to2026.xls` / sheet1, period 2023-01…2026-02 | **24,906** |
| **30 synthetic** | `GENERATED_BACKFILL_unilever_sku_<period>` — 24 months 2021-01…2022-12 + 6 months 2026-03…2026-08, ~630–690 rows each | **19,677** |
| | **staged total** | **44,583** |

Fact table `unilever_sku_demand_fact`: 44,575 total = 24,906 real + 19,669 demo.

- Staged 44,583 − fact 44,575 = **8-row attrition** between staging and load
  (null/dedup drops). Negligible.
- The 30 `GENERATED_BACKFILL_*` sheets → the 19,669 `is_demo=true` rows.
  `scripts/generate_synthetic_backfill.py` produced the files;
  `convert_synthetic_to_staging.py` staged them under `doc_type='unilever_sku'`.
- The synthetic month set (2021-01…2022-12 **and** 2026-03…2026-08) is exactly
  the demo-demand month set and the purged ABC-period set from Phase 0. Same
  origin, one generation effort.

---

## 5. ABC period count — **38 is right; 36 was wrong (plan doc)**

`abc_classification` has **38 distinct `classification_period` values**, contiguous
monthly **2023-01 → 2026-02** — exactly the real Unilever demand span.

- `PROJECT_STATE_2026-09.md` (38) — **correct**.
- Plan doc (36) — **wrong** (a mis-statement; the DB has 38).
- `MAX(classification_period)` = **`2026-02`** (both the unfiltered `MAX()` and the
  `WHERE principal='unilever'` one — there are no Del Monte or synthetic periods
  left after the purge). So `run_sarima.py`'s old unconditional-`MAX()` hazard is
  currently inert.

**One thing to flag:** the Tier-A count is **not stable** month to month —
`2025-12` = 89, `2026-01` = 149, `2026-02` = 132, range across all 38 periods
**89–149**. "132 Tier-A SKUs" is one bouncy month's snapshot. Whatever cohort the
clustering test and the LP use should be pinned to a stated period and the
instability noted (a SKU near the 80% cumulative-revenue line flips tier as
monthly revenue mix shifts — `boundary_flag` exists for exactly this).

---

## Net effect on the plan

| Plan item | Change |
|---|---|
| Phase 1 verification: "`category_path` non-null for ≥90%" | → **direct match ≥79% + fallback (reported separately) + `UNCLASSIFIED` bucket <~8%** |
| Phase 1c: brand→category fallback | → **description-keyword rule** (not flat brand), + a committed brand alias table; flat brand→category is not defensible (SURF/KNORR span categories) |
| Phase 1b: `ssis_summary` | → replace the dead `sales.unilever / natural_key: null` entry with an explicit **"excluded, no fact destination"** marker. **Not** a reject-gate issue. |
| Phase 1b: `purchase_order` | reaches `Purchase_Fact` (353 real rows); 49 dedup-conflict sheets to resolve; keep in scope |
| Phase 3/4 cohort | pin to a stated ABC period; note Tier-A count instability (89–149) |
| Plan doc "36 periods" | correct to 38 |
