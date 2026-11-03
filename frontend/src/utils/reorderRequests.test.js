// node --test src/utils (npm test): the Reorder page's staff-request arithmetic.
// Figures here are made-up inputs for the arithmetic, not plan data.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  toPieces, validateProposedQuantity, quantityDifference, differenceText, quantityWarnings,
  dismissalWarnings, isStale, serverTime, stockObservationPayload, validateStockCount,
} from './reorderRequests.js';

test('cases convert to pieces with the row pack size', () => {
  assert.equal(toPieces('3', 'cases', 24), 72);
  assert.equal(toPieces('50', 'pieces', 24), 50);
  assert.equal(toPieces('', 'pieces', 24), null);
});

test('pieces that are not whole cases are refused with both neighbours offered, never rounded', () => {
  const err = validateProposedQuantity({ amount: '50', unit: 'pieces', packSize: 24, recommended: 96 });
  assert.equal(err.code, 'not_whole_cases');
  assert.deepEqual(err.alternatives, [48, 72]);
});

test('a neighbour equal to the recommendation is not offered', () => {
  const err = validateProposedQuantity({ amount: '100', unit: 'pieces', packSize: 24, recommended: 96 });
  assert.deepEqual(err.alternatives, [120]);
});

test('the recommended quantity, a negative and a fractional case are refused', () => {
  assert.equal(validateProposedQuantity({ amount: '4', unit: 'cases', packSize: 24, recommended: 96 }).code, 'quantity_unchanged');
  assert.equal(validateProposedQuantity({ amount: '-1', unit: 'pieces', packSize: null, recommended: 5 }).code, 'negative');
  assert.equal(validateProposedQuantity({ amount: '1.5', unit: 'cases', packSize: 24, recommended: 96 }).code, 'not_whole_cases');
});

test('the recommended quantity on a row that orders nothing does not point at an Accept it hasn\'t got', () => {
  const zero = validateProposedQuantity({ amount: '0', unit: 'pieces', packSize: null, recommended: 0 });
  assert.equal(zero.code, 'quantity_unchanged');
  assert.ok(!zero.message.includes('Accept'));
  assert.ok(validateProposedQuantity({ amount: '4', unit: 'cases', packSize: 24, recommended: 96 }).message.includes('Accept'));
});

test('with no pack size any whole number of pieces is fine, and 0 is allowed', () => {
  assert.equal(validateProposedQuantity({ amount: '7', unit: 'pieces', packSize: null, recommended: 5 }), null);
  assert.equal(validateProposedQuantity({ amount: '0', unit: 'pieces', packSize: 24, recommended: 96 }), null);
});

test('difference in pieces and percent; percent is null from a 0 recommendation', () => {
  assert.deepEqual(quantityDifference(120, 100), { pieces: 20, percent: 20 });
  assert.equal(quantityDifference(24, 0).percent, null);
  assert.equal(differenceText(quantityDifference(80, 100)), '−20 pieces (−20.0%)');
});

test('above-target warning is proposed − (forecast + target − stock)', () => {
  const row = { forecast: 100, rop: 50, stock: 30, orderQty: 120 };
  const w = quantityWarnings(row, 150, {});
  assert.equal(w.length, 1);
  assert.match(w[0].text, /about 30 pieces/);
  assert.equal(quantityWarnings(row, 120, {}).length, 0);
});

test('allocation warning only when the plan has cuts and the proposal is above the recommendation', () => {
  const row = { forecast: null, rop: 50, stock: 30, orderQty: 120 };
  assert.deepEqual(quantityWarnings(row, 144, { planHasCuts: true }).map((w) => w.key), ['allocation']);
  assert.equal(quantityWarnings(row, 96, { planHasCuts: true }).length, 0);
  assert.equal(quantityWarnings(row, 144, { planHasCuts: false }).length, 0);
});

test('dismissal warns when opening stock is below safety stock and something was to be ordered', () => {
  assert.equal(dismissalWarnings({ stock: 5, safetyStock: 10, orderQty: 24 }).length, 1);
  assert.equal(dismissalWarnings({ stock: 5, safetyStock: 10, orderQty: 0 }).length, 0);
});

