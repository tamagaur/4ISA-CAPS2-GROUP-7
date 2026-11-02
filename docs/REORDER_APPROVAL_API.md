# Reorder approval and reversal: API for the frontend (2026-10-23)

Backend only. Code: `backend/routers/reorder_approval.py` (new), `backend/routers/recommendations.py` (PATCH gate).
Migrations **0067** (reversal) and **0068** (approval) are **applied** to `public` (2026-10-23). Before that
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
| `POST /recommendations/{key}/quantity-change` | `lp.decide` or `lp.propose` | `{quantity, reason, reviewed?, stock_observation?}` (reason required since 2026-10-28) | **202** `{outcome:"held", change}` or **200** `{outcome:"applied", item}` |
| `GET /recommendations/changes?state=pending_approval\|approved\|rejected\|all&recommendation_key=` | `lp.decide` or `lp.propose`; admin sees all, others only their own | | `{count, items:[change]}` newest first |
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


---

# Staff requests, stock counts and history (2026-10-28, migration 0070)

Code: `backend/routers/reorder_requests.py` (new), `backend/stock_observation.py` (new), guards added to
`backend/routers/reorder_approval.py` and `backend/routers/recommendations.py`. Tests: `tests/backend/test_reorder_requests.py`.
Migration **0070** (`lp_dismissal_request`, `lp_stock_observation`; written as 0069 and renumbered 2026-10-29, since
`0069_rollover_ledger.sql` was applied to `public` on 2026-10-24) is **written, NOT applied** to `public`; approved
by Yuan 2026-10-28, who applies it. Until it is applied the new endpoints answer 503 `requests_not_ready` and every existing path behaves as before (the dismissal
guard and the stock-count fields are only active once the tables exist).

## Permissions

| Key | Who | Lets them |
|---|---|---|
| `lp.view` | staff preset | see recommendations and which rows are under review (`GET /open-requests`) |
| `lp.propose` (new, in the staff preset, Yuan 2026-10-28; an admin can untick it per account) | staff | request a quantity change, request a dismissal, report stock counted, see their own requests and history |
| `lp.decide` (**admin-only**, Yuan 2026-10-28) | admin | accept or dismiss directly (PATCH), propose a quantity change |
| role `admin` | admin | approve or reject any request, verify a stock count, reverse a decision, grant direct apply |

Nobody settles their own request (409 `self_approval`). Settling routes check the role on top of the key.
`lp.decide` is never a staff permission: the catalog marks it `admin_only`, saving it for a staff account answers
422 `admin_only_permission` with nothing written, and a stored staff grant counts for nothing
(`backend/permissions.ADMIN_ONLY_KEYS`). Upstream, `lp.decide` also implies `lp.view` (Yuan, commit `a7b707d`, not
on this branch yet), which makes it wider than when this was first written.

Reasons: a request's reason and an admin's rejection reason are **8 to 500 characters once trimmed**, checked on the
server (422 otherwise) as well as on the page (`backend/schemas/recommendations.REQUEST_REASON_MIN`).

## State machine (one waiting request per row, either kind)

```
lp_dismissal_request.state
(staff asks, reason required)             --> pending_approval
pending_approval --approve (admin)--> approved   recommendation becomes dismissed (decided_by = the requester)
pending_approval --reject  (admin, reason)--> rejected   recommendation stays pending and active
```

- A request never changes the recommendation: `status` stays `pending`, `q_i` untouched, nothing counted in the plan.
- While a dismissal request OR a quantity change waits, nobody decides the row directly (PATCH 409) and no second
  request of either kind is accepted (409). Checked under the row lock (`FOR UPDATE`) in both request paths.
- Approval refused: row decided meanwhile (409), cycle superseded (request closed as rejected, 409), `q_i` moved by
  an LP rerun since the request (409 `recommendation_changed`: reject it, ask again), approver is the requester.

## Endpoints

| Method and path | Who | Body | Success |
|---|---|---|---|
| `POST /recommendations/{key}/dismissal-request` | `lp.propose` (not an admin: 400 `use_direct_dismissal`) | `{reason, stock_observation?}` | **202** request |
| `GET /recommendations/dismissal-requests?state=&recommendation_key=` | `lp.decide` or `lp.propose`; admin all, others own | | `{count, items}` |
| `POST /recommendations/dismissal-requests/{request_key}/approve` | admin | `{note?}` | request (approved) |
| `POST /recommendations/dismissal-requests/{request_key}/reject` | admin | `{reason}` required | request (rejected) |
| `PATCH /recommendations/{key}` (existing) | `lp.decide` | adds optional `stock_observation` on a dismissal | unchanged |
| `GET /recommendations/stock-observations?state=unverified\|verified\|rejected\|all&recommendation_key=` | `lp.decide` or `lp.propose`; admin all, others own | | `{count, items}` |
| `POST /recommendations/stock-observations/{key}/verify` | admin (not the reporter) | `{verified, note?}` (note required when false) | observation |
| `GET /recommendations/open-requests` | `lp.view` | | `{ready, items:[{kind, key, recommendation_key, recommended_q_i, proposed_q_i, requested_at, mine, requested_by}]}` (`requested_by` only for an admin or the requester) |
| `GET /recommendations/{key}/history` | `lp.decide` or `lp.propose` | | `{..., events:[{at, kind, actor, summary, quantity_before, quantity_after, reason}]}` oldest first; a non-admin sees their own requests and counts plus every decision |

`stock_observation` input: `{quantity, unit: "pieces"|"cases", counted_at?, location?, notes?}`.

