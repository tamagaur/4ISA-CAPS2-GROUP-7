# Grain Decision — Daily vs. Weekly vs. Monthly, and Disaggregation Feasibility

Synthesis, not a new audit. Every number below is pulled from prior read-only
audits already in `reports/` — `FULL_DATA_AUDIT.md`, `FULL_AUDIT.md`,
`SEASONALITY_AND_BASELINES.md`, `DEMAND_DIAGNOSIS.md`, `ADVISER_EVIDENCE.md`,
`FORECASTING_METHOD_RECOMMENDATION.md` — cross-checked against each other, not
re-derived from raw files this pass. Two sub-questions in Task 6/7 of the
original brief (the measured MAPE/MAE of a reconstructed daily series, and the
sales-register-vs-summary/inventory-balance tie-out) were **never actually
run** in any prior session and are marked UNVERIFIED below rather than
estimated — per this project's anti-fabrication rule, a number nobody computed
does not get invented to fill a table cell.

---

## Q1 — What is the finest grain that is ACTUALLY, CONSISTENTLY available?

**Monthly. Not weekly, and daily only survives as isolated, non-comparable, unloadable fragments.**

### The evidence

- **Unilever demand** (`Unilever_SKU_Demand_Fact_Real`, the only confirmed
  SKU-level Unilever source): 24,906 real rows, 1,807 distinct SKUs, date span
  **2023-01 to 2026-02 (38 months)**. The fact table's own grain is
  `calendar_month` — there is no finer timestamp anywhere upstream of it that
  survived into the loaded fact (FULL_DATA_AUDIT.md §B1).
- **Del Monte** — all four populated fact tables (`Inventory_Fact`,
  `Purchase_Fact`, `SellOut_Fact`, `Sales_Fact`) are monthly-period-keyed and
  **non-contiguous**: e.g. `inventory_sign_off` covers only 17 of 36 possible
  months in the 2023-01→2025-12 span (FULL_DATA_AUDIT.md §C1, §C7). The gaps
  are confirmed to be real reporting gaps, not upload failures — identical gap
  shape across all four independently-sourced fact tables.
