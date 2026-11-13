# Backend Onboarding Guide

**Last generated against commit `8fc5cd0` (2026-08).** The code moves fast — if something here doesn't match what you see in the file, trust the file and ping Yuan (or whoever touched it last) to get this doc updated.

This is for Audrey, Thea, and Maika. You don't need to have opened this repo before. This covers everything that runs on a server or in a script — the data pipeline, the database, and the API. It does **not** cover the Next.js frontend at all.

Read this on your phone if you want; every section is short enough to skim, and the file-by-file part is meant to be looked up, not read start to finish.

---

## 1. Getting it running locally

This is the first thing you'll need, before any of the explanation below matters.

1. **Clone the repo** and `cd` into it.
2. **Python version:** this repo is developed against **Python 3.13**. Create a virtual environment with whatever 3.13.x you have (`python -m venv .venv`, then activate it).
3. **Install dependencies:** `pip install -r requirements.txt`. Every version in that file is pinned — don't `pip install --upgrade` anything without checking with Yuan first (there's a rule about this in the file's own header comment).
4. **Set up your `.env`:** copy `.env.example` to `.env` (never commit `.env` — it's gitignored) and fill in three values:
   - `SUPABASE_DB_URL` / `SUPABASE_KEY` — only needed once a real Supabase project exists (see `SUPABASE_SETUP.md`). Nothing in Extract/Transform needs these; only `analytics/db/seed_date_dim.py`, `analytics/etl/load.py`, and `backend/` do.
   - `BACKEND_API_KEY` — any long random string works locally; this gates the FastAPI endpoints (once auth is actually wired up — see the gotcha in §4.4).
5. **Get the raw data:** `data/raw/` isn't part of the repo (it's real SSM client data — gitignored, ask Yuan for the folder directly). Extract, and everything downstream, has nothing to read without it.
6. **Run Extract:** `python -m analytics.etl.extract.driver` from the repo root. This reads everything in `data/raw/` and writes typed output to `staging/` (also gitignored — it's regenerated, not committed). Takes a couple of minutes against the full real corpus. When it finishes, open `staging/_review.html` in a browser to see what actually staged.
7. **Run the tests:** `pytest tests/ -q` from the repo root. Most of the suite runs fine with no `.env` and no `data/raw/` at all (synthetic fixtures); a handful of tests in `tests/etl/test_extract.py` and `tests/test_transform_config.py` skip themselves cleanly if `data/raw/` or `staging/_manifest.json` aren't present, rather than failing.

**Verify this yourself:** if steps 1–7 above worked, `pytest tests/ -q` should end with a line like `117 passed` (see §4.6 for what that number actually covers, and treat this doc's number as a snapshot — run it yourself for the current count).

---

## 2. How the whole thing fits together (one page)

Think of it as a conveyor belt with five stops. A file drops in one end; a number shows up on a dashboard at the other end.

**Stop 1 — Raw files.** SSM (San San Marketing) hands us real Excel/CSV exports: Sales Registers, Purchase Orders, Inventory Sign-Offs, Sell Out reports, Sales Returns (RMR GS/BO), a Unilever SKU-level file, and Unilever's SSIS Sales Summary reports. These live in `data/raw/` and are never edited by any of our code — the raw files stay exactly as SSM gave them to us.

**Stop 2 — Extract.** One Python script (`analytics/etl/extract/driver.py`) reads every raw file, figures out what kind of document it is, and writes it out as a "staging" table (a `.parquet` file — a fast, typed version of a spreadsheet) under `staging/`. Extract does **not** rename columns, pick a "correct" answer between two conflicting sheets, or clean anything up — it just reads faithfully and tags each row with where it came from (which file, which sheet, which region, which principal — Unilever or Del Monte — and so on). Those tags are called **provenance columns** (see the glossary). This is also where **DEC-04** and **DEC-07** matter: DEC-04 says every fact has exactly one "system of record" sheet per company, and DEC-07 says the labels we use in config must match what Extract actually produces, not a label someone guessed.

**Stop 3 — Transform.** `analytics/etl/transform.py` takes staged data and turns it into something that matches our database's shape: it renames SSM's messy real-world column names ("REFNBR", "AMOUNT", "Town Display"...) to our clean names (`invoice_num`, `net_amount`, `region`...), picks the one correct source when SSM's files duplicate each other, and removes true duplicate rows. This is where **DEC-02** (transaction-grain facts vs. product-grain facts) and **DEC-03** (Unilever is forecast per-SKU, Del Monte per-category — because that's the finest grain the real data actually supports) live. **Important: there is no single script that runs Transform end-to-end yet** — the pieces exist and are tested, but nobody has wired them into one driver the way Extract has `driver.py`. See the file-by-file section for exactly what's built vs. missing.

**Stop 4 — Load.** `analytics/etl/load.py` takes Transform's clean output and writes it into our Postgres database (hosted on Supabase). This is where **DEC-09** lives: before a fact row (say, a sale) can be saved, Load looks up or creates the dimension row it points to (the customer, the salesman, the product) and gets its ID — this happens here, not in Transform, because some tables *require* that ID to exist before the row can be saved at all.

**Stop 5 — The database, then the API.** Once data is in Postgres (`analytics/db/schema.sql` defines every table), separate analytics scripts read it and write derived results back: `analytics/classification/abc.py` ranks products by revenue (ABC analysis), `analytics/forecasting/sarima.py` predicts next month's demand per SKU, `analytics/optimization/lp.py` turns that forecast into a recommended order quantity. The FastAPI backend (`backend/`) then serves all of this — inventory levels, forecasts, recommendations, ABC tiers — over HTTP, for the dashboard to display. **The backend only ever reads from Supabase — it never runs the pipeline itself and never imports the `analytics` package.**

One thing that's true of the whole project and worth knowing up front: **nothing here ever guesses.** If a value can't be honestly determined from the real data, the code leaves it blank (`NULL`) and says so, rather than inventing a plausible-looking number. You'll see this pattern — called the anti-fabrication principle — everywhere, and it explains a lot of code that might otherwise look overly defensive.

**Verify this yourself:** run Extract (§1 step 6), then open `staging/_manifest.json` and check the `"doc_type"` field on a few staged rows against the seven names in Stop 2 above — that file is the ground truth for what actually ran, not this paragraph.

---

## 3. Suggested reading order (5 files)

Not alphabetical — read in this order to build the pipeline in your head, stop to stop:

1. **`analytics/db/schema.sql`** — Start at the destination. This is every table the pipeline is building toward. Skim it before anything else so you know what "done" looks like.
2. **`analytics/etl/extract/_shared.py`** — The real engine behind Extract. Long file, but it's the one place that explains how a messy Excel file becomes a clean, tagged table.
3. **`config/source_of_truth.yaml`** — The map of "when SSM gives us two versions of the same data, which one do we trust." Short file, huge conceptual weight (DEC-04).
4. **`analytics/etl/transform.py`** — How staged data becomes database-shaped data. Read this with `source_of_truth.yaml` open next to it.
5. **`analytics/etl/load.py`** — How clean data actually lands in Postgres, including the dimension-lookup trick (DEC-09) that's easy to miss if you only read `schema.sql`.

After these five, the rest of the file-by-file section below will make sense without reading every file top to bottom.

**Verify this yourself:** these five are a recommendation, not a fact you can check — but once you've read them, the fastest self-test is to open `analytics/db/schema.sql` and `analytics/db/models.py` side by side and confirm they still describe the same 14 tables. If they've drifted, that's real and worth flagging.

---

## 4. File-by-file

### 4.1 `analytics/etl/` — the pipeline's core stages

**Verify this yourself:** `pytest tests/etl/ -q` — every claim in this subsection about a function's behavior should have a matching test. For the "Extract works, Transform/Clean/Granularity don't have a driver yet" claim specifically: `find analytics/etl -maxdepth 2 -iname "*driver*"` should return only `extract/driver.py`.

#### `analytics/etl/__init__.py`, `analytics/etl/extract/__init__.py`
**What they do:** Package docstrings only — the `extract` one usefully lists all seven document families and their driver files in one place. No code in either.
**Status:** N/A.

#### `analytics/etl/extract/_shared.py`
**What it does:** The real Extract engine. Every per-file-type driver (below) is just a thin wrapper around this.
**Why it exists:** So the messy work of reading Excel files — detecting where the header row is, figuring out which region/company a sheet belongs to, deciding if a column is text/money/date, verifying totals — is written once and shared, instead of copy-pasted seven times.
**Calls / called by:** Called by all seven family drivers (`sales_register.py`, `unilever_sku.py`, etc.) and by `driver.py` indirectly. Calls into `profiling/` (an earlier discovery-pass module that already figured out how to detect headers and infer document types) rather than re-inventing that logic.
**Key functions:**
- `select_source_files` — lists every real Excel/CSV file under `data/raw/`.
- `infer_sheet_region` / `infer_sheet_role` — tags a sheet as `pangasinan`/`ilocos`/etc. and as `raw_data`/`invoice_reg`/`gs`/`bo`/etc.
- `classify_column` / `coerce_column` — decides if a raw column is text, a code (never turn into a number — leading zeros are real), money, or a date, and converts it safely.
- `totals_row_checksum` — compares our computed sum against the spreadsheet's own totals row, as a sanity check (never a reason to drop data — see Gotchas).
- `extract_sheet` / `process_file` / `parse_doc_type_files` — the actual per-sheet, per-file, per-document-type pipeline.
- `write_staging_table` / `build_manifest` / `save_manifest` — writes the `.parquet` output and the `staging/_manifest.json` audit trail.
**Gotchas:** A checksum mismatch does **not** cause a row to be dropped — it's staged anyway with a flag (`_checksum_status = mismatch`), because SSM's own totals rows sometimes have stale formulas. Also: `region` defaults to the literal string `"unknown"` and `principal` to `"ambiguous"` when Extract genuinely can't tell — these are placeholders, not real values, and downstream code has to know not to treat them as real (see `transform.py`'s `backfill_provenance_fields`).
**Status:** Working, run against the real corpus (1,041 sheets staged, 0 unexplained failures as of the last real run).