## Units

The product master has ONE unit figure: `Product_Dimension.pack_size`, pieces per case (trusted, see
`backend/stock_units.py`). There is no packs-per-case, inner pack, minimum order or other order multiple anywhere, so:

- the plan's unit is pieces; quantities are entered in pieces or cases and always stored in pieces;
- a typed order quantity must be whole cases when the pack is > 1 (existing `backend/case_pack.py`, 422
  `not_whole_cases` with `nearest_below`/`nearest_above`); it is refused, never rounded;
- a stock count in cases needs a pack size (422 `no_case_size`) and a whole number (422 `not_whole_cases`); it is
  stored as typed plus `pieces_per_case` and `quantity_pieces` (a CHECK constraint keeps them consistent);
- "packs" are not offered anywhere: no data supports them.

## Stock counts are observations

`lp_stock_observation` keeps who, role, when (reported and counted), where, the unit typed, the pieces, the context
(`quantity_change`, `dismissal_request`, `direct_dismissal`) and a verification state. **Nothing in forecasting,
safety stock, target stock, the LP or the dashboards reads it** (`tests/backend/test_reorder_requests.py` fails if
anything in `analytics/`, `scripts/` or `transform/` mentions the table). Verifying records the check only.
Stock on hand stays `Inventory_Fact` (SSM's stock-on-hand file). Making a verified count stock on hand would be a new
Inventory_Fact load: **a pipeline decision for Yuan, not made here.** Target stock (`rop_i`) is never changed by a count.

**Yuan's ruling (2026-10-28): report-only until after the defence.** The reason is timing: 51 manuscript figures were
pinned on 2026-10-24, and a second stock source would move them. When it is wired, three conditions: a count feeds
the plan only once verified by someone other than the reporter; every plan states which stock figure it used and when
it was counted (as `count_date` and `opening_basis` do); and the change is visible and reversible. The no-reader test
above stays until then.

`lp_stock_observation` and the rollover's `expected_receipt` describe the same shelf from two directions (what someone
counted, what an accepted order should have delivered). A verified count that disagrees with an expected receipt is the
same signal as a receipt that never showed up in a count: the two need reconciling when the rollover goes live
(`docs/ROLLOVER_DESIGN.md`, on Yuan's branch).

## Audit log actions added

`Reorder Dismissal Requested`, `Reorder Dismissal Request Approved` / `Rejected` / `Closed`, `Stock Count Reported`,
`Stock Count Verified` / `Rejected`. A direct dismissal stays `Reorder Recommendation Dismissed`, so the two are told
apart. Quantity entries now add the case count, e.g. `47160 -> 48000 (2000 cases of 24)`.

## Constraint checks before approval

The only verified hard order rule is whole cases (enforced on the server). The LP stores no per-row ceiling, so the
page computes two WARNINGS from the row it already shows, and an admin must confirm them before approving:
the quantity ends the month above target stock (forecast + target stock - opening stock), and the plan was cut to the
supplier allocation while this raises an order. They are not enforced by the server: no stored figure would make
that check exact.

## Not verified

Rehearsed 2026-10-29 against `public` with the runner's `--rehearse` (one transaction, always rolled back, no
`schema_migrations` row): 0070 and 0071 applied cleanly, and five check queries passed inside the transaction (the
bell's list, its insert, both request lists with the requester's name, the indexes and row-level security). The
endpoints themselves have not run against Postgres yet. Applying is Yuan's (hard rule 8: backup, runner, restart Render).


---

# The notification bell (2026-10-28, migration 0071)

Code: `backend/notifications.py` (writes), `backend/routers/notifications.py` (reads), `frontend/src/components/
NotificationBell.jsx`. Tests: `tests/backend/test_notifications.py`. Migration **0071** (`user_notification`) is
**written, NOT applied**; it depends on 0070. Until it is applied `GET /notifications` answers `ready: false` and
requests and decisions behave exactly as before.

| Event | Who is notified | Kind |
|---|---|---|
| A quantity change is held for approval | every admin except the requester | `quantity_change_requested` |
| A dismissal is requested | every admin except the requester | `dismissal_requested` |
| An admin approves / rejects a change | the requester | `quantity_change_approved` / `_rejected` |
| An admin approves / rejects a dismissal | the requester | `dismissal_approved` / `_rejected` |

Each row is written in the same transaction as the request or decision (a refused request writes none), at most
once per recipient, event and request (unique index + `ON CONFLICT DO NOTHING`). The summary is built from the
request's fields only.

| Method and path | Who | Success |
|---|---|---|
| `GET /notifications?limit=30` | any signed-in user, own rows only | `{ready, unread_count, items:[{notification_key, kind, request_kind, request_key, recommendation_key, sku_code, product_name, actor_email, actor_name, summary, created_at, read_at, request_state}]}` |
| `POST /notifications/{key}/read` | own row only (someone else's: 404) | `{updated, unread_count}` |
| `POST /notifications/read-all` | own rows | `{updated, unread_count}` |

Reading sets `read_at` only: the unread count and the Staff Requests pending count are separate numbers, and
`request_state` is read from the request's own row. There is no live push: the bell asks every 60 s while the
window is visible, on focus, and after its own writes. A notification opens `/reorder?tab=requests&request=
<request_kind>-<request_key>`. Request lists now carry `proposed_by_name` / `requested_by_name` (from `users`).

Rehearsed with 0070 on 2026-10-29 (see above); NOT applied. Written as 0070, renumbered to 0071 with 0070.
