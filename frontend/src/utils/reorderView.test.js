// node --test src/utils (npm test): which rows the Reorder page lists, which
// actions a row offers, and what a bulk accept submits.
// Figures here are made-up inputs for the logic, not plan data.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  COVER_BASIS_NOTE, MONTH_TOTAL_NOTE, awaitsDecision, bulkSummary, casesCell, casesNote, filterRows, formatUpdatedAgo,
  forecastsNoSales, isBelowTarget, isProjectedOpening, matchesSearch, noOrderReason, notPlannedLede, ordersNothing,
  paramsWithView, parseView, planOrderCounts, projectedLabel,
  projectedNote, provisionalDetail, revenueShareBasis, rowActions, splitBulkRows, tableTier, viewCounts,
} from './reorderView.js';

const source = (name) => readFileSync(new URL(`../components/${name}`, import.meta.url), 'utf8');

const row = (id, over = {}) => ({
  id,
  product: `PRODUCT ${id}`,
  sku: `100${id}`,
  urgency: 'PLANNED',
  needsReview: false,
  stockNotInCount: false,
  orderQty: 100,
  actionStatus: null,
  loadingAction: null,
  ...over,
});

const rows = [
  row(1, { product: 'SURF FABCON 360X28ML', urgency: 'CRITICAL', needsReview: true, stockNotInCount: true, orderQty: 720 }),
  row(2, { product: 'SURF POWDER 65G', urgency: 'CRITICAL', orderQty: 480 }),
  row(3, { product: 'CREAM SILK 13ML', urgency: 'URGENT', needsReview: true }),
  row(4, { product: 'KNORR SINGLES', urgency: 'PLANNED', orderQty: 0 }),
  row(5, { product: 'LADYS MAYO', urgency: 'NO DATA', stockNotInCount: true, orderQty: 96 }),
];
const ids = (list) => list.map((r) => r.id);

// ── Filters ─────────────────────────────────────────────────────────────────

test('Critical, All, Needs Review and Not in stock count list the right rows', () => {
  assert.deepEqual(ids(filterRows(rows, { view: 'critical' })), [1, 2]);
  assert.deepEqual(ids(filterRows(rows, { view: 'all' })), [1, 2, 3, 4, 5]);
  assert.deepEqual(ids(filterRows(rows, { view: 'review' })), [1, 3]);
  assert.deepEqual(ids(filterRows(rows, { view: 'not_in_count' })), [1, 5]);
  assert.deepEqual(ids(filterRows(rows, { view: 'urgent' })), [3]);
  assert.deepEqual(ids(filterRows(rows, { view: 'planned' })), [4]);
});

test('needs_review null (not assessed) is not listed as needing review', () => {
  assert.deepEqual(ids(filterRows([row(1, { needsReview: null })], { view: 'review' })), []);
});

test('the counts are the same rows the filters list, whatever the search', () => {
  assert.deepEqual(viewCounts(rows), { all: 5, critical: 2, urgent: 1, planned: 1, review: 2, not_in_count: 2 });
});

test('filtering changes neither the rows nor their order', () => {
  const before = JSON.stringify(rows);
  filterRows(rows, { view: 'critical', query: 'surf' });
  assert.equal(JSON.stringify(rows), before);
  assert.deepEqual(ids(filterRows(rows, { view: 'all', query: 'surf' })), [1, 2]);
});

// ── Search ──────────────────────────────────────────────────────────────────

test('search is case-insensitive and trimmed, over name, SKU and brand', () => {
  assert.equal(matchesSearch(rows[0], '  surf  '), true);
  assert.equal(matchesSearch(rows[0], 'FABCON'), true);
  assert.equal(matchesSearch(rows[0], '1001'), true);
  assert.equal(matchesSearch(rows[3], 'unilever brand', 'UNILEVER BRAND'), true);
  assert.equal(matchesSearch(rows[3], 'surf'), false);
  assert.equal(matchesSearch(rows[3], '   '), true);
});