#### `analytics/etl/extract/driver.py`
**What it does:** The single command that runs all seven Extract family drivers and writes everything to `staging/`.
**Why it exists:** One entrypoint (`python -m analytics.etl.extract.driver`) instead of running seven scripts by hand.
**Calls / called by:** Calls all seven `parse_*` functions below, plus `_qc.py` and `_review.py` to generate reports. Nothing calls this — it's a script you run directly.
**Key functions:** `main()` — runs everything, writes `staging/_manifest.json`, `staging/_extract_qc.md`, `staging/_review.html`.
**Gotchas:** None known.
**Status:** Working, this is the one part of the pipeline that has genuinely been run end-to-end against real data.

#### `analytics/etl/extract/sales_register.py`, `inventory_signoff.py`, `bo_rmr_gs.py`, `purchase_order.py`, `sell_out.py`, `ssis_summary.py`, `unilever_sku.py`
**What they do:** Each is a ~20-line wrapper that says "here's the document-type label for this file family, go run the shared Extract engine on it." None of them contain real parsing logic themselves.
**Why they exist:** So each of SSM's seven document families has its own entry point and its own doc-comment explaining what's special about that family's files, without duplicating the actual reading logic.
**Calls / called by:** Each calls `_shared.py`'s `parse_doc_type_files`. Each is called by `driver.py`.
**Gotchas, per family (this is where the real information is):**
| File | doc_type | Worth knowing |
|---|---|---|
| `sales_register.py` | `sales_register` | Also picks up daily-report files, tagged separately as `daily_sales_report` so Transform can tell monthly totals from daily echoes apart. |
| `inventory_signoff.py` | `inventory_sign_off` | SKU code is jammed together with the product name in one unlabeled cell — Transform has to split it. |
| `bo_rmr_gs.py` | `rmr_gs_bo` | Each file has a "ONE PAGER" sheet that's just Good Stock + Bad Order added together — a double-count trap if it's ever loaded alongside GS and BO themselves. |
| `purchase_order.py` | `purchase_order` | Same layout as Sales Register (same POS export tool). |
| `sell_out.py` | `sell_out` | No SKU column at all — only category/brand labels like `/ACE/BASE`. This is *why* Del Monte forecasting works at category grain, not SKU grain (DEC-03). |
| `ssis_summary.py` | `ssis_summary` | Unilever's real sales system-of-record. Has no invoice number of any kind — see the `sales.unilever` entry in `source_of_truth.yaml` for why that's currently a blocked fact. |
| `unilever_sku.py` | `unilever_sku` | The one file with real per-SKU demand data (not invoice-level). This is what makes Unilever's forecasting possible at all. |
**Status:** All seven working, all have run against real files.

