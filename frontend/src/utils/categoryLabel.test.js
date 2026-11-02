import test from 'node:test';
import assert from 'node:assert/strict';
import { categoryLabel } from './categoryLabel.js';

test('a path reads as its parts, title-cased, joined with a dot', () => {
  assert.equal(categoryLabel('/SWEET SPAG SAUCE/PROMO'), 'Sweet Spag Sauce · Promo');
  assert.equal(categoryLabel('/TOTAL 100% JUICES/ACE - BASE REGULAR'), 'Total 100% Juices · Ace - Base Regular');
  assert.equal(categoryLabel('FRUITS/'), 'Fruits');
});

test('a plain name stays plain', () => {
  assert.equal(categoryLabel('BEVERAGE'), 'Beverage');
  assert.equal(categoryLabel('Del Monte Culinary General'), 'Del Monte Culinary General');
});

test('nothing to format is returned as is', () => {
  assert.equal(categoryLabel(null), null);
  assert.equal(categoryLabel(undefined), undefined);
  assert.equal(categoryLabel(''), '');
  assert.equal(categoryLabel('/'), '/');
});
