# Rollover design: accepted orders, expected receipts, cycle close (2026-10-24)

**Proposal only. Nothing here is built; no migration is written (next free number is 0069).** Facts below were read from the code and the live database (read-only) on 2026-10-24; the rest is recommendation. Unilever only: Del Monte has no per-product plan to roll.

**The hole.** An accepted order feeds nothing: `run_lp` reads stock only from `inventory_fact_real` at the opening count, `decided_q_i` was read by no computation (this is the state before migration 0069, which since lets an accepted order become an expected receipt in the next opening stock), and the PO Qty columns (`inventory_fact.po_qty_cases/po_qty_pieces`, migration 0042) are empty in every recent Unilever count. The next plan learns an order existed only by finding its pieces in the next count. Unilever has no delivery records at all (receipts are derived as closing − opening + sold).

## a. Expected receipts

A new table `expected_receipt`, one row per accepted order line, written inside `decide_row`'s transaction (the only writer of a decision), voided by `/reverse` and by a dismissal. Pieces = `plan_q_i` (accepted quantity, else `q_i`). `expected_on` = decision date + `Product_Dimension.lead_time_days` (3, placeholder `pending_confirmation`).

| Option for "counts as arrived" | Verdict |
|---|---|
| On acceptance | No. Stock that is still on a truck is counted as shelf stock; the next plan under-orders. |
| After the 3-day lead time | No. The 3 days is unconfirmed, and it assumes every order arrives whole and on time. Nothing in the data can check that. |
| On someone confirming it | Not as the rule. No one at SSM records deliveries today; a rule that needs a clerk's click is a rule that silently stays at "in transit". Keep it as an optional override (`state = 'arrived'`, `confirmed_by`). |
| **Only when a stock count dated on or after `expected_on` exists** | **Recommended.** The count is the only evidence of stock and the only one this database has. Until then the row is `expected`; past `expected_on` it is shown `overdue`, never auto-arrived. |

States: `expected`, `overdue` (derived, not stored), `arrived_in_count`, `confirmed`, `cancelled`.

## b. Precedence

A real count overrides any projected stock outright; the count is the truth about what is on the shelf. Receipts are then settled against the count's date `D`:

| Receipt | Treatment |
|---|---|
| `expected_on` ≤ `D` | Inside the count by assumption. Set `arrived_in_count`, `settled_by_count = D`. **Never added again.** If the product's stock did not rise, that is recorded as `not_visible_in_count` (a possible short delivery), not corrected. |
| `expected_on` > `D` (count taken before it arrived) | Still `expected`; added on top of the count. |
| Count dated before the order was accepted | Not affected. |
| The count's own PO Qty, if SSM ever fills it | Cross-check only: compared with the ledger's open pieces, difference reported, not added (DEC-34/37 stands until SSM defines it). |

## c. Opening stock for the next cycle

`opening_i = count_i(latest count ≤ cycle start) + Σ expected_receipt_i (state expected, expected_on > count date)`, floored at 0 and labelled.
When the month's count is **not yet loaded**, a clearly labelled projection: `count_i(M−1) + Σ expected_receipt_i(accepted in M) − sales_i(M)`, where `sales_i(M)` is the real month if loaded, else that month's forecast, flagged `projected_on_forecast`. A projection is never stored as a count and never feeds accuracy.

| Term | Table |
|---|---|
| Count, count date, pack size | `inventory_fact_real` (`snapshot_date`, `_period`), `product_dimension.pack_size`; conversion in `backend/stock_units.py` |
| Expected receipts | new `expected_receipt` |
| Sales / forecast | `unilever_sku_demand_fact_real`, `forecast_result` |
| Decided quantity | `lp_recommendation.decided_q_i` (read by the ledger writer only, through `plan_q_i`) |

`run_lp` reads one new view, `stock_opening_v`, instead of the count directly. This lets an accepted order reach the optimisation through opening stock, on purpose, by decision; the forecast and the safety stock still never read a decision.

**The safety property relaxed, plainly (built 2026-10-24).** Until now `run_lp` refused to plan a cycle with no stock count for the month before it, and used no other month's stock. It now plans on a **projected** opening when that count is not loaded yet (the earlier count + receipts on the way − that month's sales). What that costs: a projection is an estimate, not a measurement, and an order can be sized on stock that is not what the warehouse holds. What keeps it honest: every plan built that way carries `opening_basis = projected` in `lp_run.inputs`, in the run notes, in `GET /recommendations` and `GET /dashboard` (`stock_counts[].opening_basis`, with `count_now_loaded` once the real count arrives, so the plan can be re-run), and on the dashboard card text. What does not change: a later count than the opening month is never used, a count a team ruling sets aside is still refused (never projected over), receipts of a cycle's own orders never change that cycle's plan, and `--require-count` restores the old refusal. Decided quantities reach the opening stock only; the forecast, the safety stock and the LP objective still never read them (`tests/optimization/test_run_lp_projected.py`).

