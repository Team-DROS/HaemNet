import assert from 'node:assert/strict';
import { test } from 'node:test';

import { PAUSE_OPTIONS, callsStatus, pauseState } from '../components/availability.js';

const NOW = new Date('2026-11-25T10:00:00Z');
const inHours = (h) => new Date(NOW.getTime() + h * 3600 * 1000).toISOString();

test('pause options stay within what the server accepts', () => {
  for (const days of PAUSE_OPTIONS) assert.ok(Number.isInteger(days) && days >= 1 && days <= 30);
  assert.ok(PAUSE_OPTIONS.includes(7), 'a week is the headline choice');
});

test('no break, a bad value or a break that ended all mean available', () => {
  for (const value of [null, undefined, '', 'soon', inHours(-1)]) {
    assert.deepEqual(pauseState(value, NOW), { paused: false, until: null, daysLeft: 0 });
  }
});

test('days left rounds up', () => {
  assert.equal(pauseState(inHours(2), NOW).daysLeft, 1);
  assert.equal(pauseState(inHours(24), NOW).daysLeft, 1);
  assert.equal(pauseState(inHours(25), NOW).daysLeft, 2);
  assert.equal(pauseState(inHours(7 * 24), NOW).daysLeft, 7);
  assert.equal(pauseState(inHours(2), NOW).until.toISOString(), inHours(2));
});

test('calls status combines opt-out and breaks', () => {
  assert.equal(callsStatus({ optedOut: false, pausedUntil: null }, NOW), 'on');
  assert.equal(callsStatus({ optedOut: false, pausedUntil: inHours(5) }, NOW), 'paused');
  assert.equal(callsStatus({ optedOut: false, pausedUntil: inHours(-5) }, NOW), 'on');
  assert.equal(callsStatus({ optedOut: true, pausedUntil: inHours(5) }, NOW), 'off');
});