#### `analytics/etl/extract/_qc.py`
**What it does:** Turns Extract's raw results into a human-readable markdown report (`staging/_extract_qc.md`).
**Why it exists:** So you can see at a glance how many sheets staged vs. rejected, and which checksums passed/failed, without opening the raw manifest JSON.
**Calls / called by:** Called by `driver.py`. Reads data from `_shared.py`'s result objects.
**Key functions:** `generate_qc_report`, `save_qc_report`.
**Gotchas:** Deliberately produces no timestamps — running it twice on the same input gives byte-identical output, which is checked elsewhere.
**Status:** Working.

#### `analytics/etl/_review.py`
**What it does:** Generates a self-contained HTML page (`staging/_review.html`) you can open in a browser to browse every staged/rejected sheet with filters.
**Why it exists:** So reviewing 1,041 staged sheets doesn't mean scrolling through JSON.
**Calls / called by:** Called by `driver.py`. Reads only `staging/_manifest.json` (nothing else), so it could be pointed at any future stage that writes the same manifest shape.
**Key functions:** `render_review`.
**Gotchas:** None known.
**Status:** Working.

#### `analytics/etl/_coerce.py`
**What it does:** Two small, shared number-parsing helpers: `to_decimal` (money, exact to the cent) and `to_number` (best-effort int/float), both handling comma-formatted strings like `"24,190"`.
**Why it exists:** Extract and Transform both need to parse "numbers that look like text" the same way — this was pulled out in 2026-08 specifically so the two stages can't quietly drift apart on what counts as a valid number.
**Calls / called by:** Imported by both `extract/_shared.py` and `transform.py`.
**Key functions:** `to_decimal`, `to_number`.
**Gotchas:** None known.
**Status:** Working.

#### `analytics/etl/transform.py`
**What it does:** Turns staged (raw-shaped) data into database-shaped data: picks the correct source sheet, renames columns to our canonical names, fills in a few computed/backfilled fields, and removes true duplicates.
**Why it exists:** This is the layer that reconciles SSM's real-world messiness (three different spreadsheet vocabularies over the years, columns that don't exist in every file, typos) into one consistent shape Load can write to Postgres.
**Calls / called by:** Called by tests directly (no orchestration script calls it yet — see Gotchas). Calls `_coerce.py` and `extract/_shared.py` (for one shared regex).
**Key functions:**
- `apply_column_map` — renames raw SSM headers (`"REFNBR"`, `"AMOUNT"`) to our canonical names (`invoice_num`, `net_amount`) using a `config/column_maps/*.yaml` file per document type.
- `backfill_provenance_fields` — fills in `region`/`principal` from Extract's `_region`/`_principal` tags wherever the real column is missing, **but never copies Extract's own "couldn't tell" placeholders** (`"unknown"`, `"ambiguous"`) into the real column.
- `filter_source_of_truth` — keeps only the one system-of-record sheet per fact/company, using `config/source_of_truth.yaml` (DEC-04).
- `dedup_facts` — removes exact duplicate rows on the confirmed natural key; if two rows share a key but disagree on the amount, **both are kept and flagged**, never silently resolved.
- `reformat_calendar_month` — converts Unilever's `"10.2025"` date format to our `"2025-10"` convention.
- `coerce_numeric_columns` — parses comma-formatted number-as-text columns (Unilever SKU file specifically).
- `split_sku_description` — splits Inventory Sign-Off's combined "SKU code + product name" cell into two real columns.
- `transform_fact` — the convenience function that chains all of the above for one fact/principal combination.
**Gotchas:** **There is no script that calls `transform_fact()` for all seven document families and writes the result anywhere.** Every piece here is tested against real staged data individually, but nobody has built the equivalent of Extract's `driver.py` for this stage. If you're picking up backlog work on the pipeline, this is very likely it. Also: `sales.unilever`'s natural key is deliberately `null` in config — calling `transform_fact` for that fact/principal combination will raise on purpose (see the glossary's "source of truth" entry).
**Status:** Individual functions are working and tested against real data. The stage as a whole (all seven families, wired together) has never been run end-to-end.

