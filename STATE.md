# STATE (current state only; reference lives in CLAUDE.md / ARCHITECTURE.md). Last verified 2026-11-02.
# Keep the `plan:` line exact: tests/invariants/test_a_plan_agreement.py fails if it disagrees with live.

plan: rows=109 pieces=435988 cycle=2026-03-01 lp_run=6
  (Unilever, t12m_new Tier A as of 2026-02; 73 rows order >0; total = sum of plan_q_i. Nothing decided yet except legacy row 4.)

Main-BE: read the tip from `git log newrepo/Main-BE` (this line would lag by one commit). check.sh --full GREEN on the tree of the last governance-audit commit (2026-11-02): 2277 passed, 18 skipped, 0 failed of 2295.
Main-FE merge (2026-11-02): newrepo/Main-FE 1590a97 and d80f405 merged into Main-BE, pushed to Main-BE by Kelvin's instruction; check.sh --fast GREEN and the whole pytest suite passed (2166, 27 skipped: no data/raw client files, no local policy csv, opt-ins). lp.decide stays admin-only; quantity-change reason required (8+ chars).
Governance (2026-11-02): docs/DATA_GOVERNANCE.md; roles named (team's own assignment; data owner Sir Abe has not acknowledged), retention and notice written, G2/G3/G5/G6/G7/G8 done, G4 open (backup list attached, nothing deleted), G13 handover open. G8 startup checks are on Main-BE (not deployed). G7 first review run 2026-11-02 (5 accounts, all admin, 2 to confirm, none removed); G12 answered (personal names present, 0 phone or email values in the customer, outlet, invoice and salesman fields of public or the raw files; 2,436 raw cells with a street-style word not read one by one; minimisation open); G4 table corrected (74 folders: 7 keep, 58 delete, 9 not governed, 653.81 MB; nothing deleted). Test totals pinned from the merged --full run: 2295 collected, 2277 passed, 18 skipped. Decisions never reach the forecast or safety stock; an accepted order becomes an expected receipt in the next opening stock (live holds none).
Chapter 4 code figures (2026-11-02): docs/CHAPTER4_CODE_FIGURES.json pins route count and sign-in split, @cached GET routes, opt-in list size and the pytest totals, each with its command; scripts/check.sh fails on drift (python -m scripts.chapter_figures --write re-pins). Frozen rows behind the 51 pinned figures are tracked in docs/published_snapshot_2026-10-24/ (trimmed columns), so a clean clone runs the pinned-figure check. TC82 (rollover scratch test) passes 61 of 61 after app.users was named in five queries.
  Latest 4: D3 per-SKU cover in pieces, D2/BE-2 Del Monte class changes, D1 audit-log session cap, D4 range-card cache.
  Then (2026-10-28): lp.view gate on error-decomposition + /inventory/current + the /dashboard demonstration plan; lp.decide implies lp.view (permissions.IMPLIES).
Next free migration: 0073. 0070 (dismissal requests + stock observations), 0071 (notification bell) and 0072 (audit_log append-only triggers) are APPLIED to public 2026-11-02 by Kelvin's go-ahead (additive: 0 rows written, audit_log 120 rows unchanged, lp_recommendation 289 unchanged; UPDATE/DELETE/TRUNCATE on app.audit_log confirmed refused). The files are on Main-BE (pushed 2026-11-02). Main-BE's own STATE.md still says 0070 is free: update it when this branch is merged.

Pinned (published) figures: docs/PUBLISHED_FIGURES_SNAPSHOT_2026-10-24.json, frozen rows in
  docs/published_snapshot_2026-10-24/ (tracked, trimmed to the columns the check reads). Headline: MASE < 1 for 109 of 175; Tier A exceeds safety stock 749 months.
  Verify: python -m scripts.snapshot_published_figures --verify   (or scripts/check.sh --fast, which runs it)
  Loading March 2026 sales moves the live marts, never the pinned figures.

Weeks of cover: ONE basis, pieces over pieces (Dashboard 7.06, 2026-02 count, 12 months to 2026-02); the pesos basis gives 6.21. Del Monte has no pieces, so its card stays pesos.

Open defects (2026-11-02): KNOWN_ISSUES.md: 7 left (A7 C1 M1 M2 M3 M5 P3). T1 fixed, M4 closed 2026-11-02. A13 Q15 P5b closed 2026-10-31 (committed in a29d683): dismiss reason 8-500 characters; close_cycle refuses an incomplete plan for the cycle being closed (the next cycle is only reported) (LP rows = ok forecasts with MASE < 1; 109 = 109 for 2026-03); row 4 labelled outside_plan in cycle=all. Every run_lp / close_cycle refusal now exits non-zero (2; errors 1). Eight SSM items are closed with a written limitation (L1-L8). run_lp refuses an already-planned cycle (--replan) and both runners refuse a stale ABC period (--allow-stale-abc), exit 2. check.sh --full allows only the 18 tests in scripts/known_opt_in_skips.txt to skip.
Checks: scripts/check.sh --fast (constant) / --full (everything). Skipped is a failure. Open defects: KNOWN_ISSUES.md.
Throwaway local Postgres for destructive QA (never live): scripts/local_pg.py, restored 2026-11-02 from backups/full_backup_20261102T114428Z (109 rows, 435,988 pieces); 2026-10-30 results in reports/QA_PIPELINE_2026-10-30.md used the older 16 Oct backup.

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
  Data Management page (local only): python -m scripts.local_app signs in without a password on the throwaway database and shows the batch
  (backend/routers/monthly_batch.py, mounted only when MONTHLY_BATCH_ENABLED and 127.0.0.1:55432, so the deployed API stays at the pinned 84 routes). Deployed login unchanged.
  Generated sales are is_demo = true and only in the local ssm_practice copy (no page reads it). The forecast refuses them, so a practice month stops: KNOWN_ISSUES M5, decision open.
Forecast run (2026-10-30): writes its own cycle only; it no longer deletes other cycles' rows (own-cycle strays are flagged in model_params.retired). Tasks 2-5 of the rollover-hardening prompt: unresolved; neither the prompt nor that session report can be found (Kelvin, 2026-11-02), so what they covered is unknown.

Decided by the team, 2026-11-02 (the proponents; no external confirmation; entries in ARCHITECTURE.md):
  DEC-41 calendar factor (shrink 0.5, 3 prior months; live on all 175 ok rows; Sir Catubag has not signed it off, so the flag stays False)
  DEC-42 Tier A basis t12m_new (rule in DEC-38; 189 products as of 2026-02)
  DEC-43 Del Monte taxonomy: pre-2025 and post-2025 kept separate, no mapping
  DEC-44 the four optimisation inputs adopted as stated assumptions (NOT confirmed by SSM, see below)
  DEC-45 scripts/clean_dead_skus.py stays gated, not run before the defence

Blocked (nothing below is ours to decide):
  Technical Adviser (Sir Catubag): DEC-40 Dashboard basis; safety stock from monthly sigma.
  SSM: the four cost inputs are still UNCONFIRMED by SSM (procurement, storage, warehouse capacity, supplier ceilings; DEC-44
    adopts them as assumptions, it does not confirm them); meaning of PO Qty;
    the 2 Mar count (about twice its neighbours); Ilocos Sur stock vs La Union sales; whether zero-sale months are omitted.
    SSM is not reachable; do not wait on it (team, 2026-11-02). Each open question is a written limitation, KNOWN_ISSUES.md L1-L8.
    New sales files remain the one thing no workaround replaces on live.
  Yuan: lifting the hold on prescriptive claims; approving any dead-SKU disable (837 would go; nobody approved; DEC-45).
