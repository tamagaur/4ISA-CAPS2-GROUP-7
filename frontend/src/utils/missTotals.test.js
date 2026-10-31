// utils/missTotals.js: a missing miss total is "—", never ₱0 (audit A-FE-10). Run: npm test
import test from 'node:test';
import assert from 'node:assert/strict';
import { formatCount, missShare } from './missTotals.js';
import { formatCompactPesos, NOT_COLLECTED } from './formatters.js';

test('a miss total: null and undefined print the marker, a real 0 prints ₱0', () => {
  assert.equal(formatCompactPesos(null), NOT_COLLECTED);
  assert.equal(formatCompactPesos(undefined), NOT_COLLECTED);
  assert.equal(formatCompactPesos(0), '₱0');
  assert.equal(formatCompactPesos(60_400_000), '₱60.4M');
  // Unsigned by design: the caller prepends a sign.
  assert.equal(formatCompactPesos(-2_500), '₱3k');
});

test('missShare: absent value or sales gives no share', () => {
  assert.equal(missShare(null, 100), null);
  assert.equal(missShare(undefined, 100), null);
  assert.equal(missShare(50, null), null);
  assert.equal(missShare(50, undefined), null);
  assert.equal(missShare(NaN, 100), null);
});

test('missShare: nothing sold gives no share (no division by zero)', () => {
  assert.equal(missShare(50, 0), null);
  assert.equal(missShare(50, -10), null);
});

test('missShare: a real zero is a 0 share, a normal value its ratio', () => {
  assert.equal(missShare(0, 200), 0);
  assert.equal(missShare(50, 200), 0.25);
  assert.equal(missShare(-50, 200), -0.25);
});

test('formatCount: absent is the marker, 0 is 0', () => {
  assert.equal(formatCount(null), NOT_COLLECTED);
  assert.equal(formatCount(undefined), NOT_COLLECTED);
  assert.equal(formatCount(0), '0');
  assert.equal(formatCount(-3), '-3');
  assert.equal(formatCount(1234), (1234).toLocaleString());
});
