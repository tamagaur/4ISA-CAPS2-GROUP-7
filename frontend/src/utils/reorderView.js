// frontend/src/utils/reorderView.js — what the Reorder page lists and offers
// (2026-11-02): which rows a filter or search shows, which actions a row has
// for this user, and what a bulk accept would submit. Kept apart from the
// components so node --test can check it (reorderView.test.js).
//
// Nothing here works out a quantity. Every figure comes from GET
// /recommendations; a filter only chooses which rows are listed, and the
// server still checks every action.
import { formatDate, formatMonth } from './formatDate.js';
import { wholeUnits } from './formatNumber.js';

// ── How old the page's figures are ──────────────────────────────────────────
// The planning panel's Last Update, worded like the top bar's DataFreshness.
export function formatUpdatedAgo(fetchedAt, now) {
  if (!fetchedAt) return '—';
  const seconds = Math.max(0, Math.round((now - fetchedAt) / 1000));
  if (seconds < 60) return 'Just now';
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  return new Date(fetchedAt).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

// ── What the figures are measured over ──────────────────────────────────────
// Days of cover, as GET /recommendations serves it (pieces over pieces since
// 2026-10-28, D3).
export const COVER_BASIS_NOTE = 'Stock in pieces ÷ average daily sales in pieces over the last 3 sales months; a month '
  + 'with no sales counts as 0. In pieces like the Dashboard’s weeks of cover, which averages 12 months of sales, so the '
  + 'two can differ.';

// A row's revenue share comes from the ABC run of `month`. Unilever's run ranks
// the 12 months ending then, and a product added as new keeps its 12-month share
// (analytics/classification/orchestrate_abc.py classify_unilever_t12m_new); Del
// Monte's ranks that one month.
export function revenueShareBasis(principal, month) {
  return principal === 'unilever' ? `of revenue over the 12 months to ${month}` : `of ${month} revenue`;
}

// The suggested order is the month's need (forecast + target stock − opening
// stock), not one delivery. Worded as the Data Dictionary's Suggested Order.
export const MONTH_TOTAL_NOTE = 'This is the total for the month, which SSM splits into weekly purchase orders.';

// How a plan's opening stock was obtained (GET /recommendations stock_counts[]
// .opening_basis, backend/stock_units.py with_opening_basis). A plan made before
// its opening count was loaded starts from a projection, and `period` is then the
// earlier count it started from: never worded as a count of the opening month.
export const isProjectedOpening = (count) => count?.opening_basis === 'projected';
export const projectedLabel = (count) => `projected from the ${formatMonth(count.period)} count`;
export function projectedNote(count) {
  const counted = count.counted_on ? `, counted ${formatDate(count.counted_on)}` : '';
  return `PROJECTED opening stock (from the ${formatMonth(count.period)} count${counted}, plus orders on the way, less `
    + 'sales): this plan was made before its opening count was loaded.'
    + `${count.count_now_loaded ? ' That count has arrived since, so the plan can be re-run from it.' : ''}`;
}

// ── How much of the plan orders ─────────────────────────────────────────────
// The quantity a row adds to the plan is the accepted one, else the plan's (GET
// /recommendations plan_q_i and order_count). 0 pieces, or no quantity, orders nothing.
export const ordersNothing = (row) => !((wholeUnits(row.planQty ?? row.orderQty) || 0) > 0);

// Over the whole plan, decided rows too, so the count sits beside the total it
// describes.
export function planOrderCounts(rows) {
  const none = rows.filter(ordersNothing).length;
  return { ordering: rows.length - none, none };
}

// What still waits for someone: a row with something to order and no decision.
export const awaitsDecision = (row) => !row.actionStatus && !ordersNothing(row);

// Act Now: every row below its target stock, Critical and Urgent by the one rule
// (backend/stock_status.py), so the list follows the urgency rather than a number.
export const isBelowTarget = (row) => row.urgency === 'CRITICAL' || row.urgency === 'URGENT';

// A forecast under 1 piece is no sale expected, yet the row can still order: with
// no forecast the target stock is the safety stock, so the order only buys that
// buffer. Someone should look, so it stays out of Accept all. The review flag means
// something else (a large miss is likely), and the plan's quantity doesn't change.
export const forecastsNoSales = (row) => !ordersNothing(row) && row.forecast != null && Number(row.forecast) < 1;
export const NO_SALES_FORECAST_NOTE = 'The forecast for this month is under 1 piece, so this order only buys safety stock. '
  + 'Check that the product is still selling before ordering.';

// Why a row with nothing to order has nothing to decide. A row reaches 0 pieces
// either because its stock covers the month, or because the ceilings left it none.
// The first is only as good as the count behind it, so a flagged count is named.
export function noOrderReason(row, { countLabel, countFlag } = {}) {
  if (row.shortUnits > 0) return 'The allocation left nothing for this product, so there is nothing to accept or dismiss.';
  const covered = 'Stock already covers the month’s forecast and the target stock, so there is nothing to accept or dismiss.';
  return countFlag ? `${covered} This depends on the stock ${countLabel}, ${countFlag.replace(/\.$/, '')}.` : covered;
}

// ── What the plan leaves out ────────────────────────────────────────────────
// GET /recommendations' not_planned, in words from its own rows: how many, as of
// which ABC run, and why. Any other reason the server gives is counted, not dropped.
const NOT_PLANNED_REASONS = [
  ['accuracy', 'with a forecast that did not pass the accuracy check'],
  ['short_history', 'with too little sales history'],
  ['no_recent_sales', 'with no recent sales'],
];

export function notPlannedLede(items, month) {
  const named = new Set(NOT_PLANNED_REASONS.map(([code]) => code));
  const parts = NOT_PLANNED_REASONS
    .map(([code, words]) => [items.filter((item) => item.reason_code === code).length, words])
    .filter(([count]) => count > 0)
    .map(([count, words]) => `${count.toLocaleString()} ${words}`);
  const other = items.filter((item) => !named.has(item.reason_code)).length;
  if (other > 0) parts.push(`${other.toLocaleString()} for another reason`);
  const one = items.length === 1;
  return `${items.length.toLocaleString()} top seller${one ? '' : 's'} (Class A${month ? ` as of ${month}` : ''}) `
    + `${one ? 'has' : 'have'} no suggested order: ${parts.join(', ')}.`;
}

// ── What SSM has not confirmed ──────────────────────────────────────────────
// The detail behind the page's provisional notice, from the run's own recorded
// inputs (lp_model.inputs), its stock count flag and its data notes. Anything
// the run didn't record is left out, never filled in.
export function provisionalDetail({ inputs = {}, countLabel, countFlag, notes = [] } = {}) {
  const money = (v) => `₱${Number(v).toFixed(2)}`;
  return [
    inputs.warehouse_capacity != null && `Warehouse capacity: ${Number(inputs.warehouse_capacity).toLocaleString()} pieces.`,
    inputs.allocation_pct != null && `Supplier allocation: ${inputs.allocation_pct}% of last year’s sales.`,
    inputs.storage_cost_per_unit != null && `Storage cost: ${money(inputs.storage_cost_per_unit)} a piece a month.`,
    inputs.default_procurement_cost_per_unit != null
      && `Procurement cost: from the stock file, or ${money(inputs.default_procurement_cost_per_unit)} a piece where it gives none.`,
    countFlag && `Stock ${countLabel}: ${countFlag}.`,
    ...notes,
  ].filter(Boolean).join(' ');
}

// ── Cases ───────────────────────────────────────────────────────────────────
// Pieces as a case count from the row's pack size (pieces per case, GET
// /recommendations' pack_size): "131 cases × 360" when the quantity is whole
// cases, as every order of a run made since migration 0066 is (the LP rounds
// to case packs), "≈ 363 cases of 288" when it isn't (an older run, a target
// stock, a stock count). null with no pack size (pieces only) or nothing to
// count.
export function casesNote(pieces, packSize) {
  const whole = wholeUnits(pieces); // the figure the table shows
  if (!whole || !(packSize > 0)) return null;
  const cases = whole / packSize;
  const size = packSize.toLocaleString();
  if (cases < 1) return `under 1 case of ${size}`;
  const n = Math.round(cases);
  const word = `case${n === 1 ? '' : 's'}`;
  return Number.isInteger(cases)
    ? `${n.toLocaleString()} ${word} × ${size}`
    : `≈ ${n.toLocaleString()} ${word} of ${size}`;
}

// The same count for a column already headed Cases: "131 × 360", "≈ 3 of 288".
export const casesCell = (note) => (note ? note.replace(/ cases? /, ' ') : null);

// ── Which rows are listed ───────────────────────────────────────────────────
// One view at a time. The three urgencies keep the address the dashboard
// already links to (?urgency=critical); the other two read the row's own flags:
//   review        needs_review is true (null, "not assessed", is not listed)
//   not_in_count  stock_not_in_count is true
const URGENCY_VIEWS = { critical: 'CRITICAL', urgent: 'URGENT', planned: 'PLANNED' };
const FLAG_VIEWS = {
  review: (row) => row.needsReview === true,
  not_in_count: (row) => row.stockNotInCount === true,
};

export function parseView(params) {
  const urgency = (params.get('urgency') || '').toLowerCase();
  if (URGENCY_VIEWS[urgency]) return urgency;
  const view = params.get('view');
  return FLAG_VIEWS[view] ? view : 'all';
}

// A copy of the address's parameters with this view set, and every other
// parameter left as it was.
export function paramsWithView(params, view) {
  const next = new URLSearchParams(params);
  next.delete('urgency');
  next.delete('view');
  if (URGENCY_VIEWS[view]) next.set('urgency', view);
  else if (FLAG_VIEWS[view]) next.set('view', view);
  return next;
}

export function matchesView(row, view) {
  if (URGENCY_VIEWS[view]) return row.urgency === URGENCY_VIEWS[view];
  return FLAG_VIEWS[view] ? FLAG_VIEWS[view](row) : true;
}

// Each word typed must appear in the product name, SKU or brand, in any case
// and any order: "surf 360" finds SURF FABCON ... 360X28ML.
export function matchesSearch(row, query, brand) {
  const words = String(query ?? '').trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return true;
  const text = [row.product, row.sku, brand].filter((v) => v != null).join(' ').toLowerCase();
  return words.every((word) => text.includes(word));
}

// The rows a view and a search leave, in the order they came (the plan's rank).
export function filterRows(rows, { view = 'all', query = '', brandOf = () => null } = {}) {
  return rows.filter((row) => matchesView(row, view) && matchesSearch(row, query, brandOf(row)));
}

// How many rows each view holds, for the filter chips. Search doesn't change them.
export function viewCounts(rows) {
  const counts = { all: rows.length };
  [...Object.keys(URGENCY_VIEWS), ...Object.keys(FLAG_VIEWS)].forEach((view) => {
    counts[view] = rows.filter((row) => matchesView(row, view)).length;
  });
  return counts;
}

// ── Which columns fit ───────────────────────────────────────────────────────
// By the width the table actually has, so closing the sidebar gives columns
// back. Anything a tier leaves out is in the review drawer.
export function tableTier(width) {
  if (width >= 1060) return 'full';
  if (width >= 920) return 'compact'; // cases move under the pieces
  if (width >= 620) return 'tablet'; // badges move under the product; cover and rank to the drawer
  return 'cards';
}

// ── Which actions a row has ─────────────────────────────────────────────────
// The one place the table and the review drawer ask, so neither can offer a
// way around the other. It only decides what is offered: the server checks
// every request (lp.decide on PATCH, lp.propose on a request, role admin on
// settling one) whatever a page sends.
//
// ctx: { canDecide, canPropose, isAdmin, approvalReady, requestsReady,
//        canSeeHistory, appliesDirectly, whatIf, openRequest, bulkRunning }
//
// Returns { state, primary, secondary }. state is what the row is doing:
// loading | decided | what_if | open_request | no_order | actionable | view_only.
export function rowActions(row, ctx) {
  const {
    canDecide = false, canPropose = false, isAdmin = false, approvalReady = false, requestsReady = false,
    canSeeHistory = false, appliesDirectly = false, whatIf = false, openRequest = null, bulkRunning = false,
  } = ctx;
  const review = { id: 'review_order', label: 'Review order' };
  // A what-if row was never saved, so it has no history to read.
  const history = canSeeHistory && !whatIf ? [{ id: 'history', label: 'History' }] : [];

  if (row.loadingAction) return { state: 'loading', primary: null, secondary: [] };
  if (row.actionStatus) return { state: 'decided', primary: null, secondary: [review, ...history] };
  if (whatIf) return { state: 'what_if', primary: null, secondary: [review] };

  // A request is waiting: the server refuses any other decision (409) until
  // an admin settles it, so nothing else is offered.
  if (openRequest) {
    return isAdmin
      ? { state: 'open_request', primary: { id: 'review_request', label: 'Review request' }, secondary: [review, ...history] }
      : { state: 'open_request', primary: review, secondary: history };
  }

  const canSeeRequests = canDecide || canPropose;
  const quantity = canSeeRequests && approvalReady
    ? [{
      id: 'quantity',
      label: appliesDirectly ? 'Change quantity' : 'Request quantity change',
      disabled: bulkRunning,
    }]
    : [];

  // Nothing to order: nothing to accept or dismiss, and no dismissal to ask for.
  // A quantity stays on offer, for someone who doubts the stock figure behind the 0.
  if (ordersNothing(row)) return { state: 'no_order', primary: null, secondary: [review, ...quantity, ...history] };

  if (canDecide) {
    return {
      state: 'actionable',
      // A flagged row is still confirmed before it is accepted, and the
      // confirmation is what sends reviewed=true (the server's 409 otherwise).
      primary: { id: 'accept', label: 'Accept', disabled: bulkRunning, confirmReview: row.needsReview === true },
      secondary: [review, ...quantity, { id: 'dismiss', label: 'Dismiss', disabled: bulkRunning }, ...history],
    };
  }

  if (canPropose) {
    // Asking for a dismissal is for someone who can't dismiss.
    const dismissal = !isAdmin && requestsReady ? [{ id: 'request_dismissal', label: 'Request dismissal' }] : [];
    return { state: 'actionable', primary: review, secondary: [...quantity, ...dismissal, ...history] };
  }

  return { state: 'view_only', primary: review, secondary: history };
}

// ── What a bulk accept submits ──────────────────────────────────────────────
// Splits the rows in view into what "Accept all in view" submits and what it
// leaves out, and why. The dialog keeps `eligible` and submits that same list,
// so what it previews is what it sends. Flagged rows are accepted one at a time
// (they need reviewed=true), a row with a request open would answer 409, a row
// that orders nothing has nothing to accept, and a row forecast to sell nothing
// needs someone to look at it.
export function splitBulkRows(rows, hasOpenRequest = () => false) {
  const eligible = [];
  const excluded = { decided: [], openRequest: [], noOrder: [], flagged: [], noSalesForecast: [] };
  rows.forEach((row) => {
    if (row.actionStatus) excluded.decided.push(row);
    else if (hasOpenRequest(row)) excluded.openRequest.push(row);
    else if (ordersNothing(row)) excluded.noOrder.push(row);
    else if (row.needsReview) excluded.flagged.push(row);
    else if (forecastsNoSales(row)) excluded.noSalesForecast.push(row);
    else if (!row.loadingAction) eligible.push(row);
  });
  return { eligible, excluded };
}

// The figures the bulk dialog shows, counted from the list it will submit.
export function bulkSummary(rows) {
  return {
    count: rows.length,
    totalPieces: rows.reduce((sum, row) => sum + (wholeUnits(row.orderQty) || 0), 0),
    critical: rows.filter((row) => row.urgency === 'CRITICAL').length,
    notInCount: rows.filter((row) => row.stockNotInCount === true).length,
  };
}