#### `analytics/etl/granularity.py`
**What it does:** Reconciles that Unilever and Del Monte's real data doesn't support the same level of detail. Unilever's file already has real per-SKU monthly numbers (just validates it, no reshaping needed). Del Monte's Sales Register is invoice-level with no SKU column at all, so its category-grain sell-out totals get spread across the business days of the month using **uniform temporal disaggregation**: each month's total ÷ that month's business-day count, same share on every day, no shape assumed. This is the exact behavior the manuscript specifies (Sec 3.2.2: "because the predictive models require continuous daily observations, aggregated monthly records are disaggregated into daily intervals") — this module is that step, implemented.
**Why it exists:** DEC-03: forecasting at SKU grain for Del Monte would mean inventing numbers the source data doesn't contain. This module makes that boundary explicit in code, not just in a comment.
**Calls / called by:** Not yet called by anything outside tests (same "written, not wired up" situation as `transform.py`).
**Key functions:**
- `resolve_delmonte_category_grain` — the uniform-disaggregation function described above. Reconciles exactly to the source total (checked in code: the reconstructed daily sum must match the original monthly total to the cent, or `total_mismatch` is populated) and leaves no gaps within the business days it produces. Raises if you accidentally hand it invoice-grain data instead of Sell Out data — that would be exactly the kind of fabrication DEC-03 forbids.
- `resolve_unilever_sku_grain` — passes Unilever's real SKU data through unchanged, just checks there are no gaps in the month sequence. Requires you to explicitly say whether "cases" or "pieces" is the quantity that counts — it refuses to guess (see the module's own comment for why this is still open).
- `resolve_granularity` — picks the right one of the above two based on which company you're processing.
**Gotchas:** The "cases vs. pieces" question for Unilever's `quantity_sold` is a real, still-open decision — don't pick one without checking with Yuan first, the code won't let you skip declaring it anyway. Also worth knowing: `resolve_delmonte_category_grain`'s output is uniform *within* each month by construction (every business day in a given month gets the identical share) — it's a faithful disaggregation of the real monthly total, but it does not, and cannot, recover any real day-to-day shape. Don't mistake variation in that output for a signal.
**Status:** Written and tested against fixtures; not yet wired into a real pipeline run.

#### `analytics/etl/clean.py`
**What it does:** The last polish before Load: flags outliers (never deletes them), standardizes product codes, computes the Bad Order rate, and does a final "does this have every required column" check.
**Why it exists:** Separates "does this row look statistically odd" and "is this feature computable" from Transform's job of "is this the right row at all."
**Calls / called by:** Not yet called by an orchestration script. Tested directly.
**Key functions:**
- `flag_iqr_outliers` — statistical outlier detection; flags via `_outlier_flag`, never drops the row.
- `compute_bo_rate` — `(BO units / units received) × 100`, left `NULL` (not `0`) when we don't actually know units received — `0%` would falsely claim "no bad orders" when the truth is "we don't know."
- `validate_output_schema` — checks a handful of required columns are present before Load would see this data.
- `clean_pipeline` — chains the above.
**Gotchas:** None known.
**Status:** Working, tested; not yet wired into a real pipeline run.

#### `analytics/etl/load.py`
**What it does:** Writes clean data into Postgres/Supabase. Also resolves dimension foreign keys (customer, salesman, product) by looking them up or inserting them just before the fact row that needs them is saved.
**Why it exists:** This is DEC-09 in code: some fact tables (like `Unilever_SKU_Demand_Fact`) *require* a valid `product_key` to exist before the row can save at all — there's no way to "save now, fix the link later" for those, so the lookup has to happen right here, right before the write.
**Calls / called by:** Called by `seed_date_dim.py` (the only real caller today) and by tests. Not yet called by a Transform-to-Load orchestration script.
**Key functions:**
- `load_to_supabase` — the main upsert function: `INSERT ... ON CONFLICT DO UPDATE`, batched, raises loudly if the number of rows written doesn't match what was attempted.
- `resolve_dimension_fk` / `build_dimension_key_frame` — the DEC-09 lookup-or-insert logic. A row whose natural key has any missing part gets `NULL` for that foreign key rather than a guessed match.
**Gotchas:** None known — this one's had real fixes applied and real tests added this session (see the git log for `analytics/etl/load.py`).
**Status:** Working and tested (including against a fixture standing in for a live database — 117/117 tests pass as of this doc). Never yet run against a real live Supabase database, because the project doesn't have one created yet.

---

### 4.2 `analytics/db/` — the database definition

**Verify this yourself:** open `analytics/db/schema.sql` and count the `CREATE TABLE` statements (14) plus `CREATE OR REPLACE VIEW` (1). For "never run against a live database": check whether `SUPABASE_SETUP.md` or anyone on the team has a real connection string yet — nothing in the repo itself can tell you that, it's a team-state fact, not a code fact.

