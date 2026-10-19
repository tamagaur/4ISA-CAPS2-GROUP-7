// node --test src/utils  (npm test). The live figures used below are GET
// /dashboard's for Unilever, Mar 2025 – Feb 2026, read on 2026-10-11.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  coverScale, excessOverPolicy, expectedByNow, formatCompactCount, formatPercent, neededPerMonth, policyRatio,
  shareOf, urgencyParts,
} from './kpiMath.js';

// GET /dashboard's allocation for Unilever, read 2026-10-18: FY 2025 sales
// ₱393.4M over 12 months, Jan–Feb 2025 ₱67.4M, Jan–Feb 2026 ₱65.1M, the 103%
// target ₱405.2M.
const ALLOC = {
  target: 405218729.91, priorYtd: 67383411.68, basisSales: 393416242.63,
  ytdMonths: 2, priorMonths: 2, basisMonths: 12,
};

test('sales expected by now follow last year\'s own share of the year', () => {
  assert.equal((expectedByNow(ALLOC) / 1e6).toFixed(1), '69.4');
});

test('expected by now is null without a like-for-like, whole-year basis', () => {
  assert.equal(expectedByNow({ ...ALLOC, priorMonths: 1 }), null);
  assert.equal(expectedByNow({ ...ALLOC, basisMonths: 6 }), null);
  assert.equal(expectedByNow({ ...ALLOC, priorYtd: null }), null);
  assert.equal(expectedByNow({ ...ALLOC, ytdMonths: 0 }), null);
});

test('what each remaining month needs is the gap over the months left', () => {
  assert.equal((neededPerMonth({ target: ALLOC.target, ytdSales: 65080308.3, ytdMonths: 2 }) / 1e6).toFixed(1), '34.0');
  assert.equal(neededPerMonth({ target: 100, ytdSales: 120, ytdMonths: 3 }), 0);
  assert.equal(neededPerMonth({ target: 100, ytdSales: 100, ytdMonths: 12 }), null);
  assert.equal(neededPerMonth({ target: null, ytdSales: 1, ytdMonths: 1 }), null);
});

test('stock beyond the rule is the share of the cover past it, of the stock value', () => {
  assert.equal((excessOverPolicy(46576778.51, 6.21, 3) / 1e6).toFixed(1), '24.1');
  assert.equal(excessOverPolicy(1000, 3, 3), 0);
  assert.equal(excessOverPolicy(1000, 2, 3), 0);
  assert.equal(excessOverPolicy(1000, null, 3), null);
  assert.equal(excessOverPolicy(1000, 6, 0), null);
});

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
