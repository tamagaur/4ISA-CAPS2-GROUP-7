# Database Architecture — SSM Decision Support Dashboard

This covers the database only. For the full project (Extract/Transform
pipeline, frontend, backend API, team/manuscript context), see
[`ARCHITECTURE.md`](ARCHITECTURE.md) at the repo root — this file is a
zoomed-in companion to that, not a replacement. For column-by-column
detail on every table, see [`DATABASE_SCHEMA.xlsx`](DATABASE_SCHEMA.xlsx)
— one sheet per table/view, with the raw DDL underneath each. To
actually stand the database up, see [`SUPABASE_SETUP.md`](SUPABASE_SETUP.md).

## 1. Overview

One Supabase (PostgreSQL) project, one `public` schema — no
microservices, no domain-schema separation. This is a deliberate choice,
not an oversight: the system serves one client (SSM) with 1-2 real users
and one linear ETL → warehouse → dashboard pipeline, not multiple
independent business processes each with their own lifecycle and user
base. That kind of separation solves a scaling/ownership problem this
project doesn't have.

| Item | Status (2026-08) |
|---|---|
| Database engine | PostgreSQL 15+ via Supabase |
| Schema | All tables in `public` |
| Total tables | 14 (5 dimensions, 3 transaction-mart facts, 3 product-mart facts, 3 analytics-output tables) |
| Total views | 1 (`bo_monitoring_view`) |
| Cross-table pattern | Real foreign keys throughout — no soft links, no cross-schema boundaries to bridge |
| DDL ever executed against a live database | **No, not yet** — reviewed and fixed against real staged data (2026-08), execution is the next concrete step |
| Estimated size | ~15.3 MB for the real current schema — see §6 |

## 2. Design approach — Fact Constellation, two marts

The warehouse is a Galaxy / Fact Constellation schema (manuscript Sec
3.3): multiple fact tables sharing conformed dimensions, rather than one
star schema, because SSM's operations span genuinely distinct processes
(sales, purchasing, inventory, returns) that don't reduce to one grain.

Within that, the facts split into **two marts** (DEC-02):

- **Transaction mart** — `Sales_Fact`, `Purchase_Fact`,
  `SalesReturn_Fact`. Invoice grain. Their source files carry no SKU
  column at all, so they carry **no `product_key` FK** — adding one
  without a real source column behind it would be fabricating data that
  doesn't exist (this project's anti-fabrication principle).
- **Product mart** — `Inventory_Fact`, `SellOut_Fact`,
  `Unilever_SKU_Demand_Fact`. SKU or category grain. These **do** join
  `Product_Dimension`, because their source files carry real
  product/category identifiers.

A third group, **analytics outputs** (`ABC_Classification`,
`Forecast_Result`, `LP_Recommendation`), is written by the `analytics/`
pipeline and read-only from the backend's point of view — the
architecture boundary documented in the main `ARCHITECTURE.md`.

## 3. Grain map (DEC-03) — the single most important thing to know

**Unilever and Del Monte are not forecast at the same grain, and this is
intentional, not inconsistent:**

| Principal | Grain | Demand source | Why |
|---|---|---|---|
| Unilever | **SKU** | `Unilever_SKU_Demand_Fact` (the La Union file — the sole confirmed SKU-level source in the entire corpus) | Real per-SKU demand exists in the source. |
| Del Monte | **Category/brand** | `SellOut_Fact` | Sales/returns/purchases are invoice-level with no SKU column anywhere in that file family; category is the honest ceiling the data supports. |

`Product_Dimension` covers both — one dimension, two kinds of "product
identity," distinguished by its own `grain` column (`'sku'` vs.
`'category'`). This is why `ABC_Classification` legitimately has
SKU-grain rows for Unilever sitting next to category-grain rows for Del
Monte in the same table: expected behavior, not a bug to reconcile.

## 4. Source-of-truth map (DEC-04)

Several source file families contain more than one view of the same
underlying transactions (e.g. a daily echo of a monthly Sales Register,
or an "INVOICE REG" sheet duplicating a "RAW DATA" sheet). Exactly one
view per fact per principal is ever loaded — the rest are staged for
audit but never promoted. This is enforced at two layers:

1. **Transform** (`config/source_of_truth.yaml`) filters by `_sheet_role`
   and `_doc_type` before a row ever reaches Load.
