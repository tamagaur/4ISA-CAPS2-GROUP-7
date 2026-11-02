# Known issues (rewritten 2026-10-30 from the 2026-10-28 carry-over plus `reports/QA_PIPELINE_2026-10-30.md`)

Sources: findings 5-13 of `reports/AUDIT_2026-10-23.md` (A#), 8-15 of `reports/QA_BACKEND_2026-10-24.md` (Q#), 1-10 of
`reports/QA_PIPELINE_2026-10-30.md` (P#), and C1 (found 2026-10-28). Every row is one of:
**fixed**, **not a defect**, **needs Kelvin's decision**, **needs a client answer**, **needs a migration**, **won't-fix (reason)**,
**closed with limitation**. Nothing leaves this file without one of those and a reason.

**Tally.** Open at the start of 2026-10-30: 17 (7 carried in this file; 10 in `QA_PIPELINE_2026-10-30.md`, not yet in it).
First session that day: 8 left the list (5 fixed: A11 P5-forecast-half P7 P8 P10; 2 already fixed: P4 P9; 1 not a defect: P6); one row
added (P5b). Second session that day: 4 more fixed (A6 A12 P1 P2). **On 2026-10-30 12 of the 17 closed; on 2026-10-31 A13, Q15 and P5b closed too, so the table holds 3 (A7 C1 P3). On 2026-10-31 a full-suite run added T1 (a guard test failing at 4a80d41): 4 open. On 2026-11-02 T1 was fixed and M1 added: 4 open (A7 C1 M1 P3).** Each has an owner: a migration (C1 P3), won't-fix with a reason (A7), a decision (M1).
Eight client items are closed with a written limitation (L1-L8); they were not rows before.

## Open

| ID | Sev | What it is | Why it is not fixed | Owner |
|---|---|---|---|---|
| A7 | Med | With `DM_DEMO_ENABLED` on and `X-Data-Mode: preview`, a real Unilever SKU's forecast marks its `real_copy` months `demonstration: true` and shows the demo MA3 forecast. | It is the sanctioned demonstration path as built: CLAUDE.md rule 2 (Kelvin, 2026-10-15/16) wires the Unilever demo forecast into `GET /forecast/{sku}` behind the flag AND the preview header, labelled at top level and per row, with `origin: real_copy` telling real from generated. Nothing reaches a `_Real` view or the real forecast. | **won't-fix (by recorded decision, rule 2)**; reopen if you read the rule differently |
| C1 | Low | `/recommendations` on the mart path runs three statements per cycle, not two: the mart has pesos only and weeks of cover is in pieces (D3), so `_attach_avg_pieces` reads `quantity_sold` live. | The fix adds a column to `mart.planning_mart`: a migration on planning data. Out of scope, as the brief says. | **needs a migration** (next free 0070) |
| M1 | Low | Once a month after 2026-02 is loaded, `scripts/accuracy_as_served.py` stops at its check that the latest sales month equals the window end (`scripts/backtest_forecast_run.WINDOW`, hand-set to 2026-02). | It stops rather than give a wrong figure, and moving the window moves quoted figures, so that should be done on purpose. The batch does not call it; `scripts/cycle_feedback.py` scores the new month. Not reachable until a new month loads. | **needs Kelvin's decision** when a real month arrives |
| P3 | Med-Low | After a second ABC re-run, cached `GET /abc` keeps the old classes: the cache's data version (`mart.refresh_status`) does not carry `abc_classification.computed_at`. | Adding `MAX(computed_at)` to the per-request version query costs about 23 ms a read on 75,430 rows (measured on the local copy) because no index covers it; the cheap fix is an index or a view change, i.e. a migration. Bites only on an ABC run on its own. | **needs a migration** |

## Surfaced for decision (item 3 of the brief): effect on the published figures

Live, read-only (transaction-scoped READ ONLY, pooler :6543), cycle 2026-03-01, 2026-10-30:
plan = 109 rows, 435,988.00 pieces; of them 73 have q_i > 0 (sum 435,988.00) and 36 have q_i = 0; row 4 is `accepted`,
1,331.24 pieces, `lp_run_key` NULL, decided 2026-08-24 by a team account, outside the plan.

| | Change | Moves | Does not move |
|---|---|---|---|
| **A12** | Report orders only: add an `order_count` (73) beside the 109. Additive. | Nothing, if the 109 stays the plan's row count. If the plan itself is redefined as the 73, the `plan:` line in STATE.md, `tests/invariants/test_a_plan_agreement.py`, and every "109 rows" sentence (the CH4-5 edits already say "109 rows, 73 ordering") change from 109 to 73. | The 435,988 pieces (the 36 zero rows add 0). Tier A 189, MASE 109 of 175 (a different 109). |
| **A13** | Bring row 4 into the plan. | 109 becomes 110 rows and 435,988 becomes 437,319.24 pieces (a non-integer, since it predates case-pack rounding). That breaks the plan invariant and is a gate stop. | |
| **A13** | Leave it out of `cycle=all` (hide or delete the row). | The cycle table reads 109 and nothing in the plan changes; the accepted decision's audit trail is the cost. | |

A12 was then done as the additive field only (second session; see Closed). A13 was then done as the label (2026-10-31, see Closed on 2026-10-31): row 4 stays out of the plan.

## Closed on 2026-11-02

| ID | How | Evidence |
|---|---|---|
| T1 | **fixed**: `scripts/manuscript_figures.py` exempted from the guard test, because it reads the field from the API response to draw a figure and feeds nothing back. | `tests/backend/test_recommendation_decisions.py` |

## Closed on 2026-10-31 (Kelvin's decisions, implemented; not committed)

| ID | How | Evidence |
|---|---|---|
| Q15 | Dismiss reason is 8 to 500 characters after trimming, server-side (`DISMISS_REASON_MIN/MAX`, `backend/schemas/recommendations.py`); matches section 4.2.3.3. | `tests/backend/test_recommendation_decisions.py` (7, 8, 500, 501 and whitespace-padded cases) |
| P5b | A complete plan = one run-keyed LP row for every forecast row of the cycle with status ok and MASE below 1. `close_cycle` refuses when the counts differ and names both; checked for the cycle being closed only; the next cycle is a reported forward-look line, never a refusal. Live, read-only: 2026-03 = 109 against 109. | `tests/test_close_cycle.py`; `scripts/close_cycle.py` `PLAN_COUNTS_SQL` |
| A13 | Row 4 in `cycle=all` carries `outside_plan: true` and `plan_note` ("Accepted recommendation outside the current plan ..."). Plan clauses untouched: 109 and 435,988 do not move. | `tests/backend/test_recommendations.py` |
| Exit codes | `run_lp` now exits with `main()`'s return (it dropped it before); refusals exit 2, errors 1. `close_cycle` exits 2 on any refusal, dry run included. | `tests/optimization/test_run_lp_script.py`, `tests/test_close_cycle.py` |

## Closed on 2026-10-30

| ID | How | Evidence |
|---|---|---|
| A11 | **fixed** | `stored_run` returned None for every non-real mode; it now returns None only when the rows come from preview files (`predictive_preview`). Preview with no files names the real run. `tests/backend/test_recommendation_decisions.py::test_preview_without_preview_files_still_names_the_real_run`. |
| P5 (forecast half) | **fixed** | `close_cycle` `forecast_next` now requires a forecast row at the next cycle for every Tier A product of the cycle's ABC run. On the local database: all present passes; deleting one of 191 rows makes it fail. `tests/test_close_cycle.py`. |
| P7 | **fixed** | `GET /category-trends?principal=delmonte` sends `revenue: null` on `category_absent` points (was 0.0). The projection still reads the zero; `revenue_last_12` is unchanged. `tests/backend/test_category_trends.py`. |
| P8 | **fixed** | `permissions.normalize` drops a removal an implied grant undoes (`lp.view:false` beside `lp.decide:true` stores `{lp.decide: true}`), on read and on write. `tests/backend/test_permissions.py`. |
| P10 | **fixed** | `kpis.weeks_of_cover` adds `stock_value_unit: "pesos"` and `stock_pieces` (the numerator of the pieces ratio). 7.06 unchanged. `tests/backend/test_dashboard.py`. |
| A12 | **fixed** (second session) | `GET /recommendations` adds `order_count`: items whose planned order is above zero (73 of 109 in cycle 2026-03). Additive; `count`, the 109 rows and the 435,988 pieces are untouched. The dashboard's pending count is a different number and was not touched. `tests/backend/test_recommendation_decisions.py`. |
| A6 | **fixed** (second session), default kept | Every decomposition response now carries `figures_basis`: `window`, `tier_filter` and what it applies to, `served_tiers` (A), `counterfactual_tiers` (B, C) and `counterfactual_rows_included`. The default `tier=all` is unchanged on purpose. (`basis` was already a field on the concentration response and is left alone.) The two Del Monte "not available" bodies carry no figures and no basis. `tests/backend/test_error_decomposition_views.py`. |
| P1 | **fixed** (second session) | `run_lp.py` refuses a real run on a cycle that already has rows from a run (`lp_run_key` set), exit 2; `--replan` overrides; a dry run only warns. Shown on the local database: first run rc 0, second rc 2, `--replan` rc 0. `scripts/run_guards.py`, `tests/test_run_guards.py`. |
| P2 | **fixed** (second session) | `run_baseline_forecast.py` and `run_lp.py` refuse (exit 2, every mode) when the ABC period is older than the latest real sales month; `--allow-stale-abc` overrides. Shown locally with the March ABC rows removed: both rc 2, both rc 0 with the flag, rows restored. |
| P4 | **already fixed** | 9ab29f9: the forecast run writes its own cycle only; no DELETE of other cycles remains in `run_baseline_forecast.py`. |
| P9 | **already fixed** | 0dab236: `scripts/report_target.report_path`; a local-database run writes under `local/nonlive_reports/`, tree clean after a run (shown 2026-10-30). |
| P6 | **not a defect** | The cold cache was the QA harness: `TestClient(app)` is not entered as a context manager, so the lifespan never ran. In the server, `check_db_connection()` at startup calls `marts.present()`; shown on the local copy: `present_known()` False before it, True after. |
| (test) | fixed | `test_only_the_displayed_plan_total_reads_the_decided_quantity` failed on a clean checkout because it scanned the QA harness (`scripts/local_api_qa_matrix.py`, which reads the API's `plan_q_i`); the harness files are now skipped. |

## Closed since the earlier reports (kept so the numbering stays traceable)

| ID | Fixed in | Note |
|---|---|---|
| A5 | 7ff277d | No summed revenue share across two principals on `/abc` |
| A8 | 7ff277d | Generated category-trend months are labelled |
| A9 | 7ff277d | A quantity change on a superseded cycle is closed, not left pending |
| A10 | 7ff277d | An approval later reversed says so |
| Q8 | a7b707d | `lp.decide` implies `lp.view` |
| Q9-Q14 | fb11477 | Inverted range 422; SKU text bounded; audit-log limit; grant audit only on change; typed dates; strict types |

## Closed with limitation (the answers are not coming; written 2026-10-30)

Each is stated as a limitation of the work, not as pending work. Manuscript locations are those the repository can show; the
manuscript text itself is not in git, so where no location is on record it says so and names the proposed home.

| ID | Limitation | In the system | Manuscript states it |
|---|---|---|---|
| L1 | `po_qty_pieces` has no definition from SSM and is unusable: the column totals 1-3 million pieces a month (1,644,300 on the 2 Mar 2026 count against a March plan of 325,468 and about 1.69M on hand), too large to be stock on the way. It is stored as the file has it, shown as information, and never added to stock or subtracted from an order. Stock in transit is covered by `expected_receipt`, the team's own ledger of accepted orders (migration 0069). | ARCHITECTURE.md DEC-34 and DEC-37; `docs/ROLLOVER_DESIGN.md` §f | **No location on record.** Proposed: §4.4.4 Limitations and Deviations (p.60), where `docs/CH4-5_EDITS_2026-10-22_corrected.md` item 23 collects the other SSM-unconfirmed inputs. |
| L2 | There is no promotion calendar. Stockout exposure (months where the forecast fell short of actual sales) can be measured; whether a promotion, a price change or a supply failure caused a miss cannot be said. | the error decomposition and forecast-error cards state a size, never a cause | **No location on record.** Proposed: §4.4.4. |
| L3 | There are no Unilever delivery records. Stock on hand cannot be reconciled against movement (opening + deliveries - sales = closing), so a count that looks wrong (the 2 Mar count, about twice its neighbours) can be flagged but not corrected. The only stock evidence is the monthly count. | `expected_receipt` settles against the next count, not against a delivery document; DEC-34 | **No location on record.** Proposed: §4.4.4. |
| L4 | Prices (procurement cost per piece, from the stock file; the 33.48 median default is applied to no product this cycle), storage cost (0.50), warehouse capacity (3,816,842, the most stock held in one count) and supplier ceilings (103% of last year's sales) are set from SSM's stock file and recorded stock levels, not confirmed by SSM. **The review and lead days (`review_days` 5, `lead_days` 3: weekly orders delivered 2-3 days later) were stated by SSM (Sir Abe) at the 2026-09-28 meeting, not confirmed in writing.** (Date as given by Kelvin 2026-10-30; `analytics/params.py:267` names Sir Abe without a date and lines 221 and 257 date the meeting 2026-09-29: unresolved which.) | `analytics/params.py` `PLACEHOLDERS` (lines 262-284) | **Cost inputs: Table 4.2.23 "Cost inputs" row and §4.4.4 "Four LP inputs ... SSM has not confirmed them", and §5.2.3** (`docs/CH4-5_EDITS_2026-10-22_corrected.md`, items near lines 172-174, 216, 269, 305; also §4.1.3 as referenced there). **Review and lead days: no location on record.** |
| L5 | New monthly files may not arrive: per-SKU sales end 2026-02. The live plan stays at cycle 2026-03 until a real month exists. The monthly loop has only been shown on generated sales, on the local database. | `scripts/run_month.py` refuses a month with no sales; `reports/MONTHLY_BATCH_REHEARSAL_2026-11-02.md` | **No location on record.** Proposed: §4.4.4. |
| L6 | Stock counts come from Ilocos Sur and per-SKU sales from La Union (UNVERIFIED). They are treated as one stock position; this is an assumption, not something the data shows. | Plans compare the two directly | **No location on record.** Proposed: §4.4.4. |
| L7 | Whether SSM's sales listing omits zero-sale months cannot be confirmed. A Unilever month with no row is treated as zero sales, on the evidence in `CLAUDE.md` ("Why data is missing"). | `backend/series_gaps.py`, `scripts/cycle_feedback.py` | **No location on record.** Proposed: §4.4.4. |
| L8 | Monthly stock counts swing widely (1.69M to 3.80M pieces in the last seven) and plan size moves with them. A count cannot be checked with SSM, so it is accepted as recorded. | `scripts/run_month.py` prints each count against the median of the six before it for the person approving; it corrects nothing and sets no threshold | **No location on record.** Proposed: §4.4.4. |
