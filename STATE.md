# STATE (current state only; reference lives in CLAUDE.md / ARCHITECTURE.md). Last verified 2026-10-28.
# Keep the `plan:` line exact: tests/invariants/test_a_plan_agreement.py fails if it disagrees with live.

plan: rows=109 pieces=435988 cycle=2026-03-01 lp_run=6
  (Unilever, t12m_new Tier A as of 2026-02; 73 rows order >0; total = sum of plan_q_i. Nothing decided yet except legacy row 4.)

Main-BE: a40c7df on newrepo (pushed and verified with ls-remote 2026-10-30; it was a672532 before). Read the tip from `git log newrepo/Main-BE`.
  Latest 4: D3 per-SKU cover in pieces, D2/BE-2 Del Monte class changes, D1 audit-log session cap, D4 range-card cache.
  Then (2026-10-28): lp.view gate on error-decomposition + /inventory/current + the /dashboard demonstration plan; lp.decide implies lp.view (permissions.IMPLIES).
Next free migration: 0070 (0069 rollover ledger is applied to public; 0068 before it).

Pinned (published) figures: docs/PUBLISHED_FIGURES_SNAPSHOT_2026-10-24.json, frozen rows in
  local/published_snapshot_2026-10-24/ (git-ignored). Headline: MASE < 1 for 109 of 175; Tier A exceeds safety stock 749 months.
  Verify: python -m scripts.snapshot_published_figures --verify   (or scripts/check.sh --fast, which runs it)
  Loading March 2026 sales moves the live marts, never the pinned figures.

Weeks of cover: ONE basis, pieces over pieces (Dashboard 7.06, 2026-02 count, 12 months to 2026-02); the pesos basis gives 6.21. Del Monte has no pieces, so its card stays pesos.

Open defects (2026-10-30): KNOWN_ISSUES.md was rewritten: 17 open at the start, 8 left the list (5 fixed, 2 already fixed, 1 not a defect), 9 left with an owner, 1 new row (P5b). Four SSM items are closed with a written limitation (L1-L4).
Checks: scripts/check.sh --fast (constant) / --full (everything). Skipped is a failure. Open defects: KNOWN_ISSUES.md.
Throwaway local Postgres for destructive QA (never live): scripts/local_pg.py; 2026-10-30 results in reports/QA_PIPELINE_2026-10-30.md (local copy of the 16 Oct backup, so its plan is not the live plan).

Tracked reports (2026-10-30): scripts that write a committed reports/ or docs/ file go through scripts/report_target.report_path; a run against the local Postgres writes local/nonlive_reports/ instead (git-ignored).
Forecast run (2026-10-30): writes its own cycle only; it no longer deletes other cycles' rows (own-cycle strays are flagged in model_params.retired). Tasks 2-5 of the rollover-hardening prompt are NOT done: stopped at a gate, see the session report.

Blocked (nothing below is ours to decide):
  Technical Adviser (Sir Catubag): DEC-38 Tier A basis t12m_new + DEC-40 Dashboard basis; calendar factor (live on all 175
    ok rows); safety stock from monthly sigma; Del Monte DEC-03 category vocabulary.
  SSM: cost params (procurement, storage, warehouse capacity, supplier ceilings are placeholders); meaning of PO Qty;
    the 2 Mar count (about twice its neighbours); Ilocos Sur stock vs La Union sales; whether zero-sale months are omitted.
  Yuan: lifting the hold on prescriptive claims; approving any dead-SKU disable (837 would go; nobody approved).
