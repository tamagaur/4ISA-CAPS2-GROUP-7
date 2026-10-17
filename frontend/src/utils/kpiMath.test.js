// node --test src/utils  (npm test). The live figures used below are GET
// /dashboard's for Unilever, Mar 2025 – Feb 2026, read on 2026-10-11.
import test from 'node:test';
import assert from 'node:assert/strict';
import { coverScale, formatCompactCount, formatPercent, policyRatio, shareOf, urgencyParts } from './kpiMath.js';

test('policy ratio is weeks of cover over the policy weeks', () => {
  assert.equal(policyRatio(6.21, 3).toFixed(1), '2.1');
  assert.equal(policyRatio(3, 3), 1);
  assert.equal(policyRatio(1.5, 3), 0.5);
});

test('policy ratio is null when either side is missing or the policy is not positive', () => {
  assert.equal(policyRatio(null, 3), null);
  assert.equal(policyRatio(6.21, null), null);
  assert.equal(policyRatio(6.21, 0), null);
  assert.equal(policyRatio(undefined, undefined), null);
});

test('cover meter ends past the cover and past twice the policy, on an even week', () => {
  assert.equal(coverScale(6.21, 3), 8);
  assert.equal(coverScale(1.5, 3), 8);
  assert.equal(coverScale(20, 3), 22);
  assert.equal(coverScale(4, null), 6);
  assert.equal(coverScale(0, 3), 8);
});

test('cover meter has no scale without a cover figure', () => {
  assert.equal(coverScale(null, 3), null);
  assert.equal(coverScale(undefined, undefined), null);
  assert.equal(coverScale(-1, 3), null);
});

test('share below safety stock: 10 of 91 is 11%', () => {
  const share = shareOf(10, 91);
  assert.ok(Math.abs(share - 10 / 91) < 1e-12);
  assert.equal(formatPercent(share), '11%');
});

test('share is null with nothing to divide by, never 0', () => {
  assert.equal(shareOf(0, 0), null);
  assert.equal(shareOf(3, null), null);
  assert.equal(shareOf(null, 91), null);
  assert.equal(formatPercent(null), '—');
});

test('a percentage never rounds a real share to 0% or a part share to 100%', () => {
  assert.equal(formatPercent(shareOf(0, 91)), '0%');
  assert.equal(formatPercent(shareOf(1, 400)), '<1%');
  assert.equal(formatPercent(shareOf(399, 400)), '>99%');
  assert.equal(formatPercent(shareOf(91, 91)), '100%');
});

test('urgency parts add up to the pending count: 16 + 5 + 76 = 97', () => {
  const parts = urgencyParts({ pending: 97, critical: 16, urgent: 5, noData: 0 });
  assert.deepEqual(parts.map((p) => [p.key, p.value]), [['critical', 16], ['urgent', 5], ['planned', 76]]);
  assert.equal(parts.reduce((sum, p) => sum + p.value, 0), 97);
});

test('rows without a stock figure are their own part, not counted as planned', () => {
  const parts = urgencyParts({ pending: 10, critical: 2, urgent: 1, noData: 3 });
  assert.deepEqual(parts.map((p) => [p.key, p.value]), [['critical', 2], ['urgent', 1], ['planned', 4], ['nodata', 3]]);
});

test('no split when nothing is pending or the counts disagree', () => {
  assert.equal(urgencyParts({ pending: 0 }), null);
  assert.equal(urgencyParts({ pending: null, critical: 1 }), null);
  assert.equal(urgencyParts({ pending: 5, critical: 4, urgent: 3 }), null);
});

test('compact counts', () => {
  assert.equal(formatCompactCount(3800930), '3.8M');
  assert.equal(formatCompactCount(356287), '356.3K');
  assert.equal(formatCompactCount(999960), '1.0M');
  assert.equal(formatCompactCount(812), '812');
  assert.equal(formatCompactCount(0), '0');
  assert.equal(formatCompactCount(null), '—');
});