#### `analytics/db/schema.sql`
**What it does:** The actual `CREATE TABLE` statements for all 14 tables plus one view, in Postgres SQL. This is the single source of truth for the database's shape.
**Why it exists:** Every other database-facing file (`models.py`) is just a Python mirror of this file — if you ever need to change a column, change it here first.
**Calls / called by:** Nothing calls this from Python — it's meant to be run directly against Postgres (via the Supabase SQL editor or `psql`).
**Key sections (not functions, since this is SQL):**
- **Dimensions** (Section 1): `Date_Dimension`, `Product_Dimension` (covers both Unilever SKUs and Del Monte categories — DEC-03), `Customer_Dimension`, `Salesman_Dimension`, `Supplier_Dimension`.
- **Transaction mart** (Section 2, DEC-02): `Sales_Fact` (Del Monte only — DEC-10), `Purchase_Fact`, `SalesReturn_Fact`. None of these carry a `product_key` — their source files have no SKU column, and adding one would be fabrication.
- **Product mart** (Section 3): `Inventory_Fact`, `SellOut_Fact` (Del Monte category grain), `Unilever_SKU_Demand_Fact` (Unilever SKU grain).
- **Analytics outputs** (Section 4): `ABC_Classification`, `Forecast_Result`, `LP_Recommendation`.
- **`BO_Monitoring_View`** (Section 5): a view, not a table, computing Bad Order rate at (company, region, month) grain.
**Gotchas:** `Sales_Fact` only ever holds Del Monte rows (Unilever's sales system has no invoice number to key on). `SalesReturn_Fact.bo_units` will always be `NULL` — no source column for it exists anywhere in the real data, only a peso value. Several `region`/`return_slip_num` columns are nullable and sit inside `UNIQUE` constraints — meaning a row with a blank region isn't fully protected against an accidental duplicate load. This was checked against real data (8.7% of real `Sales_Fact` rows are missing region even after backfilling) and left nullable on purpose rather than rejecting real transactions — see `DATABASE_ARCHITECTURE.md` for the exact numbers.
**Status:** Written, reviewed against real data, has never been executed against a live database — the Supabase project doesn't exist yet.

#### `analytics/db/models.py`
**What it does:** The same 14 tables + relationships as `schema.sql`, written as Python classes (SQLAlchemy ORM) instead of raw SQL.
**Why it exists:** So Python code (Load, the backend) can work with rows as Python objects instead of hand-writing SQL everywhere.
**Calls / called by:** Not currently imported by any runtime code — `load.py` talks to the database directly via SQLAlchemy Core, not through these ORM classes. Exists for potential future use and as a second, cross-checkable description of the schema.
**Key classes:** One per table, matching `schema.sql` name-for-name (e.g. `SalesFact`, `ProductDimension`).
**Gotchas:** This file **could not be imported by anyone at all** until a bug was fixed in 2026-08 — it had two conflicting module docstrings stacked on top of each other, which is invalid Python. If you find code elsewhere that looks like it should be using this file and isn't, that bug (now fixed) is probably why.
**Status:** Fixed and importable as of 2026-08; not currently used by any running code.

#### `analytics/db/seed_date_dim.py`
**What it does:** Generates one row per calendar day from 2021-01-01 to 2026-12-31 and writes it into `Date_Dimension`.
**Why it exists:** Every fact table joins against `Date_Dimension` for day/week/month/quarter context — this has to be populated before any real fact data can be usefully queried by date.
**Calls / called by:** Calls `load.py`'s `load_to_supabase`. Run directly as a script (`python -m analytics.db.seed_date_dim`) — nothing else calls it.
**Key functions:** `generate_date_range`, `validate_date_range`, `upsert_date_dimension`.
**Gotchas:** `fiscal_period` is left `NULL` for every row on purpose — SSM's fiscal calendar isn't confirmed anywhere in the source data, so this doesn't guess one.
**Status:** Written and tested; never run against a real database (same blocker as everything else — no live Supabase project yet).

#### `analytics/db/__init__.py`
**What it does:** Just a package docstring, no code.
**Status:** N/A.

---

### 4.3 `analytics/` root and the model layer

**Verify this yourself:** `pytest tests/classification/ tests/forecasting/ tests/optimization/ -q` — all pass against synthetic data. For "never run against real numbers": `grep -rn "classify_abc\|fit_sarima\|build_lp_model" --include=*.py analytics backend` and check whether anything outside `tests/` calls these functions (as of this doc, nothing does).

#### `analytics/config.py`
**What it does:** Loads and validates `SUPABASE_DB_URL` and `SUPABASE_KEY` from a `.env` file, and fails immediately with a clear error if either is missing.
**Why it exists:** So a misconfigured run fails with "you forgot to set SUPABASE_DB_URL" instead of a confusing database connection error three steps later.
**Calls / called by:** Meant to be the one place every other module gets its settings from. **Not actually used yet** — `seed_date_dim.py` and `backend/deps.py` both read `os.environ` directly instead (flagged in their own comments as "should switch to this once it's ready").
**Key functions:** `get_settings()`.
**Gotchas:** None known.
**Status:** Working, but not yet adopted by the code that should be using it.

#### `analytics/__init__.py`
**What it does:** Just a package docstring describing all five sub-packages (`db`, `etl`, `classification`, `forecasting`, `optimization`) and stating the architecture boundary: the backend never imports this package.
**Status:** N/A.

#### `analytics/classification/abc.py`
**What it does:** ABC/Pareto classification — given one row per product with its total revenue, ranks them and assigns tier A (top 80% of revenue), B (next 15%), or C (the rest).
**Why it exists:** Feeds `ABC_Classification` — only Tier A products go on to get a SARIMA forecast (Phase 4 only runs for the "worth the compute" products).
**Calls / called by:** Not yet called by any orchestration script — there's no code yet that pulls real revenue numbers out of the database and hands them to this function.
**Key functions:** `classify_abc(revenue_df)` — deliberately grain-agnostic; it doesn't know or care whether it's ranking Unilever SKUs or Del Monte categories, because that decision (DEC-03) is made by whoever calls it, not by this function.
**Gotchas:** Raises on negative revenue (treated as an upstream data bug, not something to silently clamp to zero) and on duplicate product IDs (it expects one row per product, already summed).
**Status:** Working and tested against synthetic data; never run against real revenue numbers because nothing yet computes and hands it that input.

#### `analytics/forecasting/sarima.py`
**What it does:** Per-SKU demand forecasting using SARIMA (a statistical time-series model). Splits history into train/holdout, grid-searches model parameters, evaluates accuracy, and produces a one-month-ahead forecast.
**Why it exists:** This is the actual "predict what SSM will need to order" step (Phase 4).
**Calls / called by:** Not yet called by any orchestration script. Uses the `statsmodels` library.
**Key functions:** `train_holdout_split` (strictly time-based, never random — a shuffled split would leak future data into training), `grid_search_sarima`, `evaluate_sarima` (computes MAPE among other metrics), `passes_mape_gate` (a SKU with ≥20% forecast error gets flagged to the dashboard, never silently dropped), `forecast_one_step`.
**Gotchas:** Needs at least 24 months of history to run its decomposition step. Every parameter combination tried during the grid search is logged, even the ones that failed, so the search is auditable.
**Status:** Working and tested against synthetic time series; never run against real Unilever SKU demand data.

#### `analytics/optimization/lp.py`
**What it does:** Turns a forecast into a recommended order quantity, using a linear program (LP) solved in stages: it first fills each product's need in layers (this month's demand, then safety stock, then the rest of the target), then closes any shortfall against SSM's 3-week cover rule, and only then applies the weights (0.45 purchase cost, 0.35 the revenue-weighted share of need met, 0.20 storage) to decide which products give way when the warehouse or the per-principal supplier allocation binds.
**Why it exists:** This is the final "here's what to order" step (Phase 5) that feeds `LP_Recommendation`, which the dashboard shows to a human to accept or dismiss.
**Calls / called by:** `scripts/run_lp.py` (and `scripts/run_month.py` through it); every live plan (`lp_run`) was written this way. Uses the `pulp` library with the CBC solver.
**Key functions:** `compute_safety_stock`, `target_stock` and `net_need` (what to order, net of stock on hand), `build_lp_model`, `solve_lp` (returns `None` — never raises — if the problem is infeasible, so the caller can show a warning instead of crashing).
**Gotchas:** The "storage" term is one flat cost per piece ordered (₱0.50, DEC-44 placeholder) for every product, not spoilage or Bad Order data; the manuscript's older text calls it a "spoilage cost", which the code does not have. Because the cost is the same for every product and the term is normalised (h·ΣQ / h·Σneed), it cannot change any plan today.
**Status:** Live: every plan since lp_run 1 (2026-10-03) comes from it; lp_run 10 is the current one (STATE.md).

