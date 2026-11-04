# Test plan and results: SSM Decision Support Dashboard

Written for: the manuscript's testing section (§4.3) and the panel. Backend and pipeline at `kelvin/freeze-package`
(commit 4a80d41, the HEAD the run was made from; working tree clean at its start). The frontend is out of scope for this run: a page whose only behaviour is in the frontend is marked "not executed",
with the reason given.

Contents: 1 Test items, 2 Features to be tested, 3 Item pass/fail criteria, 4 Test case results (two rounds), 5 Integration
testing coverage.

---

## 1. Test items

Each row names a function, the module it lives in, and the test files that exercise it. Rows are grouped by quality attribute.

### 1.1 Security

| # | Function | Module | Tested by |
|---|---|---|---|
| S1 | `require_permission(*keys)`: a 403 unless the user holds one of the keys | `backend/permissions.py` | `tests/backend/test_permissions.py`, `test_admin_only_writes.py` |
| S2 | `effective()`, `with_implied()`, `normalize()`: role preset + grants − removals; `lp.decide` implies `lp.view` | `backend/permissions.py` | `tests/backend/test_permissions.py` |
| S3 | `require_admin_for()`: only an admin creates, promotes, changes or deletes an admin | `backend/permissions.py` | `tests/backend/test_permissions.py`, `test_users.py` |
| S4 | `require_lp_admin`, `require_grant_admin`: approve, reject, reverse and grant need the key **and** the admin role | `backend/routers/reorder_approval.py` | `tests/backend/test_reorder_approval.py` |
| S5 | `get_current_user()`: re-reads the account, its role and its session on every request | `backend/deps.py` | `tests/backend/test_permissions.py`, `test_auth.py` |
| S6 | `decode_access_token()`: refuses expired, tampered and unsigned tokens | `backend/auth_utils.py` | `tests/backend/test_auth.py` |
| S7 | `LoginLimiter`: locks an email or an IP after 5 failures for 15 minutes | `backend/login_limiter.py` | `tests/backend/test_login_limiter.py`, `test_auth.py` |
| S8 | `InputGuardMiddleware`: refuses a NUL character or a non-finite JSON number with 400 | `backend/input_guard.py` | `tests/backend/test_client_errors.py` |
| S9 | `clean_error()`, `validation_error_handler()`: a 422 never echoes a password or other secret | `backend/error_redaction.py` | `tests/backend/test_secret_redaction.py` |
| S10 | `matching_step()`, `issue_pending_token()`: the second sign-in step (paused on the shipped server) | `backend/mfa.py` | `tests/backend/test_mfa.py` |
| S11 | `revoke_user_sessions()`: a role change or a deletion signs the user out | `backend/sessions.py` | `tests/backend/test_users.py`, `test_permissions.py` |

### 1.2 Reliability

| # | Function | Module | Tested by |
|---|---|---|---|
| R1 | `RecommendationDecision` validation: a dismissal reason of 8 to 500 characters; a finite, non-negative quantity | `backend/schemas/recommendations.py` | `tests/backend/test_recommendation_decisions.py` |
| R2 | The decision state machine: decided once, superseded cycles refused, reversal by an admin | `backend/routers/recommendations.py`, `backend/routers/reorder_approval.py` | `tests/backend/test_recommendation_decisions.py`, `test_reorder_approval.py` |
| R3 | `check_whole_cases()`: a typed quantity must be whole cases | `backend/case_pack.py` | `tests/backend/test_reorder_approval.py` |
| R4 | `stock_status()`: CRITICAL / LOW / IN STOCK / NO DATA / NO ROP, one rule for every screen | `backend/stock_status.py` | `tests/backend/test_stock_status.py`, `test_abc.py`, `test_recommendations.py` |
| R5 | `unilever_points()`, `gap_note()`: a no-row month is a zero (`no_sale`), a blank is null | `backend/series_gaps.py` | `tests/backend/test_series_gaps.py`, `test_forecast.py` |
| R6 | `stale_abc_refusal()`, `cycles_with_a_plan()`: the runners refuse a stale ABC period or an already-planned cycle (exit 2) | `scripts/run_guards.py` | `tests/test_run_guards.py`, `tests/optimization/test_run_lp_script.py` |
| R7 | `close_cycle` `PLAN_COUNTS_SQL`: refuses to close an incomplete plan | `scripts/close_cycle.py` | `tests/test_close_cycle.py` |
| R8 | The five cross-endpoint invariants: plan, cover, ABC basis, pinned figures, policy | `tests/invariants/` (live, read-only) | `tests/invariants/test_a_…` to `test_e_…` |

### 1.3 Efficiency

| # | Function | Module | Tested by |
|---|---|---|---|
| E1 | `cached(endpoint)`: a response cache keyed by data version and permission set | `backend/response_cache.py` | `tests/backend/test_response_cache.py` |
| E2 | `prefetch()`, `rows()`, `first()`: batches a route's statements into one round trip | `backend/batch.py` | `tests/backend/test_batch.py` |
| E3 | `planning_mart.refresh()`, `present()`: `/recommendations` reads one precomputed table | `backend/planning_mart.py` | `tests/test_planning_mart.py` |
| E4 | `marts.present()`: the range-based dashboard reads the data marts | `backend/marts.py` | `tests/test_marts.py`, `tests/backend/test_dashboard_range.py` |

### 1.4 Maintainability

| # | Function | Module | Tested by |
|---|---|---|---|
| M1 | Every `public.users` view against every `ALTER TABLE app.users`; no migration number used twice | `analytics/db/migrations/` | `tests/backend/test_migrations.py`, `tests/test_scratch_migration_guard.py` |
| M2 | `abc_method()`, `abc_method_sql()`: one Tier A basis, read from one setting | `analytics/params.py` | `tests/test_abc_reader_pinning.py`, `tests/forecasting/test_abc_method_pinning.py` |
| M3 | Parameters in one place, with a source tag | `analytics/params.py` | `tests/test_params.py` |
| M4 | `report_path()`: a run against a non-live database never rewrites a tracked report | `scripts/report_target.py` | `tests/test_report_target.py` |
| M5 | `check.sh` skip accounting: only the 18 listed opt-in tests may skip | `scripts/check.sh`, `scripts/known_opt_in_skips.txt` | `tests/test_check_helpers_skips.py` |
| M6 | Every route is guarded, and frontend keys equal the catalog | `backend/permissions.py` (`CATALOG`) | `tests/backend/test_permissions.py` |

### 1.5 Functionality

