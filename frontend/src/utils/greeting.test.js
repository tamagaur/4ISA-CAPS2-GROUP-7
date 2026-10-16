import test from 'node:test';
import assert from 'node:assert/strict';
import { firstNameOf, greetingFor } from './greeting.js';

test('greeting follows the hour', () => {
  assert.equal(greetingFor(5), 'Good morning');
  assert.equal(greetingFor(11), 'Good morning');
  assert.equal(greetingFor(12), 'Good afternoon');
  assert.equal(greetingFor(17), 'Good afternoon');
  assert.equal(greetingFor(18), 'Good evening');
  assert.equal(greetingFor(23), 'Good evening');
  assert.equal(greetingFor(0), 'Good evening');
  assert.equal(greetingFor(4), 'Good evening');
});

test('first name is the first word, else the email', () => {
  assert.equal(firstNameOf('Mikhaella Audrey Bugayong'), 'Mikhaella');
  assert.equal(firstNameOf('  Audrey  '), 'Audrey');
  assert.equal(firstNameOf('', 'tamago@example.com'), 'tamago');
  assert.equal(firstNameOf(null, null), '');
});