## d. Cycle close

| Step | Exists | To build |
|---|---|---|
| Load the month's sales and count | `run_canonical_load --slice principal:table:YYYY-MM` (idempotent; nothing is edited by hand) | check "both loaded" before going on |
| Settle receipts against the new count | no | `expected_receipt` update (b) |
| ABC, then forecast run | `orchestrate_abc`, `run_baseline_forecast --write` | refuses unless the step before finished |
| Stock roll-forward | no (a count is only ever the next opening) | `stock_opening_v` (c) |
| LP run | `run_lp` (plans from the M−1 count, refuses otherwise) | reads the view |
| Retire the old plan | `current_cycle()` withholds old rows; `--retire-stale-pending` deletes pending | a `closed` state, not deletion: decided rows keep their decision |
| Refresh marts | at the end of the loader and the forecast write | none |
| Record the cycle | no: a cycle is "the newest `planning_cycle_date`" | `planning_cycle` (cycle, state, steps done, run ids, counts) |

One command, `scripts/close_cycle.py`, dry run by default, writing only with `--approved-by NAME --expect-cycle YYYY-MM` (the gate pattern of `clean_dead_skus.py`; M-gates stay human). **Blocker for the real April cycle: March 2026 sales are not loaded** (per-SKU sales end 2026-02), so the April forecast cannot run, whatever is built.

## e. The synthetic test month

Rows flagged `is_demo = true` never pass the `_Real` views, so they cannot exercise the real code path. The test therefore runs in a **scratch schema** (`ssm_rollover_test`, `rehearse_fills --build`), where the code is the production code with `--schema`. Only March sales are generated: the 6 Apr count is real and already loaded. The generator is seeded, written to scratch only, rows tagged `fill_source = 'rollover_test'`.

Proof sequence: accept orders on the March plan, check the ledger rows and that a reversal voids one; project the April opening and check the formula by hand on three products; load the real 6 Apr count and check receipts ≤ `D` settle and later ones stay; run `close_cycle` twice (second run changes nothing); check decided rows survive as `closed`.

Isolation, all checked by the test, not by habit: schema name must start `ssm_` and the script refuses `--target-public`; row counts of ten public tables before and after must be equal; no `rollover_test` string may exist in public or `mart`; the scratch schema is dropped afterwards (rule 16). Known hazard: a scratch build applies pending migrations, and one naming `app.users` runs on live (RUNNING.md); none is pending now, and the test checks that first. **This reads rule 2 as allowing test data in a disposable schema, outside every result; Yuan to confirm.**

## f. Schema, and po_qty_pieces

| Object | Columns |
|---|---|
| `expected_receipt` | `receipt_id`, `recommendation_key`, `product_key`, `sku_code`, `pieces`, `ordered_at`, `expected_on`, `state`, `settled_by_count` (date), `settled_at`, `confirmed_by`, `voided_by_decision` |
| `planning_cycle` | `cycle`, `state` (open/closing/closed), `opening_count_date`, `opening_basis` (count/projected), `forecast_run_id`, `lp_run_id`, `closed_by`, `closed_at` |
| `lp_recommendation` | adds `closed_at` (status stays `accepted`/`dismissed`) |
| `stock_opening_v` | view: the formula in (c), with a `basis` column |

**Same hole, one mechanism.** `po_qty_pieces` is a count-time report by the warehouse of stock on order; `expected_receipt` is our own record of the same quantity. Both mean "ordered, not yet in the count". Define that once (the ledger's open pieces), keep the two sources apart (the count column stays observed data, never written from the ledger) and reconcile them when PO Qty is ever filled. Until SSM defines PO Qty it stays information only.

## g. A past month corrected after accuracy was published (scope only)

`mart.forecast_run_value` is frozen, but `mart.accuracy_mart` reads actuals live, so published accuracy changes silently on the next load, and ABC, bins, the stored forecast, safety stock and the plan built from that month go stale unseen (`planning_stale` knows only the Tier A basis and review flags). A correction must record: `corrected_period`, product, old value, new value, reason, who, when, and the load event it came from (`etl_load_event` exists). It must then mark every dependent output stale and stamp each published figure with the actuals version it used. Not designed here: whether old figures are restated or frozen with a footnote.

## h. A verified stock count and an unmet expected receipt are one signal (scope only)

A staff-reported stock count that an admin has verified (`lp_stock_observation`, reorder-request workflow) and an `expected_receipt` that never showed up in a real count both say the same thing from opposite directions: the stock we believe is on the shelf and the stock we believe is on its way disagree with what was observed. When the rollover goes live, something must reconcile them, because today the ledger settles a receipt only against a loaded count (section b) and the reorder-request design deliberately keeps verified reports out of anything the plan reads. Not designed here: which source wins, whether a verified report may settle or flag a receipt, or whether `not_visible_in_count` is raised from either side.
