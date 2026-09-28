# Coverage grid, both principals, 2021-01 → 2026-09 (read-only recon, 2026-09-28)

Read-only session (session pooler, `transaction_read_only = on`). Month = `_period` (`calendar_month` for Unilever demand).
Del Monte fix batches 1–7 are live (b00dd19..36bdc4d); precondition held: real Del Monte sales 2025-04 = 962 / ₱9,699,904.53.
Unilever half: `coverage_grid_unilever.md` (not redone; extended by one month, 2026-09 = N in both schemas).

**R** real in public · **V** synthetic in ssm_synth_v2 only · **P** synthetic in public only · **PV** public v1 + ssm_synth_v2 v2 ·
**B** real + synthetic in the same table-month · **N** neither · **NA** the table cannot hold this principal. Counts: rows (v1 / v2).

## Del Monte

| Table | Runs of identical months |
|---|---|
| `sales_fact` | 21-01→22-12 PV 16,984/16,982 · 23-01→23-06 R 4,693 · 23-07 PV 980/980 · 23-08→23-09 R 1,496 · 23-10 PV 625/625 · 23-11→24-02 R 2,818 · 24-03→25-02 PV 10,584/10,584 · 25-03→25-04 R 2,085 (v2 2,649: the 564 held "(2)" rows) · 25-05 PV 774/774 · 25-06 R 1,230 · 25-07 PV 954/954 · 25-08→25-12 R 5,104 · 26-01→26-08 PV 4,261/3,411 · 26-09 N |
| `salesreturn_fact` | 21-01→22-12 N · 23-01→23-06 R 336 · 23-07 N · 23-08→23-09 R 150 · 23-10 N · 23-11→24-02 R 285 · 24-03→25-02 N · 25-03→25-04 R 140 · 25-05 N · 25-06 R 120 · 25-07 N · 25-08→25-12 R 573 (incl. 224 RMR 25-10/11; v2 349) · 26-01→26-03 N · 26-04→26-08 PV 250/251 · 26-09 N |
| `sellout_fact` | 21-01→22-12 PV 2,932/2,932 · 23-01→23-06 R 705 · 23-07 PV 122/122 · 23-08→23-09 R 246 · 23-10 PV 121/121 · 23-11 R 121 · 23-12 PV 117/117 · 24-01→24-02 R 243 · 24-03→25-02 PV 1,397/1,229 · **25-03→25-04 B** 19 real + 168 v1 · 25-05 PV 94/10 · **25-06 B** 9 + 84 · 25-07 PV 94/10 · **25-08→25-09 B** 16 + 168 · 25-10→25-11 PV 188/20 · **25-12 B** 8 + 84 · 26-01→26-08 PV 724/70 · 26-09 N |
| `inventory_fact` | 21-01→21-08 P 2,669 · 21-09 PV 342/1 · 21-10→22-12 P 4,731 · 23-01→23-06 R 1,695 · 23-07 P 287 · 23-08→23-09 R 1,033 (v2 849, pre batch 2) · 23-10→23-11 P 615 · 23-12→24-02 R 883 · 24-03→25-02 P 3,762 · 25-03→25-04 R 584 · 25-05 P 359 · 25-06 R 304 · 25-07 P 304 · 25-08→25-09 R 627 · 25-10→25-11 P 690 · 25-12 R 415 · 26-01→26-03 P 901 · 26-04→26-08 PV 1,074/831 · 26-09 N |
| `purchase_fact` | 21-01→23-08 PV 1,159/1,159 · 23-09 R 34 · 23-10 PV 31/31 · 23-11→24-02 R 162 · 24-03→25-02 PV 472/472 · 25-03→25-04 R 102 · 25-05 PV 54/54 · 25-06 R 58 · 25-07 PV 27/27 · 25-08 R 74 · 25-09 N (the 18 real rows are quarantined, D12) · 25-10→25-11 PV 69/69 · 25-12 R 69 · 26-01→26-08 PV 334/402 · 26-09 N. Plus 117 v1 rows with `_period = 'unknown'` (invoice dates 2021-01→2026-03, none in a real purchase month) |

## Unilever (from coverage_grid_unilever.md + 2026-09)

| Table | Runs |
|---|---|
| Sales = `unilever_sku_demand_fact` | 21-01→22-12 PV 15,753/8,444 · 23-01→26-02 R 24,906 · 26-03→26-08 PV 3,916/3,799 · 26-09 N |
| `inventory_fact` | 21-01→22-12 N · 23-01→26-03 R 27,282 · 26-04→26-09 N |
| `purchase_fact`, `salesreturn_fact` | NA, all months: no Unilever source (0 rows in either schema) |
| `sales_fact`, `sellout_fact` | NA, all months: live `CHECK (principal = 'delmonte')` |

## Overlaps: synthetic rows in a real Del Monte table-month (expected 0)