| # | Function | Module | Tested by |
|---|---|---|---|
| F1 | `run_abc()`: ABC by 12-month revenue, `t12m_new` Tier A | `analytics/classification/orchestrate_abc.py` | `tests/classification/test_orchestrate_abc.py`, `test_tier_a_basis.py`, `test_abc.py` |
| F2 | `classify_fsn()`: fast / slow / non-moving | `analytics/classification/fsn.py` | `tests/test_fsn.py` |
| F3 | `bin_at()`, `route()`: MA3 / TSB / XGBoost+MA3 by months with sales | `analytics/forecasting/router.py` | `tests/forecasting/test_router.py` |
| F4 | `calendar_factor()`: the March adjustment | `analytics/forecasting/calendar.py` | `tests/forecasting/test_calendar.py` |
| F5 | `_sigma_d_for_product()`, `safety_stock_for()`: σ_d and SS_i | `scripts/run_lp.py` | `tests/optimization/test_run_lp_script.py` |
| F6 | `compute_safety_stock()`, `target_stock()`, `net_need()`, `build_lp_model()`, `solve_lp()` | `analytics/optimization/lp.py` | `tests/optimization/test_lp.py` |
| F7 | `round_to_case_packs()`: whole packs, inside the ceilings | `analytics/optimization/lp.py` | `tests/optimization/test_case_pack_rounding.py` |
| F8 | The 18 routers behind the ten pages (dashboard, abc, forecast, category-trends, sku, recommendations, audit-log, users, auth, inventory, …) | `backend/routers/*.py` | `tests/backend/test_*.py` (one file per router) |

---

## 2. Features to be tested

The pages are the ten in the side navigation, in its order (`frontend/src/permissions/keys.js` `PAGES`, Main-FE), then the
two pages outside it. Definitions only.

| Feature | Definition |
|---|---|
| Dashboard | KPI cards (sales, stock value, weeks of cover, safety-stock rate), sales vs stock, ABC mix, tier stock, portfolio forecast, reorder preview, policy comparison, and the range cards (Pareto, year on year, accuracy, class changes, error decomposition) for a chosen principal and period. Opens with `dashboard.view`. LP figures need `lp.view`. |
| Reference Guide | Definitions of the dashboard's terms and figures. Opens with `dashboard.view`. Frontend only. |
| SKU Forecast | One product's actual monthly sales (gaps labelled) and its served forecast with status, model and MASE; a Del Monte category says why it has no product forecast. Opens with `forecast.view`. |
| Category Trends | Monthly revenue per category with a trend projection; Del Monte collection gaps labelled, not zeroed. Opens with `category_trends.view`. |
| SKU Management | The product master: list, add, edit; stock in pieces; the reorder point when the user holds `lp.view`. Opens with `sku.view`. Writing needs `sku.edit`. |
| ABC Classification | Class A/B/C per product for a period, with revenue shares, the Tier A basis per principal and stock status. Opens with `abc.view`. |
| Reorder Recs | The current cycle's plan: forecast, safety stock, target, stock, order, urgency; accept, dismiss, quantity change, approval, reversal. Opens with `lp.view`. Deciding needs `lp.decide`. Approving, rejecting, reversing and granting need the admin role. |
| Audit Log | Who changed what and when, and session lengths. Opens with `audit_log.view`. |
| Data Management | Uploads (Module 07). Opens with `upload.run`. A mock page: no backend route. |
| User Management | Invite, edit, delete users; roles and per-user permissions. Opens with `users.manage`. |
| Profile (outside the navigation) | The user's own name, picture and password. Any signed-in user. |
| Card preview (outside the navigation) | Section B cards on sample data. Admin only (`users.manage` route guard). |
| Role: Admin | Holds every permission, and overrides do not apply to it. Only an admin may approve, reject or reverse a decision, grant direct apply, or create, promote, change or delete an admin. At least one admin must remain. |
| Role: Staff | Preset: `dashboard.view`, `abc.view`, `forecast.view`, `category_trends.view`, `sku.view`, `lp.view` (`backend/permissions.py` `PRESETS`). By default, no `lp.decide`, `sku.edit`, `audit_log.view`, `upload.run` or `users.manage`. An admin may grant or remove single permissions for one staff user. |

---

## 3. Item pass/fail criteria

Modules follow the navigation. T-IDs and test-case IDs share a number (T5 ↔ TC05) up to T64; TC65-TC82 are the 18 opt-in tests of T65 and T66 (§4.3); TC83 is
T83. Each Pass and Fail is something a tester can observe.

### Dashboard

| Test ID | Test description | Criteria ID | Pass | Fail |
|---|---|---|---|---|
| T1 | Dashboard needs sign-in | C1 | `GET /dashboard` with no token answers 401 | Any 2xx, or a body with figures |
| T2 | LP figures withheld from a user without `lp.view` | C2 | The response, fresh or from the cache, has no `reorder_preview`, safety-stock or order figures | Any LP figure appears, including from another user's cached entry |
| T3 | Error decomposition needs `lp.view`, not only `dashboard.view` | C3 | The four `/dashboard/error-decomposition*` routes answer 403 to a `dashboard.view`-only user | 200 with figures |
| T4 | A year-0 period is a client error | C4 | `period=0000-01` answers 422 on every route that takes a period | 500 on any route |
| T5 | A start after the end is refused | C5 | `start_period` after `period` answers 422 | 200 over a silently swapped or substituted window |
| T6 | The plan total does not fall when a row is decided | C6 | After an accept, the Dashboard order total and product count equal `/recommendations`' (decided rows stay in the plan) | Dashboard total below the Reorder total after a decision |
| T7 | Live plan agreement across every path | C7 | `/recommendations`, `/dashboard`, the policy card, the mart and STATE.md all read 109 rows and 435,988 pieces | Any path differs, or STATE.md's `plan:` line differs from live |
| T8 | Weeks of cover is pieces over pieces and states its stock unit | C8 | `basis` "pieces"; `stock_value_unit` "pesos" and `stock_pieces` present; pinned 7.06 reproduces | Pesos stock value beside a pieces basis with no unit, or 7.06 does not reproduce |
| T9 | The Dashboard names its ABC basis | C9 | The response names its basis, and its ABC mix reproduces from the database | No basis named, or the mix does not reproduce |

### Reference Guide

| Test ID | Test description | Criteria ID | Pass | Fail |
|---|---|---|---|---|
| T10 | The page opens with `dashboard.view` and shows its terms | C10 | The page renders its 25 terms in five sections for a staff user | A blank page, a redirect, or a missing section |

### SKU Forecast

| Test ID | Test description | Criteria ID | Pass | Fail |
|---|---|---|---|---|
| T11 | Forecast needs sign-in | C11 | `GET /forecast/{sku}` with no token answers 401 | Any 2xx |
| T12 | Unilever gaps render as zero with a reason; a blank is null | C12 | A no-row month inside the product's span is `quantity: 0, reason: "no_sale"`; a blank capture is `null` with `blank_capture` | A no-row month absent or null, or a blank rendered as 0 |
| T13 | A Del Monte category says why there is no forecast | C13 | 200 with a `blocked_reason` | 404, or a fabricated forecast |
| T14 | A NUL character in the path is a client error | C14 | `/forecast/a%00b` answers 400 | 500 |
| T15 | The router picks the model by history length; the calendar factor reads only earlier months | C15 | 3-11 months with sales → MA3, 12-23 → TSB, 24+ → XGBoost+MA3; the factor uses months before the target only | Wrong bin at a boundary, or a factor that reads the target month or later |

### Category Trends

