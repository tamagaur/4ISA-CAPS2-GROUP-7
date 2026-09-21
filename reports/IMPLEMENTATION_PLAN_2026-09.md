# Implementation plan — remaining work, ordered by importance

**Written 2026-09-19.** Diagnosis only; no code or data was changed to produce
this. Code-level findings are from the live working tree. Data-state findings
are quoted from `PROJECT_STATE_2026-09.md` (dated 2026-09-16) and were **not**
re-verified against the database — campus WiFi (`CICS-Staff`) blocks Postgres
ports 5432/6543, so no live query was possible. Re-confirm §Phase 0.4 before
relying on any row count here.

**Ordering principle:** claim-critical before feature-complete. Anything that
makes the project's central claim *sayable* outranks anything that adds another
chart.

**Blocker legend**

| Mark | Meaning |
|---|---|
| 🟢 | No blockers — doable on campus WiFi right now |
| 🌐 | Needs a non-campus network (database access) |
| 👥 | Needs Yuan, the client, or a group decision |

---

## Phase 0 — Credibility fixes

**~2 hours · 🟢 · do today**

All writing, no engineering, zero risk. These are the cheapest wins available
and they fix the three things a reviewer meets first.

| # | Task | Why it matters |
|---|---|---|
| 0.1 | Fix `README.md`'s pipeline status. It currently reads "🔴 Not started — Supabase (no live database exists yet; nothing has been loaded into it)" while the database holds 17,406 products, 24,906 demand rows and 38 ABC periods. | First file anyone opens. It contradicts the working system. |
| 0.2 | Fill or delete `ROADMAP.md` — currently a single empty heading (`## Feature Proposals`). | An empty roadmap reads as an abandoned project. |
| 0.3 | Write the **Del Monte scope statement**: one paragraph stating Del Monte is master-data-only this phase, and why (invoice-grain sales data with no SKU column — DEC-03). | Converts an apparent oversight into a documented decision. Large difference in a panel. |
| 0.4 | Re-verify and re-date `PROJECT_STATE_2026-09.md` §11, which concludes "**cutover has NOT completed**". That contradicts the live database. | Your own source of truth currently disagrees with reality. |

**Exit test:** a stranger reading `README.md` and `PROJECT_STATE_2026-09.md`
comes away with an accurate picture of what works.

---

## Phase 1 — Make the northstar claim sayable

**~1 day · 🟢 mostly**

This is the highest-value item in the plan.

`README.md` states the thesis: replace SSM's blanket three-week safety-stock
rule with per-SKU recommendations. `reports/API_CONTRACTS.md:142` names the
payoff — **PR4, "the north-star payoff"** — specified to return
`working_capital`, `capital_freed` and `est_stockout_rate` **in pesos**.

What exists (`backend/routers/dashboard.py:1099`) is a `policy_comparison`
block inside `GET /dashboard` comparing LP safety stock against the 3-week rule
**in units (pieces)**, deliberately not converted to money. There is no
`/policy-comparison` endpoint, no `Policy_Comparison` table, and no
`capital_freed` figure.

**The sentence the project exists to produce — "this frees ₱X million in
working capital" — is currently not computable.**

| # | Task | Notes |
|---|---|---|
| 1.1 | Reframe the comparison as **units + percent**: "the LP policy holds N% less safety stock than the blanket 3-week rule across M comparable SKUs". | Achievable with data already in hand. Do not wait for pesos. |
| 1.2 | Surface `sku_count` and the percentage prominently in `PolicyComparisonWidget`. | Must be readable at a glance during a live demo. |
| 1.3 | Write the assumption note: both sides in pieces; pesos unavailable because `unit_cost_per_case` is per *case* and `pack_size` is unreliable. | Pre-empts the obvious follow-up question. |
| 1.4 | *(optional)* Promote to a real `GET /policy-comparison` per API_CONTRACTS PR4. | Only if time allows; the dashboard block already works. |

