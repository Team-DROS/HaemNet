import assert from 'node:assert/strict';
import { test } from 'node:test';

import { COOLDOWN_DAYS, HEALTH_QUESTIONS, daysUntilEligible, evaluateAnswers } from '../components/eligibility.js';

const allSafe = Object.fromEntries(HEALTH_QUESTIONS.map((q) => [q.id, q.safe]));

test('every question has a unique id and a yes or no safe answer', () => {
  const ids = HEALTH_QUESTIONS.map((q) => q.id);
  assert.equal(new Set(ids).size, ids.length);
  for (const q of HEALTH_QUESTIONS) assert.ok(q.safe === 'yes' || q.safe === 'no');
});

test('all safe answers mean the donor can go ahead', () => {
  assert.deepEqual(evaluateAnswers(allSafe), { complete: true, eligible: true, failed: [] });
});

test('an unanswered question blocks going ahead but is not a failure', () => {
  const { well, ...rest } = allSafe;
  assert.equal(well, 'yes');
  assert.deepEqual(evaluateAnswers(rest), { complete: false, eligible: false, failed: [] });
  assert.deepEqual(evaluateAnswers(undefined), { complete: false, eligible: false, failed: [] });
});

test('each unsafe answer is reported in question order', () => {
  const answers = { ...allSafe, alcohol: 'yes', well: 'no' };
  assert.deepEqual(evaluateAnswers(answers), { complete: true, eligible: false, failed: ['well', 'alcohol'] });
});

test('only yes and no count as answers', () => {
  assert.equal(evaluateAnswers({ ...allSafe, well: 'maybe' }).complete, false);
});

test('recovery window counts calendar days', () => {
  const now = new Date(2026, 10, 25, 9, 0);
  assert.equal(daysUntilEligible(null, now), 0);
  assert.equal(daysUntilEligible('not a date', now), 0);
  assert.equal(daysUntilEligible(new Date(2026, 10, 25, 23, 59), now), COOLDOWN_DAYS);
  assert.equal(daysUntilEligible(new Date(2026, 10, 24, 23, 59), now), COOLDOWN_DAYS - 1);
  assert.equal(daysUntilEligible(new Date(2026, 8, 30), now), 0); // 56 days earlier
  assert.equal(daysUntilEligible(new Date(2026, 9, 1).toISOString(), now), 1);
});
