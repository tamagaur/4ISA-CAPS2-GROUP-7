# Experiment log

`reports/experiment_log.csv` is the project's record of forecasting experiments:
what was tried, on which SKUs and months, against which baseline, and how it came
out. **Losing, tied, untestable and crashed runs are recorded, not omitted** — a
model that was tried and failed is a result.

One row = one run x bin x model x test window.

## Rules

1. **Nothing is typed from memory.** Every number in the log is computed from an
   artifact file by a script. If the artifact is gone, the row is kept with
   `status = artifact_missing` and blank values.
2. **Every cited artifact lives inside the repo**, under
   `reports/experiment_artifacts/` (or is an already-tracked file under `reports/`).
3. **Synthetic data is never reportable.** Any row whose `data_arm` involves
   `is_demo` rows has `reportable = no`. Those rows exist to show what synthetic
   history does to a model, not to support a result.
4. `status` records a *decision* and is set by Yuan. The default is `diagnostic`.
   The log builder never marks anything adopted.

## Columns

| Column | Meaning |
|---|---|
| `run_id` | Name of the experiment; rows sharing it came from one run. |
| `run_date` | Date of the run. For files that predate the log, the file's modified date. |
| `source_script` | Script that produced the artifact. "scratch ..." scripts are copied under `experiment_artifacts/scripts/`. |
| `git_commit` | Code state the run used, where known. |
| `cohort`, `abc_period`, `abc_method` | SKU set, always with its ABC period. |
| `n_skus` | SKUs scored in this row (pairs with both the model and the baseline finite). |
| `data_arm` | `real`, or a description of the synthetic prefix used. |
| `train_pool` | What the model was fitted on. |
| `split_protocol` | How train and test months were separated. |
| `window_start`, `window_end` | Test window (`YYYY-MM`). Blank start = per-SKU split, window differs by SKU. |
| `bin` | Segment scored; `ALL` = whole cohort. |
| `model`, `baseline_model` | Model scored and what it is compared with (MA3 unless stated). |
| `metric` | `median_wape` (median across SKUs of per-SKU WAPE), `pooled_wape` (one month, across a bin's SKUs), or `median_smape` / `median_mase` for older files with no WAPE. |
| `model_value`, `baseline_value` | Metric for the model and the baseline, on the same SKUs. |
| `diff_ci_lo`, `diff_ci_hi`, `ci_level` | Bootstrap interval on (model - baseline) median, resampling SKUs. |
| `n_better`, `n_worse` | SKUs where the model beat / lost to the baseline. |
| `mase_pass_pct` | Share of scored SKUs with MASE < 1 for the model. |
| `n_boot`, `seed` | Bootstrap resamples and seed. |
| `verdict` | `win` (interval below 0), `loss` (interval above 0), `tie` (interval includes 0), `underpowered` (bin too small to name a winner; values still shown), `not_testable` (fewer than 5 scorable SKUs, or model fits under half the bin), `crashed`. |
| `reportable` | `no` for anything touching synthetic data. |
| `status` | `diagnostic`, `adopted`, `shadow`, `rejected`, `superseded`, `artifact_missing`. |
| `notes`, `artifact_path` | Context, and the file the row was computed from. |

## Reading the intervals

Each row's interval is computed with a fresh random stream from the same seed, so
any single row can be reproduced on its own. Session printouts used one running
stream, so an interval here can differ from a printed one in the third decimal.
The half-year block tests and the monthly scoreboard reproduce exactly.

A `tie` means no difference could be detected with this many SKUs — not that the
two models are identical. Check `n_better` / `n_worse` alongside it.

## Backfilled 2026-09-21

Built by `experiment_artifacts/scripts/build_experiment_log.py`, then `backfill_gate_d.py`.

| run_id | What it is |
|---|---|
| `routing_8020`, `routing_7030` | 17 models per combined_v1 bin, single time split, plus routing strategies and a merged-long check. |
| `synthetic_arm_A_8020`, `synthetic_arm_B_8020` | Same, with the 2021-22 synthetic months as training context. Not reportable. |
| `candidate_search_tierA` | 35 candidates incl. XGBoost variants, random forest, ridge, neural net, auto-ETS, ensembles; every-month test. Includes the two LightGBM crashes. |
| `block_tests_tierA`, `monthly_scoreboard_tierA` | XGBoost+MA3 average and TSB vs MA3 by half-year block and by month. |
| `global_model_trainA_evalABC` | XGBoost trained on Tier A origins, scored on Tier A and Tier A+B+C. |
| `global_model_trainABC_evalABC` | `artifact_missing`: the result file was overwritten by the run above. |
| `synthetic_prefix_check_tierA` | Synthetic prefix applied to TSB and XGBoost. Not reportable. |
| `xgboost_bakeoff_old` | The 2026-09-02 XGBoost bake-off CSVs already under `reports/`. |
| `gate_d_bakeoff` | The 2026-09-20 Gate D bake-offs (17-model, auto-ARIMA, global XGBoost), real and synthetic arms, 89 evaluable Tier A SKUs. Backfilled by `scripts/backfill_gate_d.py` from `gate_d_*.csv`; the workbook `gate_d_model_bakeoff_unilever_tierA.xlsx` is the same run's presentation view. These artifacts predate the `months_train` label fix. Synthetic arms are not reportable. |

## Adding a run

Append rows; never edit old ones. If a result is superseded, add the new run and
change the old rows' `status` to `superseded`. Save the per-SKU or per-origin
table the numbers came from under `experiment_artifacts/` and cite it.
