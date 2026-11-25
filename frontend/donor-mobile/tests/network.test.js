import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  REQUESTS_CACHE_MAX_AGE_MS, connectionState, minutesSince, profileView, readSavedRequests, serializeRequests,
} from '../components/network.js';

test('only a definite answer counts as offline', () => {
  assert.equal(connectionState(null), 'unknown');
  assert.equal(connectionState({ isConnected: null }), 'unknown');
  assert.equal(connectionState({ isConnected: false, isInternetReachable: null }), 'offline');
  assert.equal(connectionState({ isConnected: true, isInternetReachable: false }), 'offline');
  assert.equal(connectionState({ isConnected: true, isInternetReachable: null }), 'online');
  assert.equal(connectionState({ isConnected: true, isInternetReachable: true }), 'online');
});

test('a server outage never shows the join form', () => {
  assert.equal(profileView({ hasSaved: true, server: 'found' }), 'dashboard');
  assert.equal(profileView({ hasSaved: false, server: 'found' }), 'dashboard');
  assert.equal(profileView({ hasSaved: true, server: 'missing' }), 'join');
  assert.equal(profileView({ hasSaved: false, server: 'missing' }), 'join');
  assert.equal(profileView({ hasSaved: true, server: 'unreachable' }), 'dashboard');
  assert.equal(profileView({ hasSaved: false, server: 'unreachable' }), 'retry');
});

test('saved requests round-trip and drop damaged rows', () => {
  const now = 1_700_000_000_000;
  const raw = serializeRequests([{ dispatch_id: 'a', units: 1 }, null, { units: 2 }], now);
  assert.deepEqual(readSavedRequests(raw, now + 1000), { savedAt: now, requests: [{ dispatch_id: 'a', units: 1 }] });
  assert.deepEqual(readSavedRequests(serializeRequests('nope', now), now), { savedAt: now, requests: [] });
});

test('old, future-dated or broken saves are ignored', () => {
  const now = 1_700_000_000_000;
  assert.equal(readSavedRequests(serializeRequests([], now - REQUESTS_CACHE_MAX_AGE_MS - 1), now), null);
  assert.equal(readSavedRequests(serializeRequests([], now + 10 * 60000), now), null);
  for (const raw of [null, '', '{', '{"requests":[]}', '{"savedAt":1}']) assert.equal(readSavedRequests(raw, now), null);
});

test('minutes since', () => {
  assert.equal(minutesSince(1000, 1000 + 59_999), 0);
  assert.equal(minutesSince(0, 5 * 60000), 5);
  assert.equal(minutesSince(10_000, 0), 0);
  assert.equal(minutesSince(undefined, 0), null);
});
