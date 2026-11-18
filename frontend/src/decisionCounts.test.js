import assert from 'node:assert/strict';
import test from 'node:test';
import { decisionCounts, decisionLine, planStateLine } from './decisionCounts.js';

test('counts each status of the plan', () => {
  const items = [{ status: 'pending', q_i: 5 }, { status: 'pending', q_i: 7 }, { status: 'accepted' }, { status: 'dismissed' }];
  assert.deepEqual(decisionCounts(items), { accepted: 1, dismissed: 1, pending: 2, noOrder: 0 });
});

test('an empty plan counts nothing, and an unknown status is not counted', () => {
  assert.deepEqual(decisionCounts(), { accepted: 0, dismissed: 0, pending: 0, noOrder: 0 });
  assert.deepEqual(decisionCounts([{ status: 'other' }]), { accepted: 0, dismissed: 0, pending: 0, noOrder: 0 });
});

test('a pending row that orders nothing is not waiting for a decision (scenario audit 2026-11-18)', () => {
  const items = [{ status: 'pending', q_i: 0, plan_q_i: 0 }, { status: 'pending', q_i: 0 }, { status: 'pending', q_i: null },
    { status: 'pending', q_i: 12 }, { status: 'accepted', q_i: 9 }];
  const counts = decisionCounts(items);
  assert.deepEqual(counts, { accepted: 1, dismissed: 0, pending: 1, noOrder: 3 });
  assert.equal(decisionLine(counts), '1 accepted, 0 dismissed, 1 not decided; 3 order nothing, so need no decision');
  // all orderable rows decided: nothing is "not decided", and the banner stops reading as outstanding work
  assert.equal(decisionCounts([{ status: 'accepted', q_i: 4 }, { status: 'pending', q_i: 0 }]).pending, 0);
});

test('reads as the review screen reads', () => {
  assert.equal(decisionLine({ accepted: 0, dismissed: 0, pending: 109 }), '0 accepted, 0 dismissed, 109 not decided');
  assert.equal(decisionLine({ accepted: 1200, dismissed: 3, pending: 0 }), '1,200 accepted, 3 dismissed, 0 not decided');
});

test('run or closed says both months, and nothing when the API sends nothing', () => {
  assert.equal(planStateLine(null), null);
  assert.equal(planStateLine({ cycle: '2026-04', state: 'run', closed_at: null, prior: { cycle: '2026-03', state: 'run' } }),
    'This plan (2026-04) is run, not closed. 2026-03 is run, not closed.');
  assert.equal(planStateLine({ cycle: '2026-03', state: 'closed', closed_at: '2026-11-04 13:50:00+00', prior: null }),
    'This plan (2026-03) is closed on 2026-11-04.');
});
