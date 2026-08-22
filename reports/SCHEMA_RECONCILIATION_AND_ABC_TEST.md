# Schema Reconciliation + ABC Orchestration Test

Covers: merging `group7/kelvin-etl` and pushing to the new repo, reconciling the live Supabase schema against both sides' tracked migrations, and testing `analytics/classification/orchestrate_abc.py` against the loaded database.

## 0. Merge + push

`git merge group7/kelvin-etl --no-edit` — clean merge, matched the earlier dry-run exactly (`Auto-merging analytics/db/schema.sql`, no conflicts). Merge commit `29f0abb`. Pushed to the new repo: `git push group7 kelvin-etl:kelvin-etl` → `0abfa2b..29f0abb`.

**Note**: this merge was only pushed to `group7` (4ISA-Capstone-Group-7/SSM-DSD), per instruction. It was **not** pushed to `origin` (KYG07/Capstone-Project) — local `kelvin-etl` is now 19 commits ahead of `origin/kelvin-etl` (the 3 already-pushed session commits plus this merge's 16 incoming commits). `origin` is untouched; flagging in case that divergence matters for whatever `origin` is still used for.

## 1. Live Supabase schema state — verified directly, both sides

Queried `information_schema.columns` directly against the live database before making any change:

| Check | Live state before this task |
|---|---|
| `is_demo` on all 6 fact tables | **Present on all 6** — `sales_fact`, `purchase_fact`, `inventory_fact`, `sellout_fact`, `unilever_sku_demand_fact`, `salesreturn_fact` — all `boolean NOT NULL DEFAULT false`. (Applied earlier this session via `0001_add_is_demo.sql`.) |
| `boundary_flag` on `abc_classification` | **Absent.** Query returned no row. `abc_classification`'s live column list was exactly `classification_key, product_key, principal, classification_period, tier, revenue_share, cumulative_share, computed_at` — no `boundary_flag`. |
| `abc_classification` row count | 0 |

**Why the gap**: `group7`'s `boundary_flag` change was written as a `schema.sql` comment plus a one-line raw `ALTER ... IF NOT EXISTS` — never as a tracked migration file, and never run against this project's live Supabase instance. Confirmed directly: `orchestrate_abc.py`'s own docstring states *"Not yet run against a live database as of this writing"* — that branch had no live database to run it against in the first place.

## 2. What was applied, and in what order

1. **`is_demo`** — already live from earlier this session (`0001_add_is_demo.sql`), no action needed.
2. **`boundary_flag`** — folded their raw comment-ALTER into a new tracked file, `analytics/db/migrations/0002_add_boundary_flag.sql` (idempotent, `ADD COLUMN IF NOT EXISTS`), then applied it directly:
   ```sql
   ALTER TABLE ABC_Classification ADD COLUMN IF NOT EXISTS boundary_flag BOOLEAN NOT NULL DEFAULT FALSE;
   ```
   Ran inside a transaction, committed successfully, zero errors.

Order was 0001 then 0002 (matches file numbering) — no real interdependency between them since they touch entirely different tables, but numbering preserves the actual sequence in which each was designed and applied.

`analytics/db/migrations/0002_add_boundary_flag.sql` is a new, currently **uncommitted** file — not committed per "report before deciding next steps."

## 3. Zero-drift verification

Re-queried every column/view/seed-row this project's tracked migrations claim, directly against live, after applying 0002:

```
is_demo on all 6 fact tables:        6/6 OK (boolean, NOT NULL, default false)
boundary_flag on abc_classification:  OK (boolean, NOT NULL, default false)
_real views (6):                      6/6 exist
inventory_fact._period/quantity_pieces: OK (text / numeric)
supplier_dimension seed:              OK (2 rows, Del Monte + Unilever)

=== ALL CLEAR - ZERO DRIFT ===
```

`schema.sql` itself required no further edits — the merge already combined both sides' table definitions correctly (verified in the earlier dry-run, re-confirmed here): it has `is_demo` on all 6 fact tables, `boundary_flag` on `ABC_Classification`, and all 6 `_Real` views, matching live exactly. A fresh database built from `schema.sql` today would match the current live schema.

## 4. Running `orchestrate_abc.py` against live data

No period was specified in the instruction, so I chose **2024-01** — a month with real (non-synthetic) data for both principals (real Unilever coverage is 2023-01→2026-02; real Del Monte fine-grained sell_out coverage includes 2024-01) — and ran:

```
python -m analytics.classification.orchestrate_abc --period 2024-01
```

**It did not complete. It crashed on the very first principal (Unilever), before any row was written:**

```
TypeError: unsupported operand type(s) for -: 'decimal.Decimal' and 'float'
```

Full traceback path: `orchestrate_abc.run_abc()` → `run_abc_for_principal("unilever", ...)` → `classify_abc(clean_df)` → `abc.py:127 out["boundary_flag"] = out["cumulative_share"].apply(_is_near_boundary)` → `abc.py:145 abs(cumulative_share - TIER_A_CUTOFF) <= BOUNDARY_MARGIN` → `TypeError`.

**Root cause, traced precisely, not guessed**: `analytics/classification/abc.py:54-56` defines `TIER_A_CUTOFF = 0.80` and `BOUNDARY_MARGIN = 0.02` as plain Python `float` literals. `orchestrate_abc.py`'s `_fetch_unilever_sku_revenue()` builds its DataFrame directly from a raw SQLAlchemy `select()` over `unilever_sku_demand_fact.net_amount` — a Postgres `NUMERIC` column, which psycopg2/SQLAlchemy return as Python `decimal.Decimal` objects, not `float`, when read this way (no `pd.read_sql`-style dtype coercion happens anywhere in the fetch path). `total_revenue`, `revenue_share` (`Decimal / Decimal`), and `cumulative_share` (`.cumsum()` over Decimals) all stay `Decimal` all the way through. `_assign_tier()` (using `<=`, a comparison Python's `Decimal` supports against `float`) succeeds fine on this same data — **`_is_near_boundary()` is the only function in the whole call path that does float/Decimal *arithmetic* (subtraction)**, which `Decimal.__sub__` explicitly refuses for a mismatched `float` operand. This is exactly the class of bug this session hit repeatedly with its own synthetic-data work (Decimal-vs-float dtype mismatches from Postgres NUMERIC columns) — but here it's in the newly-merged `boundary_flag` feature, which per its own module docstring had never been run against a live, Postgres-sourced DataFrame before.

