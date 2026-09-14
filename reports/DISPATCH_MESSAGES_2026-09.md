# Dispatch messages — 2026-09-09

Two cover notes for Yuan to send. Attachments are the existing question docs.

---

## A. To Sir Catubag (adviser)

**Attach:** `ADVISER_QUESTIONS_SIRCG.md`
**Subject:** SSM DSD — 8 methodology decisions for your ruling before we rebuild

---

Sir, good day.

Following the professor's approval of our analytics-question mind map, we did a
full read-only re-check of the whole pipeline (ETL → ABC → forecasting → LP)
against it. The map is now our working spec, and lining the code up against it
surfaced **8 decisions that are yours to make** rather than ours to code around.

The attached document lays out each one with the evidence we gathered and our
recommendation. A quick orientation:

- **Q1 (replenishment horizon)** and **Q8 (ABC period basis)** are on the critical
  path — they decide the time base of the whole prescriptive layer and which SKUs
  it covers. If you can weigh in on those two first, we can keep moving.
- **Q3 (forecast gate)**: MAPE < 20% is structurally unreachable on this demand
  (best median ~33%). We recommend MASE < 1.0. This changes prescriptive coverage
  from ~19 SKUs to ~67.
- **Q5 (LP restructure)**: we found the service-level term in the current
  objective is normalized to ~1e-5 and never actually influences the result. The
  map already calls for service level as a *constraint*. We want to take that to
  you as the proposal.
- **Q2, Q4, Q6, Q7** (σ form, ROP→S, weights provenance, EOQ/DEC-08) are lower
  urgency but still need your sign-off before the manuscript can be corrected.

We are proceeding on **provisional defaults** (compute both ABC bases with
single-period as the default cohort; MASE < 1.0 provisionally) so nothing stalls,
and will revise once you rule. Nothing is being written to the live database.

Thank you, Sir.

---

## B. To SSM — via Thea

**Attach / relay:** `CLIENT_QUESTIONS_SSM.md`
**For:** the SSM procurement / warehouse contact

---

Hi Thea — could you relay the attached six questions to SSM (whoever handles
procurement and the warehouse)?

Context you can give them: we're at the point where the replenishment model needs
six operational facts about how their warehouse and supplier arrangements actually
work. It's all plain business language — nothing technical. "We don't track that"
is a fine answer; we have fallback estimates for anything they can't give us.

The two that matter most:

1. **How often they review stock and place orders** (weekly / fortnightly /
   monthly), and **how many days from placing an order to it being on the shelf.**
   This sets the timing for the entire model.
2. **The most stock each supplier will deliver in a cycle** — or a copy of the
   annual (52-week) allocation schedule if they have one.

The other four (warehouse capacity, holding cost, supplier price list, ordering
cost) are for costing and can come later if needed.

If they can answer 1 and 2 this week that unblocks the biggest piece. Thanks!

---

## Tracking

Log responses against `ADVISER_QUESTIONS_SIRCG.md` items 1–8 and
`CLIENT_QUESTIONS_SSM.md` items 1–6. Update the decision inventory in
`PROJECT_STATE_2026-09.md` from PROVISIONAL to RULED as each comes back.