- **The files literally named "DAILY"** (`SSIS DAILY SALES SUMMARY REPORT
  ...`, `SSIS DAILY OCTOBER 1-30, 2021.xlsx`, etc.) are **not daily records at
  file grain** — each one is a single workbook covering an entire ~29-30 day
  window, with a `RAW DATA` sheet that does carry per-transaction rows
  (4,997–5,130 rows for a single month, per FULL_AUDIT.md's raw sheet dump).
  That's the closest thing to daily granularity anywhere in the corpus — but:
  - **No confirmed natural key exists for these rows.** Every plausible key
    combination (`[Salesman, CALENDAR DAY, OUTLET]`,
    `[CALENDAR DAY, OUTLET, REASON CODE]`, etc.) sits at **84–86% duplicate
    rows** across 624,886 staged rows from 105 files (FULL_DATA_AUDIT.md
    §B10). The true grain is finer than any column combination present can
    express, or the same day is genuinely re-reported across multiple
    overlapping "DAILY"/"MONTHLY"/"SALES SUMMARY" files covering the same
    dates — not distinguished from each other in any prior pass.
  - **Consequence: `ssis_summary`'s `natural_key` is `null` by design** —
    `transform_fact()` refuses to run for it at all. All 624,886 rows sit in
    `staging/` only; **zero of them have ever reached a fact table**
    (FULL_DATA_AUDIT.md §D2). This is the single largest raw-vs-loaded gap in
    the entire pipeline.
  - The SOH (stock-on-hand) sheets in the same files have the identical
    problem one level up: `(Article No, period)` alone has a **64.2%
    duplicate rate** (FULL_DATA_AUDIT.md §B7), traced to the same
    overlapping-file pattern — a "DAILY" file and a "SALES SUMMARY" file both
    carrying an identical `SOH(DEC 1, 2021)` snapshot with matching values.
- **Weekly**: no source in this corpus reports at a weekly cadence at all —
  not filename-implied, not found on inspection. It was never a real
  candidate; the actual choice is monthly vs. the fragmentary daily material
  above.

### Usable date range and observation count per Category A SKU

- Real, loadable, SKU-level, monthly data exists for **38 months (2023-01 to
  2026-02)** on the Unilever side.
- Of the 136 Unilever Tier-A (Category-A-equivalent) SKUs used in this
  session's forecasting work: **99 have ≥24 months** of that 38-month span;
  **89 reached a full SARIMA fit** (`status='ok'`); only **52 survive** the
  strictest combined filter tested (≥36 months history AND no early exit
  before the corpus's last real month) (FULL_DATA_AUDIT.md §E2–E4). Per-SKU
  observation counts, min/median/max, are in `reports/audit_E1_full_136.csv`
  and `reports/demand_diagnosis_shape_full.csv` (all 1,807 SKUs) — re-running
  that exact table wasn't necessary here since it already exists at full
  granularity.
- **Important qualifier already flagged in this session's own prior work**:
  the 136-SKU population above was later found to be contaminated by
  synthetic data bleeding into the "current period" selection
  (`FORECASTING_METHOD_RECOMMENDATION.md` §0) — the clean, all-real Tier-A
  population for the latest real period (2026-02) is **132 SKUs**, with
  substantially more short-history SKUs (40/132, 30%, under 12 months) than
  the contaminated list suggested. Any per-SKU observation-count table pulled
  from this corpus should be re-derived against the 132-SKU real list, not
  the 136-SKU contaminated one, if it's going into the manuscript.

**Recommendation: model at monthly grain.** Nothing finer clears the bar of
"actually, consistently available" — daily exists only as unkeyed staging
fragments that cannot currently be turned into a fact table without solving
the natural-key problem first, and weekly doesn't exist as a source at all.

---

## Q2 — Is monthly-to-daily disaggregation defensible, or must the pipeline aggregate upward?

**Aggregate upward. Disaggregation is not defensible with what's in this corpus, and the specific quantitative test (Task 6d's MAPE/MAE) was never run — not because it was skipped carelessly, but because step (a) already fails.**

Task 6 asks a sequential question: find overlap months with both a monthly
summary and true daily records for the same region/SKU set → derive a
share-of-month profile → test its stability → measure reconstruction error.
Step (a) is where this breaks:

- The "daily" material (the `RAW DATA` / `Invoice Reg` sheets inside the
  "DAILY" files) is **invoice-grain, not SKU-grain** — it carries
  `Salesman, CALENDAR DAY, OUTLET, GSV, ...` and a real `Invoice No.` in only
  1 of 105 files checked (FULL_DATA_AUDIT.md §B10). It does not carry a
  product/SKU column at all in the general case. There is no SKU-level daily
  series to derive a share-of-month profile *from* — the "true daily
  records" half of the comparison doesn't exist at the grain the monthly
  summary needs to be split into.
- Even at the outlet/day grain the raw sheets do carry, the 84–86%
  duplicate-key rate means it's not established which rows are genuine
  additional transactions and which are the same day re-reported by an
  overlapping file. Building a "true" daily profile on top of that
  ambiguity would be building on an unresolved data-quality problem, not a
  clean baseline.
- On the Del Monte side, no source has SKU-level daily or even monthly flow
  data to disaggregate from in the first place — `purchase_order`,
  `sales_register`, and `sales_return` all lack a product/SKU column
  entirely, confirmed against `information_schema.columns`
  (FULL_DATA_AUDIT.md §C5–C6). There is nothing to disaggregate.

**Task 6d (measured MAPE/MAE of a reconstructed daily series): UNVERIFIED —
not computed.** No prior session attempted this test, and it should not be
attempted by first assuming a profile is stable; the honest state is "the
precondition for the test (a real SKU-level daily series to validate against)
does not exist," which is itself the answer to Q2, not a gap needing a
fabricated number.

**Conclusion: disaggregating monthly totals into daily figures here would
manufacture data, not recover it.** The pipeline should aggregate upward to
monthly (already what it does) rather than attempt to invent daily shape from
a corpus that never captured SKU-level daily data validly in the first place.

---

## Strongest panelist objection, and the data's answer

**Objection**: "You have files literally named 'DAILY' — how can you claim
monthly is the finest usable grain? Isn't that just a modeling shortcut,
not a data limitation?"

**Answer**: The filename is not the grain. Every "DAILY" file's `RAW DATA`
sheet was opened and profiled (not trusted by name) — it does contain
per-transaction rows, but (1) those rows carry no SKU/product column in the
overwhelming majority of files, so they cannot produce a SKU-level daily
demand series regardless of key quality, and (2) even at the outlet/day grain
they do carry, no combination of the columns present forms a clean key —
84–86% duplicate rows against every candidate tested. This was verified by
directly testing five different plausible key combinations against 624,886
staged rows, not asserted from the filename or skipped. The daily material
is real, but it is unusable *for SKU-level demand modeling* in its current
form — that is a distinct, weaker, and more defensible claim than "no daily
data exists," and it is the one this document is actually making.

A second, related version of the same objection — "then why not fix the key
and load it?" — is answered directly in `FULL_DATA_AUDIT.md` §B10/§D2: doing
so would require either resolving which of several overlapping source files
is authoritative per period (the same class of problem `source_of_truth.yaml`
already solves for other doc types via `cross_check_roles`, not yet solved for
`ssis_summary`) or confirming a genuine missing grain dimension inside the
already-collapsed summary columns — both are real engineering work, not
something this audit can resolve by re-reading the files harder.

---

## Data problems for the cleaning stage, ranked by threat to modeling

1. **`ssis_summary` has no working natural key (85% duplicate rate on every
   candidate) and is never loaded** — the largest single raw-vs-loaded gap
   in the pipeline (624,886 rows stuck in staging). Blocks any attempt at
   finer-than-monthly Unilever modeling and blocks Del Monte SKU-level
   demand entirely, since it's the only place transaction-level Del Monte
   sales data lives at all. **Highest threat** — this is the actual reason
   Q1/Q2 resolve the way they do.
2. **Del Monte `SalesReturn_Fact` never populated despite 19 real files on
   disk** (0 rows loaded, no Load driver built) — silently understates
   returns in any KPI or safety-stock calculation that should net them out.
3. **Duplicate/overlapping source files at identical periods** — the same
   `SOH(DEC 1, 2021)` snapshot, or the same day's sales, appearing near-
   identically across a "DAILY" file and a "SALES SUMMARY" file covering the
   same dates. Root cause of both the SSIS natural-key failure and the SOH
   64.2% duplicate-key rate above. Needs a `cross_check_roles`-style
   authoritative-file resolution before any finer-grain rebuild is
   attempted.
4. **Non-contiguous real months, both principals** — Del Monte real coverage
   is 17–22 months scattered across a 36-month span depending on doc type;
   Unilever's own SKU population is >50% under 12 months of real history.
   Any model choice (including the monthly-grain recommendation above) still
   has to handle large real gaps, not just accept monthly as sufficient.
5. **Inconsistent Del Monte SKU coding** — 604 distinct real inventory
   `sku_code`s split roughly evenly between a confirmed `9D[A-Z]{2}\d{4,6}`
   pattern and an uncharacterized "other" format that coexists in every
   single real month (not an era boundary) — 1,790 rows never individually
   verified as a real second code family vs. parsing artifacts
   (FULL_DATA_AUDIT.md §C2). On the Unilever side, 22 Article No pairs show
   confirmed renumbering, several **bidirectionally** (the same two codes
   each appear as "old" and "new" relative to each other in different
   windows) — a source-system instability, not a clean one-way reissue.
6. **Del Monte sell-out taxonomy break (Jan 2025)** — 94 distinct
   `category_path` values before, a different set after, zero real months
   with both eras present to check continuity directly (CLAUDE.md open item,
   confirmed in FULL_DATA_AUDIT.md §C4). Affects category-level trending,
   not SKU-level modeling directly.
7. **Reconciliation checks (Task 7) were never run** — sales-register-vs-
   summary tie-out and the inventory balance identity
   (opening + purchases − sell-out − returns = closing) have no completed
   check anywhere in this repo's audit history. **UNVERIFIED, flagged as
   outstanding work**, not lower-priority by evidence — it's simply untested,
   and given items 1–3 above, a reconciliation attempt would likely surface
   the same overlapping-file ambiguity rather than a clean pass/fail.
8. **No zero-quantity rows are ever explicit** — an absent month means zero
   sold by convention, not a stored zero (DEMAND_DIAGNOSIS.md §2). Low threat
   on its own, but any grain change or gap-filling logic must apply this
   convention consistently or it will silently invent "missing" months that
   are actually confirmed zeros.

---

## Bottom line

- **Q1: monthly**, confirmed consistently available 2023-01 to 2026-02
  (Unilever, 38 months) and 2023-01 to 2025-12 non-contiguously (Del Monte).
  Category-A SKU observation counts range from single digits up to 38
  months; only 52 of 136 candidate SKUs clear the strictest history-and-
  recency bar tested.
- **Q2: aggregate upward, do not disaggregate.** The precondition for a
  defensible daily split — a real, cleanly-keyed, SKU-level daily series to
  derive and validate a profile against — does not exist in this corpus.
  Task 6d's MAPE/MAE test was not run because it cannot be run honestly on
  data that fails the input requirement, not because it was skipped.
- **The five-year span is not five continuous years of usable records.**
  Real, loadable data is non-contiguous (Del Monte: 17–22 of 36 months per
  doc type) and, for the majority of the Unilever SKU catalog, under 12
  months of real history per SKU. Treat any "5 years of data" framing in the
  manuscript as the corpus's outer date bound, not its usable density.