test('stale = the row quantity moved since the request; unknown when the row is not on the page', () => {
  const req = { state: 'pending_approval', recommended_q_i: 96 };
  assert.equal(isStale(req, { orderQty: 96.001 }), false);
  assert.equal(isStale(req, { orderQty: 120 }), true);
  assert.equal(isStale(req, null), null);
  assert.equal(isStale({ ...req, state: 'approved' }, { orderQty: 120 }), null);
});

test('a server time without a zone is read as UTC', () => {
  assert.equal(serverTime('2026-10-23T09:00:00').toISOString(), '2026-10-23T09:00:00.000Z');
  assert.equal(serverTime('2026-10-23T09:00:00+08:00').toISOString(), '2026-10-23T01:00:00.000Z');
  assert.equal(serverTime(null), null);
});

test('stock count payload drops blanks; validation needs whole cases', () => {
  assert.equal(stockObservationPayload({ quantity: '' }), null);
  assert.deepEqual(stockObservationPayload({ quantity: '3', unit: 'cases', location: ' Bay 2 ', notes: '' }),
    { quantity: 3, unit: 'cases', location: 'Bay 2' });
  assert.equal(validateStockCount({ quantity: '2.5', unit: 'cases', packSize: 24 }), 'Enter a whole number of cases.');
  assert.equal(validateStockCount({ quantity: '2.5', unit: 'pieces', packSize: 24 }), null);
});

test('case count is whole or approximate, and absent without a case size', async () => {
  const { casesText } = await import('./reorderRequests.js');
  assert.equal(casesText(96, 24), '4 cases');
  assert.equal(casesText(24, 24), '1 case');
  assert.equal(casesText(100, 24), '≈ 4.2 cases');
  assert.equal(casesText(100, null), null);
  assert.equal(casesText(100, 1), null);
});

test('request IDs carry the kind, since the two tables number separately', async () => {
  const { requestId } = await import('./reorderRequests.js');
  assert.equal(requestId({ kind: 'quantity_change', change_key: 7 }), 'QC-7');
  assert.equal(requestId({ kind: 'dismissal', request_key: 7 }), 'DR-7');
});

test('deep-link request param maps to the list key; anything else is ignored', async () => {
  const { parseRequestLink } = await import('./reorderRequests.js');
  assert.deepEqual(parseRequestLink('quantity_change-7'), { kind: 'quantity_change', key: 'c7' });
  assert.deepEqual(parseRequestLink('dismissal-4'), { kind: 'dismissal', key: 'd4' });
  assert.equal(parseRequestLink('dismissal-'), null);
  assert.equal(parseRequestLink('QC-7'), null);
  assert.equal(parseRequestLink(null), null);
});

test('counts and filters come from one state=all list', async () => {
  const { requestCounts, filterRequests } = await import('./reorderRequests.js');
  const items = [
    { kind: 'quantity_change', change_key: 1, state: 'pending_approval', by: 'ana@x.ph', byName: 'Ana Cruz', product_name: 'Soap', sku_code: '111' },
    { kind: 'dismissal', request_key: 1, state: 'approved', by: 'ben@x.ph', byName: null, product_name: 'Shampoo', sku_code: '222' },
    { kind: 'quantity_change', change_key: 2, state: 'rejected', by: 'ana@x.ph', byName: 'Ana Cruz', product_name: 'Lotion', sku_code: '333' },
  ];
  assert.deepEqual(requestCounts(items), { all: 3, pending_approval: 1, approved: 1, rejected: 1 });
  assert.equal(filterRequests(items, { status: 'pending_approval' }).length, 1);
  assert.equal(filterRequests(items, { query: 'ana cruz' }).length, 2);
  assert.equal(filterRequests(items, { query: 'ben@' }).length, 1);
  assert.equal(filterRequests(items, { query: 'dr-1' })[0].product_name, 'Shampoo');
  assert.equal(filterRequests(items, { status: 'approved', query: '333' }).length, 0);
});
