// Run: npm test
import test from 'node:test';
import assert from 'node:assert/strict';
import { formatCoverDays } from './formatNumber.js';

test('cover shows whole days, and <1 below one day', () => {
  assert.equal(formatCoverDays(18.2), '18');
  assert.equal(formatCoverDays(1.0), '1');
  assert.equal(formatCoverDays(1.5), '2');
  assert.equal(formatCoverDays(0.6), '<1');
  assert.equal(formatCoverDays(0.1), '<1');
  assert.equal(formatCoverDays(0), '<1');
});

test('no cover figure stays no figure', () => {
  assert.equal(formatCoverDays(null), null);
  assert.equal(formatCoverDays(undefined), null);
});
