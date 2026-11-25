import assert from 'node:assert/strict';
import { test } from 'node:test';

import { ALERT_CHANNEL_ID, alertState, alertTarget, isExpoPushToken, tokenUpdate } from '../components/pushLogic.js';

const TOKEN = 'ExponentPushToken[xxxxxxxxxxxxxxxxxxxxxx]';
const OTHER = 'ExpoPushToken[yyyyyyyyyyyyyyyy]';
const notification = (data) => ({ request: { content: { data } } });

test('the channel id matches the backend', () => {
  assert.equal(ALERT_CHANNEL_ID, 'emergency-requests');
});

test('only Expo push tokens are accepted', () => {
  assert.equal(isExpoPushToken(TOKEN), true);
  assert.equal(isExpoPushToken(OTHER), true);
  for (const bad of ['', 'ExponentPushToken[]', 'fcm-token', null, undefined, 42]) assert.equal(isExpoPushToken(bad), false);
});

test('a new request alert opens that request, an acceptance opens the trip', () => {
  assert.deepEqual(alertTarget(notification({ type: 'new_request', dispatch_id: 'd-1' })), { action: 'show-request', dispatchId: 'd-1' });
  assert.deepEqual(
    alertTarget({ notification: notification({ type: 'dispatch_accepted', dispatch_id: ' d-2 ' }) }),
    { action: 'show-trip', dispatchId: 'd-2' },
  );
});

test('unknown or incomplete alerts do nothing', () => {
  for (const value of [
    null, undefined, {}, notification(null), notification({ type: 'new_request' }),
    notification({ type: 'marketing', dispatch_id: 'd-1' }), notification({ type: 'new_request', dispatch_id: 7 }),
  ]) assert.equal(alertTarget(value), null);
});

test('the server token changes only when this phone has a different one', () => {
  assert.deepEqual(tokenUpdate(null, TOKEN), { needed: true, token: TOKEN });
  assert.deepEqual(tokenUpdate(TOKEN, TOKEN), { needed: false, token: TOKEN });
  assert.deepEqual(tokenUpdate(TOKEN, OTHER), { needed: true, token: OTHER });
  assert.deepEqual(tokenUpdate(TOKEN, null), { needed: true, token: null });
  assert.deepEqual(tokenUpdate(null, null), { needed: false, token: null });
  assert.deepEqual(tokenUpdate('garbage', 'also garbage'), { needed: false, token: null });
});

test('alert state in plain terms', () => {
  assert.equal(alertState({ isDevice: false, permission: 'granted', token: TOKEN }), 'unsupported');
  assert.equal(alertState({ isDevice: true, permission: 'granted', token: TOKEN }), 'on');
  assert.equal(alertState({ isDevice: true, permission: 'granted', token: null }), 'pending');
  assert.equal(alertState({ isDevice: true, permission: 'denied', canAskAgain: false }), 'blocked');
  assert.equal(alertState({ isDevice: true, permission: 'denied', canAskAgain: true }), 'off');
  assert.equal(alertState({ isDevice: true, permission: 'undetermined' }), 'off');
});
