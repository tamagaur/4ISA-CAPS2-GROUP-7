# Phase 2 Binning, Round 1 (2026-09-17)

BINS ONLY. No forecasting model run, no bake-off, no MASE, no model
assignment — that is Phase 3. Cohort: Unilever Tier A as of 2026-02,
single-period (132 SKUs), from `abc_classification`. Series: monthly
`quantity_sold` from `unilever_sku_demand_fact_real`, 2023-01 to 2026-02.

Built and verified in scratch schema `ssm_binning_phase2` (migration 0018
+ schema.sql written, not yet applied to public — see §3).

## 1. Bin counts with rules (scheme `length_v1`)

| Bin | Count | Rule |
|---|---|---|
| insufficient | 13 | history_months < 3 |
| short | 30 | 3 ≤ history_months ≤ 11 |
| long | 89 | history_months ≥ 12 |

Matches the expected 13/30/89 exactly — no explanation needed. (Expected
counts were themselves derived from the same cohort/cutoffs in an earlier
diagnostic session; this run reproduces them independently via the new
`analytics/segmentation` module and the DB, not by re-using that number.)

## 2. Trait distributions per bin

**Trend (Mann-Kendall, p<0.05) × bin**

| Bin | up | down | none |
|---|---|---|---|
| insufficient | 0 | 0 | 13 |
| short | 28 | 0 | 2 |
| long | 40 | 11 | 38 |

**Stability group × bin**

| Bin | all_38 | at_least_30 | churn |
|---|---|---|---|
| insufficient | 0 | 0 | 13 |
| short | 0 | 0 | 30 |
| long | 21 | 18 | 50 |

**Restart flag and CV × bin**

| Bin | restart=yes | CV min | CV mean | CV max |
|---|---|---|---|---|
| insufficient | 0 | 4.31 | 5.07 | 6.16 |
| short | 0 | 1.79 | 2.37 | 3.16 |
| long | 1 | 0.16 | 0.61 | 1.50 |

CV falls monotonically with history length, as expected (fewer, spikier
sales months inflate CV). All 13 insufficient SKUs show trend=none — with
1-2 nonzero months in a 38-month series, Mann-Kendall has no basis to call
a direction.

## 3. Expected public changes

| Change | Detail |
|---|---|
| Migration | **0018** (`analytics/db/migrations/0018_sku_segment_and_traits.sql`) — next free number; 0001-0017 exist (0002 duplicated, pre-existing, not this migration's problem) |
| New tables | `sku_traits`, `sku_segment` (schema.sql updated in the same file) |
| Rows to `sku_traits` | 132 (one per cohort SKU) |
| Rows to `sku_segment` | 132 (one per cohort SKU, scheme=`length_v1`) |
| Existing tables touched | None — additive only, no ALTER on `abc_classification` or any fact table |

Not yet applied to public — stopping at the write gate as instructed.

## 4. How to run the dashboard

```
python tools/bin_viewer/build.py --schema ssm_binning_phase2   # now, against scratch
python tools/bin_viewer/build.py                                # after the public write
```

Then open `tools/bin_viewer/bin_viewer.html` directly in a browser
(double-click, no server, no internet required). Full usage in
`tools/bin_viewer/README.md`.

## 5. Open items

| Item | Note |
|---|---|
| Phase 3: reconcile MA3 MASE 0.940/56.3% (deployed, rolling-origin) vs 1.217/29.4% (diagnostic, static 80/20 split) | Different evaluation protocols, not a contradiction — flagged for Phase 3 to state explicitly which one is authoritative |
| Phase 3: review teammate changes to `run_baseline_forecast.py` from the 2026-09-17 merge (`c8a6c4c`) | Not opened this session (out of BINS-ONLY scope) |
| Verify `transform_ssis_soh` `unit_cost_per_case`/`stock_status` output matches public | Not checked this session (out of scope) |
| `get_settings().supabase_db_url` (from `SUPABASE_DB_URL`) rejects writes with `ReadOnlySqlTransaction` on this project's Supabase connection; `orchestrate_segment.py` falls back to `SUPABASE_DIRECT_URL` when set | Confirmed by testing, not investigated further — same latent issue likely affects `orchestrate_abc.run_abc()`'s own `settings.supabase_db_url` engine, unconfirmed |
| Migration `0002` is duplicated (`0002_add_boundary_flag.sql`, `0002_add_sku_management_fields.sql`) | Pre-existing, noted again for whoever owns migration hygiene |
| 8 negative `quantity_sold` rows across the cohort's 2023-01–2026-02 window, clipped to 0 for trait computation | Not investigated (root cause out of scope) |
