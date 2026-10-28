# Known issues (carried over 2026-10-28; nothing here was fixed by that carry-over)

Source: findings 5-13 of `reports/AUDIT_2026-10-23.md` (A#) and 8-15 of `reports/QA_BACKEND_2026-10-24.md` (Q#),
minus what is already fixed. Status is `open` or `won't-fix (reason)`; nothing has been ruled won't-fix yet.
"Re-checked" means reproduced against the live app on 2026-10-28; otherwise the status comes from the commit log.

## Open

| ID | Severity | What it is | Status |
|---|---|---|---|
| A6 | Medium | `/dashboard/error-decomposition` (and its three siblings) default to `tier=all`; B and C are COUNTERFACTUAL backtests never served, so the headline mixes them in. Now labelled (`counterfactual_note`, `by_tier`), default unchanged; two concentration answers (pieces vs pesos) still coexist. | open (re-checked: default still `all`) |
| A7 | Medium | With `DM_DEMO_ENABLED` on and `X-Data-Mode: preview`, a real Unilever SKU's forecast response marks its real months `demonstration: true` and swaps in the demo MA3 forecast. | open (no commit has touched the forecast route; not re-reproduced, needs the flag) |
| Q8 | Medium-Low | A user with `lp.decide` but not `lp.view` can decide, and the response returns the whole LP row. Needs a ruling: `lp.decide` implies `lp.view`, or the write responses drop the figures. | open (a decision, not a code defect) |
| A11 | Low | Preview mode with no preview files describes real LP rows as default parameters (`lp_model.run` None, `inputs_source: defaults`). | open (re-checked) |
| A12 | Low | "109 pending" counts 36 rows that plan a zero order; only 73 are orders and no field says so. | open (re-checked: no orders-only count in the payload) |
| A13 | Low | Legacy accepted row 4 (no `lp_run_key`) is in the cycle table (110 rows) but outside the plan (109); `cycle=all` shows it. | open (re-checked 110 vs 109). Reversal can no longer put it back into the plan (7bc7e19) |
| Q15 | Low | Dismiss accepts a 1-character reason; only blank and over-500 are refused. Needs a ruling on a minimum. | open (a decision) |

## Closed since the reports (kept so the numbering stays traceable)

| ID | Fixed in | Note |
|---|---|---|
| A5 | 7ff277d | No summed revenue share across two principals on `/abc` |
| A8 | 7ff277d | Generated category-trend months are labelled |
| A9 | 7ff277d | A quantity change on a superseded cycle is closed, not left pending |
| A10 | 7ff277d | An approval later reversed says so |
| Q9-Q14 | fb11477 | Inverted range 422; SKU text bounded; audit-log limit; grant audit only on change; typed dates; strict types (`tests/backend/test_qa_findings_8_15.py`) |