---

### 4.4 `backend/` — the FastAPI app

**Verify this yourself:** `grep -rn "get_current_user" backend/routers/` — as of this doc that returns nothing, which is the evidence behind the "auth isn't actually wired up" claim below. Re-run it yourself before relying on that being still true. To see the stubs live: `uvicorn backend.main:app --reload`, then hit `http://localhost:8000/health` and any router path (e.g. `/abc`) with no API key at all — both currently respond.

#### `backend/main.py`
**What it does:** Creates the FastAPI app and mounts all five routers, plus one unauthenticated `/health` endpoint.
**Why it exists:** The single entrypoint for the API server.
**Calls / called by:** Imports and mounts every file in `backend/routers/`.
**Gotchas:** The file's own docstring says "each router declares dependencies=[Depends(get_current_user)] itself" — **this is not actually true in the current code.** None of the five routers below import or use `get_current_user`. Every endpoint right now is unauthenticated and returns an empty stub. Flag this to Yuan before treating auth as done.
**Status:** Working as a stub server (returns empty responses); auth described in the docstring is not wired up yet.

#### `backend/deps.py`
**What it does:** Defines `get_db()` (a database session) and `get_current_user()` (checks an `X-API-Key` header against `BACKEND_API_KEY`).
**Why it exists:** Shared FastAPI dependencies every real endpoint should use.
**Calls / called by:** Meant to be used by every router via `Depends(...)`. **Currently used by none of them** (see `main.py`'s gotcha above).
**Key functions:** `get_db`, `get_current_user`.
**Gotchas:** Auth here is a static API key, not a real per-user login — flagged in the file's own comment as a deliberate simplification (a JWT library isn't in `requirements.txt` yet), not a final decision.
**Status:** Written and usable, but not yet actually applied to any endpoint.

#### `backend/routers/inventory.py`, `forecast.py`, `recommendations.py`, `abc.py`
**What they do:** Each defines one endpoint (`GET /inventory/current`, `GET /forecast/{sku_id}`, `GET /recommendations`, `GET /abc`). **Every single one is a stub** — each just returns an empty list or dict, with no database query, no auth check, nothing.
**Why they exist:** They establish the URL shape and response format the frontend can start building against, before the real data-reading logic exists.
**Calls / called by:** Mounted by `main.py`. None of them call `deps.py` or any database code yet.
**Gotchas:** If you're implementing one of these for real, the matching Pydantic response schema already exists in `backend/schemas/` — read that first, it documents real quirks (see below) you'd otherwise have to rediscover.
**Status:** **Stub only.** None of these actually read from the database. This is very likely where a chunk of remaining backend work lives.

#### `backend/schemas/abc.py`
**What it does:** Defines the JSON shape `GET /abc` should return (`ABCItem`, `ABCResponse`).
**Gotchas:** `sku_id` here is genuinely a category path for Del Monte rows, not a SKU — a naming compromise flagged directly in the file's own comment, not a naming bug.
**Status:** Schema defined; not yet consumed by a working endpoint.

#### `backend/schemas/bo_monitoring.py` (removed 2026-09-29)
**What it did:** Defined the JSON shape for `GET /bo-monitoring`. The Bad Orders page was dropped from the app on purpose, so the route, this schema and its test were deleted; the ETL still computes the Bad Order rate and `BO_Monitoring_View` still exists in the database.
**Gotchas:** Deliberately has no `sku_id` field at all, unlike the original spec's TODO comment — Bad Order data has no SKU column anywhere upstream, so a per-SKU field would be fabricated. The response is at (company, region, month) grain instead, matching `BO_Monitoring_View`.
**Status:** Schema defined; not yet consumed by a working endpoint.

#### `backend/schemas/forecast.py`
**What it does:** Defines the JSON shape for `GET /forecast/{sku_id}` (`ForecastResponse`).
**Status:** Schema defined; not yet consumed by a working endpoint.

#### `backend/schemas/inventory.py`
**What it does:** Defines the JSON shape for `GET /inventory/current` (`InventoryItem`, `InventoryResponse`).
**Gotchas:** `unit` (unit of measure, e.g. "pcs") is always `null` — no source file anywhere carries a unit-of-measure column, so it's never fabricated.
**Status:** Schema defined; not yet consumed by a working endpoint.

#### `backend/schemas/recommendations.py`
**What it does:** Defines the JSON shape for `GET /recommendations` (`RecommendationItem`, `PaginatedRecommendations`).
**Status:** Schema defined; not yet consumed by a working endpoint.