**Rows landed in `ABC_Classification`: 0.** Verified directly by querying the table after the crash — confirms the failure happened before `_upsert_abc_classification()` was ever reached (that call sits after `classify_abc()` in `run_abc_for_principal()`, and the crash is inside `classify_abc()` itself).

**Tier split / principal split**: not obtainable — the run never got far enough to produce a tiered DataFrame for either principal. Del Monte's branch was never reached at all (Unilever runs first and the script has no per-principal error isolation — one failure aborts the whole `run_abc()` call).

Per instruction: **the script was not touched or rewritten.** This is exactly what broke, reported as found.

## 5. `/abc` — what it actually returns

Rather than infer this from reading the code, I exercised the real endpoint function directly against the live database (imported `backend.routers.abc.get_abc`, called it with a live `Session` and a synthetic admin `TokenPayload`, bypassing only FastAPI's dependency-injection wiring — the SQL query and response-building logic executed exactly as they would behind a real HTTP request):

```python
get_abc(principal=None, classification_period=None, db=<live Session>, current_user=<admin>)
# ->
items=[] count=0 classification_period=None tier_summary=[]
```

**Real, valid, empty response — not an error.** The endpoint's own logic (`backend/routers/abc.py:42-47`) checks `SELECT MAX(classification_period) FROM ABC_Classification` first; on an empty table this returns `NULL`, and the endpoint short-circuits to an empty `ABCResponse` before ever reaching the join query. This is the correct, intended behavior for an empty table — the endpoint implementation itself is not broken, only starved of data because §4's orchestration script never successfully wrote anything.

## 6. The fix

Cast at the fetch boundary, not by changing `abc.py`'s constants — `analytics/classification/orchestrate_abc.py`'s `_fetch_unilever_sku_revenue()` and `_fetch_delmonte_category_revenue()` now do `df["total_revenue"] = df["total_revenue"].astype(float)` immediately after building the DataFrame from the raw `select()` result, before the null-check/dropna/groupby steps that already existed. `abc.py` itself was not touched.

**Checked for the same vulnerability elsewhere** (per instruction — report, don't fix): grepped `analytics/` for every `select(...)`/`conn.execute(select(...))` call site. Found exactly one other: `analytics/etl/load.py:144`, inside `resolve_dimension_fk()`. Read it directly — it selects only a dimension table's primary key (`BIGINT`) and natural-key columns (`TEXT` — `sku_code`, `principal`, `region`, etc.), never a `NUMERIC` amount column, and does no arithmetic on the result (it's a join/merge for FK lookup). **Not the same class of bug** — confirmed by reading, not assumed. No other `analytics/` or `backend/` code path reads a `NUMERIC` column via a raw, uncoerced `select()` and then does float arithmetic on it.

## 7. Per-principal error isolation

`run_abc()` now loops `for principal in ("unilever", "delmonte")` with each `run_abc_for_principal()` call wrapped in its own `try/except Exception`. On failure: prints `ABC classification FAILED for principal=... period=...: <type>: <message>`, and appends an `AbcRunReport` with a new `error: str | None` field set (rather than raising and killing the other principal's run). `_print_report()` checks `report.error` first and prints just the failure line if set, skipping the normal tier/upsert breakdown. `AbcRunReport` callers that don't care about failures (there are none yet outside this module and its tests) are unaffected — the field defaults to `None`.

## 8. Full run results

**2024-01 (first, isolated run):** completed cleanly.
```
=== ABC classification: unilever / 2024-01 ===
  Products classified: 545        Tier breakdown: {'C': 265, 'B': 155, 'A': 125}
  Near tier boundary: 108         Rows upserted: 545
  Excluded (negative revenue, needs a human look): [37 product_keys]

=== ABC classification: delmonte / 2024-01 ===
  Products classified: 79         Tier breakdown: {'C': 47, 'B': 22, 'A': 10}
  Near tier boundary: 16          Rows upserted: 79
  Excluded (negative revenue, needs a human look): [50208]
```

**All 68 periods, 2021-01 through 2026-08:** ran `run_abc(period)` for every month. **0 failures across all 136 (principal × period) runs.** Per-period `rows_upserted` (unilever, delmonte) — full list:

2021-01: 610,71 · 02: 596,80 · 03: 620,68 · 04: 599,78 · 05: 585,82 · 06: 629,75 · 07: 608,72 · 08: 608,67 · 09: 622,71 · 10: 618,73 · 11: 601,78 · 12: 631,74 · 2022-01: 620,78 · 02: 613,69 · 03: 630,74 · 04: 603,67 · 05: 610,76 · 06: 621,78 · 07: 607,71 · 08: 598,77 · 09: 631,76 · 10: 595,74 · 11: 598,70 · 12: 608,76 · 2023-01: 545,71 · 02: 533,73 · 03: 543,75 · 04: 521,74 · 05: 567,68 · 06: 549,71 · 07: 569,75 · 08: 566,**0** · 09: 555,75 · 10: 558,75 · 11: 554,75 · 12: 527,71 · 2024-01: 545,79 · 02: 559,74 · 03: 542,71 · 04: 578,69 · 05: 594,72 · 06: 609,78 · 07: 622,74 · 08: 592,73 · 09: 598,72 · 10: 629,71 · 11: 655,71 · 12: 599,80 · 2025-01: 672,13 · 02: 631,12 · 03: 639,5 · 04: 638,4 · 05: 684,14 · 06: 676,5 · 07: 677,13 · 08: 680,4 · 09: 732,4 · 10: 711,14 · 11: 721,13 · 12: 597,4 · 2026-01: 746,13 · 02: 710,14 · 03: 623,13 · 04: 600,7 · 05: 617,7 · 06: 617,8 · 07: 590,2 · 08: 607,7

**Total rows landed in `abc_classification`: 45,176** (verified: `SELECT count(*)`, and this matches the sum of `rows_upserted` exactly — no re-run collisions in this pass, since each period was run exactly once).

**Tier split:** A: 9,380 · B: 12,437 · C: 23,359.
**Principal split:** unilever: 41,538 · delmonte: 3,638.
**Principal × tier:** unilever A/B/C: 8,496 / 11,393 / 21,649. delmonte A/B/C: 884 / 1,044 / 1,710.
**`boundary_flag=true` count:** 8,734.
**Distinct `classification_period` values present:** 68 (all of them).

**One anomaly, investigated, not fixed:** `2023-08` is the only period with `delmonte=0`. Traced directly: `sellout_fact` has 137 rows for `_period='2023-08'`, all `is_demo=false` (real data) — and **every single one of those 137 rows has `net_amount` equal to the literal Postgres `NUMERIC` value `NaN`** (not `NULL` — confirmed by reproducing the exact crash a naive `Decimal < 0` comparison hits on this data, `decimal.InvalidOperation`, then re-querying with the same `.astype(float)` cast the fix uses and confirming all 137 become `float('nan')`, correctly caught by `.isna()`/`dropna()`). This is a new, real data-quality finding — the fixed pipeline handled it correctly (excluded, not crashed, not fabricated), so `delmonte=0` for 2023-08 is the right output, not a bug. Not investigated further or fixed; flagging for whoever owns real Del Monte sell_out data quality.

## 9. `/abc` re-verified against the populated table

Re-ran the same direct endpoint-function exercise as §5, now against 45,176 live rows:

```python
get_abc(principal=None, classification_period=None, db=<live Session>, current_user=<admin>)
# -> count=614, classification_period='2026-08' (the latest period present - MAX() default),
#    tier_summary=[TierSummary(tier='A', sku_count=137, revenue_share_total=1.5717),
#                  TierSummary(tier='B', sku_count=180, revenue_share_total=0.3217),
#                  TierSummary(tier='C', sku_count=297, revenue_share_total=0.1065)]
```
137+180+297 = 614, matching §8's `2026-08: unilever=607, delmonte=7` exactly (607+7=614) — **both principals confirmed present in one response** (no `principal` filter applied). One Del Monte row's `sku_id` resolves to the literal string `DAIRY` (one of the 5 coarse category names, per `COALESCE(sku_code, category_path)` — consistent with `reports/SELLOUT_COVERAGE_DIAGNOSIS.md`'s earlier finding on the coarse taxonomy). Real, valid, non-empty response.

## 10. The origin question

Fetched `origin` fresh and compared every branch that exists on both remotes against its `group7` counterpart, post-merge-and-push:

```
AUDREY-TRY-MERGE:              origin fully contained in group7 - OK
CP-backend:                    origin fully contained in group7 - OK
THEA-AUDREY-merge:              origin fully contained in group7 - OK
Try-CPBackend:                  origin fully contained in group7 - OK
kelvin-etl:                     origin fully contained in group7 - OK
maica/transform-null-key-fix:   origin fully contained in group7 - OK
master:                         origin fully contained in group7 - OK
thea/updates:                   origin fully contained in group7 - OK
```

**Every commit reachable from any `origin` branch is now also reachable from the matching `group7` branch.** `group7` additionally has one branch `origin` doesn't (`j0018-patch-1`) — `group7` having more, not less. `origin/kelvin-etl` and `origin/master` were checked individually first (both showed `merge-base --is-ancestor` true) before the full sweep across all 8 shared branches confirmed the same for every one.

**`origin` is safe to abandon — nothing would be lost.** This only holds as of right now, though: it's true because this session just pushed `kelvin-etl` to `group7` moments ago. If anyone pushes new work to `origin` specifically after this check (rather than to `group7`), that would re-diverge it and this conclusion would need re-verification.

## Summary

- Merge + push to `group7`: done, clean, no conflicts.
- `origin` (KYG07/Capstone-Project): confirmed safe to abandon as of this check — every branch's commits are already contained in `group7`.
- Live schema: fully reconciled, zero drift, both `is_demo` and `boundary_flag` present and tracked (`0001`, `0002`).
- `orchestrate_abc.py`: **fixed** (float cast at the fetch boundary) and **error-isolated** (one principal's failure can't block the other). Ran clean across all 68 periods, 0 failures, 45,176 rows landed.
- `abc_classification` / `/abc`: both populated and verified serving real data for both principals.
- One new data-quality finding surfaced (2023-08 Del Monte `net_amount` = NUMERIC NaN for all 137 rows that period) — not fixed, flagged for the data owner.
