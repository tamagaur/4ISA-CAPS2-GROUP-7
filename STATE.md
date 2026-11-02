# STATE (current state only; reference lives in CLAUDE.md / ARCHITECTURE.md). Last verified 2026-11-02.
# Keep the `plan:` line exact: tests/invariants/test_a_plan_agreement.py fails if it disagrees with live.

plan: rows=109 pieces=435988 cycle=2026-03-01 lp_run=6
  (Unilever, t12m_new Tier A as of 2026-02; 73 rows order >0; total = sum of plan_q_i. Nothing decided yet except legacy row 4.)

Main-BE: a29d683 on newrepo (pushed 2026-10-31, ls-remote verified; it was 90da3d6 before; this line itself lags by one STATE commit). Read the tip from `git log newrepo/Main-BE`.
  Latest 4: D3 per-SKU cover in pieces, D2/BE-2 Del Monte class changes, D1 audit-log session cap, D4 range-card cache.
  Then (2026-10-28): lp.view gate on error-decomposition + /inventory/current + the /dashboard demonstration plan; lp.decide implies lp.view (permissions.IMPLIES).
Next free migration: 0070 (0069 rollover ledger is applied to public; 0068 before it).

Pinned (published) figures: docs/PUBLISHED_FIGURES_SNAPSHOT_2026-10-24.json, frozen rows in
  local/published_snapshot_2026-10-24/ (git-ignored). Headline: MASE < 1 for 109 of 175; Tier A exceeds safety stock 749 months.
  Verify: python -m scripts.snapshot_published_figures --verify   (or scripts/check.sh --fast, which runs it)
  Loading March 2026 sales moves the live marts, never the pinned figures.

Weeks of cover: ONE basis, pieces over pieces (Dashboard 7.06, 2026-02 count, 12 months to 2026-02); the pesos basis gives 6.21. Del Monte has no pieces, so its card stays pesos.

Open defects (2026-11-02): KNOWN_ISSUES.md: 4 left (A7 C1 M1 P3). T1 fixed 2026-11-02. A13 Q15 P5b closed 2026-10-31 (committed in a29d683): dismiss reason 8-500 characters; close_cycle refuses an incomplete plan for the cycle being closed (the next cycle is only reported) (LP rows = ok forecasts with MASE < 1; 109 = 109 for 2026-03); row 4 labelled outside_plan in cycle=all. Every run_lp / close_cycle refusal now exits non-zero (2; errors 1). Eight SSM items are closed with a written limitation (L1-L8). run_lp refuses an already-planned cycle (--replan) and both runners refuse a stale ABC period (--allow-stale-abc), exit 2. check.sh --full allows only the 18 tests in scripts/known_opt_in_skips.txt to skip.
Checks: scripts/check.sh --fast (constant) / --full (everything). Skipped is a failure. Open defects: KNOWN_ISSUES.md.
Throwaway local Postgres for destructive QA (never live): scripts/local_pg.py; 2026-10-30 results in reports/QA_PIPELINE_2026-10-30.md (local copy of the 16 Oct backup, so its plan is not the live plan).

Manuscript figures (2026-10-31): python -m scripts.manuscript_figures (read-only; needs requirements-figures.txt) writes
  17 Chapter 4 figures to reports/figures/, the number map and captions to reports/figures/FIGURES.md, and Tables 4.2.19,
  4.2.20, 4.2.4 to docs/MANUSCRIPT_TABLE_DATA_2026-10-30.md. It exits 2 while a figure is HELD: figure l (block results)
  is held because cells_all.csv gives XGBoost+MA3 (long) 0/2/0 where the manuscript and DEC-26 say 0 wins/4 ties/1 loss.
Test plan + worked calculations (2026-10-31, NOT committed): docs/TEST_PLAN.md (test items, features, criteria T1-T83, results
  in two rounds, coverage) and docs/MANUSCRIPT_WORKED_CALCULATIONS.md (SKU 62687212 traced to plan_q_i 9,744; SKU 69668149
  ordered 0; urgency subtotals 118,644 + 67,276 + 250,068 = 435,988). The worked-calculations file holds per-product sales
  (hard rule 9): commit it only if the manuscript publishes 62687212. Coverage (coverage.py 7.16.2, local .venv only):
  51.9% statements / 44.4% branches over the 216 imported files; backend 93.6% / 87.0%.
Tracked reports (2026-10-30): scripts that write a committed reports/ or docs/ file go through scripts/report_target.report_path; a run against the local Postgres writes local/nonlive_reports/ instead (git-ignored).
Monthly batch (2026-11-02, branch kelvin/monthly-batch, not pushed): python -m scripts.run_month (dry run by default; load, ABC, forecast, LP,
  marts, review, then a separate --close) and python -m scripts.cycle_feedback (read-only). Rehearsed on the local Postgres only, with generated
  March sales: reports/MONTHLY_BATCH_REHEARSAL_2026-11-02.md. Never run on live; the real load step has not run as a write. Live plan unchanged.
Forecast run (2026-10-30): writes its own cycle only; it no longer deletes other cycles' rows (own-cycle strays are flagged in model_params.retired). Tasks 2-5 of the rollover-hardening prompt: unresolved; neither the prompt nor that session report can be found (Kelvin, 2026-11-02), so what they covered is unknown.

Blocked (nothing below is ours to decide):
  Technical Adviser (Sir Catubag): DEC-38 Tier A basis t12m_new + DEC-40 Dashboard basis; calendar factor (live on all 175
    ok rows); safety stock from monthly sigma; Del Monte DEC-03 category vocabulary.
  SSM: not reachable; do not wait on it (team, 2026-11-02). Each open question is a written limitation, KNOWN_ISSUES.md L1-L8.
    New sales files remain the one thing no workaround replaces on live.
  Yuan: lifting the hold on prescriptive claims; approving any dead-SKU disable (837 would go; nobody approved).