test('each word must match, in any order', () => {
  assert.equal(matchesSearch(rows[0], '360 surf'), true);
  assert.equal(matchesSearch(rows[0], 'surf powder'), false);
});

test('search narrows the view it is combined with', () => {
  assert.deepEqual(ids(filterRows(rows, { view: 'critical', query: 'powder' })), [2]);
  assert.deepEqual(ids(filterRows(rows, { view: 'review', query: 'powder' })), []);
  const brandOf = (r) => (r.id === 3 ? 'CREAMSILK' : null);
  assert.deepEqual(ids(filterRows(rows, { view: 'urgent', query: 'creamsilk', brandOf })), [3]);
});

// ── The address ─────────────────────────────────────────────────────────────

test('the dashboard links keep working: ?urgency= in either case', () => {
  assert.equal(parseView(new URLSearchParams('urgency=critical')), 'critical');
  assert.equal(parseView(new URLSearchParams('urgency=URGENT')), 'urgent');
  assert.equal(parseView(new URLSearchParams('urgency=nonsense')), 'all');
  assert.equal(parseView(new URLSearchParams('view=review')), 'review');
  assert.equal(parseView(new URLSearchParams('view=nonsense')), 'all');
  assert.equal(parseView(new URLSearchParams('')), 'all');
});

test('changing the view leaves every other parameter alone', () => {
  const params = new URLSearchParams('urgency=critical&sku=123&from=2025-03');
  assert.equal(paramsWithView(params, 'all').toString(), 'sku=123&from=2025-03');
  assert.equal(paramsWithView(params, 'review').toString(), 'sku=123&from=2025-03&view=review');
  assert.equal(paramsWithView(new URLSearchParams('view=review'), 'planned').toString(), 'urgency=planned');
  assert.equal(params.get('urgency'), 'critical'); // the original isn't touched
});

// ── Row actions ─────────────────────────────────────────────────────────────

const ADMIN = {
  canDecide: true, canPropose: true, isAdmin: true, approvalReady: true, requestsReady: true, canSeeHistory: true, appliesDirectly: true,
};
const STAFF = {
  canDecide: false, canPropose: true, isAdmin: false, approvalReady: true, requestsReady: true, canSeeHistory: true, appliesDirectly: false,
};
const VIEWER = { canDecide: false, canPropose: false, isAdmin: false };
const all = (a) => [a.primary?.id, ...a.secondary.map((s) => s.id)].filter(Boolean);
const label = (a, id) => [a.primary, ...a.secondary].find((s) => s?.id === id)?.label;

test('admin, pending row: Accept, with the rest in the menu', () => {
  const a = rowActions(row(1), ADMIN);
  assert.equal(a.state, 'actionable');
  assert.equal(a.primary.id, 'accept');
  assert.deepEqual(a.secondary.map((s) => s.id), ['review_order', 'quantity', 'dismiss', 'history']);
  assert.equal(label(a, 'quantity'), 'Change quantity');
});

test('admin, flagged row: Accept stays, and says it must be confirmed as reviewed', () => {
  assert.equal(rowActions(row(1, { needsReview: true }), ADMIN).primary.confirmReview, true);
  assert.equal(rowActions(row(1), ADMIN).primary.confirmReview, false);
});

test('staff, pending row: Review order and requests, never a direct decision', () => {
  const a = rowActions(row(1), STAFF);
  assert.equal(a.primary.id, 'review_order');
  assert.deepEqual(a.secondary.map((s) => s.id), ['quantity', 'request_dismissal', 'history']);
  assert.equal(label(a, 'quantity'), 'Request quantity change');
  assert.ok(!all(a).includes('accept'));
  assert.ok(!all(a).includes('dismiss'));
});

test('staff with a direct-apply grant: the quantity is worded as a change, and still no Accept', () => {
  const a = rowActions(row(1), { ...STAFF, appliesDirectly: true });
  assert.equal(label(a, 'quantity'), 'Change quantity');
  assert.ok(!all(a).includes('accept'));
});