| Check | public | ssm_synth_v2 |
|---|---|---|
| sales, returns, inventory, purchases | 0 | 0 |
| sell-out | **504 v1 rows** in 6 real months (25-03/04/06/08/09/12) | 0 |
| v2 synthetic in a month public now holds real (v2 predates the fixes) | — | 0 |
| returns 2025-10/11 (now real, 224 RMR rows) | 0 synthetic | 0 synthetic (0 real: pre batch 4) |
| sales 2024-09: synthetic vs the held "(2)" sheet (564 rows, invoices 2024-09-03→30, pending SSM) | 710 v1 rows / ₱6,377,658.12, 0 real | 710 v2 rows / ₱6,961,656.97, 0 real. If SSM confirms "(2)" is Sep-2024, 2024-09 becomes B in both |

## Grain of the Del Monte synthetic rows (v1 public / v2 ssm_synth_v2)

| Table | Key (one row per key in both blocks) | v1 | v2 |
|---|---|---|---|
| sales | invoice × `region` (town names, as on real rows) | 35,162; 21,164 customers (83 also on real rows), 26 NULL customer | 34,310; 20,613 customers (69 on real), 0 NULL |
| returns | slip × region × invoice (ilocos / pangasinan) | 250 | 251 |
| sell-out | category × region × period | 6,293; 85 categories, 1 not in real | 4,631; 85, 1 not in real |
| inventory | SKU × snapshot × region | 15,734 rows / 14,752 codes: 232 in the real 394 alphanumeric, 0 in the 203 numeric count-sheet codes, **14,520 codes outside the real 597** (15,178 rows) | 832 rows / 262 codes, all in the real 394 alphanumeric |
| purchases | bill × region × invoice date | 2,263 | 2,214 |

The real 597 set is the same before and after batch 2's Aug-2023 re-key (597 = 394 alphanumeric + 203 numeric).

## Calibration: was each block's source taken before the fixes?

All three fixes live in Transform or in the database; `staging/` still holds the raw rows, so a pool read from staging includes them whatever its date.
In staging: FAKE BOOKING = 84 rows (14 invoices × 6 copies, REMARKS column); "(2)" sheet = 3,468 rows (one 578-row sheet copied into 6 workbooks);
Aug-2023 count-block codes = raw `__col1__`.

| Block | Built | Real inputs | FAKE BOOKING | "(2)" sheet | Aug-2023 re-key |
|---|---|---|---|---|---|
| v1 raw workbooks (`data/raw/Synthetic Data`, 374 files, 21-01→26-03) | 2026-08-20 | UNVERIFIED (generator not in repo) | before (by date) | before (by date) | before (by date) |
| v1 forward 26-04→26-08, 4 families + returns (public) | 2026-08-20 | every 2025 parquet in `staging/<family>/`, synthetic copies included (HEAD 82be56b:225-228; fixed 09-21) | in pool (staging as of 08-20 UNVERIFIED) | in pool (same) | not in pool (2025 only) |
| v2 converted (same months as v1 workbooks) | 2026-09-21 | Net Amount pool, town/branch and salesman maps = every real staged sales_register row; 33 real sell-out negatives; inventory kept to the live 597 as of 09-21 | in the Net Amount pool | in the Net Amount pool | no effect (597 set unchanged) |
| v2 forward 26-04→26-08 (sales, purchases, sell-out, inventory) | 2026-09-21 | real 2025 staged rows, numeric Net Amount (sales pool 9,675) | 84 of 9,675 | 3,468 of 9,675 (35.8%), and per-file row-count draws include the 578-row copies | not in pool |
| v2 returns 26-04→26-08 | 2026-09-21 | real 2025 staged sales_return (Sep + Dec 2025) | n/a | n/a | n/a |

## Every N table-month, split

| Principal | Table | FILL NOW (2021-01 → 2022-12) | PENDING SSM (2023-01 → 2026-09) |
|---|---|---|---|
| Del Monte | salesreturn_fact | 21-01→22-12 (24) | 23-07, 23-10, 24-03→25-02, 25-05, 25-07, 26-01→26-03, 26-09 (20) |
| Del Monte | sales_fact | — | 26-09 |
| Del Monte | sellout_fact | — | 26-09 |
| Del Monte | inventory_fact | — (P: v1 only; v2 holds 1 row, so a v2 cutover leaves 21-01→22-12 N) | 26-09 |
| Del Monte | purchase_fact | — | 25-09, 26-09 |
| Unilever | unilever_sku_demand_fact | — (PV) | 26-09 |
| Unilever | inventory_fact | 21-01→22-12 (24) | 26-04→26-09 (6) |
| Unilever | purchase_fact, salesreturn_fact, sales_fact, sellout_fact | NA | NA |

