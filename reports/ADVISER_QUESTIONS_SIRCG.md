# Questions for Sir Catubag — SSM DSD re-check

**Context:** The analytics-question mind map is approved and is now our spec. A
full read-only re-check of the pipeline against it surfaced eight decisions that
are yours to make, not ours to code around. Each has the evidence and our
recommendation. Items 1 and 5 are on the critical path — they block Phase 4 and
they change how many SKUs the prescriptive layer covers. Item 8 (ABC period
basis) shapes the cohort for Phases 3 and 4.

---

## 1. Replenishment horizon — how long is one review cycle?

**Why it matters:** the prescriptive layer computes safety stock and an order-up-to
level over a horizon. The map says "replenish to S at each **weekly** review." But
SSM's only per-SKU demand data is **monthly** — there is no weekly demand series
anywhere, verified line-by-line across all 106 raw files. Monthly forecast +
monthly σ + a weekly horizon is a unit mismatch, and scaling monthly→weekly by √
assumes day-to-day independence that this demand (66% zero-months) does not have.

**Options:**
- **(a)** Treat the review + lead-time window as **≈ one month** given SSM's
  current 3-week blanket rule and an unknown supplier lead time. Everything stays
  monthly; "weekly" in the map becomes "each review cycle." *(Our recommendation
  — it's the only horizon the data supports without an assumption.)*
- **(b)** We get the actual **review cadence** and **order-to-shelf lead time**
  from SSM (client question sheet), then size σ over that window **empirically**
  (rolling-window standard deviation of demand sums over the window), not by √.

**Blocks:** the entire Order-Up-To-Level model (Phase 4b). We cannot write S-level
code until this is settled.

---

## 2. Safety-stock σ — confirm the monthly form

The manuscript (§3.4.3.1) specifies `σ = standard deviation of historical monthly
demand`, `ROP = next-month forecast + safety stock` — a one-month horizon, no
conversion. The **current code** divides monthly σ by √(business days) to get a
"daily" σ, then adds that to a monthly forecast. Result: safety stock is ~4–5×
too small (live example: safety stock of 89 units against a reorder point of
2,443).

**Recommendation:** revert the code to the manuscript's monthly form. One caveat
— the manuscript uses the population standard deviation (`1/n`); the code uses the
sample form (`1/(n−1)`). We will align to whichever you prefer (they differ by <2%
at n=38).

**Confirm:** monthly σ, one-month horizon, population (`1/n`) or sample form?

---

## 3. Forecast-accuracy gate — MAPE < 20% is unreachable; move to MASE < 1?

Every accuracy study we have run agrees: **no forecasting method reaches a median
MAPE below 20% on this data** — the best is ~33%, and only 13–15% of individual
Tier-A SKUs ever clear 20%. The cause is structural: many SKUs have near-zero or
negative demand months, which blow up MAPE's denominator. This is a property of
the demand, not a model failure.

**Recommendation:** replace the `MAPE < 0.20` gate with **`MASE < 1.0`** (a
forecast that beats "just reorder last month's demand") plus a per-SKU sMAPE
report. Under MASE < 1, **67 of the ~89 backtestable Tier-A SKUs pass** (vs 19
under MAPE < 20%).

**Decide:** keep MAPE < 20%, or move to MASE < 1? This changes prescriptive
coverage from ~19 SKUs to ~67.

---

## 4. Reorder Point → Order-Up-To Level (S) — the map changes the policy

The map's prescriptive layer now specifies an **Order-Up-To Level S = expected
demand over the review period + safety stock**, replacing the plain reorder point
(ROP) in the current code and the manuscript (§3.4.3.2). ROP becomes the *trigger*
("reorder when on-hand falls to ROP"), S becomes the *target* ("order up to S").
This is the standard periodic-review policy and it fits SSM's cyclic ordering
better than a continuous reorder point.

**This is a real model change.** We will not implement it without your sign-off.
Depends on Q1 (the horizon).

---

## 5. LP restructure — service level as a constraint, not a weighted objective

The map's PR3 reads: *"minimize total holding and ordering cost, subject to the
fixed allocation and **meeting the target service level**."* Service level as a
**constraint**, not a `w₂` term in the weighted objective.

**Why this matters:**
- [Superseded 2026-09-30, corrected 2026-11-13: the LP is now solved in stages (layers, then the 3-week cover rule, then
  w₁ purchase cost − w₂ revenue-weighted need met + w₃ storage); w₃ is a flat storage cost, never spoilage; the
  normalisation problem below was fixed 2026-09-18 (8f79729). The text below is the question as asked on 2026-09-14.]
- The current LP objective is `minimize w₁·cost − w₂·service + w₃·spoilage`. We
  verified empirically that the `w₂·service` term is normalized to ~1e-5 and never
  actually influences the answer — the LP returns `Q = ROP` for 94% of SKUs and is
  insensitive to every cost/capacity parameter.
- Moving service to a constraint makes the objective honest. The answer still sits
  at `Q = max(ROP, service floor)` for most SKUs — per-SKU differentiation only
  appears where the warehouse or supplier allocation actually binds — but it is
  then a *correct* answer, not an artifact of a normalization bug.
- It also **removes spoilage from the objective** (bad orders move to the
  descriptive layer — the returns data has no product identifier, so a per-SKU
  spoilage term was never computable). That orphans `w₃`, which means the weights
  **0.45 / 0.35 / 0.20 no longer describe the model.**

**Questions for you:**
- (a) Confirm service level moves to a constraint.
- (b) With spoilage gone from the objective, is it still a multi-objective
  weighted LP, or is it now simply *minimize holding cost subject to
  {demand coverage, service level, supplier allocation, warehouse capacity}*?
- (c) If weighted, what do the weights weight now?

---

## 6. LP weights provenance — where did 0.45 / 0.35 / 0.20 come from?

The manuscript attributes the weights to "stakeholder consultation," but they do
not appear in any of the three panel scribes' notes on record. If item 5 changes
the objective, this may be moot — but if weights survive in any form, we need a
sourced basis (a documented SSM priority statement) before the defense.

---

## 7. EOQ / DEC-08 — was it ever actually required?

DEC-08 has been open since 2026-07: **EOQ appears in no panel scribe's notes.**
Before we add it (or defend its absence), we need to know whether a panelist
verbally required it, or whether it was a literature mix-up. Our position: EOQ's
assumptions (constant known demand, order any time, no allocation ceiling) are all
violated here, and it needs its own missing parameter (ordering cost). If it must
be addressed, we would show it as a **display-only reference figure**, not in the
optimization.

---

## 8. ABC period basis — single calendar month vs trailing 3-month?

The manuscript specifies ABC on a **single calendar month** of revenue. We
re-checked the Tier-A cohort across all 38 monthly periods (2023-01 → 2026-02) and
found it is **a small stable core with a churning boundary**, not a stable set:

- **49-SKU stable core** — Tier A in ≥30 of 38 periods (21 in all 38). Every one
  has ≥36 months of history and a smooth demand shape (ADI ≈ 1, low CV²).
- **~366 "occasional" SKUs** — Tier A in a median of **7 of 38 periods**; 40% have
  under 12 months of history; mostly intermittent/lumpy.
- The **monthly Tier-A count swings 89 → 149 → 132** over the last three periods.
  It is driven by **revenue concentration, not revenue level** — correlation with
  monthly HHI is **−0.74** and with the number of SKUs selling that month
  **+0.70**, while correlation with total monthly revenue is only +0.31. When a
  few large orders land, fewer SKUs clear the 80% cutoff.
- **2025-12 (count = 89)** is a documented anomaly: lowest revenue month of the 38,
  most concentrated, fewest SKUs selling, and a spike of return-heavy
  negative-revenue SKUs.

**Why it matters:** the ABC period decides which SKUs get a forecast and which
enter the LP. A single anomalous month (like 2025-12) would drop ~40 real
mid-tier SKUs out of the prescriptive layer for that cycle.

**Recommendation:** compute ABC on a **trailing 3-month revenue window** as the
**cohort of record** for forecasting and the LP — it smooths the concentration
swings while still tracking genuine tier movement. Keep the **single-period**
classification available alongside it for comparison and manuscript continuity.

**This is a methodology change from the manuscript, so it is your call.** We will
not switch the cohort of record without your ruling. Phase 2 will compute both
either way.

---

## Also for your awareness (no decision needed now)

- **DEC-23** (SARIMA replacement): the map's method choice supersedes this — the
  deployed forecaster is a 3-month moving average, chosen from a 17-method
  bake-off in which SARIMA was worst. We will confirm the final method (possibly a
  clustered / per-segment approach — see the separate model note) in Phase 3.
- **`BOUNDARY_MARGIN = 0.02`** in the ABC code (flags SKUs near a tier cutoff) is a
  placeholder — we could not confirm it against manuscript §3.6. Low priority.
- **Del Monte** is out of active scope (thin data), but we are building every
  layer to accept it when the client delivers. The Jan-2025 taxonomy break
  (74 → 5 categories) will need a ruling — bridge table or era-split — before Del
  Monte category analysis is trustworthy.
