# LP Readiness — what is blocking a defensible optimization result

**Read-only analysis, 2026-09-06, branch `kelvin-etl`.** No pipeline code or data
changed. Sources: `analytics/optimization/lp.py`, `scripts/run_lp.py`,
`scripts/run_baseline_forecast.py`, `analytics/etl/granularity.py`,
`analytics/db/schema.sql`, `config/analytics_params.yaml`, live queries against the
Supabase DB, `3ISA_7_CP-1_Manuscript.pdf` (via `scratch/manuscript_full.txt`),
`ARCHITECTURE.md`, and the prior reports named in each section. Numbers marked
**UNVERIFIED** were never computed by anyone and are not estimated here.

---

## TL;DR

**The LP stage cannot produce a defensible result today, and four client numbers
are not the whole reason.** Even with those numbers, the LP as implemented is
**structurally degenerate**: verified empirically, it returns `Q_i = ROP_i` for
406 of 430 existing recommendation rows and its output does not move at all across
the entire plausible range of every cost and capacity parameter. On top of that:
the safety-stock term has a unit-mismatch bug (daily-scaled buffer added to a
monthly forecast), Del Monte is entirely absent from the analytics layer (0 ABC
rows, 0 forecasts, 0 recommendations), only 19 of 132 Unilever Tier-A SKUs clear
the forecast gate, and the implemented objective and constraints differ materially
from the manuscript on 11 points.

What the LP can honestly produce right now: a monthly MA3 forecast and a reorder
point for 19 Unilever SKUs. The optimization layer on top of that is **runnable,
not defensible.**

---

# TASK 1 — LP readiness inventory (from the code, not the docs)

## 1.1 Objective function as actually implemented

`analytics/optimization/lp.py:143-158`:

```
minimize   Z = w1·TC  −  w2·SL  +  w3·SC
```

| Term | Implemented formula (lp.py) | Line |
|---|---|---|
| `w1, w2, w3` | `0.45, 0.35, 0.20` (module constants; also `config/analytics_params.yaml`) | 66 |
| `TC` (total cost) | `Σ_i  procurement_cost_per_unit_i · Q_i` | 154 |
| `SL` (service level) | `(Σ_i Q_i)  /  (Σ_i ROP_i)` — pooled ratio, **constant denominator** | 155 |
| `SC` (storage cost) | `Σ_i  storage_cost_per_unit_i · Q_i` — flat per-unit, same rate every SKU | 156 |