Synthetic already sits in the PENDING window (not N, so not in the list above): Del Monte sales, sell-out, inventory and purchases in every
non-R month from 2023-07 on (purchases from 2023-01), returns 26-04→26-08; Unilever demand 26-03→26-08. Keep or remove is a decision.
*Decided 2026-09-28: it stays until SSM's files replace it month by month.*

## After the clean-pool rebuild of ssm_synth_v2 (2026-09-28) - simulated cutover

`scripts/build_synthetic_v2_clean_pool.py` resampled from the REAL rows in public (the `_Real` views, after the Del Monte fixes), not
staging/, and wrote only to ssm_synth_v2. Public is unchanged. Simulated cutover = public real rows + ssm_synth_v2 synthetic rows
(what `apply_synth_v2_to_public.py` leaves). **R** real · **S** synthetic (v2) · **N** neither. Counts: rows.

| Pool | Old (staging) | New (public real) |
|---|---|---|
| Del Monte sales | converter 18,684 / forward 9,675, each incl. 3,468 "(2)" + 84 FAKE BOOKING | 17,426 (0 "(2)", 0 FAKE BOOKING) |
| Del Monte inventory | forward 3,370 incl. 1,428 price-list rows | 5,145 alphanumeric-code rows (0 price-list, 0 of the 203 numeric count-sheet codes) |
| Del Monte returns | forward 609 (2025) | 1,380 (monthly files, `source IS NULL`) |
| Unilever inventory | none (no generator) | 8,906 (2023 rows) |

| Block written to ssm_synth_v2 | Rows |
|---|---|
| Del Monte sales, regenerated (48 months: 2021-22, 2023+ gaps, 2026-04..08) | 34,310 replaced by 43,843 (old rows kept in `ssm_synth_v2.bk_20260928_dm_sales_demo`) |
| Del Monte inventory, every month public holds v1-only synthetic (46) | 14,319 (1 stray converted row replaced) |
| Del Monte returns 2021-01 → 2022-12 | 1,971 |
| Unilever inventory 2021-01 → 2022-12 (477 SKUs of the demand placeholder, 2023 same-month stock) | 8,292 |

| Table | Post-cutover runs |
|---|---|
| DM `sales_fact` | 21-01→22-12 S 21,694 · 23-01→06 R · 23-07 S · 23-08→09 R · 23-10 S · 23-11→24-02 R · 24-03→25-02 S 10,589 · 25-03→04 R · 25-05 S · 25-06 R · 25-07 S · 25-08→12 R · 26-01→08 S 7,114 · 26-09 N |
| DM `salesreturn_fact` | 21-01→22-12 S 1,971 · 23-07, 23-10, 24-03→25-02, 25-05, 25-07, 26-01→03, 26-09 N · 26-04→08 S 251 · other months R |
| DM `sellout_fact` | every non-R month S from 2021-01 to 2026-08 · 26-09 N (the 504 v1 rows in real months are gone) |
| DM `inventory_fact` | 21-01→22-12 S 7,358 · every other non-R month to 26-08 S · 26-09 N |
| DM `purchase_fact` | every non-R month S from 2021-01 to 2026-08 except 25-09 N · 26-09 N (the 117 'unknown'-period rows are gone) |
| Unilever demand | 21-01→22-12 S 8,444 · 23-01→26-02 R · 26-03→08 S 3,799 · 26-09 N |
| Unilever `inventory_fact` | 21-01→22-12 S 8,292 · 23-01→26-03 R · 26-04→26-09 N |

| Check (simulated cutover) | Result |
|---|---|
| synthetic rows in a real table-month, 7 grids | 0 |
| table-months covered in public today that become N | none |
| N table-months in 2021-01 → 2022-12 (NA excluded) | 0 - **FILL NOW list is empty** |
| the 504 v1 sell-out rows / the 117 'unknown' purchases in v2 | 0 / 0 (both removed by the cutover) |
| synthetic-source rows flagged real; GENERATED_BACKFILL_ rows not is_demo | 0; 0 |
| v2 synthetic FKs with no public dimension row (the cutover would abort) | 0 (was 3,108 customers before the sales regeneration) |
| Del Monte synthetic sales 2024-09 (to remove if SSM confirms "(2)" is Sep-2024) | 954 rows / ₱10,252,969.47 |

PENDING SSM after the cutover (N, not generated by decision): Del Monte returns 23-07, 23-10, 24-03→25-02, 25-05, 25-07, 26-01→03, 26-09;
Del Monte sales, sell-out, inventory 26-09; purchases 25-09, 26-09; Unilever demand 26-09; Unilever inventory 26-04→26-09.
Not regenerated (outside this pass): the v2 forward inventory and purchases 26-04..08 still come from staging pools (inventory pool 42%
price-list rows; purchases pool held the 18 quarantined Sept-2025 lines); sell-out has 92 loader-merged synthetic rows named
`AGGREGATED_source_file_defect_category` (is_demo inherited, true).