test('staff, flagged row: a flag gives staff nothing extra', () => {
  assert.deepEqual(all(rowActions(row(1, { needsReview: true }), STAFF)), all(rowActions(row(1), STAFF)));
});

test('view only: Review order and nothing that writes', () => {
  const a = rowActions(row(1), VIEWER);
  assert.equal(a.state, 'view_only');
  assert.deepEqual(all(a), ['review_order']);
});

test('what the server hasn\'t set up isn\'t offered', () => {
  const staff = rowActions(row(1), { ...STAFF, approvalReady: false, requestsReady: false, canSeeHistory: false });
  assert.deepEqual(all(staff), ['review_order']);
  const admin = rowActions(row(1), { ...ADMIN, approvalReady: false, canSeeHistory: false });
  assert.deepEqual(all(admin), ['accept', 'review_order', 'dismiss']);
});

test('a request waiting: no decision on offer; an admin can open the request', () => {
  const openRequest = { kind: 'quantity_change', key: 7 };
  const admin = rowActions(row(1), { ...ADMIN, openRequest });
  assert.equal(admin.state, 'open_request');
  assert.equal(admin.primary.id, 'review_request');
  assert.deepEqual(admin.secondary.map((s) => s.id), ['review_order', 'history']);

  const staff = rowActions(row(1), { ...STAFF, openRequest });
  assert.equal(staff.primary.id, 'review_order');
  assert.deepEqual(staff.secondary.map((s) => s.id), ['history']);

  const viewer = rowActions(row(1), { ...VIEWER, openRequest });
  assert.deepEqual(all(viewer), ['review_order']);
  [admin, staff, viewer].forEach((a) => {
    ['accept', 'dismiss', 'quantity', 'request_dismissal'].forEach((id) => assert.ok(!all(a).includes(id), id));
  });
});

test('an accepted or dismissed row has nothing left to decide, for anyone', () => {
  ['ACCEPTED', 'DISMISSED'].forEach((actionStatus) => {
    [ADMIN, STAFF].forEach((ctx) => {
      const a = rowActions(row(1, { actionStatus }), ctx);
      assert.equal(a.state, 'decided');
      assert.equal(a.primary, null);
      assert.deepEqual(a.secondary.map((s) => s.id), ['review_order', 'history']);
    });
  });
});

test('a what-if row was never saved: nothing to decide and no history', () => {
  const a = rowActions(row(1), { ...ADMIN, whatIf: true });
  assert.equal(a.state, 'what_if');
  assert.deepEqual(all(a), ['review_order']);
});

test('a row being saved offers nothing', () => {
  assert.deepEqual(rowActions(row(1, { loadingAction: 'ACCEPTED' }), ADMIN), { state: 'loading', primary: null, secondary: [] });
});

test('while a bulk accept runs, a row\'s own decisions wait', () => {
  const a = rowActions(row(1), { ...ADMIN, bulkRunning: true });
  assert.equal(a.primary.disabled, true);
  assert.equal(a.secondary.find((s) => s.id === 'dismiss').disabled, true);
  assert.equal(a.secondary.find((s) => s.id === 'quantity').disabled, true);
  assert.equal(a.secondary.find((s) => s.id === 'review_order').disabled, undefined);
});

// ── Bulk accept ─────────────────────────────────────────────────────────────

test('bulk: flagged rows, open requests and decided rows are left out, each under its reason', () => {
  const list = [
    row(1, { needsReview: true }),
    row(2),
    row(3, { actionStatus: 'ACCEPTED' }),
    row(4),
    row(5, { loadingAction: 'ACCEPTED' }),
    row(6, { needsReview: true }), // also has a request open: the request is what blocks it first
  ];
  const { eligible, excluded } = splitBulkRows(list, (r) => r.id === 4 || r.id === 6);
  assert.deepEqual(ids(eligible), [2]);
  assert.deepEqual(ids(excluded.flagged), [1]);
  assert.deepEqual(ids(excluded.openRequest), [4, 6]);
  assert.deepEqual(ids(excluded.decided), [3]);
});