All three terms are linear in `Q_i`. The net objective coefficient on each `Q_i`
is `w1·c_i + w3·s_i − w2/ΣROP`. Because `ΣROP` is in the thousands, the
service-level pull is ≈ `−0.35/21000 ≈ −1.6e-5` — negligible against `w1·c_i` for
any `c_i` above ~`3e-5`. **The solver therefore minimizes by driving every `Q_i`
to its lower bound `ROP_i`.** (Confirmed in Task 2's sensitivity run.)

## 1.2 Decision variables

| Variable | Meaning | Units | Bounds | Source (lp.py) |
|---|---|---|---|---|
| `Q_i` (one per SKU) | recommended order / acceptance quantity | pieces (Unilever, DEC-11) | continuous, `lowBound=0` | 145-148 |

## 1.3 Constraints

| # | Name (lp.py) | Formula | Units | RHS comes from | Line |
|---|---|---|---|---|---|
| 1 | `warehouse_capacity` | `Σ_i Q_i ≤ warehouse_capacity` | pieces (unit **count**, no per-unit volume) | `--warehouse-capacity` CLI arg — no data source | 161-164 |
| 2 | `supplier_ceiling_{principal}` | `Σ_{i∈p} Q_i ≤ supplier_ceilings[p]` — **per principal**, not per SKU | pieces | `--supplier-ceiling PRINCIPAL=VALUE` CLI arg — no data source | 168-175 |
| 3 | `demand_coverage_{sku}` | `Q_i ≥ ROP_i` — hard lower bound, per SKU | pieces | `ROP_i` computed per SKU (see 1.4) | 178-182 |

`build_lp_model` raises if `skus` is empty or a principal has no ceiling entry
(lp.py:129-141). `solve_lp` returns `None` (never raises) on any non-Optimal
status (lp.py:200-201). `scripts/run_lp.py::_diagnose_infeasibility` proves the
only two infeasibility routes are `ΣROP > warehouse_capacity` and
`Σ_{i∈p}ROP_i > ceiling[p]`.

## 1.4 ROP / safety-stock inputs

`ROP_i = forecast_i + SS_i` (`compute_rop`, lp.py:94-98)
`SS_i  = 1.28 · σ_d`         (`compute_safety_stock`, lp.py:81-91; `Z=1.28` from `config/analytics_params.yaml`)

- `forecast_i` = `Forecast_Result.forecast_value` — the **MA3 one-step-ahead
  monthly forecast** written by `scripts/run_baseline_forecast.py`
  (`DEPLOYED_METHOD = "ma3"`, line 748). Real, backtested.
- `σ_d` (`scripts/run_lp.py::_sigma_d_for_product`, lines 111-167):
  - **Del Monte**: `std` of the business-day-distributed Sell Out series
    (`resolve_delmonte_category_grain`). Every day inside a month is identical, so
    this variance is entirely month-to-month — a real number, not a daily signal.
  - **Unilever**: `σ_monthly / √(avg business days per month)` ≈ `σ_monthly / 4.6`
    (run_lp.py:163). **This daily-scaled buffer is then added to a monthly
    forecast in `compute_rop` — a unit mismatch.** See Task 3.

## 1.5 Parameter table

| Parameter | Symbol | Units | Current source | Current value | Status |
|---|---|---|---|---|---|
| LP weights | `w1,w2,w3` | – | `config/analytics_params.yaml` + `lp.py` const | 0.45 / 0.35 / 0.20 | **REAL (asserted)** — "stakeholder consultation" per manuscript; not in any scribe note (same evidentiary gap as DEC-08) |
| Service-level Z | `Z` | – | `config/analytics_params.yaml` | 1.28 (90% SL) | **REAL** — manuscript: confirmed by SSM procurement mgmt |
| Next-month demand forecast | `Ŷ_i` | pieces / month | `Forecast_Result.forecast_value` (MA3) | 19 SKUs clear the gate | **REAL** (method), **partial coverage** |
| Demand std for safety stock | `σ_d` | pieces/day (Unilever, post-conversion) | `run_lp.py` from `*_Real` views | computed | **REAL data, DISPUTED method** + unit-mismatch bug (Task 3) |
| Procurement / unit cost | `c_i` / `procurement_cost_per_unit` | ₱ / unit | `Product_Dimension.unit_price`, else `--default-procurement-cost-per-unit` | `unit_price` **0 / 17,536** populated → 100 % fallback | **MISSING** (unused real proxy: `Inventory_Fact.unit_cost_per_case`, 27,282 Unilever rows, per case) |
| Storage / holding cost | `storage_cost_per_unit` (code) / `h_i` (manuscript) | ₱/unit flat (code); ₱/unit/month (manuscript) | `--storage-cost-per-unit` CLI | none | **MISSING** |
| Warehouse capacity | `W` | pieces (code); volume (manuscript `ΣQ_i·V_i`) | `--warehouse-capacity` CLI | none | **MISSING** |
| Per-unit storage volume | `V_i` | m³ / unit | **not in code at all** | – | **MISSING** (manuscript-only; code drops it) |
| Supplier ceiling | `A_i` | pieces | `--supplier-ceiling` CLI, **per principal** | none | **MISSING** + grain mismatch (manuscript per-SKU) |
| Bad-Order rate | `BO_rate_i` | fraction | **not in code** | – | **MISSING** (manuscript SC term; code substitutes flat storage) |

## 1.6 Placeholder-standing-in-for-real flags

1. **Procurement cost** — 100 % operator fallback today. Every `TC` value is
   fictional and identical-per-unit across SKUs.
2. **Storage cost, warehouse capacity, supplier ceilings** — no value at all;
   every run to date used operator-typed guesses.
3. **Net effect, verified against the live DB:** **406 of 430
   `LP_Recommendation` rows have `q_i = rop_i` exactly.** The LP is returning the
   demand-coverage lower bound — it is contributing nothing beyond `ROP`.
4. **The existing 430 rows are stale** — they pre-date the MA3 forecast rebuild
   (all `Forecast_Result` rows were `generated_at` 2026-09-01; the LP rows span 34
   planning cycles 2023-05 → 2026-03 in the old per-SKU-date SARIMA-era style). A
   fresh `run_lp.py` against current `Forecast_Result` would write ~19 rows at one
   planning date.

---

# TASK 2 — the four cost / capacity parameters

`scripts/run_lp.py` requires exactly four CLI arguments with no defaults:
`--default-procurement-cost-per-unit`, `--storage-cost-per-unit`,
`--warehouse-capacity`, `--supplier-ceiling`. (The manuscript's fuller model
implies **six** — it also names `V_i` storage volume and `BO_rate_i` — but the
implemented model needs these four.)

## 2.0 Sensitivity check — RUN, not described

Ran `analytics/optimization/lp.py` directly on 5 representative SKUs (ROPs
2,443 / 14,519 / 1,988 / 1,331 / 1,217; ΣROP = 21,498), sweeping each parameter
across its full plausible range:

| Parameter | Range swept | Effect on `Q_i` |
|---|---|---|
| procurement cost | ₱0.001 → ₱1,000 / unit | **none** — `Q_i = ROP_i` throughout |
| storage cost | ₱0.001 → ₱1,000 / unit | **none** |
| warehouse capacity | ΣROP → ∞ | **none** (below ΣROP → INFEASIBLE, no output) |
| supplier ceiling | ΣROP → ∞ | **none** (below ΣROP → INFEASIBLE) |

**The reorder recommendations do not change for any value of any of the four
parameters.** The only thing the four numbers can do is make the problem
infeasible. They cannot change a feasible answer. (Reason: §1.1 — the
service-level term is normalized by `ΣROP` and is ~5 orders of magnitude smaller
than the cost terms, so the solver always sits every SKU on its `ROP_i` floor.)

**Consequence:** obtaining the four numbers from SSM makes a run *legitimate* but
does **not** make the recommendations any different from publishing `ROP_i`
directly. The LP needs a structural change (a per-SKU force that can push some
`Q_i` above `ROP` and trade off across SKUs) before the parameters matter at all.
That is an adviser / team design decision — see Task 4 and Deliverable §5.

## 2.1 Procurement / unit cost `c_i`

- **Plain-language question:** "For each product, what do you currently pay your
  supplier per case (or per piece)?"
- **Unit / magnitude:** ₱ per case; ~₱50–₱2,000/case is typical FMCG.
- **Where it enters:** `TC` term (weight `w1`, the highest weight).
- **Without it:** one flat operator number applied to every SKU — `TC` cannot
  discriminate between SKUs.
- **Sensitivity:** none (§2.0).
- **Fallback:** `Inventory_Fact.unit_cost_per_case` (the "Last Purchase Price
  GSV/CS" field, DEC-19) is **populated for 27,282 Unilever rows** — a real,
  in-house price, per case, needing `÷ pack_size` to reach per-piece.
  Defensibility cost: **low** — it is SSM's own recorded purchase price. This is
  the cheapest of the four to close, and it does not require asking SSM anything
  beyond "is that column kept current?".

## 2.2 Storage / holding cost `h_i`

- **Plain-language question:** "What does it cost you per month to keep one case
  of stock in the warehouse?" — or, if not tracked: "total monthly warehouse cost
  (rent, power, staff, insurance)" + "cases in the warehouse on an average day".
- **Unit / magnitude:** ₱ per case per month; perhaps ₱1–₱20/case/month.
- **Where it enters:** `SC` term (`w3`) in code; `TC` (`h_i`) in the manuscript.
- **Without it:** flat operator guess.
- **Sensitivity:** none (§2.0).
- **Fallback:** derive from SSM's monthly warehouse operating cost ÷ average units
  stored (both still have to be asked). External proxy: published PH 3PL storage
  rate (~₱150–₱250/pallet/month) allocated by units-per-pallet. Defensibility
  cost: **medium** — a generic 3PL rate is not SSM's cost structure; a panelist
  can fairly say "that isn't your number."

## 2.3 Warehouse capacity `W`

- **Plain-language question:** "When the warehouse is completely full, roughly how
  much stock does it hold — in pallets, in cases, or as a multiple of one normal
  delivery?"
- **Unit / magnitude:** one number, pieces / cases / pallets.
- **Where it enters:** constraint 1.
- **Without it:** operator sets it very large → constraint never binds.
- **Sensitivity:** none, unless set below `ΣROP` → then **INFEASIBLE** (no
  recommendation produced at all for that cycle).
- **Fallback:** estimate from floor area × racking height — still needs SSM to
  supply dimensions. No external proxy. Defensibility cost: **high** if guessed.

## 2.4 Supplier ceiling `A_i` / `A_principal`

- **Plain-language question:** "For the coming order cycle, what is the maximum
  quantity Unilever — and Del Monte — will actually deliver to you?" (The annual
  52-week allocation schedule the manuscript already cites answers this.)
- **Unit / magnitude:** pieces per principal per cycle (code) or per SKU
  (manuscript).
- **Where it enters:** constraint 2.
- **Without it:** `run_lp.py` refuses to start (required, no default).
- **Sensitivity:** none, unless below `Σ_{i∈p}ROP_i` → **INFEASIBLE** for that
  principal.
- **Fallback:** none. This is a hard commercial fact SSM holds on file.
  Defensibility cost: **high** if guessed.

## 2.5 Priority

Because sensitivity is zero, priority = "needed for a legitimate run", not
"changes the answer":

1. **Structural LP fix** (not a parameter) — without it the other four are moot.
2. **Procurement cost** — has a usable in-house proxy *now*, so least blocking.
3. **Warehouse capacity, supplier ceiling** — needed to press "go"; only real
   source is SSM; guessing is indefensible.
4. **Storage cost** — needed for a meaningful `SC`; weak external proxy exists.

---

# TASK 3 — the σ conversion and monthly safety stock  (adviser ruling)

## 3.1 What the safety-stock formula requires

Classically, `SS = Z · σ_L`, where `σ_L` is the standard deviation of demand over
the **replenishment lead time** `L`. If per-period demand is i.i.d. with
per-period σ, then `σ_L = σ_period · √L`.

## 3.2 What the manuscript actually specifies (§3.4.3.1–3.4.3.2)

- `SS_i = Z · σ_di`, where `σ_di` = **standard deviation of historical *monthly*
  demand** — the formula is given explicitly with `D_t` = monthly demand.
- `ROP_i = Ŷ_(t+1,i) + SS_i`, where `Ŷ_(t+1,i)` = the **next-month** forecast.

So the manuscript works entirely at a **one-month horizon and needs no
conversion**. Lead time does not appear in the manuscript formula — SSM operates
on a periodic supplier-allocation cycle and the decision the dashboard supports is
a monthly "accept this quantity."

## 3.3 What the code actually does (contradicts the manuscript)

`scripts/run_lp.py::_sigma_d_for_product` (Unilever branch, lines 151-165):
computes `σ_monthly`, then `σ_d = σ_monthly / √(avg business days) ≈ σ_monthly / 4.6`,
then `SS_i = 1.28 · σ_d`. But `compute_rop` adds that to the **monthly** forecast:

```
ROP_i  =  (monthly MA3 forecast)  +  (daily-scaled safety stock)
```

**This is a unit mismatch.** `SS_i` comes out ≈ 4–5× too small. Visible in the
live data: `LP_Recommendation` sample rows have `ss_i = 89` against `rop_i =
2,443`; `ss_i = 5.7` against `rop_i = 1,331`. Safety stock is a rounding error on
the reorder point.

## 3.4 What σ can actually be computed from monthly data

- `σ_monthly` — std of the 38-month zero-filled series (or of the non-zero
  months). Real, defensible, directly computable.
- Nothing finer. **No daily Unilever series exists anywhere in the corpus**
  (`reports/GRAIN_DECISION.md` Q1: monthly is the finest consistently-available
  grain; the "DAILY"-named files carry no SKU column and have an 84–86%
  duplicate-key rate). Del Monte: not even monthly SKU-level flow exists — only
  category grain via Sell Out.

## 3.5 Candidate conversion approaches

| # | Approach | Formula | Assumption | Assumption supported by the data? |
|---|---|---|---|---|
| **1** | **Monthly σ, one-month horizon** (manuscript's own spec) | `SS = Z · σ_monthly` | Review / decision cycle ≈ 1 month | Business fact — ask SSM the actual review period. No statistical assumption. |
| 2 | Disaggregate to daily, rescale to lead time | `σ_daily = σ_monthly/√n`; `SS = Z·σ_daily·√L` | Demand i.i.d. across days | **No.** Untestable (no daily data) and contradicted by demand shape — 66 % zero-months, intermittent/lumpy (`DEMAND_DIAGNOSIS.md` §2, §4). This is what the code half-implements. |
| 3 | Multi-month lead time, monthly blocks | `σ_L = σ_monthly · √L` (L in months) | Demand independent **across months** | Weak. Testable via lag-1 ACF of the monthly series — not run (**UNVERIFIED**), but the series is short (≤38 pts) and intermittent, so independence is a stretch. Only relevant if `L > 1` month. |
| 4 | Empirical rolling-window σ | `σ_L = std( rolling L-month demand sums )` | none (直接 measures L-month variability) | Best if `L` is known and `> 1` month. Not currently implemented. |

## 3.6 Lead-time data

**Essentially none.** `Purchase_Fact` carries a single date
(`invoice_date` / `_period`) — there is **no separate PO-date vs. receipt-date
pair**, so order-to-delivery lead time cannot be measured from any loaded table.
`units_received` is frequently NULL. The only lead-time figure anywhere in the
project is SSM's existing "3-week" blanket rule — the thing being replaced.
**Lead-time variance is not estimable from any loaded data.**

## 3.7 Recommendation

**Adopt Approach 1** — use `σ_monthly` directly at a one-month horizon, matching
the manuscript. **Remove the `√(business-days)` conversion from `run_lp.py`** — it
is a code-only deviation, it is dimensionally inconsistent with `compute_rop`, and
its i.i.d.-daily premise is untestable and contradicted by the demand shape. If
SSM reports a review / lead-time window materially longer than one month, switch
to **Approach 4** (empirical rolling L-month σ), not a `√L` scaling.

**Strongest objection to this recommendation:** "A one-month horizon ignores lead
time. If the supplier takes three weeks to deliver after you reorder, a buffer
sized only to one month's forecast error under-protects the reorder-to-delivery
window."
**Honest answer:** true in a classical continuous-review model, but (a) SSM's
replenishment is periodic acceptance against a pre-committed allocation, not
continuous review, so the risk window is the review period, not a separate lead
time; (b) there is no lead-time data to size that window anyway; (c) the
manuscript already commits to the one-month framing and SSM's procurement head
signed off on the 90 % service level against it. Putting lead time in requires
SSM's actual order-to-shelf days **and** a switch to Approach 4.

*(This ruling is written out as a question sheet in Deliverable §3.)*

---

# TASK 4 — the EOQ term (DEC-08)

## 4.1 The decision record

`ARCHITECTURE.md` §5, **DEC-08 — status: OPEN — verify first.** Verbatim:

> EOQ does **not** appear in any of the three panel scribe's notes on record.
> Before adding: confirm the exact panel/adviser requirement (verbal comment? RRL
> conflation?). If confirmed, EOQ enters as a **benchmark/reference quantity** that
> the multi-objective LP refines under SSM's real constraints — never as a second,
> competing order-quantity decision alongside LP.

Still listed under `ARCHITECTURE.md` "Still open" (2026-08). No EOQ term exists
anywhere in `analytics/optimization/lp.py`.

## 4.2 Options and what each implies

| Option | Objective impact | Extra parameters | Favoured by |
|---|---|---|---|
| **A — omit EOQ** | none — `Q_i` from the LP is the only order quantity | none | EOQ's assumptions (constant known demand rate, order any time, no allocation ceiling, continuous replenishment) are **all violated here** — demand is intermittent, there is a supplier allocation ceiling, ordering is on a fixed cycle. EOQ's own inputs (ordering cost `K`, holding cost `h`) are as missing as the LP's. The manuscript's own RRL (Becerra/Mula/Sanchis 2022; Santos 2024) frames the contribution as *integrating forecast uncertainty into LP constraints* — not EOQ. |
| **B — EOQ as a display-only reference column** | none | `K` (ordering cost per PO) | Gives the panel a "we considered EOQ" answer; lets procurement eyeball whether the LP quantity sits in a sane lot-size range; costs nothing in the optimization. |
| **C — EOQ inside the objective** as a `|Q_i − EOQ_i|` lot-sizing penalty | objective becomes piecewise-linear (auxiliary vars), reweights `w1/w2/w3` semantics, imports EOQ's broken assumptions into the core model | `K` + solver complexity | Essentially nothing on this data; only if the panel explicitly demanded EOQ be *optimized*. |

## 4.3 Recommendation

**Option A, pending the DEC-08 source check. Fall back to Option B only if the
panel genuinely asked for EOQ.**

Reasoning: EOQ answers "how much to order per PO to trade ordering cost against
holding cost when you can order at any time." **That is not SSM's problem.** SSM's
problem is "how much of a pre-committed periodic allocation to accept" — which is
exactly what the LP's `Q_i` already is. Bolting EOQ on adds assumptions the data
breaks and at least one more missing parameter (`K`) for zero decision value. If
the requirement turns out to be real, Option B satisfies it at minimum cost and
keeps the objective clean.

---

# TASK 5 — SKU coverage

## 5.1 The population

- **132 real Unilever Tier-A SKUs** (ABC period 2026-02).
- **Del Monte: 0.** Verified live — `ABC_Classification` has **no Del Monte rows
  at all**, `Forecast_Result` has **0 Del Monte rows**, `LP_Recommendation` is
  100 % Unilever. `SellOut_Fact_Real` holds 98 distinct category-grain
  `product_key`s that were never classified or forecast. **The entire prescriptive
  stage is Unilever-only.** This is a larger coverage gap than 19/132.

## 5.2 Why each of the 132 Unilever SKUs is in or out (queried live)

| Bucket | Count | Cause |
|---|---|---|
| **Clears the LP gate** (`status='ok'` AND `mape < 20`) | **19** | — |
| `status='ok'`, `mape` 20–999 | 96 | **genuine** — MA3 holdout MAPE above 20 % |
| `status='ok'`, `mape ≥ 999` (capped sentinel) | 4 | **artifact** — near-zero / negative holdout actuals blow MAPE's `|actual|` denominator up; MASE stays sane (`DEMAND_DIAGNOSIS.md` §3) |
| `status='insufficient_data'` (provisional trailing average) | 13 | **genuine** — < 3 months of real sales (`MIN_MONTHS_WITH_SALES`) |
| `status='dead_sku'` | 0 | — |

Cross-checks on the 119 `status='ok'` rows:
- median `mape` = **40.5 %**, median `mase` = **0.94**
- `mase < 1` (beats naive): **67 / 119**
- of the 19 that clear the `mape < 20` gate, only **17 also have `mase < 1`** — 2
  pass on MAPE but are worse than a naive forecast.

## 5.3 Genuine data limits vs. threshold artifacts

- **Genuine:** the 13 `insufficient_data` (real short history — 40/132 Tier-A SKUs
  have < 12 months, `FORECASTING_METHOD_RECOMMENDATION.md` §0), and most of the 96
  mid-MAPE rows. `reports/MODEL_BAKEOFF_UNILEVER.md` is unambiguous: **no method
  median-clears MAPE 0.20 on this data** — best median is 0.333 (SBA α=.3); only
  13–15 % of Tier-A SKUs clear MAPE < 0.20 under the best method. Monthly FMCG
  demand at SKU grain does not forecast to ±20 %.
- **Artifact:** the 4 sentinel rows (MAPE broken by the sign/scale of the actual,
  not by forecast quality). And, arguably, the `mape < 20` gate itself — it is a
  manuscript number (§3.4.2.2) carried over from a different modelling context and
  is provably unreachable here.

## 5.4 What alternative thresholds yield (queried live)

| Gate | Unilever SKUs admitted |
|---|---|
| `mape < 20` (current) | **19** |
| `mape < 30` | 38 |
| `mape < 40` | 58 |
| `mape < 50` | 76 |
| `mase < 1` (bake-off's recommended replacement) | **67** |
| `mase < 1` AND `mape < 100` | 62 |
| `mase < 1` OR `mape < 20` | 69 |

- Moving from `mape < 20` to **`mase < 1` is defensible** — it is the explicit
  recommendation of `MODEL_BAKEOFF_UNILEVER.md` ("replace it with a **MASE < 1**
  gate … plus a per-SKU sMAPE report"), `mase < 1` means "beats a naive forecast"
  (a real quality bar), and `DEMAND_DIAGNOSIS.md` §3 concludes "MASE is the metric
  to trust" on this demand profile. 67/132 = 51 % of Tier A.
- **Loosening MAPE to <40 or <50 to hit a bigger number is gaming** — it admits
  forecasts with 40–50 % error and no principled justification.
- Adding a **portfolio / category-level accuracy report** alongside the per-SKU
  gate (also a bake-off recommendation) is defensible and is standard practice for
  intermittent demand.

## 5.5 Is 19 SKUs enough for a panel demo?

**Weak.** A panel will ask: "You classify 1,807 SKUs, forecast 132, optimize 19,
and cover zero Del Monte — what does the system do for the other 98.9 %?" The
honest position: the pipeline *shape* is demonstrated end-to-end on 19, but 19
SKUs is a thin slice from which to argue the ₱50–60M trapped-capital business case
the manuscript rests on. Switching the gate to `mase < 1` (67 Unilever SKUs) and
adding Del Monte are both needed before the coverage argument holds up.

## 5.6 What would widen it, ranked by effort

1. **Switch the LP gate from `mape < 20` to `mase < 1`** — one predicate in
   `scripts/run_lp.py` + a manuscript edit. **19 → 67 Unilever SKUs.** No new
   data. Defensible on its own merits (bake-off recommendation). *Lowest effort,
   biggest single gain.*
2. **Gate on MASE when MAPE is uncomputable / capped** — recovers the 4 sentinel
   SKUs. Trivial. → ~71.
3. **Run Del Monte category-grain forecasting** and write it to `Forecast_Result`.
   `run_lp.py`'s demand query and `granularity.py` already handle the Del Monte
   path; `run_baseline_forecast.py` is Unilever-only and needs a sibling / an
   extension. Adds the entire Del Monte side (≤98 categories). **Medium effort, no
   new data.**
4. **Adopt SBA α=0.3 as the deployed method** instead of MA3 (bake-off: MASE 0.788
   vs 0.819, beats naive 79 % vs 75 %). Marginally more SKUs clear `mase < 1`. Low
   code effort, but it is a method change that touches the manuscript.
5. **Get more real Unilever history from SSM** (the ongoing monthly feed past
   2026-02; pre-2023 is confirmed not to exist). Helps the 13 `insufficient_data`
   SKUs and tightens everyone's error. High effort / external / slow.
6. **Portfolio-level forecast + accuracy target** as a parallel track for SKUs
   that cannot clear a per-SKU bar. Medium effort — design + manuscript.

---

# TASK 6 — terminology consistency (feeds the manuscript revision)

Code / data truth vs. the manuscript and CLAUDE.md. Chapter/section cited where
identifiable.

| # | Claim (manuscript / CLAUDE.md) | Where | Reality |
|---|---|---|---|
| 1 | "SARIMA … is the **primary forecasting model** applied to Category A SKUs" | Manuscript **§3.4.2.2** (section title: *"SARIMA (Seasonal Demand Forecasting)"*); also **§1.4** objectives, **§3.4.2** intro, ToC | **MA3** (3-month moving average) is deployed for all Tier A — `scripts/run_baseline_forecast.py:748` `DEPLOYED_METHOD = "ma3"`. SARIMA was benchmarked and is the **worst of 17 methods** (`MODEL_BAKEOFF_UNILEVER.md`: seasonal SARIMA MASE 0.989, barely beats naive; ~100× slower; ruled out fixed-spec *and* auto-selected). Not in the deployed pipeline. |
| 2 | "seasonal structure of demand … seasonal differencing … calendar-driven demand cycles"; decomposition isolates "predictable seasonal bumps from … holidays" | Manuscript **§3.4.2.1, §3.4.2.2** | **No annual seasonality found.** `ARCHITECTURE.md` DEC-23 / `DEMAND_DIAGNOSIS.md` §4 / `ADVISER_EVIDENCE.md`: significant lag-12 ACF in only **5.1 %** of Tier-A SKUs (= the 5 % false-positive rate); **0/16** aggregate series; **0/20** in the longest-history sample. Seasonal terms fit noise. |
| 3 | "five (5) years historical records, spanning **2020 to 2025**" | Manuscript **§3.4.1.1** | Usable SKU-level data: Unilever **2023-01 → 2026-02** (38 months); Del Monte non-contiguous 2023 → 2025 (17–22 months per doc-type). **2020 does not exist** in the corpus; the corpus extends to 2026. Already in `ARCHITECTURE.md` "Manuscript errata"; still uncorrected in the manuscript. |
| 4 | "the model utilizes **five years** of historical transaction records and employs a strict **80/20 time-based split**" | Manuscript **§3.4.2.2** | Median Tier-A SKU has **< 12 months** of real history (`FORECASTING_METHOD_RECOMMENDATION.md` §0: 40/132 under 12 months). Deployed MA3 uses only the **last 3 observations**; the backtest is **rolling-origin 1-step over the last 6 months** (`MODEL_BAKEOFF_UNILEVER.md`), not one 80/20 split. |
| 5 | "years of **daily** transaction logs" | Manuscript **§1.3** (Project Context) | No usable SKU-level daily data exists. `GRAIN_DECISION.md` Q1/Q2: files named "DAILY" are monthly workbooks whose rows carry no SKU column and have an 84–86 % duplicate-key rate; `ssis_summary` (1.95M rows) is never loaded; disaggregation "would manufacture data, not recover it." |
| 6 | ROP / SL use "**SARIMA** forecasted demand `Ŷ_(t+1,i)`" | Manuscript **§3.4.3.2, §3.4.3.3** | `Ŷ` is the **MA3** one-step forecast. Formula structure is fine; only the model name is wrong. |
| 7 | `TC = Σ(h_i · Q_i)`, `h_i` = **holding** cost per unit per month | Manuscript **§3.4.3.3** | Code (`lp.py:154`): `TC = Σ(procurement_cost_i · Q_i)` — **acquisition** cost, not holding cost. |
| 8 | `SL = Σ(Q_i / Ŷ_(t+1,i))` — per-SKU ratio sum, denominator = forecast | Manuscript **§3.4.3.3** | Code (`lp.py:155`): `SL = ΣQ_i / ΣROP_i` — **pooled** ratio, denominator is **ROP**, not the forecast. |
| 9 | `SC = Σ(BO_rate_i · Q_i · c_i)` — **spoilage cost from Bad Orders** | Manuscript **§3.4.3.3** | Code (`lp.py:156`): `SC = Σ(storage_cost_i · Q_i)` — flat per-unit storage, **no BO rate, no per-SKU cost**. `ARCHITECTURE.md` §7(5) already flags "no BO term exists anywhere in the LP objective at any grain." |
| 10 | Warehouse constraint `Σ(Q_i · V_i) ≤ W` — **volume-weighted** | Manuscript **§3.4.3.3** | Code (`lp.py:161`): `Σ Q_i ≤ W` — unit **count**; `V_i` is absent from the code entirely. |
| 11 | Supplier ceiling `Q_i ≤ A_i` — **per-SKU** allocation | Manuscript **§3.4.3.3** | Code (`lp.py:168-175`): `Σ_{i∈principal} Q_i ≤ ceiling[principal]` — **per-principal aggregate**, not per-SKU. |
| 12 | "solved using PuLP applying the **simplex method**" | Manuscript **§3.4.3.3** | Code uses **CBC** (`pulp.PULP_CBC_CMD`, `lp.py:197`) — a branch-and-cut solver (simplex only for its internal LP relaxations). Imprecise. |
| 13 | "**SARIMA** forecasting" in the pipeline line; "run_sarima.py has confirmed bugs … Needs fix" | **CLAUDE.md** (Project; Known open items) | `run_sarima.py` is **not in the deployed path**; MA3 via `run_baseline_forecast.py` is. The `run_sarima.py` bugs are moot for the LP. **Stale.** |
| 14 | "`scripts/generate_sarima_artifact.py` queries `fr.forecast_quantity` but real column is `forecast_value` — will crash as-is" | **CLAUDE.md** open items | Real column confirmed `forecast_value` (schema + live). Both `generate_sarima_artifact.py` and `scripts/plot_forecast.py:27` still reference `forecast_quantity` — but both are SARIMA-era, off the LP path. **Stale-but-real dead code**, harmless to the LP. |
| 15 | Pipeline: "SARIMA forecasting → safety stock/ROP" | **CLAUDE.md** line 1; `ARCHITECTURE.md` §1, §7 | Should read "**MA3 one-step forecast** → safety stock/ROP". `ARCHITECTURE.md` §1's analytical-goal line and §7 "Analytics" bullet both still say SARIMA. |
| 16 | Manuscript Table 3.3.1 omits `Unilever_SKU_Demand_Fact`, `Forecast_Result`, `LP_Recommendation` | **§3.3.1**; `ARCHITECTURE.md` errata (already logged) | All three exist in `schema.sql`. |
| 17 | "`σ_di` = standard deviation of historical **monthly** demand" | Manuscript **§3.4.3.1** | **Manuscript is correct here.** The **code contradicts the manuscript** by converting to daily (`run_lp.py:163`). This is the one place the code should change to match the manuscript, not the reverse (Task 3). |

**Net:** the manuscript's §3.4.2 (forecasting) is wrong on the model, the
seasonality, the data span, and the training protocol; its §3.4.3.3 (LP) describes
a different objective and different constraints than the code implements on 5 of
its ~8 lines. Both sections need rewriting against the implementation — except
§3.4.3.1, where the code needs fixing to match the manuscript.

---

# DELIVERABLE

## D1 — Blocker table

| # | Blocker | Who resolves | What exactly is needed | What it blocks | Severity |
|---|---|---|---|---|---|
| **B1** | **LP objective is structurally degenerate** — `Q_i = ROP_i` for 406/430 rows; output insensitive to all four parameters (verified) | **Us + adviser** | A design decision: either add a per-SKU force to the objective that can push some `Q_i` above `ROP` and trade off across SKUs, or accept that "`Q_i = ROP_i`" *is* the recommendation and stop calling it an optimization | Any claim that the LP optimizes anything | **CRITICAL** |
| **B2** | **Safety-stock unit mismatch** — daily-scaled `SS` added to a monthly forecast; `SS` ≈ 4–5× too small; code contradicts manuscript §3.4.3.1 | **Us** (code) **+ adviser** (ruling) | Remove the `√(business-days)` conversion in `run_lp.py`; use `σ_monthly` directly (Approach 1). Adviser confirms horizon | Every `ROP_i` and `SS_i` value | **CRITICAL** |
| **B3** | **Procurement cost `c_i`** — `Product_Dimension.unit_price` 0/17,536 populated; 100 % operator fallback | **SSM**, or **us** via the `Inventory_Fact.unit_cost_per_case` proxy (27k Unilever rows) + pack-size conversion | Per-SKU supplier price, per case | A non-fictional `TC` term | **HIGH** |
| **B4** | **Storage / holding cost `h_i`** — no value | **SSM** | ₱ per case per month to hold stock (or total monthly warehouse cost + average cases on hand) | A meaningful `SC` / `TC` term | **HIGH** |
| **B5** | **Warehouse capacity `W`** — no value | **SSM** | Max total units / cases / pallets the warehouse holds | Constraint 1; feasibility | **HIGH** |
| **B6** | **Supplier ceiling `A`** — no value; `run_lp.py` won't start without it | **SSM** | Max units Unilever / Del Monte will deliver per cycle (the annual allocation schedule) | Constraint 2; the run cannot start | **HIGH** |
| **B7** | **Del Monte has 0 ABC rows, 0 forecasts, 0 recommendations** | **Us** | Classify Del Monte (ABC) and run category-grain forecasting; write to `Forecast_Result` | Half the project's stated scope | **HIGH** |
| **B8** | **Only 19/132 Unilever Tier-A SKUs clear the gate**; `mape < 20` is unreachable on this data | **Us + adviser** | Switch the LP gate to `mase < 1` (→ 67 SKUs) + a per-SKU sMAPE report; edit manuscript §3.4.2.2 | Demoable coverage; the business-value argument | **MEDIUM** |
| **B9** | **EOQ / DEC-08 unresolved** since 2026-07 | **Adviser + panel** | Confirm whether EOQ was ever actually required; if yes, adopt Option B (reference column only) | Manuscript finalization | **MEDIUM** |
| **B10** | **Code ≠ manuscript on 11 LP / forecast specifics** (Task 6) | **Us** (code + manuscript) **+ Thea** (manuscript) | Rewrite manuscript §3.4.2.2 and §3.4.3.3 to the implemented model; fix §3.4.3.1 in code instead | Defense consistency | **MEDIUM** |
| **B11** | **LP weights** `0.45/0.35/0.20` sourced to "stakeholder consultation", not in any scribe note (same gap as DEC-08) | **Adviser** | Confirm the provenance, or re-derive from a documented SSM priority statement | Defensibility of the weighting | **LOW** |
| **B12** | **430 existing `LP_Recommendation` rows are stale** (pre-date the MA3 rebuild; SARIMA-era) | **Us** | Re-run `run_lp.py` after B1–B3; expect ~19 (or ~67) rows at one planning date | DB currency | **LOW** |

## D2 — Question sheet for San San Marketing

*(Plain language. Every question is about how your operations actually work — no
model knowledge needed. Answer what you can; "we don't track that" is a useful
answer too.)*

**1. Supplier delivery limits.**
For the coming order cycle, what is the most stock **Unilever** will deliver to
you? And **Del Monte**? If you have the annual allocation schedule (the 52-week
plan), a copy of that answers this completely.
*→ number of cases (or pieces), per supplier*

**2. Warehouse capacity.**
When your warehouse is completely full, roughly how much stock does it hold? Use
whatever unit is natural — total pallets, total cases, or "about X times a normal
delivery."
*→ one number*

**3. Cost to hold stock.**
Roughly what does it cost you to keep **one case** of product sitting in the
warehouse for **one month**? If you don't track it that way: what is your total
monthly warehouse cost (rent, electricity, warehouse staff, insurance), and about
how many cases are in the warehouse on an average day?
*→ ₱ per case per month, or the two numbers for us to divide*

**4. What you pay your suppliers.**
Do you have a current price list of what you pay Unilever and Del Monte **per
case, by product**? If your Stock-on-Hand file's "Last Purchase Price" column is
kept up to date, please confirm that — we can read prices from there.
*→ ₱ per case, by product (or confirmation that the SOH column is current)*

**5. Ordering cost.** *(Only if you can answer easily — otherwise skip.)*
Roughly what does it cost you in staff time and paperwork to place and receive
**one** purchase order, regardless of how big it is?
*→ ₱ per order*

**6. How your replenishment cycle works.**
How often does the procurement team actually review stock and accept a supplier
allocation — weekly, every two weeks, monthly? And once you place an order, how
many days until it is on your shelves?
*→ a cadence, and a number of days*

## D3 — Question sheet for the adviser

### Ruling 1 — how to size safety stock from monthly-only demand data

Unilever demand exists **only monthly** (confirmed — no daily data anywhere in
the corpus). The manuscript (§3.4.3.1) already specifies σ as the **standard
deviation of monthly demand**, and ROP as **next month's forecast + safety
stock** — a one-month horizon, no conversion.

The current **code** instead divides the monthly σ by √(business days) to get a
"daily" σ, then adds that daily-scaled buffer to a monthly forecast — a unit
mismatch that makes safety stock ~4–5× too small (in the live data: a safety
stock of 89 units against a reorder point of 2,443).

**Options:**

| # | Approach | Assumption | Data support |
|---|---|---|---|
| **1** | **Monthly σ, one-month horizon** (the manuscript's own formula) | review cycle ≈ 1 month | business fact (SSM question 6); no statistical assumption |
| 2 | daily σ = σ_month/√n, then × √(lead-time days) | demand i.i.d. day-to-day | **not supported** — untestable (no daily data) and contradicted by the demand shape (66 % zero-months). This is what the code half-does. |
| 3 | σ over L months = σ_month·√L | months independent | weak — short, intermittent series; **not tested** |
| 4 | empirical: std of rolling L-month demand totals | none | best **if** lead time L is known and > 1 month; needs L from SSM |

**Our recommendation: Option 1** — revert the code to the manuscript formula. If
SSM reports a review / lead-time window materially longer than a month, use
Option 4, not a √L scaling.

**Strongest objection:** a one-month horizon ignores the reorder-to-delivery lead
time. **Our answer:** SSM's replenishment is periodic acceptance against a
pre-committed allocation, not continuous review, so the risk window is the review
period; and there is no lead-time data to size anything else. Modelling lead time
explicitly needs SSM's actual order-to-shelf days plus Option 4.

### Ruling 2 — the Economic Order Quantity term (DEC-08)

DEC-08 has been OPEN since 2026-07: **EOQ appears in no panel scribe's notes on
record.** Before any manuscript or code change we need to know whether EOQ was
ever actually required (a verbal panel comment? a literature mix-up?).

**Options if it must be addressed:**

| Option | What it does | Cost |
|---|---|---|
| **A — omit EOQ** | the LP's `Q_i` stays the only order quantity | none. EOQ's assumptions (constant known demand, order any time, no allocation ceiling) are all violated here; it needs its own missing parameter (ordering cost). |
| **B — EOQ as a display-only reference column** | show `√(2DK/h)` next to `Q_i` and `ROP_i` in the dashboard; does not touch the objective | one extra SSM number (ordering cost `K`, SSM question 5) |
| **C — EOQ inside the objective** | penalize `|Q_i − EOQ_i|`; complicates the objective and imports EOQ's broken assumptions | high; not recommended |

**Our recommendation: A**, pending the source check; **B** if the requirement is
confirmed real. EOQ answers "how much to order per PO when you can order any
time" — that is not SSM's problem; SSM's problem ("how much of a pre-committed
allocation to accept") is exactly what the LP's `Q_i` already is. The manuscript's
own literature framing (Becerra/Mula/Sanchis 2022) positions the contribution as
integrating forecast uncertainty into LP constraints, not EOQ.

## D4 — What the LP can and cannot produce today

**With only what is currently available, the LP stage can produce:**
- For **19 Unilever Tier-A SKUs** (67 if the gate moves to `mase < 1`): a reorder
  point `ROP_i = MA3 one-month forecast + safety stock`, and a "recommended
  quantity" `Q_i`.
- The forecast term is real (MA3, rolling-origin backtested).
- The pipeline runs end-to-end without crashing.

**It cannot produce:**
- Any `Q_i` that differs from `ROP_i`. Verified: `Q_i = ROP_i` for ~94 % of rows,
  and the output is completely insensitive to all four cost / capacity parameters.
  The LP is not optimizing — it is echoing the reorder point.
- A correctly-scaled safety stock (unit-mismatch bug: daily `SS` on a monthly
  `ROP`).
- Anything for **Del Monte** (0 ABC rows, 0 forecasts).
- A real total-inventory-cost or spoilage-cost figure (all cost inputs are
  operator placeholders; the spoilage term is not even Bad-Order-linked as the
  manuscript specifies).
- Coverage beyond ~14 % of Unilever Tier A / ~1 % of the classified catalogue.

**Defensible, or merely runnable? — Merely runnable.** The LP stage produces
numbers, but `Q_i` carries no optimization information (it equals `ROP_i`), the
safety-stock component is mis-scaled, every cost input is a guess, half the scope
is absent, and the implemented objective and constraints differ materially from
the manuscript. The current `LP_Recommendation` table cannot be shown to a panel
as a result. What **is** defensible today is narrower: *the MA3 monthly forecast
for 19–67 Unilever SKUs, and a reorder point built from it.* The optimization
layer is not yet a result.

## D5 — Strongest panelist objection, and the honest answer

**Objection:**
> "Your linear program's recommended order quantity `Q_i` is identical to your
> reorder point `ROP_i` for essentially every SKU. You have built a multi-objective
> optimizer that, on your own data, does nothing an optimizer is for — it never
> trades cost against service across SKUs, it just returns the lower bound. And you
> cannot show it does anything, because the inputs that would make it bind are all
> numbers you do not have. Is the LP stage not just decorative?"

**Honest answer:**
As currently implemented and parameterized, that is correct — the LP is
degenerate. The demand-coverage constraint (`Q_i ≥ ROP_i`) is the only per-SKU
force in the model; the cost terms all point the same direction (minimize `Q`), so
the solver sits every SKU on its floor, and the service-level term is normalized
by `ΣROP` to the point of numerical irrelevance. The four missing parameters can
only make the problem *infeasible*, not more interesting.

Fixing this needs two things, and only one of them is "get numbers from SSM":

1. **SSM's real capacity and allocation ceilings**, so that the aggregate
   constraints actually *bind* and the model is forced to allocate a scarce total
   across SKUs — that alone makes `Q_i ≠ ROP_i` for the SKUs that get squeezed.
2. **A per-SKU term in the objective that can prefer holding more of some SKUs
   than others** — e.g. a service-level reward that is not normalized away, or the
   spoilage cost actually varying by SKU as the manuscript intends.

Until both are in place, the honest framing is that the prescriptive output is
"reorder point plus a feasibility check," not an optimization — and the manuscript
should say exactly that rather than overclaim.

---

## Appendix — commands used for the live checks

- Sensitivity sweep: `python -c` driving `analytics.optimization.lp.build_lp_model` /
  `solve_lp` on 5 SKUs with ROPs `[2443, 14519, 1988, 1331, 1217]`, varying each
  of the four parameters over the ranges in Task 2.0.
- DB counts: `Forecast_Result` (132 rows: 119 `ok`, 13 `insufficient_data`, 0
  `dead_sku`, 0 Del Monte); `LP_Recommendation` (430 rows, 100 % Unilever, 406
  with `q_i = rop_i`); `ABC_Classification` (0 Del Monte rows);
  `Product_Dimension.unit_price` (0 / 17,536 populated);
  `Inventory_Fact.unit_cost_per_case` (27,282 Unilever rows populated);
  `SellOut_Fact_Real` (98 distinct category `product_key`s).
- Gate thresholds: counts of `status='ok'` rows by `mape` / `mase` cutoffs
  (Task 5.4).
