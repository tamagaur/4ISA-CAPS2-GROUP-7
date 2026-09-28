# Unilever coverage grid, 2021-01 → 2026-08 (read-only recon, 2026-09-28)
Read-only session on `SUPABASE_DB_URL` (`transaction_read_only = on`), filtered `principal = 'unilever'`; no Del Monte rows selected. R real in public · V synthetic in ssm_synth_v2 only · P synthetic in public only · **PV** public holds v1 AND ssm_synth_v2 holds v2 (different rows) · N neither. Inventory month = `_period` (stock at month close; `snapshot_date` falls 1-6 days into the next month).

| Table | 2021-01 → 2022-12 | 2023-01 → 2026-02 | 2026-03 | 2026-04 → 2026-08 |
|---|---|---|---|---|
| Sales = `unilever_sku_demand_fact` | PV · v1 15,753 / v2 8,444 | R · 24,906 rows, 1,807 SKUs | PV · v1 670 / v2 644 | PV · v1 3,246 / v2 3,155 |
| `inventory_fact` | N | R · 26,497 rows, 0 is_demo | R · 785 (snapshot 2026-04-06) | N |
| `purchase_fact` | N | N | N | N |
| `salesreturn_fact` | N | N | N | N |
| `sales_fact`, `sellout_fact` | N (live CHECK `principal = 'delmonte'`) | N | N | N |

| Check (task) | public | ssm_synth_v2 |
|---|---|---|
| 2 · synthetic rows in a real table-month (expected 0) | 0 demand, 0 inventory | 0 demand, 0 inventory |
| 2 · real rows diff public ↔ ssm_synth_v2 (EXCEPT ALL, both ways) | demand 0/0, inventory 0/0 | — |
| 3 · 2021-22 placeholder: tables · grain · is_demo | demand only · month × SKU × la_union, 1 row per key · 15,753/15,753 true (v1, `_src_file` GENERATED_BACKFILL_*) | demand only · same grain · 8,444/8,444 true (v2) |
| 3 · router rejects by provenance? | Yes: live `unilever_sku_demand_fact_real` = `WHERE is_demo = false`; returns 24,906 rows, 0 is_demo, 2023-01 → 2026-02 | same view def |
| 4 · synthetic SKUs outside real 1,807 | 0 of 1,594 | 0 of 911 |
| 4 · SKUs with pre-2023 rows but first real month ≥ 2024-01 | 695 | 5 |
| 4 · synthetic FK → non-(unilever, sku) product | 0 of 19,669 | 0 of 12,243 |

| 5 · Block | Script | Inputs | Pool holds recovery-changed rows? |
|---|---|---|---|
| v1 (public, 19,669) | `generate_synthetic_backfill.py` @ HEAD (106cd0b) | every `staging/unilever_sku/*.parquet`, NO is_demo filter (HEAD:89-91); presence = rows / 38 months; values = resampled real row × month-of-year multiplier | No (recovery wrote 0 Unilever demand rows). Own SYNTH copies in the pool on a re-run: UNVERIFIED |
| v2 (ssm_synth_v2, 12,243) | same file, working copy (uncommitted) | real staged parquet (mtime 2026-09-14, 24,906 rows, is_demo dropped, L126-138) + `soh_witness_2021_2022.parquet` (existence only) | No. Recovery (09-22/23) changed Unilever only in Product_Dimension (pack 291, brand_source 380, brand 1); pack size is read from the parquet (L196) |

| Must be generated / regenerated | Status |
|---|---|
| Demand 2021-01 → 2022-12, 2026-03 → 2026-08 | No regeneration: v2 is built and sits in ssm_synth_v2. Public still serves v1 → needs `apply_synth_v2_to_public.py` cutover (Yuan's go). That script also rewrites Del Monte demo rows + deletes Del Monte product rows: do not run while the Del Monte session writes |
| Inventory 2021-01 → 2022-12, 2026-04 → 2026-08 (29 mo) | N, and no Unilever inventory generator exists. Decision needed (SOH witness is existence-only by rule) |
| Purchases + returns, all 68 mo | N in both schemas, no generator, no Unilever rows loaded. Decision needed |

Side findings: runner `assert_real_rows(demand)` (run_baseline_forecast.py:926) is a no-op, since `fetch_demand` returns no is_demo column; only the view guards. Unilever inventory: `region`, `demand_period`, `days_offset` NULL on all 27,282 rows.
