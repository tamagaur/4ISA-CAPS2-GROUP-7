// utils/forecastAccuracyScope.js: the accuracy card's coverage line on the SKU Forecast page. Run: npm test
import test from 'node:test';
import assert from 'node:assert/strict';
import { accuracyScopeLine } from './forecastAccuracyScope.js';

test('names the one principal the figures cover', () => {
  assert.equal(
    accuracyScopeLine(['unilever']),
    'Unilever products whose forecast was checked against sales, over the months picked above.',
  );
});

test('names both when the response covers both', () => {
  assert.match(accuracyScopeLine(['unilever', 'delmonte']), /^Unilever and Del Monte products /);
});

test('says nothing when the response covers no principal', () => {
  assert.equal(accuracyScopeLine([]), null);
  assert.equal(accuracyScopeLine(undefined), null);
});
