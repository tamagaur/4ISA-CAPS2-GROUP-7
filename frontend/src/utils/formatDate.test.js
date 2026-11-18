import test from 'node:test';
import assert from 'node:assert/strict';
import { philippineDay, formatDate } from './formatDate.js';

test('philippineDay names the Philippine calendar day of a UTC instant', () => {
  // 08:08 UTC is 16:08 in Manila: the same day.
  assert.equal(philippineDay('2026-11-13T08:08:47+00:00'), '2026-11-13');
  // 17:00 UTC on the 13th is 01:00 on the 14th in Manila: the UTC slice would say the 13th.
  assert.equal(philippineDay('2026-11-13T17:00:00+00:00'), '2026-11-14');
  // The month boundary: 16:00 UTC on 30 Nov is 00:00 on 1 Dec in Manila.
  assert.equal(philippineDay('2026-11-30T16:00:00Z'), '2026-12-01');
  assert.equal(philippineDay('2026-11-30T15:59:59Z'), '2026-11-30');
});

test('philippineDay leaves a calendar date alone and survives nothing and nonsense', () => {
  assert.equal(philippineDay('2026-11-13'), '2026-11-13');
  assert.equal(philippineDay(null), null);
  assert.equal(philippineDay('not a date'), 'not a date');
  assert.equal(formatDate(philippineDay('2026-11-30T16:00:00Z')), 'Dec 1, 2026');
});
