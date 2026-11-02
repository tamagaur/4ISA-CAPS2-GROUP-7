import test from 'node:test';
import assert from 'node:assert/strict';
import { createLatestOnly } from './latestOnly.js';
import { latestRunFor, requestedAbcPeriod, shownAbcPeriod } from './abcMonth.js';

test('a response from a superseded request is never current, even if it lands last', async () => {
  const gate = createLatestOnly();
  const applied = [];
  const load = (principal, delayMs) => {
    const tag = gate.start();
    return new Promise((r) => setTimeout(r, delayMs)).then(() => { if (gate.isCurrent(tag)) applied.push(principal); });
  };
  // Unilever is slow, Del Monte (requested second) is fast: Unilever lands AFTER Del Monte.
  await Promise.all([load('unilever', 30), load('delmonte', 5)]);
  assert.deepEqual(applied, ['delmonte']);
});

test('invalidate() drops the response of a request still in flight', () => {
  const gate = createLatestOnly();
  const tag = gate.start();
  gate.invalidate();
  assert.equal(gate.isCurrent(tag), false);
});

test('with no pick the ABC page asks for the range end, for every principal', () => {
  // Del Monte then Unilever: the same request both times, so Unilever is back on 2026-02.
  assert.equal(requestedAbcPeriod(null, '2026-02'), '2026-02');
  assert.equal(requestedAbcPeriod(undefined, '2026-02'), '2026-02');
});

test("the person's pick is asked for as it is, never moved by a response", () => {
  assert.equal(requestedAbcPeriod('2025-05', '2026-02'), '2025-05');
});

test('the picker shows the run on screen once its answer is current, else the month asked for', () => {
  // Del Monte asked for 2026-02 and answered with its latest run, 2025-12.
  assert.equal(shownAbcPeriod('2026-02', '2025-12', true), '2025-12');
  // The previous principal's answer is still on screen while the new one loads.
  assert.equal(shownAbcPeriod('2026-02', '2025-12', false), '2026-02');
  assert.equal(shownAbcPeriod('2026-02', null, true), '2026-02');
});

test('latestRunFor reads one principal, or the latest of any', () => {
  const runs = { Unilever: '2026-02', 'Del Monte': '2025-12' };
  assert.equal(latestRunFor(runs, 'Del Monte'), '2025-12');
  assert.equal(latestRunFor(runs, null), '2026-02');
  assert.equal(latestRunFor({}, 'Unilever'), null);
});
