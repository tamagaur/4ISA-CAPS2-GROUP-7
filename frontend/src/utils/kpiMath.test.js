// node --test src/utils  (npm test). The live figures used below are GET
// /dashboard's for Unilever, Mar 2025 – Feb 2026, read on 2026-10-11.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  allocationPace, classAChecks, coverScale, excessAbovePolicy, coverSplit, coverVerdict, formatCompactCount, formatPercent, policyRatio,
  shareOf, stockChangeTone, urgencyParts,
} from './kpiMath.js';

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

// The figures below are the 2026-10-18 design mock-up's (Unilever, Jan–Feb
// 2026), not live ones: they check the arithmetic, not the data.
test('expected by now follows last year: Jan–Feb 2025 x 103%', () => {
  const pace = allocationPace({
    ytdSales: 65.1e6, ytdMonths: 2, priorYtdSales: 67.4e6, priorYtdMonths: 2, pct: 103, target: 405.2e6, monthsLeft: 10,
  });
  assert.ok(Math.abs(pace.expected - 69.422e6) < 1);
  assert.ok(Math.abs(pace.gap - -4.322e6) < 1);
  assert.ok(Math.abs(pace.perMonthNeeded - 34.01e6) < 1);
  assert.equal(formatPercent(pace.share), '16%');
  assert.equal(pace.reached, false);
});

test('no expected figure when last year has a different number of months on record', () => {
  const pace = allocationPace({ ytdSales: 10, ytdMonths: 3, priorYtdSales: 9, priorYtdMonths: 2, pct: 103, target: 100, monthsLeft: 9 });
  assert.equal(pace.expected, null);
  assert.equal(pace.gap, null);
  assert.ok(Math.abs(pace.perMonthNeeded - 10) < 1e-9);
});

test('nothing to pace without sales this year; nothing per month once reached', () => {
  assert.equal(allocationPace({ ytdSales: null, ytdMonths: 0 }), null);
  const done = allocationPace({ ytdSales: 120, ytdMonths: 11, target: 100, monthsLeft: 1 });
  assert.equal(done.reached, true);
  assert.equal(done.perMonthNeeded, null);
});

test('cover split: 6.2 weeks against 3 is 3 needed and 3.2 extra', () => {
  const s = coverSplit(6.2, 3);
  assert.equal(s.needed, 3);
  assert.ok(Math.abs(s.extra - 3.2) < 1e-9);
  assert.equal(s.short, 0);
  assert.deepEqual(coverSplit(1.5, 3), { needed: 1.5, extra: 0, short: 1.5 });
  assert.equal(coverSplit(null, 3), null);
  assert.equal(coverSplit(2, 0), null);
});

test('cover verdict in words', () => {
  assert.equal(coverVerdict(6.21 / 3).text, 'About double the target');
  assert.equal(coverVerdict(1).text, 'On target');
  assert.equal(coverVerdict(0.5).tone, 'negative');
  assert.equal(coverVerdict(1.2).text, 'A little above the target');
  assert.equal(coverVerdict(1.6).text, 'About 1.5× the target');
  assert.equal(coverVerdict(3.1).text, 'About triple the target');
  assert.equal(coverVerdict(null), null);
});

test('Class A checks: 6 low and 66 OK of 72 checked, 117 of 189 not checked', () => {
  assert.deepEqual(classAChecks({ all: 189, checked: 72, below: 6 }), { below: 6, ok: 66, unchecked: 117 });
  assert.equal(classAChecks({ all: 50, checked: 72, below: 6 }), null);
  assert.equal(classAChecks({ all: 189, checked: 72, below: null }), null);
});

test('a rise in stock is bad above the policy and good below it', () => {
  assert.equal(stockChangeTone(5, 2.07), 'negative');
  assert.equal(stockChangeTone(-5, 2.07), 'positive');
  assert.equal(stockChangeTone(5, 0.5), 'positive');
  assert.equal(stockChangeTone(5, 1), 'neutral');
  assert.equal(stockChangeTone(5, null), 'neutral');
  assert.equal(stockChangeTone(0, 2), 'neutral');
});

test('money past the 3-week rule: ₱46.6M at 6.21 weeks is about ₱24.1M', () => {
  const x = excessAbovePolicy(46576778.51, 6.21, 3);
  assert.ok(Math.abs(x - 46576778.51 * 3.21 / 6.21) < 1e-6);
  assert.equal((x / 1e6).toFixed(1), '24.1');
  // the same as stock − 3 weeks × (stock ÷ weeks)
  assert.ok(Math.abs(x - (46576778.51 - 3 * (46576778.51 / 6.21))) < 1e-6);
});

test('nothing tied up at or below the rule, or without both figures', () => {
  assert.equal(excessAbovePolicy(6.7e6, 2.69, 3), null);
  assert.equal(excessAbovePolicy(9e6, 3, 3), null);
  assert.equal(excessAbovePolicy(null, 6.2, 3), null);
  assert.equal(excessAbovePolicy(46e6, 0, 3), null);
});