test('bulk: the eligible list is the very rows given, in their order', () => {
  const list = [row(1), row(2), row(3)];
  const { eligible } = splitBulkRows(list);
  eligible.forEach((r, i) => assert.equal(r, list[i]));
});

test('bulk: a row not in the stock count but not flagged is submitted, and counted for the warning', () => {
  const list = [row(1, { stockNotInCount: true, needsReview: false }), row(2)];
  const { eligible } = splitBulkRows(list);
  assert.deepEqual(ids(eligible), [1, 2]);
  assert.equal(bulkSummary(eligible).notInCount, 1);
});

test('bulk: the figures are counted from the list that is submitted', () => {
  const list = [
    row(1, { urgency: 'CRITICAL', orderQty: 720 }),
    row(2, { urgency: 'CRITICAL', orderQty: 480.4, stockNotInCount: true }),
    row(3, { orderQty: 0 }),
    row(4, { orderQty: null }),
  ];
  // 480.4 counts as 481, the whole pieces the table shows (formatNumber wholeUnits).
  assert.deepEqual(bulkSummary(list), { count: 4, totalPieces: 1201, critical: 2, notInCount: 1 });
  assert.deepEqual(bulkSummary([]), { count: 0, totalPieces: 0, critical: 0, notInCount: 0 });
});

test('bulk: a row that orders nothing is left out, ahead of being flagged, and has its own reason', () => {
  const list = [
    row(1),
    row(2, { orderQty: 0 }),
    row(3, { orderQty: 0, needsReview: true }),
    row(4, { orderQty: 0, actionStatus: 'ACCEPTED' }), // already decided: said as that
    row(5, { orderQty: 0 }), // a request open: said as that
  ];
  const { eligible, excluded } = splitBulkRows(list, (r) => r.id === 5);
  assert.deepEqual(ids(eligible), [1]);
  assert.deepEqual(ids(excluded.noOrder), [2, 3]);
  assert.deepEqual(ids(excluded.flagged), []);
  assert.deepEqual(ids(excluded.decided), [4]);
  assert.deepEqual(ids(excluded.openRequest), [5]);
});

// ── Rows that order nothing ─────────────────────────────────────────────────

test('a row orders nothing at 0 pieces or no quantity, and an accepted quantity counts', () => {
  assert.equal(ordersNothing(row(1, { orderQty: 0 })), true);
  assert.equal(ordersNothing(row(1, { orderQty: null })), true);
  assert.equal(ordersNothing(row(1, { orderQty: 0.4 })), false); // shows as 1 piece, as the table rounds it
  assert.equal(ordersNothing(row(1, { orderQty: 0, planQty: 600, actionStatus: 'ACCEPTED' })), false);
});

test('only a row with something to order and no decision is waiting for one', () => {
  assert.equal(awaitsDecision(row(1)), true);
  assert.equal(awaitsDecision(row(1, { orderQty: 0 })), false);
  assert.equal(awaitsDecision(row(1, { actionStatus: 'DISMISSED' })), false);
});

test('admin, nothing to order: no Accept or Dismiss, a quantity can still be set', () => {
  const a = rowActions(row(1, { orderQty: 0 }), ADMIN);
  assert.equal(a.state, 'no_order');
  assert.equal(a.primary, null);
  assert.deepEqual(a.secondary.map((s) => s.id), ['review_order', 'quantity', 'history']);
});

test('staff, nothing to order: no dismissal to ask for, a quantity can still be requested', () => {
  const a = rowActions(row(1, { orderQty: 0 }), STAFF);
  assert.equal(a.state, 'no_order');
  assert.deepEqual(a.secondary.map((s) => s.id), ['review_order', 'quantity', 'history']);
  assert.equal(label(a, 'quantity'), 'Request quantity change');
});

