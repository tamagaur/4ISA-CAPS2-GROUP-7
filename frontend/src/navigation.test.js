import test from 'node:test';
import assert from 'node:assert/strict';
import { P } from './permissions/keys.js';
import { nextNavItem } from './navigation.js';

test('next page follows the sidebar order', () => {
  const canOpen = () => true;
  assert.equal(nextNavItem('/reorder', canOpen).path, '/sku-management');
  assert.equal(nextNavItem('/abc', canOpen).path, '/forecast');
  assert.equal(nextNavItem('/forecast', canOpen).path, '/category-trends');
});

test('next page skips tabs the current user cannot open', () => {
  const canOpen = (permission) => permission !== P.SKU_VIEW;
  assert.equal(nextNavItem('/reorder', canOpen).path, '/abc');
});

test('there is no next page after the last visible tab', () => {
  assert.equal(nextNavItem('/users', () => true), null);
});