#### `backend/routers/__init__.py`, `backend/schemas/__init__.py`
**What they do:** Package docstrings only, listing every router/schema and its intended endpoint/fields.
**Status:** N/A.

---

### 4.5 `config/` — the data dictionaries

Two kinds of file live here. `source_of_truth.yaml` decides *which* sheet is authoritative for each fact. The `column_maps/*.yaml` files decide *how to rename* each document type's raw columns. Neither contains any code — Transform reads both at runtime.

**Verify this yourself:** `pytest tests/test_transform_config.py -v` (run Extract first if `staging/_manifest.json` doesn't exist yet) — this test file's whole job is catching exactly the kind of drift between these config files and what Extract actually produces that this subsection describes.

#### `config/source_of_truth.yaml`
**What it does:** For every fact (sales, purchases, returns, inventory, sell-out, Unilever SKU demand), states which document type and sheet role is the real system of record, which roles are cross-checks to ignore, and what the natural key is (the combination of columns that makes a row unique).
**Why it exists:** This is DEC-04 written down as data instead of scattered across code comments — one place to check "which sheet actually counts."
**Gotchas:** `sales.unilever`'s `natural_key` is deliberately `null` — Unilever's real sales data has no invoice/reference column of any kind, so there's currently no honest key to dedup on. `transform_fact()` will raise, on purpose, if you try to use this entry. This is a real, currently-unresolved gap, not a bug.
**Status:** Working, actively read by `transform.py`, kept in sync with `schema.sql` by hand (a mismatch here is exactly the class of bug DEC-07 exists to catch).

#### `config/column_maps/sales_register.yaml`, `purchase_order.yaml`, `rmr_gs_bo.yaml`, `inventory_sign_off.yaml`, `sell_out.yaml`, `unilever_sku.yaml`, `ssis_summary.yaml`, `daily_sales_report.yaml`
**What they do:** Each maps one document type's real, messy raw column names to our canonical field names (e.g. Sales Register's `"REFNBR"` / `"Invoice Num"` / `"REFERENCE #"` — three different names used in different years — all map to `invoice_num`).
| File | Worth knowing |
|---|---|
| `sales_register.yaml` | Covers three historical column-naming eras ("vocab A/B/C") in the same file. |
| `purchase_order.yaml` | Looks like `sales_register.yaml` (same POS tool) but `"Customer Name"` here actually means the *supplier* — don't merge these two maps. |
| `rmr_gs_bo.yaml` | Narrower column set than Sales Register — no Branch Code, Invoice Num, or Discount Rate columns exist in this file family at all. |
| `inventory_sign_off.yaml` | The SKU code + product name arrive jammed into one cell, and which column that is depends on which year's export template you're looking at — see the file's own long comment before touching this one. |
| `sell_out.yaml` | No date/period column in the sheet at all — the month comes from Extract's filename tagging, not from any cell. |
| `unilever_sku.yaml` | Several columns still need numeric coercion flagged as TODO in the file itself (now handled by `transform.coerce_numeric_columns`, which reads this file's TODO markers as its checklist). |
| `ssis_summary.yaml` | Deliberately does not map any kind of invoice/reference column — none exists (see the `sales.unilever` entry in `source_of_truth.yaml`). |
| `daily_sales_report.yaml` | Exists purely so Transform can tag/report on these files without crashing — they are never actually promoted to load (they're a cross-check of the monthly Sales Register, per DEC-04). |
**Status:** All working, all built from real staged column names (not guessed).

#### `config/alias_tables/discount_rate_labels.csv`
**What it does:** A tiny two-column lookup (`raw_label,canonical_label`) that standardizes discount-rate text labels like `"LESS 2%"` / `"Less 2%"` into one spelling.
**Why it exists:** `discount_rate_label` is a text label (e.g. "Public Pricelist"), never a number — this table just normalizes spelling drift, it doesn't compute anything.
**Status:** Working, small, stable.

---

### 4.6 `tests/` — what's actually covered

Every file below currently passes — **117 tests, confirmed with a fresh full run right before this line was written** (`pytest tests/ -q` → `117 passed`). None of them exercise a real live database — they either use synthetic data or, where real staged data exists on disk, read it directly.

**Verify this yourself:** `pytest tests/ -q`. If the number you get isn't 117, the code has changed since this doc was generated — trust your own run, then update this doc's commit line at the top.

| File | What it covers |
|---|---|
| `tests/conftest.py` | Just a docstring today — no shared fixtures are actually implemented yet, despite the TODO comment listing several planned ones. |
| `tests/etl/test_extract.py` | The shared Extract engine's type detection (text codes keep leading zeros, money becomes exact `Decimal`), region/role inference, and the totals-row checksum logic. Runs against real files in `data/raw/` when present, skips cleanly when not. |
| `tests/etl/test_transform.py` | Column-name mapping across historical vocab eras, unmapped-column reporting, source-of-truth filtering, dedup (including the "keep both, flag the conflict" path), the 2026-08 fixes: provenance backfill (including the "unknown"/"ambiguous" placeholder guard), the three natural-key fixes (inventory/sell_out/purchase no longer silently collapse two real regions into one), numeric coercion, and calendar-month reformatting. |
| `tests/etl/test_granularity.py` | Del Monte's even-distribution-across-business-days math (and that it reconciles exactly to the source total), the doc_type guard that stops category-grain logic from being fed invoice-grain data by accident, and Unilever's month-gap detection. |
| `tests/etl/test_clean.py` | Outliers are flagged not dropped, Bad Order rate is `NULL` (not `0`) when we don't know units received, leading zeros survive in branch codes. |
| `tests/etl/test_load.py` | The upsert SQL shape, the DEC-09 dimension lookup-or-insert logic (including the null-natural-key-part guard), all without touching a real database. |
| `tests/test_transform_config.py` | The "config matches what Extract actually staged" gate (DEC-07) — catches a config file naming a document type Extract never really produces. Skips if `staging/_manifest.json` doesn't exist (i.e. if you haven't run Extract locally yet). |
| `tests/classification/test_abc.py` | Every product gets a tier with no nulls, the 80/95 cutoffs land tiers on the correct side, sort order, and the negative-revenue guard. |
| `tests/forecasting/test_sarima.py` | The train/holdout split never leaks future data into training, SKUs failing the 20% MAPE gate are flagged not dropped, forecast values are plausible, and the parameter search log is never empty. |
| `tests/optimization/test_lp.py` | The safety-stock and reorder-point formulas, that a feasible LP returns quantities within the allocation ceiling, that an infeasible LP returns `None` instead of raising, and that the three objective weights sum to 1.00. |

No test file exists yet for `backend/` — none of the stub endpoints have tests, which lines up with them not having real logic yet either.

---

## 5. Glossary

Defined using our actual data, not textbook definitions.

- **`doc_type`** — which of SSM's seven real document families a staged row came from: `sales_register`, `purchase_order`, `inventory_sign_off`, `sell_out`, `rmr_gs_bo`, `unilever_sku`, or `ssis_summary` (plus `daily_sales_report`, a variant of `sales_register`). Every staged parquet file lives under `staging/<doc_type>/`.

- **`grain`** — the level of detail a table's rows actually represent. `Sales_Fact` is invoice-grain (one row per invoice). `SellOut_Fact` is category-grain (one row per category per region per month — there's no SKU column in that source file, so we can't honestly go any finer). This is DEC-03's whole point: Unilever and Del Monte are forecast at different grains because their real source data supports different levels of detail, and pretending otherwise would mean inventing numbers.

- **`principal`** — which of our two client companies a row belongs to: `unilever` or `delmonte`. Nearly every table has this column.

- **natural key** — the real-world combination of columns that makes a row unique, as opposed to the database's auto-generated surrogate ID. For `Sales_Fact` it's `(invoice_num, principal, region)` — `principal` is constant there (`CHECK (principal = 'delmonte')`, DEC-10 — this table only ever holds Del Monte rows), so in practice it's `region` doing the real work: the same invoice number can legitimately show up in both Pangasinan and Ilocos, and without `region` in the key those two real rows would collide as if they were duplicates. `Purchase_Fact` uses the same three-column shape and there `principal` isn't constant, so it's genuinely load-bearing on that table.

- **source of truth** — when SSM's files contain more than one view of the same data (e.g. a daily sales report that's just a slice of the monthly Sales Register), exactly one is designated the "real" one to load; the rest are kept on disk for audit but never promoted. `config/source_of_truth.yaml` is where this is declared, per fact per company.