test('view only, nothing to order: only the review', () => {
  const a = rowActions(row(1, { orderQty: 0 }), VIEWER);
  assert.equal(a.state, 'no_order');
  assert.deepEqual(all(a), ['review_order']);
});

test('nothing to order does not hide what the row is already doing', () => {
  const zero = { orderQty: 0 };
  assert.equal(rowActions(row(1, { ...zero, actionStatus: 'ACCEPTED' }), ADMIN).state, 'decided');
  assert.equal(rowActions(row(1, { ...zero, loadingAction: 'ACCEPTED' }), ADMIN).state, 'loading');
  assert.equal(rowActions(row(1, zero), { ...ADMIN, whatIf: true }).state, 'what_if');
  // A request to order some of it, still waiting for an admin.
  assert.equal(rowActions(row(1, zero), { ...ADMIN, openRequest: { kind: 'quantity_change', key: 7 } }).state, 'open_request');
});

test('the reason follows why the row reached 0 pieces', () => {
  assert.match(noOrderReason(row(1, { orderQty: 0 })), /Stock already covers/);
  assert.match(noOrderReason(row(1, { orderQty: 0, shortUnits: 480 })), /allocation left nothing/);
});

// ── A plan that started from a projection ───────────────────────────────────

test('only a projected opening is worded as one, and it names the count it started from', () => {
  const projected = { opening_basis: 'projected', period: '2026-03', counted_on: '2026-04-06', count_now_loaded: false };
  assert.equal(isProjectedOpening(projected), true);
  assert.equal(isProjectedOpening({ opening_basis: 'count', period: '2026-02' }), false);
  assert.equal(isProjectedOpening({ opening_basis: null }), false);
  assert.equal(isProjectedOpening(null), false);
  assert.equal(projectedLabel(projected), 'projected from the Mar 2026 count');
  const note = projectedNote(projected);
  assert.match(note, /^PROJECTED opening stock \(from the Mar 2026 count, counted Apr 6, 2026, plus orders on the way, less sales\)/);
  assert.ok(!note.includes('arrived since'));
});

test('a projected opening says when the count it stood in for has arrived, and copes with no count date', () => {
  const note = projectedNote({ opening_basis: 'projected', period: '2026-03', counted_on: null, count_now_loaded: true });
  assert.match(note, /from the Mar 2026 count, plus orders/);
  assert.match(note, /arrived since/);
});

// ── What the page says about a quantity ─────────────────────────────────────

test('the suggested quantity is called the month\'s total on the page and in the drawer, in one set of words', () => {
  assert.match(MONTH_TOTAL_NOTE, /total for the month/);
  assert.match(MONTH_TOTAL_NOTE, /weekly purchase orders/);
  ['ReorderRecommendations.jsx', 'ReorderReviewDrawer.jsx'].forEach((name) => {
    assert.ok(source(name).includes('MONTH_TOTAL_NOTE'), name);
  });
  assert.ok(source('DataDictionary.jsx').includes('which SSM splits into weekly purchase orders'));
});