**Do not attempt peso conversion.** It requires a cost-per-piece the data does
not contain. Fabricating one would undermine the honest-null discipline that is
currently one of the system's strongest features.

**Exit test:** you can state one sentence, containing one number, that
summarises the entire project.

---

## Phase 2 — Restore prescriptive integrity

**~1 day · 🌐 needs database**

`lp_recommendation` holds 430 rows generated **2026-08-23/24**. The prescriptive
layer — Reorder Recs, the dashboard's pending-actions KPI, and the policy
comparison — is serving month-old optimizer output.

| # | Task |
|---|---|
| 2.1 | Re-run the LP so `lp_recommendation` reflects current forecasts. |
| 2.2 | Add `model_version` to `LP_Recommendation` and a default filter on `GET /recommendations` (API_CONTRACTS PR2), so stale rows can never reach the dashboard again. |
| 2.3 | Verify Reorder Recs and `kpis.pending_reorder_actions` against the fresh output. |
| 2.4 | Re-check `policy_comparison` after 2.1 — its figures depend on LP output. |

**Risk:** 2.2 is a schema migration. Write it as a reviewable `.sql` under
`analytics/db/migrations/` first; do not run it ad hoc.

**Exit test:** every number on Reorder Recs traces to a planning cycle dated
within the current month.

---

## Phase 3 — Close the validation gaps

**~1 day · 🌐 needs database**

The existing validation is strong: rolling-origin *and* 80/20 backtests, 17
models, MASE/MAPE/sMAPE, a paired Wilcoxon signed-rank test, and 261 test
functions. Three gaps remain.

| # | Task | Output |
|---|---|---|
| 3.1 | **Prediction-interval coverage check.** `run_baseline_forecast.py:784` builds the band as `forecast ± 1.645 × RMSE` — a normal-theory interval assuming Gaussian, homoscedastic residuals. For intermittent monthly demand that assumption is likely violated, and the empirical coverage has never been measured. | Per-SKU CSV + short report |
| 3.2 | Add **signed error** (ME / MPE) to the bake-off. MASE, MAPE and sMAPE are all magnitude metrics and cannot detect systematic under-forecasting, which is a stockout generator in a replenishment system. | One extra column |
| 3.3 | Write a **one-page validation summary** consolidating the eight existing reports into defense language. | The document a panel will actually read |

3.1 matters because that confidence cone is the most prominent uncertainty claim
in the whole UI. Three outcomes, all publishable: coverage ≈ 90% (say so),
materially below (report it honestly or widen `CONFIDENCE_Z` to the empirical
quantile), or varies by volatility band (tie it to the stored `cv_band`).

3.3 is the highest-value item in this phase — the validation work is excellent
but currently unreadable without opening eight separate files.

**Exit test:** one page answers "how do you know your forecasts are sensible?"

---

## Phase 4 — Finish the brand data cleanup

**~half day · 🌐 👥 needs database + Yuan**

The 12 corrupt `False` / `False (n)` rows were fixed on 2026-09-18. These were
not.

| # | Task |
|---|---|
| 4.1 | Apply `config/alias_tables/unilever_brand.csv`. All ten mappings (`REX→REXONA`, `CREAM→CREAMSILK`, `LADYS→LADY'S`, `SRF→SURF`, `BRZ→BREEZE`, `CLOSE→CLOSEUP`, `BF→BESTFOODS`, `POND'S→PONDS`, `DR.KAUFMAN→DR.KAUFMANN`, `BABY→DOVE`) are still unmerged in the database. |
| 4.2 | Stop Del Monte `brand` being copied from `category_path` (98 of 99 rows), **preserving** the genuine sub-brands: ACE, FIESTA, TODAY'S, FIT N RIGHT, HEARTSMART, BONESMART, TIPCO, MR MILK. |
| 4.3 | Fix the loader so a re-run does not undo 4.1 and 4.2. |