| Test ID | Test description | Criteria ID | Pass | Fail |
|---|---|---|---|---|
| T16 | A Del Monte category missing in a reported month is not a zero | C16 | That point has `revenue: null` and reason `category_absent` | `revenue: 0.0` |
| T17 | Generated months are labelled | C17 | In preview, every generated history point carries its origin label | A generated month indistinguishable from a real one |

### SKU Management

| Test ID | Test description | Criteria ID | Pass | Fail |
|---|---|---|---|---|
| T18 | Staff cannot add or edit a SKU, but can read | C18 | `POST /sku` and `PATCH /sku/{key}` as staff answer 403; `GET /sku` answers 200 | A staff write reaches the handler |
| T19 | A field the endpoint does not save is refused | C19 | `PATCH`/`POST` with `status`, `unit_price`, `lead_time_days` answers 4xx naming the field | 200 with the value silently dropped |
| T20 | SKU text and pack size are validated | C20 | A blank or over-long name, or a non-positive or non-numeric pack, answers 422; a Del Monte category row cannot be renamed | Stored as sent |
| T21 | A SKU code is exactly 8 digits | C21 | A code that is not 8 digits answers 422 | Created |
| T22 | The reorder point is left out without `lp.view` | C22 | `/sku` items carry no `reorder_point` or plan cycle for that user | Either field present |

### ABC Classification

| Test ID | Test description | Criteria ID | Pass | Fail |
|---|---|---|---|---|
| T23 | No revenue share summed across two principals | C23 | With no principal, no tier carries a share that adds both principals' shares | Shares totalling about 2.0 |
| T24 | The page names its Tier A basis per principal | C24 | Each principal's basis is in the response, and the tier counts reproduce from the database | Basis missing, or the counts do not reproduce |
| T25 | A second ABC re-run is served fresh | C25 | After the second re-run, cached `GET /abc` returns the new classes | The old classes from the cache |
| T26 | Classification arithmetic: ABC `t12m_new` and FSN | C26 | The unit tests' fixed cases give the stated class; the worked example reproduces the stored share and class | Any case gives another class |

### Reorder Recs

| Test ID | Test description | Criteria ID | Pass | Fail |
|---|---|---|---|---|
| T27 | `lp.decide` is not in the staff preset: staff cannot accept or dismiss | C27 | `PATCH /recommendations/{id}` as default staff answers 403 | 200, or the row changes |
| T28 | `lp.decide` implies `lp.view` | C28 | A user granted `lp.decide` with `lp.view` removed is still effectively granted `lp.view` | Can decide but is refused `GET /recommendations` |
| T29 | Approve, reject, reverse and grant are admin-only | C29 | A non-admin holding the key answers 403 `admin_required` | 200 |
| T30 | A dismissal under 8 characters is rejected | C30 | A 7-character reason (after trimming) answers 422 | 200, row dismissed |
| T31 | A dismissal over 500 characters is rejected | C31 | A 501-character reason answers 422 | 200 |
| T32 | A dismissal of 8 to 500 characters is accepted | C32 | 8 and 500 characters answer 200, row dismissed | 422 at either bound |
| T33 | A decided row cannot be decided again | C33 | A second decision answers 409 | 200, or the decision changes |
| T34 | Superseded cycles are refused, and an open change on one is closed | C34 | A decision on a superseded cycle answers 409 naming both cycles; approving a change on one closes it as rejected | 200, or a change stays `pending_approval` forever |
| T35 | A typed quantity must be whole cases | C35 | A part-case quantity answers 422 `not_whole_cases` | Applied as typed |
| T36 | A non-finite number is a client error | C36 | `NaN` or `Infinity` in the body answers 400 | 500 |
| T37 | Orders are counted apart from plan rows | C37 | `order_count` = rows with plan_q_i > 0, beside `count` | Only the 109 is given |
| T38 | The legacy accepted row stays outside the plan | C38 | Row 4 in `cycle=all` has `outside_plan: true`; it cannot be reversed back into the plan | It joins the plan (110 rows) |
| T39 | A flagged row needs a real review confirmation | C39 | Accepting a flagged row without `reviewed: true` (a JSON boolean) answers 4xx | `"reviewed": "yes"` accepted as true |
| T40 | LP arithmetic | C40 | SS_i, T_i and need_i follow the formulas; 0 ≤ Q_i ≤ need_i; rounding stays inside the ceilings | Any unit case breaks one of these |
| T41 | The LP refuses an already-planned cycle | C41 | A real run on a cycle with run-keyed rows exits 2 unless `--replan` | rc 0, and the plan moves |
| T42 | Both runners refuse a stale ABC period | C42 | ABC older than the latest real sales month exits 2 unless `--allow-stale-abc` | rc 0 |
| T43 | `close_cycle` refuses an incomplete plan | C43 | LP rows ≠ ok forecasts with MASE < 1 exits 2 and names both counts | The close writes |
| T44 | The plan reproduces from its inputs | C44 | One product's SS_i, T_i, need_i and plan_q_i, and the 435,988 total, are recomputed from raw rows equal to the stored values | Any value differs beyond 2-decimal storage |
| T83 | The forecast and the safety-stock calculation never read a decided quantity or a decision reason | C83 | The guard test finds no decision column and no `plan_q_i` in the forecasting package, the forecast runner, the LP's safety-stock functions or the backend modules that compute them; a planted read is caught | It names a file that reads one |

### Audit Log

| Test ID | Test description | Criteria ID | Pass | Fail |
|---|---|---|---|---|
| T45 | Staff cannot read the audit log | C45 | `GET /audit-log` as staff answers 403; with no token 401 | 200 |
| T46 | A negative limit is a client error | C46 | `limit=-1` answers 422 | 503 or 500 |
| T47 | A replayed grant writes one audit entry | C47 | Granting twice, or revoking nothing, writes no second entry | Two "Direct Apply Granted" entries, or a "Revoked" for no grant |
| T48 | Decisions, proposals and reversals are audited | C48 | Each writes one entry with who, when, both quantities or the reason | A transition with no entry |

### Data Management

| Test ID | Test description | Criteria ID | Pass | Fail |
|---|---|---|---|---|
| T49 | Staff do not hold `upload.run` | C49 | The staff preset and the frontend's legacy list both lack `upload.run` | Either includes it |
| T50 | An upload runs | C50 | A file uploaded on the page is loaded | No load |
| T65 | Fill rules on a rehearsal schema (17 opt-in tests) | C65 | Each of the 17 passes on a schema built by `rehearse_fills --build` | Any fails |
| T66 | Rollover end to end on a scratch clone (1 opt-in test) | C66 | All checks of `rollover_scratch_test.py` pass | Any check fails |

### User Management

| Test ID | Test description | Criteria ID | Pass | Fail |
|---|---|---|---|---|
| T51 | Staff cannot list, edit or delete users | C51 | 403 on each | 200 |
| T52 | `users.manage` without the admin role cannot reach an admin | C52 | Creating, granting, modifying or deleting an admin answers 403 `admin_required`; widening one's own access 409 | 200 |
| T53 | At least one admin remains | C53 | Demoting or deleting the last admin is refused; nobody locks themselves out | The last admin is removed |
| T54 | A contradictory override is normalised | C54 | `lp.view:false` beside `lp.decide:true` is stored as `{lp.decide: true}` | The removal is stored |
| T55 | Access changes apply on the next request | C55 | The role and permissions are read from the database per request; a role change signs the user out | The token's role is trusted |

