// node --test src/utils (npm test): the stock-detail list's "had no sale" line.
import test from 'node:test';
import assert from 'node:assert/strict';
import { noSaleNote } from './aboveRuleNote.js';

const item = (pesos, above, noSale = true) => ({ pesos, above_rule_pesos: above, no_sale_in_window: noSale });

test('every no-sale product listed: the plain line', () => {
  assert.equal(
    noSaleNote([item(10, 10), item(5, 5), item(100, 40, false)]),
    '2 products had no sale in those months, so all of their stock counts as above the rule.',
  );
});

test('no-sale products valued at 0 are counted and said, not dropped silently', () => {
  const items = [...Array.from({ length: 80 }, () => item(10, 10)), item(0, 0), item(0, 0), item(50, 0, false)];
  assert.equal(
    noSaleNote(items),
    '82 products had no sale in those months, so all of their stock counts as above the rule: '
      + '80 listed · 2 valued at ₱0 at the count, so nothing above the rule to list.',
  );
});

test('a missing stock value and a negative one are told apart from a 0', () => {
  const note = noSaleNote([item(10, 10), item(null, null), item(-3, 0)]);
  assert.match(note, /^3 products had no sale/);
  assert.match(note, /1 listed · 1 valued below ₱0 at the count · 1 with no stock value recorded/);
});

test('no no-sale product: no line', () => {
  assert.equal(noSaleNote([item(10, 4, false)]), null);
  assert.equal(noSaleNote([]), null);
  assert.equal(noSaleNote(undefined), null);
});
