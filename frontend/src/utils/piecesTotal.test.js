// node --test src/utils (npm test): the Suggested orders strip's pieces total.
import test from 'node:test';
import assert from 'node:assert/strict';
import { shownPiecesTotal } from './piecesTotal.js';
import { wholeUnits } from './formatNumber.js';

test('the total is the sum of each row rounded up, not the sum rounded up', () => {
  const rows = [{ orderQty: 10.2 }, { orderQty: 20.3 }, { orderQty: 5 }];
  // Rows show 11, 21, 5; the rounded-up sum would be ceil(35.5) = 36.
  assert.equal(shownPiecesTotal(rows), 37);
  assert.equal(shownPiecesTotal(rows), rows.reduce((s, r) => s + wholeUnits(r.orderQty), 0));
});

test('an exact integer (with float noise) is not bumped to the next piece', () => {
  assert.equal(shownPiecesTotal([{ orderQty: 1782.0000000002 }, { orderQty: 3 }]), 1785);
  assert.equal(shownPiecesTotal([{ orderQty: 0 }]), 0);
});

test('a row without a quantity leaves the total out rather than counting it as 0', () => {
  assert.equal(shownPiecesTotal([{ orderQty: 4.5 }, { orderQty: null }]), null);
  assert.equal(shownPiecesTotal([{ orderQty: 4.5 }, {}]), null);
  assert.equal(shownPiecesTotal([{ orderQty: NaN }]), null);
});

test('no rows sums to 0', () => {
  assert.equal(shownPiecesTotal([]), 0);
});