### Sign-in and Profile (outside the navigation)

| Test ID | Test description | Criteria ID | Pass | Fail |
|---|---|---|---|---|
| T56 | Invalid tokens are refused | C56 | Missing, expired, tampered and unsigned tokens answer 401 | Any 2xx |
| T57 | Five wrong passwords lock the email | C57 | The 5th failure locks; the correct password is refused while locked; the lock lifts after 15 minutes | The 6th attempt is checked |
| T58 | A NUL in a sign-in field is a client error | C58 | 400 | 500 |
| T59 | A 422 never echoes a password | C59 | The 422 body names the missing field and has no password value | The password appears in the body |
| T60 | Two-step sign-in (in-process), and paused on the shipped app | C60 | With it on, the password alone opens no session, the right code signs in once, wrong codes lock; the shipped default is paused | A password alone opens a session with it on |
| T61 | The profile edits only one's own account | C61 | A rename is trimmed and audited; bad names 422; another user's picture is refused | Another account changes |
| T62 | Forgot password follows the recorded decision | C62 | Known email: 202 and one mail; unknown: 404 "not registered", nothing sent (Audrey's decision of 2026-09-30) | A mail to an unknown email, or no mail to a known one |
| T63 | Every page opens on its own permission, for each preset | C63 | Each page's routes answer 200 on its own permission, with any one other box unticked; every route is guarded | A page needs a permission it does not declare, or a route is unguarded |
| T64 | The routes behind the pages answer on live data | C64 | `scripts/smoke_api.py`: every route 200 and PASS | Any non-200 or FAIL |

---

## 4. Test case results

### 4.1 How each round was produced

**Round 1: before the October fixes. Reconstructed only from what is in the repository.** Sources, each at the commit it names:

| Key | Source | Commit | What it is |
|---|---|---|---|
| AUD | `reports/AUDIT_2026-10-23.md` | 492365f | In-process API against live, read-only; 13 findings + "Part 1" consistency |
| QAB | `reports/QA_BACKEND_2026-10-24.md` | d2664ec | In-process API against live, all writes rolled back; 16 findings + "What held" |
| QAP | `reports/QA_PIPELINE_2026-10-30.md` | 5507f41 | Throwaway local Postgres; 10 findings + "What held"; the 18 opt-in tests |
| SUITE | `docs/CH4-5_EDITS_2026-10-22_corrected.md` item 16 | c70c88d | Suite totals only: 1,738 passed, 0 failed, 18 skipped. No per-test list |

A round-1 cell says Pass or Fail only when one of these sources records that behaviour. Where none does, the cell says
**no round-1 record**, which is neither a pass nor a fail. SUITE names no test, so it supports no single row.

**Round 2: executed 2026-10-31.**

| # | Command | Output |
|---|---|---|
| R2-a | `coverage run --branch --source=backend,analytics,scripts,transform -m pytest tests -q -p no:cacheprovider -rs --junitxml=…` | **2,049 passed, 1 failed, 18 skipped** in 0:12:25, rc 1 (2,068 test cases in the junit file). The failure is TC83; the 18 skips are §4.3 |
| R2-b | `python scripts/smoke_api.py` (read-only, live) | 14 routes, all 200 PASS; rc 0 |
| R2-c | `python -m scripts.snapshot_published_figures --verify` (read-only, live) | "OK: 51 figures reproduced from the frozen rows"; rc 0 |
| R2-d | `trace.py 39`, `trace.py 853`, `portfolio.py` (read-only, live; see `docs/MANUSCRIPT_WORKED_CALCULATIONS.md`) | every recomputed value equals the stored one |
| R2-e | `scripts/check.sh --optin`, executed 2026-11-03 on a disposable database (`ssm_optin` on 127.0.0.1:55432, seeded from `backups/full_backup_20261102T170343Z`, never live) | **18 of 18 passed**, rc 0; connections refused by the guard: 0; the database dropped afterwards |

A round-2 cell reads **Pass** only if every mapped test ran and passed in R2-a, or in R2-e for the 18 opt-in tests of §4.3 (parametrised instances included; the count
is in brackets). A mapped test that did not run would read **not executed**, never pass. The mapping is in the last column.

### 4.2 Results

| TC | T | C | Round 1 (before the fixes) | Round 2 (2026-10-31) | Round-2 evidence (tests in R2-a unless stated) |
|---|---|---|---|---|---|
| TC01 | T1 | C1 | Pass (QAB What held, Part 1: no token, 401 on every protected route) | **Pass** | `test_dashboard.py::test_requires_auth` [1] |
| TC02 | T2 | C2 | Pass (QAB finding 8: "the Dashboard/ABC/SKU pages leave LP figures out" for a user without `lp.view`) | **Pass** | `test_response_cache.py::test_the_dashboard_never_serves_lp_figures_to_a_user_without_lp_view` [1] |
| TC03 | T3 | C3 | no round-1 record (the `lp.view` gate was added 2026-10-28; no report probed these routes without it) | **Pass** | `test_dashboard_range.py::test_error_decomposition_needs_lp_view_not_just_dashboard_view` [4] |
| TC04 | T4 | C4 | **Fail** (QAB finding 5: `period=0000-01` 500 on 12 routes) | **Pass** | `test_client_errors.py::test_year_zero_is_a_422_on_the_routes_that_500ed` [10], `test_client_errors.py::test_no_route_takes_year_zero_as_a_period` [1] |
| TC05 | T5 | C5 | **Fail** (QAB finding 9: start after end answered 200 over another window) | **Pass** | `test_qa_findings_8_15.py::test_a_start_after_the_end_is_refused_not_swapped` [1] |
| TC06 | T6 | C6 | **Fail** (AUD finding 2: after one accept, Dashboard 427,060 against Reorder 435,988) | **Pass** | `test_recommendation_decisions.py::test_every_plan_read_uses_the_plan_statuses` [1], `test_recommendation_decisions.py::test_the_cycle_anchor_counts_decided_rows` [1] |
| TC07 | T7 | C7 | Pass (AUD Part 1a: 435,988, 109 rows, agree before any decision) | **Pass** | `test_a_plan_agreement.py::test_plan_row_count_and_total_agree_across_every_path` [1], `test_a_plan_agreement.py::test_state_md_plan_line_matches_the_live_plan` [1], `test_e_policy_agreement.py::test_portfolio_totals_agree_across_plan_policy_dashboard_and_mart` [1] |
| TC08 | T8 | C8 | **Fail** (QAP finding 10: `stock_value` in pesos beside `basis: pieces`; 7.06 itself reproduced) | **Pass** | `test_dashboard.py::test_kpis_weeks_of_cover_real_value` [1], `test_b_cover_agreement.py::test_dashboard_weeks_of_cover_is_pieces_over_pieces_for_its_stated_window` [1], `test_d_pinned_figures.py::test_every_pinned_figure_reproduces_from_the_frozen_rows` [1]; also R2-c |
| TC09 | T9 | C9 | **Fail** (AUD finding 1: "neither card says which basis it is") | **Pass** | `test_c_abc_basis.py::test_dashboard_states_its_basis_and_its_abc_mix_reproduces` [1], `test_c_abc_basis.py::test_the_dashboard_names_the_planning_basis_the_abc_page_uses` [1] |
| TC10 | T10 | C10 | no round-1 record | **not executed**: frontend-only page with no backend route, and the frontend is out of scope (no frontend test runner in the repo) | |
| TC11 | T11 | C11 | Pass (QAB What held, Part 1) | **Pass** | `test_forecast.py::test_requires_auth` [1] |
| TC12 | T12 | C12 | Partial: the `no_sale` half Pass (QAB Part 4: SKU 67223599 forecast `[no_sale]` gap note); the blank half no round-1 record | **Pass** | `test_forecast.py::test_actuals_render_a_no_row_month_as_zero_and_a_blank_as_null_with_reasons` [1], `test_series_gaps.py::test_no_row_between_first_and_last_sale_is_zero_no_sale` [1], `test_series_gaps.py::test_blank_quantity_is_null_never_zero` [1] |
| TC13 | T13 | C13 | Pass (QAB Part 4: "200 with `blocked_reason` on `/forecast`") | **Pass** | `test_forecast.py::test_del_monte_says_why_there_is_no_forecast_instead_of_404` [1] |
| TC14 | T14 | C14 | **Fail** (QAB finding 6: path `/forecast/a%00b` 500) | **Pass** | `test_client_errors.py::test_a_nul_in_the_path_or_query_is_a_400` [6] |
| TC15 | T15 | C15 | no round-1 record (SUITE totals only) | **Pass** | `test_router.py` (whole module) [46], `test_calendar.py` (whole module) [9] |
| TC16 | T16 | C16 | **Fail** (QAP finding 7: `revenue: 0.0` on 3 `category_absent` points) | **Pass** | `test_category_trends.py::test_delmonte_category_absent_month_has_no_revenue_value` [1] |
| TC17 | T17 | C17 | **Fail** (AUD finding 8: generated 2021-2022 months shown as ordinary history) | **Pass** | `test_category_trends.py::test_generated_months_are_labelled_in_preview_history` [1] |
| TC18 | T18 | C18 | Pass (QAB What held, Part 1: staff preset 403 exactly where the permission is absent) | **Pass** | `test_admin_only_writes.py::test_staff_cannot_write` [3], `test_admin_only_writes.py::test_staff_can_still_read` [1] |
| TC19 | T19 | C19 | **Fail** (QAB finding 1: `PATCH /sku/38 {"status":"DISABLED"}` 200, nothing changed) | **Pass** | `test_sku_writes.py::test_patch_refuses_a_field_it_does_not_save` [5], `test_sku_writes.py::test_post_refuses_a_field_it_does_not_save` [3] |
| TC20 | T20 | C20 | **Fail** (QAB finding 10: blank and 5 MB names and pack `abc` stored) | **Pass** | `test_qa_findings_8_15.py::test_a_sku_name_must_be_present_and_bounded` [4], `test_qa_findings_8_15.py::test_a_pack_size_must_be_a_positive_number` [7], `test_qa_findings_8_15.py::test_a_del_monte_category_row_cannot_be_renamed_by_hand` [1] |
| TC21 | T21 | C21 | Pass (QAB finding 10: "SKU codes are checked (exactly 8 digits, unique)") | **Pass** | `test_sku.py::test_create_rejects_a_code_that_is_not_8_digits` [5] |
| TC22 | T22 | C22 | Pass (QAB finding 8, as TC02) | **Pass** | `test_sku.py::test_reorder_point_is_left_out_without_lp_view` [1], `test_sku.py::test_plan_cycle_is_left_out_without_lp_view` [1] |
| TC23 | T23 | C23 | **Fail** (AUD finding 5: shares A 1.521, B 0.318, C 0.157) | **Pass** | `test_abc.py::test_two_principals_do_not_get_a_summed_revenue_share` [1] |
| TC24 | T24 | C24 | **Fail** (AUD finding 1) | **Pass** | `test_abc.py::test_the_abc_response_names_its_tier_a_basis_per_principal` [1], `test_c_abc_basis.py::test_abc_page_states_its_basis_and_its_tier_counts_reproduce` [1] |
| TC25 | T25 | C25 | **Fail** (QAP finding 3: changes 2 and 3 served from the cache) | **not executed**: open defect P3 (KNOWN_ISSUES.md, needs a migration); its reproduction needs the throwaway local Postgres (`scripts/local_pg.py`), which this session did not build | |
| TC26 | T26 | C26 | no round-1 record (SUITE totals only) | **Pass** | `test_fsn.py` (whole module) [8], `test_orchestrate_abc.py` (whole module) [4], `test_tier_a_basis.py` (whole module) [8]; also R2-d (ABC share and class, FSN recomputed for 2 products) |
| TC27 | T27 | C27 | Pass (QAB What held, Part 1) | **Pass** | `test_permissions.py::test_the_presets_are_the_proposals_design_table` [1], `test_admin_only_writes.py::test_staff_cannot_write` [3] |
| TC28 | T28 | C28 | **Fail** (QAB finding 8: decide without `lp.view`, refused `GET /recommendations`) | **Pass** | `test_permissions.py::test_lp_decide_implies_lp_view` [1] |
| TC29 | T29 | C29 | Pass (QAB What held, Part 1: "also refuse a non-admin who holds the key (403 `admin_required`)") | **Pass** | `test_reorder_approval.py::test_only_an_admin_can_approve_reject_reverse_or_grant` [1], `test_reorder_approval.py::test_the_admin_routes_also_check_the_role_not_only_the_key` [1] |
| TC30 | T30 | C30 | **Fail** (QAB finding 15: reason "x" accepted, 200) | **Pass** | `test_recommendation_decisions.py::test_a_dismissal_reason_under_8_characters_is_rejected` [5] |
| TC31 | T31 | C31 | Pass (QAB finding 15: 501 characters refused, 422) | **Pass** | `test_recommendation_decisions.py::test_a_dismissal_reason_over_500_characters_is_rejected` [1] |
| TC32 | T32 | C32 | Pass at 500 (QAB finding 15: 500 accepted); the 8 bound did not exist yet | **Pass** | `test_recommendation_decisions.py::test_a_dismissal_reason_of_8_to_500_characters_is_accepted` [3] |
| TC33 | T33 | C33 | Pass (QAB What held, Part 3: decided to anything 409) | **Pass** | `test_recommendation_decisions.py::test_a_decided_row_cannot_be_decided_again` [2] |
| TC34 | T34 | C34 | **Fail** (AUD finding 9: a change on a superseded cycle could never be approved and stayed queued) | **Pass** | `test_recommendation_decisions.py::test_a_row_in_a_superseded_cycle_is_refused_with_both_cycles_named` [1], `test_reorder_approval.py::test_a_change_on_a_superseded_cycle_is_closed_not_left_in_the_queue` [1] |
| TC35 | T35 | C35 | **Fail** (AUD finding 4: a part-case quantity applied) | **Pass** | `test_reorder_approval.py::test_direct_apply_by_a_granted_planner_refuses_a_part_case_quantity` [1], `test_reorder_approval.py::test_patch_by_a_granted_planner_refuses_a_part_case_quantity` [1] |
| TC36 | T36 | C36 | **Fail** (QAB finding 7: `NaN` 500) | **Pass** | `test_client_errors.py::test_a_non_finite_number_on_the_decision_route_is_a_400` [1], `test_client_errors.py::test_a_json_non_finite_number_is_a_400_not_a_500` [3] |
| TC37 | T37 | C37 | **Fail** (AUD finding 12: 109 reported with 36 zero orders inside it, no order count) | **Pass** | `test_recommendation_decisions.py::test_order_count_counts_only_items_planning_an_order` [1] |
| TC38 | T38 | C38 | **Fail** (AUD finding 13 and QAB finding 2: reversing row 4 made the plan 110 rows) | **Pass** | `test_recommendations.py::test_a_decided_row_no_lp_run_produced_is_labelled_outside_the_plan` [1], `test_reorder_approval.py::test_a_decided_row_with_no_lp_run_cannot_be_reversed_into_the_plan` [1] |
| TC39 | T39 | C39 | **Fail** (QAB finding 14: `"reviewed":"yes"` read as true) | **Pass** | `test_recommendations.py::test_a_flagged_row_is_never_accepted_without_review` [1], `test_qa_findings_8_15.py::test_reviewed_must_be_a_real_boolean` [3] |
| TC40 | T40 | C40 | no round-1 record (SUITE totals only) | **Pass** | `test_lp.py` (whole module) [23], `test_case_pack_rounding.py` (whole module) [12]; also R2-d |
| TC41 | T41 | C41 | **Fail** (QAP finding 1: re-plan 356,254 to 360,956, rc 0) | **Pass** | `test_run_lp_script.py::test_main_refuses_an_already_planned_cycle_and_a_stale_abc_period` [1], `test_run_guards.py::test_cycles_with_a_plan_counts_only_rows_that_came_from_a_run` [1] |
| TC42 | T42 | C42 | **Fail** (QAP finding 2: both runners rc 0 on a stale ABC) | **Pass** | `test_run_guards.py::test_stale_abc_is_refused_and_current_abc_is_not` [1], `test_run_guards.py::test_both_runners_expose_the_escape_flags` [1] |
| TC43 | T43 | C43 | **Fail** (QAP finding 5: one forecast and one LP row passed all five checks) | **Pass** | `test_close_cycle.py::test_an_incomplete_plan_refuses_and_names_the_count_on_each_side` [1], `test_close_cycle.py::test_a_complete_plan_109_against_109_does_not_refuse` [1], `test_close_cycle.py::test_forecast_check_is_completeness_not_existence` [1], `test_close_cycle.py::test_main_exits_2_on_a_refusal_even_for_a_dry_run` [1] |
| TC44 | T44 | C44 | Pass for the totals (AUD Part 1a/1b: 435,988; Σ`ss_i` 557,611.70; Σ`rop_i` 1,005,660.91); per-product trace no round-1 record | **Pass**: R2-d. Product 39: SS 1,822.16, T 3,976.53, need 9,723.32, plan 9,744. Product 853: need 0. Total 118,644 + 67,276 + 250,068 = 435,988 | `trace.py`, `portfolio.py` (row counts in the worked-calculations file) |
| TC45 | T45 | C45 | Pass (QAB What held, Part 1) | **Pass** | `test_audit_log.py::test_staff_cannot_read_the_audit_log` [2], `test_audit_log.py::test_requires_auth` [1] |
| TC46 | T46 | C46 | **Fail** (QAB finding 11: `limit=-1` 503) | **Pass** | `test_qa_findings_8_15.py::test_a_negative_audit_log_limit_is_a_422_not_a_503` [1] |
| TC47 | T47 | C47 | **Fail** (QAB finding 12: two "Direct Apply Granted" entries) | **Pass** | `test_qa_findings_8_15.py::test_a_replayed_grant_or_a_revoke_with_nothing_to_revoke_writes_no_audit_entry` [1], `test_qa_findings_8_15.py::test_a_real_grant_or_revoke_is_audited_once` [1] |
| TC48 | T48 | C48 | Pass (QAB What held, Part 3/6: audit entries equal successful transitions per action) | **Pass** | `test_reorder_approval.py::test_a_reversal_is_audited_with_who_when_and_why` [1], `test_reorder_approval.py::test_a_proposal_is_audited_with_who_and_both_quantities` [1], `test_recommendations.py::test_reviewed_accept_is_recorded_in_the_audit_log` [1] |
| TC49 | T49 | C49 | no round-1 record (no backend route to probe) | **Pass** | `test_permissions.py::test_the_presets_are_the_proposals_design_table` [1], `test_permissions.py::test_frontend_legacy_staff_access_is_the_staff_preset` [1] |
| TC50 | T50 | C50 | no round-1 record | **not executed**: the page is a mock (`keys.js`: "a non-working mock"); no backend route exists | |
| TC51 | T51 | C51 | Pass (QAB What held, Part 1) | **Pass** | `test_users.py::test_list_users_forbidden_for_non_admin` [1], `test_users.py::test_update_user_forbidden_for_non_admin` [1], `test_users.py::test_delete_user_forbidden_for_non_admin` [1], `test_permissions.py::test_the_admin_endpoints_need_users_manage` [3] |
| TC52 | T52 | C52 | Pass (QAB What held, Part 1: `users.manage` without admin 403 `admin_required`, own access 409) | **Pass** | `test_permissions.py::test_users_manage_alone_cannot_create_an_admin_account` [1], `test_permissions.py::test_users_manage_alone_cannot_grant_admin` [2], `test_permissions.py::test_users_manage_alone_cannot_modify_an_existing_admin` [7], `test_permissions.py::test_users_manage_alone_cannot_delete_an_admin_account` [1], `test_permissions.py::test_postman_someone_given_users_manage_cannot_widen_their_own_access` [3] |
| TC53 | T53 | C53 | no round-1 record (QAB records "cannot change their own role or delete themselves", not the last-admin rule) | **Pass** | `test_permissions.py::test_the_last_admin_cannot_be_demoted_or_deleted` [1], `test_permissions.py::test_nobody_can_lock_themselves_out` [2] |
| TC54 | T54 | C54 | **Fail** (QAP finding 8: `lp.view:false` stored beside `lp.decide:true`) | **Pass** | `test_permissions.py::test_normalize_drops_a_removal_that_an_implied_grant_undoes` [1] |
| TC55 | T55 | C55 | Pass (QAB What held, Part 1: "The role in the token is ignored") | **Pass** | `test_permissions.py::test_the_role_comes_from_the_database_not_the_token` [1], `test_permissions.py::test_an_unticked_box_applies_on_the_next_request` [1], `test_permissions.py::test_a_role_change_signs_the_user_out_like_edit_user_does` [1] |
| TC56 | T56 | C56 | Pass (QAB What held, Part 1: missing, expired, tampered, `alg:none` all 401) | **Pass** | `test_auth.py::test_decode_expired_token_raises` [1], `test_auth.py::test_decode_tampered_signature_raises` [1], `test_auth.py::test_unsigned_token_is_rejected` [1], `test_permissions.py::test_postman_a_missing_or_bad_token_is_401` [42], `test_permissions.py::test_postman_an_expired_token_says_so` [1], `test_admin_only_writes.py::test_writes_still_require_a_token` [3] |
| TC57 | T57 | C57 | no round-1 record (QAB "Not run": the lockout limiter's timing) | **Pass** | `test_auth.py::test_fifth_wrong_password_locks_the_email` [1], `test_auth.py::test_correct_password_is_refused_while_locked` [1], `test_login_limiter.py::test_locks_on_the_fifth_failure_not_before` [1], `test_login_limiter.py::test_lock_expires_after_fifteen_minutes_with_a_fresh_count` [1] |
| TC58 | T58 | C58 | **Fail** (QAB finding 6: NUL in the sign-in password 500) | **Pass** | `test_client_errors.py::test_sign_in_with_a_nul_in_the_password_is_a_400_not_a_500` [1], `test_client_errors.py::test_sign_in_with_a_nul_in_the_email_is_a_400` [1] |
| TC59 | T59 | C59 | **Fail** (QAB finding 16: 422 echoed `"password":"Hunter2-secret"`) | **Pass** | `test_secret_redaction.py::test_a_422_never_echoes_a_secret` [11], `test_secret_redaction.py::test_the_reported_case_is_a_422_that_names_the_missing_field_only` [1] |
| TC60 | T60 | C60 | no round-1 record (QAB "Not run": MFA answered 503 on live) | **Pass** | `test_mfa.py::test_with_it_the_password_alone_opens_no_session` [1], `test_mfa.py::test_the_right_code_signs_in_and_works_only_once` [1], `test_mfa.py::test_wrong_codes_lock_like_wrong_passwords` [1], `test_mfa.py::test_the_shipped_app_has_two_step_sign_in_paused` [1]. In-process only: the shipped server has it paused, so live two-step sign-in was **not executed** |
| TC61 | T61 | C61 | no round-1 record | **Pass** | `test_profile.py::test_rename_trims_saves_and_is_audited` [1], `test_profile.py::test_bad_names_are_refused` [3], `test_avatar.py::test_user_cannot_set_another_users_avatar` [1] |
| TC62 | T62 | C62 | no comparable round-1 record (QAB recorded "the same 202 for a known and an unknown email" with SMTP blanked; see Contradictions) | **Pass** | `test_accounts.py::test_forgot_password_sends_a_link_to_a_registered_email` [1], `test_accounts.py::test_forgot_password_says_when_no_account_uses_the_email` [1] |
| TC63 | T63 | C63 | Pass (QAB What held, Part 1: 71 routes, 15 identities, no guard missing) | **Pass** | `test_permissions.py::test_every_page_works_for_each_preset_with_any_one_box_unticked` [2], `test_permissions.py::test_each_page_works_on_its_own_permission_alone` [11], `test_permissions.py::test_every_route_is_guarded` [1] |
| TC64 | T64 | C64 | Pass on 2026-09-20 (CLAUDE.md: `smoke_api.py` 17 of 17 routes 200; a different route list) | **Pass**: R2-b, 14 of 14 routes 200 PASS (`/dashboard` ×3, `/abc` ×3, `/sku` ×3, `/recommendations`, `/inventory/current`, `/inventory/movement`, `/inventory/receipt-signals`, `/audit-log`) | `scripts/smoke_api.py` |
| TC83 | T83 | C83 | **Fail** (KNOWN_ISSUES.md, Closed on 2026-10-30, "(test)": failed on a clean checkout because it scanned the QA harness `scripts/local_api_qa_matrix.py`) | **Fail** | `tests/backend/test_recommendation_decisions.py::test_only_the_displayed_plan_total_reads_the_decided_quantity` [failed=1]. It names `scripts/manuscript_figures.py` (commit 4a80d41, 2026-10-31), which reads `plan_q_i` from the API response to draw a figure and feeds nothing back. That is the same shape as the QA-harness exemption. Not fixed here: `scripts/` and the test are outside this run's scope |

### 4.3 The 18 opt-in tests (`scripts/known_opt_in_skips.txt`)

Round 2: **Pass** for all 18, by `scripts/check.sh --optin` on 2026-11-03 (R2-e). They did not run in R2-a on 2026-10-31, where they skipped with the reasons listed in `scripts/known_opt_in_skips.txt`: each needs a filled rehearsal schema (`FILLS_SCRATCH_SCHEMA`) or a scratch clone (`ROLLOVER_SCRATCH=1`), and neither could be built on live.
R2-e builds both inside a disposable database restored from a local backup and refuses any other destination (`scripts/optin_guard.py`). A pass there shows the tests pass on a copy of the backup's date. It says nothing about live, where they must never run, and these 18 are not in the R2-a coverage figures of §5.

| TC | T | C | Test (`tests/etl/…`) | Round 1 | Round 2 |
|---|---|---|---|---|---|
| TC65 | T65 | C65 | `test_fills_db::test_a_second_run_changes_nothing` | Pass (QAP Task 1: 17 of 17 passed on `ssm_fills`, 73 s) | **Pass** (R2-e, `scripts/check.sh --optin`, 2026-11-03) |
| TC66 | T65 | C65 | `test_fills_db::test_real_rows_replace_the_fill_and_the_missing_branch_gets_its_adjacent_month` | Pass (QAP Task 1: 17 of 17 passed on `ssm_fills`, 73 s) | **Pass** (R2-e, `scripts/check.sh --optin`, 2026-11-03) |
| TC67 | T65 | C65 | `test_fills_db::test_the_sweep_removes_fills_the_loader_missed` | Pass (QAP Task 1: 17 of 17 passed on `ssm_fills`, 73 s) | **Pass** (R2-e, `scripts/check.sh --optin`, 2026-11-03) |
| TC68 | T65 | C65 | `test_fills_db::test_a_cell_that_once_held_real_rows_stays_empty` | Pass (QAP Task 1: 17 of 17 passed on `ssm_fills`, 73 s) | **Pass** (R2-e, `scripts/check.sh --optin`, 2026-11-03) |
| TC69 | T65 | C65 | `test_fills_db::test_a_new_stock_and_sales_month_produces_new_derived_receipts` | Pass (QAP Task 1: 17 of 17 passed on `ssm_fills`, 73 s) | **Pass** (R2-e, `scripts/check.sh --optin`, 2026-11-03) |
| TC70 | T65 | C65 | `test_fills_db::test_del_monte_split_totals_equal_real_sell_out_totals` | Pass (QAP Task 1: 17 of 17 passed on `ssm_fills`, 73 s) | **Pass** (R2-e, `scripts/check.sh --optin`, 2026-11-03) |
| TC71 | T65 | C65 | `test_fills_db::test_real_views_hold_only_real_rows_and_pass_the_forecast_guard` | Pass (QAP Task 1: 17 of 17 passed on `ssm_fills`, 73 s) | **Pass** (R2-e, `scripts/check.sh --optin`, 2026-11-03) |
| TC72 | T65 | C65 | `test_fills_db::test_the_estimated_received_series_reads_only_the_derived_table` | Pass (QAP Task 1: 17 of 17 passed on `ssm_fills`, 73 s) | **Pass** (R2-e, `scripts/check.sh --optin`, 2026-11-03) |
| TC73 | T65 | C65 | `test_fills_db::test_a_reviewed_category_map_switches_the_split_to_category_level` | Pass (QAP Task 1: 17 of 17 passed on `ssm_fills`, 73 s) | **Pass** (R2-e, `scripts/check.sh --optin`, 2026-11-03) |
| TC74 | T65 | C65 | `test_fills_db::test_a_missing_branch_beside_a_real_branch_copies_its_previous_month` | Pass (QAP Task 1: 17 of 17 passed on `ssm_fills`, 73 s) | **Pass** (R2-e, `scripts/check.sh --optin`, 2026-11-03) |
| TC75 | T65 | C65 | `test_fills_db::test_a_branch_copy_follows_its_adjacent_month` | Pass (QAP Task 1: 17 of 17 passed on `ssm_fills`, 73 s) | **Pass** (R2-e, `scripts/check.sh --optin`, 2026-11-03) |
| TC76 | T65 | C65 | `test_fills_db::test_real_rows_for_the_missing_branch_replace_its_fill` | Pass (QAP Task 1: 17 of 17 passed on `ssm_fills`, 73 s) | **Pass** (R2-e, `scripts/check.sh --optin`, 2026-11-03) |
| TC77 | T65 | C65 | `test_fills_db::test_a_branch_that_once_held_real_rows_is_not_refilled` | Pass (QAP Task 1: 17 of 17 passed on `ssm_fills`, 73 s) | **Pass** (R2-e, `scripts/check.sh --optin`, 2026-11-03) |
| TC78 | T65 | C65 | `test_fills_db::test_a_product_missing_from_the_previous_count_gets_receipts_from_opening_0` | Pass (QAP Task 1: 17 of 17 passed on `ssm_fills`, 73 s) | **Pass** (R2-e, `scripts/check.sh --optin`, 2026-11-03) |
| TC79 | T65 | C65 | `test_fills_db::test_a_product_missing_from_this_months_count_gets_receipts_from_closing_0` | Pass (QAP Task 1: 17 of 17 passed on `ssm_fills`, 73 s) | **Pass** (R2-e, `scripts/check.sh --optin`, 2026-11-03) |
| TC80 | T65 | C65 | `test_fills_db::test_every_assumed_zero_keeps_the_negative_balance_rule` | Pass (QAP Task 1: 17 of 17 passed on `ssm_fills`, 73 s) | **Pass** (R2-e, `scripts/check.sh --optin`, 2026-11-03) |
| TC81 | T65 | C65 | `test_fills_db::test_an_assumed_zero_opening_from_a_possibly_partial_count_is_flagged` | Pass (QAP Task 1: 17 of 17 passed on `ssm_fills`, 73 s) | **Pass** (R2-e, `scripts/check.sh --optin`, 2026-11-03) |
| TC82 | T66 | C66 | `test_rollover_scratch::test_rollover_on_a_scratch_schema_with_a_synthetic_march` | Pass after three harness fixes (QAP Task 1: failed three times for reasons that were not the pipeline code, then 60 of 60 checks) | **Pass** (R2-e, `scripts/check.sh --optin`, 2026-11-03; 61 of 61 checks) |

---

## 5. Integration testing coverage

**What "integration" means here.** Most backend tests drive the real FastAPI app in-process (`TestClient`) through its real
guards, dependencies and validation, with the database session replaced by a fake (`NoQuerySession` and per-file fakes). That
exercises routing → dependency → handler → schema without Postgres. Three groups do reach a real database: `tests/invariants/`
(live, read-only), `tests/test_scratch_migration_guard.py` and `tests/backend/test_migrations.py` (static, over the migration
files), and the 18 opt-in tests (a rehearsal or scratch schema on a disposable database; run by R2-e, not by the coverage run R2-a). R2-b and R2-c are live, read-only
integration runs outside pytest.

**Coverage run.** R2-a under `coverage.py` 7.16.2 with `--branch`, source `backend, analytics, scripts, transform`.
The report covers the **216 files the run imported**: `backend` 70 of its 70 tracked files, `analytics` 64 of 66, `scripts` 82 of 102. coverage.py counts a file in a directory that is not a package only when something imports it, so the 20 `scripts` files no test imports are not in the figures, not counted as 0. `transform` has no tracked Python file. Commands: `coverage run …` (R2-a), `coverage json`, then `cov_figures.py` (function and except-block counts read from the same JSON plus each file's syntax tree).

| Kind | Figure from the run | Provided by (test files) |
|---|---|---|
| Statement | **51.9%** (12,184 of 23,487 statements) | the whole suite; by package below |
| Condition (each boolean sub-expression) | **not measured**: coverage.py measures branches (arcs), not the truth of each operand of `and`/`or`. No tool in the repo produces it | — |
| Branch / decision | **44.4%** (2,931 of 6,600 branches) | the whole suite |
| Loop (zero, one, many iterations) | **not measured as a figure**: branch coverage records whether each loop was entered and skipped, but not "one" against "many" | loop-boundary cases: `tests/optimization/test_case_pack_rounding.py` (zero order, one pack, many), `tests/test_fsn.py` (0, 1, 12 sales months), `tests/backend/test_series_gaps.py` (empty series, a year-end crossing) |
| Function (a function with at least one executed statement) | **60.3%** (994 of 1,649 functions with at least one statement executed; module level excluded) | the whole suite |
| Path (each distinct route through a function) | **not measured**: no tool in the repo enumerates paths | explicit path tests on the decision machine: `tests/backend/test_recommendation_decisions.py`, `test_reorder_approval.py` (pending → accepted/dismissed → reversed → re-decided; superseded; open change) |
| Error handling (an `except` block executed) | **20.9%** (31 of 148 `except` blocks with at least one body line executed) | `tests/backend/test_client_errors.py`, `test_secret_redaction.py`, `test_audit_log.py` (read error → 503), `tests/optimization/test_run_lp_script.py` (exit 1/2 paths), `tests/test_close_cycle.py` (failed step, resume), `tests/test_run_sql_guard.py`, `tests/test_restore_public_guard.py` |

**By package** (statement and branch, from the same run):

| Package | Files measured | Statements | Branches |
|---|---:|---:|---:|
| `analytics` | 64 | 76.1% (3,581 / 4,707) | 66.9% (855 / 1,278) |
| `backend` | 70 | 93.6% (5,522 / 5,902) | 87.0% (1,353 / 1,556) |
| `scripts` | 82 | 23.9% (3,081 / 12,878) | 19.2% (723 / 3,766) |

What these figures do not show: a line executed under a fake session has not run against Postgres. The figures are for
backend, analytics, scripts and transform, and leave out the frontend. They say nothing about whether a test's assertion was
the right one.
