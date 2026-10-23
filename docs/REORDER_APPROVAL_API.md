# Reorder approval and reversal: API for the frontend (2026-10-23)

Backend only. Code: `backend/routers/reorder_approval.py` (new), `backend/routers/recommendations.py` (PATCH gate).
Migrations **0067** (reversal) and **0068** (approval) are written and **not applied** to `public`. Until they are,
the new endpoints answer 503 (`reversal_not_ready` / `approval_not_ready`) and `PATCH /recommendations/{key}` behaves
exactly as before. All quantities are pieces. Errors are `{"detail": "...", "code": "..."}` where a code is listed.

## State machines

`lp_recommendation.status` (the decision; values unchanged)

```
pending  --PATCH accept/dismiss------------------> accepted | dismissed
accepted | dismissed --POST /{key}/reverse (admin)--> pending     (the decision is kept in lp_decision_reversal)
```

`lp_quantity_change.state` (new: one row per proposed quantity change, never deleted)

```
(planner without a grant edits the quantity) --> pending_approval
pending_approval --approve (admin)--> approved    and the recommendation becomes accepted
pending_approval --reject  (admin)--> rejected    and the recommendation stays pending
```

- A proposal does not touch the recommendation: `status` stays `pending`, `recommended_q_i` is unchanged, `decided_*` stay null.
- While a change is `pending_approval`, nobody can accept or dismiss that row (PATCH answers 409 naming the change). The admin settles it first.
- One open change per row at most.
- Approve = the ordinary accept: `status` accepted, `decided_q_i` = proposed quantity, `decision_reason` = the planner's reason, `decided_by` = the planner, `decided_at` = approval time. Approver and note are on the change and in the audit log.
- Only a pending row of the principal's current LP cycle can be proposed on, approved or reversed (409 otherwise, same rule as PATCH).
- Who may apply a quantity change at once: an admin, or a user an admin has granted direct apply. Everyone else's edit is held.

## Endpoints

| Method and path | Who | Body | Success |
|---|---|---|---|
| `POST /recommendations/{key}/quantity-change` | `lp.decide` | `{quantity, reason?, reviewed?}` | **202** `{outcome:"held", change}` or **200** `{outcome:"applied", item}` |
| `GET /recommendations/changes?state=pending_approval\|approved\|rejected\|all&recommendation_key=` | `lp.decide`; admin sees all, others only their own | | `{count, items:[change]}` newest first |
| `POST /recommendations/changes/{change_key}/approve` | admin | `{note?}` | `change` (state approved) |
| `POST /recommendations/changes/{change_key}/reject` | admin | `{reason}` required | `change` (state rejected) |
| `POST /recommendations/{key}/reverse` | admin | `{reason}` required | the `RecommendationItem`, now pending |
| `GET /recommendations/direct-apply-grants/me` | `lp.decide` | | `{can_apply_directly, reason:"admin\|granted\|not_granted", approval_ready}` |
| `GET /recommendations/direct-apply-grants` | admin | | `[{user_id, email, full_name, granted_by, granted_at}]` |
| `PUT /recommendations/direct-apply-grants/{user_id}` | admin | `{granted: true\|false}` | `{can_apply_directly, reason, approval_ready}` |
| `PATCH /recommendations/{key}` (existing) | `lp.decide` | unchanged | unchanged; a `decided_quantity` different from `recommended_q_i` from a user without a grant answers **403 `approval_required`** |

"Admin" means `role = admin` on top of the key: a staff account ticked for `lp.decide` still gets **403 `admin_required`** on the admin rows.

`change` object:

```json
{"change_key": 7, "recommendation_key": 1, "sku_code": "69668151", "product_name": "...", "planning_cycle_date": "2026-03-01",
 "recommended_q_i": 142.22, "proposed_q_i": 150.0, "reason": "Truck is full", "reviewed": false,
 "state": "pending_approval", "proposed_by": "planner@...", "proposed_at": "2026-10-23T09:00:00Z",
 "resolved_by": null, "resolved_at": null, "resolution_note": null}
```

## Errors the page should handle

| Status, code | Meaning |
|---|---|
| 400 `quantity_unchanged` | The quantity equals the recommendation: accept it as it is instead |
| 403 `approval_required` | PATCH with a different quantity and no grant: use `quantity-change` |
| 403 `admin_required` | An admin-only route called by a non-admin |
| 409 (plain `detail`) | Row already decided, superseded cycle, a change already awaiting approval, a flagged product sent without `reviewed: true`, a change already settled |
| 409 `recommendation_changed` | Approving a change whose `recommended_q_i` has since moved (an LP rerun): reject it and propose again |
| 503 `approval_not_ready` / `reversal_not_ready` | Migration 0068 / 0067 not applied |

## What the page can build from this

Planner: on a quantity edit call `quantity-change`; show "sent for approval" on 202 and the new accepted row on 200. Ask `direct-apply-grants/me` first to word the button ("Apply" or "Send for approval"). Show the row as awaiting approval from `GET /recommendations/changes?state=pending_approval&recommendation_key=...` (the list endpoint `GET /recommendations` is unchanged and does not carry the change).
Admin: an inbox from `GET /recommendations/changes`, approve and reject buttons, a Reverse action on a decided row (reason required), and a grants list.

## Audit log actions added

`Reorder Quantity Change Proposed`, `Reorder Quantity Change Approved`, `Reorder Quantity Change Rejected` (each carries `SKU x: quantity before -> after`, the change number and who proposed it), `Reorder Decision Reversed`, `Direct Apply Granted`, `Direct Apply Revoked`. A user with a grant who applies a change gets the existing `Reorder Recommendation Accepted` entry ending `[quantity decided: N; applied directly, recommended M]`.

## Not verified

The SQL has not run against Postgres (the tables do not exist on `public`, and there is no local Postgres). The tests use a fake session answering by SQL text, so they check which statements run, in what order, with what values, and which never run. Run the migrations on a scratch schema and exercise each endpoint once before applying to `public`.
