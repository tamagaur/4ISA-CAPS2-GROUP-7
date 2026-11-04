import assert from 'node:assert/strict';
import test from 'node:test';
import { decisionCounts, decisionLine } from './decisionCounts.js';

test('counts each status of the plan', () => {
  const items = [{ status: 'pending' }, { status: 'pending' }, { status: 'accepted' }, { status: 'dismissed' }];
  assert.deepEqual(decisionCounts(items), { accepted: 1, dismissed: 1, pending: 2 });
});

test('an empty plan counts nothing, and an unknown status is not counted', () => {
  assert.deepEqual(decisionCounts(), { accepted: 0, dismissed: 0, pending: 0 });
  assert.deepEqual(decisionCounts([{ status: 'other' }]), { accepted: 0, dismissed: 0, pending: 0 });
});

test('reads as the review screen reads', () => {
  assert.equal(decisionLine({ accepted: 0, dismissed: 0, pending: 109 }), '0 accepted, 0 dismissed, 109 not decided');
  assert.equal(decisionLine({ accepted: 1200, dismissed: 3, pending: 0 }), '1,200 accepted, 3 dismissed, 0 not decided');
});
