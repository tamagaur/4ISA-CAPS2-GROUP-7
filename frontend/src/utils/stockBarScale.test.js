// utils/stockBarScale.js: the ABC stock check's bar length. Run: npm test
import test from 'node:test';
import assert from 'node:assert/strict';
import { shareBarWidth } from './stockBarScale.js';

test('a bar is its share of sales on a 0-100% scale', () => {
  assert.equal(shareBarWidth(21), 21);
  assert.equal(shareBarWidth(9), 9);
  assert.equal(shareBarWidth(13), 13);
  assert.equal(shareBarWidth(38), 38);
  assert.equal(shareBarWidth(21.3), 21.3);
});

test('bars are not normalised to the largest one', () => {
  // The four statuses of the page as of 2026-11-06 (48, 23, 25 and 93
  // products): the widths follow the shares alone, so the largest share is
  // 38% of the track, not all of it.
  const widths = [21, 9, 13, 38].map(shareBarWidth);
  assert.deepEqual(widths, [21, 9, 13, 38]);
  assert.equal(Math.max(...widths), 38);
  // Proportional: 38% is 38/21 times as long as 21%.
  assert.equal(shareBarWidth(38) / shareBarWidth(21), 38 / 21);
});

test('no minimum width: a tiny share stays tiny and none is nothing', () => {
  assert.equal(shareBarWidth(0.4), 0.4);
  assert.equal(shareBarWidth(0), 0);
});

test('missing or out-of-range values are held to the scale', () => {
  assert.equal(shareBarWidth(null), 0);
  assert.equal(shareBarWidth(undefined), 0);
  assert.equal(shareBarWidth(Number.NaN), 0);
  assert.equal(shareBarWidth(-5), 0);
  assert.equal(shareBarWidth(140), 100);
});