- **provenance columns** — the underscore-prefixed columns Extract attaches to every row (`_src_file`, `_src_sheet`, `_principal`, `_region`, `_period`, `_doc_type`, `_sheet_role`, and a few checksum columns). They let you trace any row in the database all the way back to the exact source cell it came from.

- **staging** — the `staging/` folder: Extract's raw output, one `.parquet` file per (source file, sheet) pair, organized by `doc_type`. This folder is gitignored — it's regenerated by running Extract locally, not committed to the repo.

- **fact vs. dimension** — a fact table records something that happened (a sale, a purchase, a return) and usually has a number attached (`net_amount`). A dimension table describes something the facts point to (a customer, a product, a date) and mostly stays the same over time. `Sales_Fact` is a fact; `Customer_Dimension` is a dimension.

- **M0/M2/M3 gates** — unclear, ask Yuan. These terms don't appear anywhere in the current codebase, `analytics/`, `backend/`, or `config/` — they may be from an older planning document or a different naming scheme than what actually got built. Don't assume a meaning; confirm before using this term with the team.

- **hard vs. soft rejects** — also unclear, ask Yuan, same reasoning as above. What the code actually has is a `staged` / `rejected` split in Extract (a sheet is `rejected` only if it's unreadable, has no detectable header/data, or contains quarantined content — never for a checksum mismatch, which stages anyway with a flag). If "hard vs. soft reject" refers to some further split within that, it isn't implemented today.

---

## 6. Where your work lives

The codebase doesn't record who owns which lane anywhere in Git — that assignment lives in the team's backlog spreadsheet, not in this repo. What follows is grounded in what the code actually needs next, organized by the lanes the pipeline naturally splits into. Match these against your actual backlog assignments with Yuan; don't assume a name-to-lane mapping from this doc alone.

- **Extract lane** (mostly done — light touch expected): `analytics/etl/extract/`, `tests/etl/test_extract.py`. If you're here, you're probably fixing an edge case in a specific file family, not building something new.

- **Transform/Clean/Granularity lane** (the biggest real gap): `analytics/etl/transform.py`, `analytics/etl/clean.py`, `analytics/etl/granularity.py`, `config/source_of_truth.yaml`, `config/column_maps/`, plus their test files. The functions are built and tested; **nobody has written the driver that runs all seven document families through Transform end-to-end and hands the result to Load**. That's a real, well-scoped, currently-open piece of work.

- **Load / database lane**: `analytics/etl/load.py`, `analytics/db/`. The code is done and tested against fixtures; what's missing is a live Supabase project to actually run it against, and then the Transform driver above to feed it real data.

- **Analytics model lane**: `analytics/classification/abc.py`, `analytics/forecasting/sarima.py`, `analytics/optimization/lp.py`, and their tests. Each function is correct and tested against synthetic data; none has been run against real numbers yet because there's no orchestration script pulling real data out of the (not yet created) database and handing it to these.

- **Backend/API lane** (the other biggest real gap): `backend/`. Every endpoint is currently a stub returning an empty response, with no database query and no auth actually applied despite `deps.py` having a working `get_current_user`. If your assignment is "make the API return real data," this is where you'll spend your time — read the matching `backend/schemas/*.py` file first for each endpoint, since the real-data quirks (like `inventory`'s always-null `unit`) are already documented there.
