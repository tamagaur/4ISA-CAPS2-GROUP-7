# ABC_Classification purge — 2026-08

**Read this before recomputing ABC or touching the routers' period logic.**

## What was deleted

Confined to `ABC_Classification`. **No fact or dimension table was touched.**
Single transaction, committed 2026-08-31.

| Scope | Rows | Periods |
|---|---|---|
| `principal='delmonte'` — every period | 19,817 | 66 (2021-01 → 2026-07) |
| `principal='unilever'` — 2021-01 → 2022-12 | ~14,660 | 24 |
| `principal='unilever'` — 2026-03 → 2026-08 | ~6,045 | 6 |
| **Total** | **40,522** | |

`ABC_Classification`: 63,745 → 23,223 rows.

### After

- `unilever`: **38 periods, 2023-01 → 2026-02, contiguous** — exactly the real per-SKU demand range (`Unilever_SKU_Demand_Fact_Real`).
- `delmonte`: **0 rows**.
- `MAX(classification_period)` across the whole table: **`2026-02`** (unilever, 710 rows) — a real period.

## Why

1. **Unilever synthetic periods.** `unilever_sku_demand_fact` is 100% `is_demo=true`
   for 2021-01 → 2022-12 and 2026-03 → 2026-08; real data is 2023-01 → 2026-02
   only (clean split, zero month overlap — verified live). ABC periods built on
   those months are synthetic rankings.
2. **Del Monte is out of active scope** and its ABC data was almost entirely
   synthetic anyway: of 66 periods, **49 were 100% synthetic, 6 mixed
   real+synthetic, 1 orphan (2026-07 — ABC rows with zero surviving source
   rows), leaving only 10 periods on 100%-real sell-out** (2023-01→06, 2023-09,
   2023-11, 2024-01, 2024-02).
3. **The routers' `MAX(classification_period)` has no principal filter**
   (`backend/routers/abc.py:81`, `backend/routers/dashboard.py:544`,
   `backend/routers/sku.py:54`, `scripts/run_lp.py:271`). Any surviving Del
   Monte period past 2026-02 would win that `MAX()` and poison the default
   view. Removing Del Monte entirely gives a clean single-principal `MAX()`.

## Verification done before the delete

- Backup file row count (40,522) == `DELETE` predicate match count — OK
- Per-(principal, period) counts: file == table — OK
- Checksum (sorted sha256 of `principal|product_key|classification_period|tier|revenue_share`):
  file == table — OK (`ae62221e95c913a2…`)
- **Dry restore**: inside a rolled-back transaction, deleted all 40,522 in-scope
  rows then re-inserted from the backup — count and checksum round-tripped — OK

## Undo

`scripts/restore_abc_purge.py` (committed alongside this note):

```
python -m scripts.restore_abc_purge --dry-run   # insert + ROLLBACK, report counts
python -m scripts.restore_abc_purge --write     # insert + COMMIT
```

Reads `reports/abc_purge_backup_2026-08.json` (full row contents, every column
except the regenerated `classification_key`). Idempotent
(`ON CONFLICT (product_key, classification_period) DO NOTHING`).

**Del Monte source data (`sellout_fact`, `sellout_fact_real`) is fully intact**
— the forward path for Del Monte is a clean recompute via
`analytics.classification.orchestrate_abc`, not this restore.

## Dangling children check (post-purge)

| Table | Rows | Del Monte rows | Rows with no surviving ABC row |
|---|---|---|---|
| `Forecast_Result` | 132 | 0 | 0 |
| `LP_Recommendation` | 430 | 0 | 0 |

No dangling children — both derived tables were Unilever-only already.

## Left open (NOT addressed in this pass)

1. **Missing principal filter in the 4 `MAX(classification_period)` call sites**
   above. `MAX()` currently lands on a real period by luck of Del Monte being
   gone; a future Del Monte recompute past 2026-02 would break the default view
   again. The routers should filter to the principal they're serving, or the
   query should pin to Unilever.
2. **The 6 mixed Del Monte 2025 periods** (2025-03, -04, -06, -08, -09, -12) —
   ~8–10 real sell-out rows each, drowned by ~84 synthetic. If Del Monte ABC is
   ever recomputed, these need the synthetic rows excluded first.
3. **Del Monte 2023-08** — 137 real `sellout_fact` rows, never classified (the
   one gap in the otherwise contiguous 2021-01 → 2026-07 Del Monte range).
4. `orchestrate_abc.py::_fetch_unilever_sku_revenue()` still reads the **base**
   `unilever_sku_demand_fact` with no `is_demo` filter (violates the
   data-interface rule). A recompute today would re-create synthetic periods.
   The current live `Forecast_Result` (132 rows) was already verified to match
   the real 2026-02 Tier A set — see the reproducibility check — but the
   contamination path is still open in code.