2. **The database itself** — every fact table's `UNIQUE` constraint
   below *is* DEC-04's natural key, so a double-load (e.g. both `RAW
   DATA` and `INVOICE REG` somehow reaching Load) fails loudly at the DB
   layer, not silently:

| Fact | Natural key (`UNIQUE` constraint) |
|---|---|
| `Sales_Fact` | `(invoice_num, principal, region)` |
| `Purchase_Fact` | `(invoice_num, principal, region)` |
| `SalesReturn_Fact` | `(return_slip_num, principal, region, return_type)` |
| `Inventory_Fact` | `(sku_code, snapshot_date, region)` |
| `SellOut_Fact` | `(category_path, region, _period)` |
| `Unilever_SKU_Demand_Fact` | `(sku_code, calendar_month)` |
| `ABC_Classification` | `(product_key, classification_period)` |
| `Forecast_Result` | `(product_key, forecast_date)` |
| `LP_Recommendation` | `(product_key, planning_cycle_date)` |

**Nullable columns inside these natural keys — real null rates (2026-08).**
Postgres treats `NULL <> NULL`, so any row where a `UNIQUE`-constrained
column is NULL isn't actually protected against a duplicate load. `region`
sits in the key for `Sales_Fact`, `SalesReturn_Fact`, and `Inventory_Fact`;
`return_slip_num` sits in `SalesReturn_Fact`'s. Checked against real
staged/transformed data rather than assumed:

| Column | Real null rate | Why | Decision |
|---|---|---|---|
| `Sales_Fact.region` | **8.7%** (1,573 / 17,985 real Del Monte rows, post-dedup) | Down from 35.9% after fixing `backfill_provenance_fields()` to recover `region` from Extract's `_region` tag per-row, not just when the whole column is missing. The residual 8.7% is genuine: both the raw source cell ("Town Display"/"AREA") *and* Extract's own filename/sheet-based `_region` guess are blank for these rows — there's no signal left to recover from. | Left nullable. Forcing `NOT NULL` would reject these rows outright at Load, which is worse than the status quo — an unprotected-but-loaded row beats a rejected real transaction. |
| `SalesReturn_Fact.region` | **0.0%** (0 / 234 real rows, post-dedup) | Real RMR GS/BO data always carries a region. | Left nullable (schema-honest headroom for a future source), but observed risk today is none. |
| `SalesReturn_Fact.return_slip_num` | **4.3%** (10 / 234 real rows, post-dedup) | A small number of real RMR rows genuinely have no slip number recorded at source. | Left nullable, same reasoning as `Sales_Fact.region` — documented, not forced. |
| `Inventory_Fact.region` | Not directly measurable — this file family's Transform still crashes (separate, tracked bug), so no real post-Transform `region` column exists yet. Proxy via Extract's own `_region` tag on the 7,019 raw staged rows: 0% truly null, but 20.3% (1,428 rows) are Extract's own "couldn't determine" placeholder, which is not a usable value either. | Upper-bound estimate only. | Revisit once Transform is unblocked for this family — don't assume the real number matches Sales_Fact's until it's actually measured. |

None of these columns were made `NOT NULL`: in every case real transactions
exist with the column genuinely blank at source, and rejecting them at Load
would lose real data rather than protect against a duplicate that isn't
actually there.

## 5. Key decisions specific to this database

Full register lives in `ARCHITECTURE.md` §5 — this is just the ones that
shape the schema directly:

- **DEC-02** (two marts) — see §2 above. Status: matches what's built;
  formal PROPOSED → DECIDED sign-off still pending.
- **DEC-04** (source-of-truth) — see §4 above. DECIDED.
- **DEC-06** (SCD Type 1) — dimensions are overwrite-in-place, no history
  columns, no effective-dating. Acceptable because forecasting cares
  about the time series, not attribute history. Status: PROPOSED.
- **DEC-09** (dimension FK resolution timing) — **DECIDED, load-time
  lookup-or-insert.** `analytics/etl/load.py`'s `resolve_dimension_fk()`
  looks up or creates the dimension row and gets its surrogate key
  immediately before the fact row that needs it is upserted. Transform
  stays database-free. This was forced by four tables
  (`Unilever_SKU_Demand_Fact`, `ABC_Classification`, `Forecast_Result`,
  `LP_Recommendation`) declaring `product_key NOT NULL` — a "load now,
  backfill the FK later" approach is physically impossible for them.
- **DEC-10** (`Sales_Fact` scope) — **DECIDED, Del Monte only.**
  Unilever's real Sales system-of-record has no invoice/reference column
  at all — see §7 for the consequence this has for `ssis_summary`.

## 6. Size estimate (before ever creating the project, 2026-08)

Estimated from real verified row counts (post-Transform, where
Transform currently runs successfully) plus Postgres's own row/index
storage overhead.

| Scenario | Size | vs. Supabase free tier (500 MB) |
|---|---|---|
| Current real schema (6 facts + 5 dimensions, `ssis_summary` excluded) | **~15.3 MB** | ~3% used, ~485 MB to spare |
| If `ssis_summary` ever gets a destination table (see §7) | **~709 MB total** (the new table alone: ~694 MB) | Exceeds free tier by ~42% — Pro tier required |

**Conclusion: free tier comfortably holds today's real schema.** The
entire size risk in this database is concentrated in one currently
nonexistent table.

## 7. Known gaps and permanent limitations

Not bugs to fix quietly — decisions and constraints worth knowing before
building on top of this schema:

- **Del Monte has no working demand path today — only Unilever can
  produce a forecast right now.** §3 names `SellOut_Fact` as Del Monte's
  demand source; the bullet below on `Inventory_Fact`/`SellOut_Fact`
  explains why that table can't actually be populated from real data yet
  (Transform crashes on this file family). Put together: until that
  Transform gap is fixed, `Forecast_Result`/`LP_Recommendation` can only
  ever get real rows for Unilever SKUs, not Del Monte categories.
- **`ssis_summary` has no fact-table destination.** It's the single
  largest staged source in the whole corpus (1,949,687 rows, 805
  sheets) — it was the intended source for Unilever rows in `Sales_Fact`
  before DEC-10 restricted that table to Del Monte. Giving it a real
  destination is an explicit, budgeted decision (~694 MB, moves the
  project off free tier), not a default "just add the table" move.
- **`SalesReturn_Fact.bo_units` will always be NULL.** No source column
  for Bad Order *quantity* exists anywhere in real RMR GS/BO data — only
  peso value. `bo_monitoring_view`'s `bo_rate` is value-based
  (`net_amount` ratio) for exactly this reason, not a temporary
  workaround.
- **`Unilever_SKU_Demand_Fact.quantity_sold`'s source field is still an
  open decision.** `sale_quantity_cases × pack_size` reconciles to
  `sale_quantity_pieces` for ~84% of real rows (median gap on the rest:
  0.045%, mostly rounding) — evidence gathered, not conclusive enough to
  pick one automatically.
- **`Inventory_Fact` and `SellOut_Fact` can't be populated from real data
  yet.** Their Transform step currently crashes on real files (a
  column-map gap, tracked in `ARCHITECTURE.md`, not a database problem)
  — the size estimate in §6 used raw staged counts as an upper bound for
  these two specifically.
- **No dimension has history.** DEC-06 (SCD Type 1) means a
  `Customer_Dimension` region change or `Product_Dimension` rename
  overwrites in place. Acceptable today; would need real schema changes
  (effective-dating columns, partial unique indexes) if reversed later.

## 8. Security and access control

- **Access is service-connection only.** The backend talks to Postgres
  via `SUPABASE_DB_URL` (plain connection string, `.env`, gitignored —
  never committed). There is no end-user-facing database credential.
- **Supabase's auto-generated Data API does not need separate
  configuration to stay closed off** — it only exposes tables explicitly
  added to it; none of this schema's tables should be added there unless
  a specific feature needs direct client-side table access, which
  nothing in this project currently does.
- **Authorization is enforced in the FastAPI layer, by role** — not by
  Postgres Row-Level Security. RLS is deliberately not used: it solves
  per-tenant row isolation (different customers seeing only their own
  rows in a shared table), and this system has one organization (SSM)
  with 1-2 real users who all see the same data. Adding RLS here would
  be defending against a threat model this system doesn't have.
- **`LP_Recommendation.decided_by` should record the authenticated
  username**, not a free-text or client-supplied value — it's the audit
  trail for who accepted/dismissed a recommendation, so it needs to come
  from the backend's own auth context at write time, not be trusted from
  the request body.

## 9. What's next

Creating the actual Supabase project (`SUPABASE_SETUP.md`) is unblocked
and independent of everything else — DDL creation and `Date_Dimension`
seeding don't depend on Transform. Loading real fact rows in depends on
the Transform driver, which doesn't exist yet (tracked separately, not a
database concern).
