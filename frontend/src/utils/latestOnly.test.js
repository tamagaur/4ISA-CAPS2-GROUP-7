import test from 'node:test';
import assert from 'node:assert/strict';
import { createLatestOnly } from './latestOnly.js';
import { monthToSelect, latestRunFor } from './abcMonth.js';

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

test('the equivalent month is kept when the principal has a run for it', () => {
  assert.equal(monthToSelect('2025-12', '2025-12'), null);
});

test('a month after the latest run of the principal moves to that latest run', () => {
  assert.equal(monthToSelect('2026-02', '2025-12'), '2025-12');
});

test('a month with no run inside the history moves back to the nearest earlier run, never forward', () => {
  assert.equal(monthToSelect('2025-05', '2025-04'), '2025-04');
  assert.equal(monthToSelect('2025-05', '2025-06'), null);
});

test('nothing is selected when there is no request or no resolved period', () => {
  assert.equal(monthToSelect(undefined, '2025-12'), null);
  assert.equal(monthToSelect('2025-12', null), null);
});

test('latestRunFor reads one principal, or the latest of any', () => {
  const runs = { Unilever: '2026-02', 'Del Monte': '2025-12' };
  assert.equal(latestRunFor(runs, 'Del Monte'), '2025-12');
  assert.equal(latestRunFor(runs, null), '2026-02');
  assert.equal(latestRunFor({}, 'Unilever'), null);
});
