// utils/formatters.js: absent data prints the NOT_COLLECTED marker, never 0 (audit FE-4, 2026-10-20).
// Run: npm test
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  NOT_COLLECTED, isMissing, formatCompactPesos, formatExactPesos, formatCompactQty,
} from './formatters.js';

const ABSENT = [null, undefined, NaN];

test('NOT_COLLECTED is the em dash the other formatters already use', () => {
  assert.equal(NOT_COLLECTED, '—');
});

test('isMissing: null, undefined and NaN are absent; 0 and numeric strings are not', () => {
  for (const v of ABSENT) assert.equal(isMissing(v), true);
  for (const v of [0, -0, 1, '0']) assert.equal(isMissing(v), false);
});

test('formatCompactPesos: absent renders the marker', () => {
  for (const v of ABSENT) assert.equal(formatCompactPesos(v), NOT_COLLECTED);
});

test('formatCompactPesos: a real zero is still ₱0, and values compact as before', () => {
  assert.equal(formatCompactPesos(0), '₱0');
  assert.equal(formatCompactPesos(500), '₱500');
  assert.equal(formatCompactPesos(1_500), '₱2k');
  assert.equal(formatCompactPesos(1_200_000), '₱1.2M');
  assert.equal(formatCompactPesos(1_510_000_000), '₱1.51B');
});

test('formatExactPesos: absent renders the marker; a real zero is ₱0', () => {
  for (const v of ABSENT) assert.equal(formatExactPesos(v), NOT_COLLECTED);
  assert.equal(formatExactPesos(0), '₱0');
  assert.equal(formatExactPesos(1234567), '₱1,234,567');
});

test('formatCompactQty: absent renders the marker; a real zero is 0', () => {
  for (const v of ABSENT) assert.equal(formatCompactQty(v), NOT_COLLECTED);
  assert.equal(formatCompactQty(0), '0');
  assert.equal(formatCompactQty(812), '812');
  assert.equal(formatCompactQty(236_000), '236k');
  assert.equal(formatCompactQty(1_350_000, 2), '1.35M');
});
