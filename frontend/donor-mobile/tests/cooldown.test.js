// Run with: npm test
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { COOLDOWN_DAYS, cooldownProgress } from '../components/cooldown.js';

test('a donor with no recorded donation is eligible', () => {
  assert.deepEqual(cooldownProgress(null), { daysElapsed: COOLDOWN_DAYS, daysRemaining: 0, progressPercent: 100 });
});

test('counts calendar days in the recovery window', () => {
  const r = cooldownProgress(new Date(2026, 0, 1, 23, 0), new Date(2026, 0, 15, 8, 0));
  assert.equal(r.daysElapsed, 14);
  assert.equal(r.daysRemaining, COOLDOWN_DAYS - 14);
  assert.equal(r.progressPercent, 25);
});

test('becomes eligible exactly after the cooldown and caps progress', () => {
  const donated = new Date(2026, 0, 1);
  assert.equal(cooldownProgress(donated, new Date(2026, 1, 26)).daysRemaining, 0);
  assert.equal(cooldownProgress(donated, new Date(2026, 5, 1)).progressPercent, 100);
});

test('counts whole days across a daylight-saving change', () => {
  // Round, not floor: a 23-hour calendar day must still count as one day.
  const r = cooldownProgress(new Date(2026, 2, 1), new Date(2026, 3, 1));
  assert.equal(r.daysElapsed, 31);
});
