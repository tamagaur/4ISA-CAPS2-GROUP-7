# Target-transform experiments (2026-09-26)

Recovered on 2026-11-03 from the local tag `archive/target-transforms-2026-09` (commits f0b0148 and fce007e), because `scripts/evidence/ch05_transforms.py` and `reports/evidence/ch05*` were built from them and the worktree they lived in no longer exists.

Each `SUMMARY.md` says the experiment is never pushed or merged. That was true when it was written; the text is kept as it was.

Here: the summaries, the per-bin results and the code. Not here: `results_by_sku.csv` and `unfit_subset.csv`, which hold per-product values (hard rule 9). They remain only under the tag, on one machine.

One line differs from the tag: `run_experiment.py` used a session-level read-only setting, which the database rule forbids on the pooler, and now uses `SET TRANSACTION READ ONLY`. The experiment was not re-run after that change.

Nothing here feeds the dashboard, the forecast or the plan. Neither experiment produced a real win over the served models.