4.3 is load-bearing: a database-only fix silently reverts on the next canonical
load.

**Note:** the alias CSV's `evidence` row counts were written against an earlier
snapshot and have drifted from live (it says REX = 24 rows; the database had
27). Re-verify before applying.

---

## Phase 5 — Execute the Del Monte decision

**Effort depends entirely on Phase 0.3**

Del Monte is present in the product master (15,339 SKU-grain + 99 category rows)
and in the UI, but absent from every analytical layer: no ABC rows, no forecast
rows. The project claims two principals; the analytics currently serve one.

**Path A — documented exclusion (recommended).** Del Monte stays
master-data-only this phase. Cost: the writing already done in 0.3. Defensible
because the source data genuinely does not support SKU-grain demand.

**Path B — build category forecasting.** Implement `/forecast/categories`
(API_CONTRACTS P1) and run ABC at category grain. Cost: several days.
**Risk:** Del Monte sellout is 17 non-contiguous months with a severe taxonomy
break (74–80 categories in 2023-01…2024-02, collapsing to 4–5 in
2025-03…2025-12), so the output may not be defensible even once built.

Recommendation: take Path A before the defense; record Path B as future work.

---

## Phase 6 — Optional breadth

**Only after Phases 0–4 are complete**

All four analytics types are already demonstrated on the dashboard
(`Dashboard.jsx:339–377` tags them explicitly), so none of this is required.

| # | Task | Value |
|---|---|---|
| 6.1 | Decide on `GET /inventory/current`, `GET /inventory/movement` and `GET /bo-monitoring` — build a consuming page or remove them. All three are implemented; none has an API wrapper in `frontend/src/api/` or any consuming component. | Three endpoints nothing calls |
| 6.2 | Document Bad Orders as **data-blocked** (`salesreturn_fact` = 0 rows). | BO is named in the problem statement; silence reads as an oversight |
| 6.3 | `GET /fsn` (D3) and `GET /decomposition` (D4). | Extra descriptive / diagnostic depth |
| 6.4 | Ingestion backend for Data Management. | Large. `DataUpload.jsx:84` is already honest that it is a shell. |

---

## Explicitly out of scope before the defense

| Item | Why not |
|---|---|
| GLM / additional forecasting models | The bake-off already shows no model beats MA3 at p < 0.05. Adding one forces re-running the full comparison and rewriting `PRODUCTION_MODEL_DECISION.md`. A GLM is a *model*, not a validation method. |
| Great Expectations / Pandera | 261 test functions plus `STAGING_CONTRACT.md` already cover this. A new framework weeks before a defense is risk, not rigour. |
| Peso conversion of the policy comparison | The data does not support a per-piece cost. |
| Ingestion backend | Large, and the page is already honestly labelled. |

---

## Data gaps that bound everything above

These are not bugs. They are the ceiling on what the project can claim, and
each should be stated rather than worked around.

| Gap | Consequence |
|---|---|
| `salesreturn_fact` = 0 rows | Bad Order monitoring impossible |
| `purchase_fact.units_received` 0 of 353 | No receipt data; no denominator for a BO *rate* |
| `abc_classification` Unilever-only | Del Monte has no ABC tiers |
| `forecast_result` 0 Del Monte rows | Del Monte has no forecast |
| Del Monte sellout: 17 non-contiguous months, taxonomy break | Category forecasting shaky even once built |

---

## Critical path

```
Phase 0 (today, 🟢)
   └─> Phase 1 (northstar claim)
          └─> Phase 2 (fresh LP) ──┐
                                   ├─> Phase 3 (validation summary)
                                   └─> Phase 4 (brand cleanup)

Phase 5 is decided by 0.3
Phase 6 only if time remains
```

**If only three things get done:** 0.1 (README), 0.3 (Del Monte statement) and
1.1 (the northstar sentence). Those are hours of work and they address the three
things most likely to be challenged.