test('the planning cycle is a dropdown only when there is more than one to choose', () => {
  const page = source('ReorderRecommendations.jsx');
  assert.ok(page.includes("cycles.length > 1 ? ' has-choice' : ''"));
  assert.match(page, /\{cycles\.length > 1 && \(\s*<select/);
});

// ── Small helpers ───────────────────────────────────────────────────────────

test('cases: whole, not whole, under one, and no pack size', () => {
  assert.equal(casesNote(47160, 360), '131 cases × 360');
  assert.equal(casesNote(360, 360), '1 case × 360');
  assert.equal(casesNote(1000, 288), '≈ 3 cases of 288');
  assert.equal(casesNote(100, 288), 'under 1 case of 288');
  assert.equal(casesNote(100, null), null);
  assert.equal(casesNote(0, 24), null);
  assert.equal(casesNote(null, 24), null);
});

test('a cases column drops the word its heading already says', () => {
  assert.equal(casesCell('131 cases × 360'), '131 × 360');
  assert.equal(casesCell('1 case × 360'), '1 × 360');
  assert.equal(casesCell('≈ 3 cases of 288'), '≈ 3 of 288');
  assert.equal(casesCell('under 1 case of 288'), 'under 1 of 288');
  assert.equal(casesCell(null), null);
});

test('the table\'s tier follows the width it has', () => {
  assert.equal(tableTier(1400), 'full');
  assert.equal(tableTier(1000), 'compact');
  assert.equal(tableTier(700), 'tablet');
  assert.equal(tableTier(360), 'cards');
});

test('last update reads in words', () => {
  const now = 1_000_000_000;
  assert.equal(formatUpdatedAgo(null, now), '—');
  assert.equal(formatUpdatedAgo(now - 5_000, now), 'Just now');
  assert.equal(formatUpdatedAgo(now - 300_000, now), '5 min ago');
});

// ── The plan the page reads ─────────────────────────────────────────────────

test('the page reads the whole plan, so a decided row stays on it after a reload', () => {
  // Manuscript 4.2.3.3: a decided row stays part of the plan. The API's default is the current cycle's plan rows.
  const page = source('ReorderRecommendations.jsx');
  assert.ok(page.includes('getRecommendations({ principal, includeNotPlanned: true })'));
  assert.ok(!page.includes("status: 'pending'"));
});

test('how much of the plan orders counts decided rows, and an accepted quantity', () => {
  const rows = [
    row(1, { planQty: 720 }),
    row(2, { planQty: 480, actionStatus: 'ACCEPTED' }),
    row(3, { planQty: 96, actionStatus: 'DISMISSED' }),
    row(4, { planQty: 0 }),
    row(5, { planQty: 0, actionStatus: 'ACCEPTED' }),
  ];
  assert.deepEqual(planOrderCounts(rows), { ordering: 3, none: 2 });
  assert.deepEqual(planOrderCounts([]), { ordering: 0, none: 0 });
});

// ── What the labels say ─────────────────────────────────────────────────────

test('cover is described as the API now serves it: pieces over pieces', () => {
  assert.match(COVER_BASIS_NOTE, /Stock in pieces ÷ average daily sales in pieces/);
  ['ReorderRecommendations.jsx', 'ReorderReviewDrawer.jsx'].forEach((file) => {
    const text = source(file);
    assert.ok(!text.includes('peso basis'), file);
    assert.ok(!text.includes('₱ basis'), file);
    assert.ok(!text.includes('Stock at last purchase price'), file);
  });
});

test('revenue share names the window it is measured over', () => {
  assert.equal(revenueShareBasis('unilever', 'Feb 2026'), 'of revenue over the 12 months to Feb 2026');
  assert.equal(revenueShareBasis('delmonte', 'Dec 2025'), 'of Dec 2025 revenue');
});

// ── The provisional notice ──────────────────────────────────────────────────

test('the provisional detail states what the run recorded, and only that', () => {
  const detail = provisionalDetail({
    inputs: { warehouse_capacity: 1000, allocation_pct: 90, storage_cost_per_unit: 1.5, default_procurement_cost_per_unit: 20 },
    countLabel: 'counted Jan 2, 2026',
    countFlag: 'accepted for now',
    notes: ['A data note.'],
  });
  ['1,000 pieces', '90% of last year', '₱1.50 a piece a month', '₱20.00 a piece where it gives none', 'Stock counted Jan 2, 2026: accepted for now.', 'A data note.']
    .forEach((part) => assert.ok(detail.includes(part), part));
  assert.equal(provisionalDetail({ inputs: {} }), '');
  assert.equal(provisionalDetail(), '');
  assert.ok(!provisionalDetail({ inputs: { allocation_pct: 90 } }).includes('Warehouse'));
});

// ── What is below target, what forecasts nothing, what the plan leaves out ───

test('Act Now is every row below its target stock, however many that is', () => {
  const list = [
    row(1, { urgency: 'CRITICAL' }), row(2, { urgency: 'URGENT' }), row(3, { urgency: 'PLANNED' }), row(4, { urgency: 'NO DATA' }),
  ];
  assert.deepEqual(ids(list.filter(isBelowTarget)), [1, 2]);
  const page = source('ReorderRecommendations.jsx');
  assert.ok(page.includes('rankedRows.filter(isBelowTarget)'));
  assert.ok(!page.includes('ACT_NOW_COUNT'), 'no fixed length with no recorded basis');
  assert.ok(!source('Dashboard.jsx').includes('the 20 with'), 'the Dashboard describes the same rule');
});

test('a row forecast to sell nothing stays out of Accept all, under its own reason', () => {
  const list = [
    row(1, { forecast: 0, orderQty: 1104 }),
    row(2, { forecast: 0.08, orderQty: 204, needsReview: true }),
    row(3, { forecast: 0, orderQty: 0 }),
    row(4, { forecast: 1, orderQty: 96 }),
    row(5, { orderQty: 96 }), // no forecast figure: unknown, not a forecast of nothing
  ];
  assert.deepEqual(list.map(forecastsNoSales), [true, true, false, false, false]);
  const { eligible, excluded } = splitBulkRows(list);
  assert.deepEqual(ids(eligible), [4, 5]);
  assert.deepEqual(ids(excluded.noSalesForecast), [1]);
  assert.deepEqual(ids(excluded.flagged), [2], 'a flagged row is counted as flagged');
  assert.deepEqual(ids(excluded.noOrder), [3]);
  // Held out of the bulk accept, not out of the plan: someone can still accept it from its own row.
  assert.equal(rowActions(list[0], { canDecide: true }).primary.id, 'accept');
});

test('a no-order reason names a flagged count, and only where the stock is the reason', () => {
  const count = { countLabel: 'counted Mar 2, 2026', countFlag: 'accepted for planning, pending SSM confirmation (decided 2026-10-03)' };
  assert.match(noOrderReason(row(1, { orderQty: 0 }), count), /depends on the stock counted Mar 2, 2026, accepted for planning, pending SSM confirmation \(decided 2026-10-03\)\.$/);
  assert.ok(!noOrderReason(row(1, { orderQty: 0 }), { countLabel: 'counted Mar 2, 2026' }).includes('depends on'), 'an unflagged count');
  assert.ok(!noOrderReason(row(1, { orderQty: 0, shortUnits: 480 }), count).includes('depends on'), 'cut by the allocation');
  assert.match(noOrderReason(row(1, { orderQty: 0 }), { countLabel: 'x', countFlag: 'ends in a stop.' }), /ends in a stop\.$/);
});

test('the not-planned lede counts every reason and names the ABC month', () => {
  const items = [
    ...Array.from({ length: 3 }, () => ({ reason_code: 'accuracy' })),
    { reason_code: 'short_history' },
    { reason_code: 'forecast_failed' },
  ];
  assert.equal(
    notPlannedLede(items, 'Feb 2026'),
    '5 top sellers (Class A as of Feb 2026) have no suggested order: 3 with a forecast that did not pass the accuracy check, '
      + '1 with too little sales history, 1 for another reason.',
  );
  assert.equal(
    notPlannedLede([{ reason_code: 'no_recent_sales' }], null),
    '1 top seller (Class A) has no suggested order: 1 with no recent sales.',
  );
});

test('the not-planned list offers no quantity and no decision', () => {
  const list = source('ReorderNotPlanned.jsx');
  ['q_i', 'orderQty', 'decideRecommendation', 'rowActions'].forEach((word) => {
    assert.ok(!list.includes(word), word);
  });
  const page = source('ReorderRecommendations.jsx');
  assert.ok(page.includes("view === 'all' && meta?.notPlanned?.length > 0"));
});
