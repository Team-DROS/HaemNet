import assert from 'node:assert/strict';
import { test } from 'node:test';

import { monitoringOptions, scrubBreadcrumb, scrubEvent, scrubText } from '../components/monitoringLogic.js';

test('phone numbers are removed in every common shape', () => {
  for (const raw of ['9876543210', '+919876543210', '+91 98765 43210', '919876543210', '09876543210', '%2B919876543210']) {
    assert.equal(scrubText(`call ${raw} now`), 'call [phone] now', raw);
  }
  assert.equal(scrubText('/api/donor/profile/%2B919876543210'), '/api/donor/profile/[phone]');
});

test('ordinary numbers survive', () => {
  assert.equal(scrubText('status 503 after 90000 ms, version 1.2.0'), 'status 503 after 90000 ms, version 1.2.0');
  assert.equal(scrubText('dispatch 5b0a8f5e-3f0a-4c53'), 'dispatch 5b0a8f5e-3f0a-4c53');
});

test('tokens are removed', () => {
  assert.equal(scrubText('Authorization: Bearer abc.def-ghi'), 'Authorization: Bearer [token]');
  assert.equal(scrubText('ExponentPushToken[xxxxxxxxxxxx] failed'), '[push-token] failed');
  assert.equal(scrubText('token eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.sig'), 'token [jwt]');
});

test('events lose the user, request bodies and headers, and are scrubbed deeply', () => {
  const event = {
    user: { id: '9876543210' },
    request: { url: 'https://api/x/+919876543210', data: { password: 'p' }, headers: { Authorization: 'Bearer t' }, cookies: 'c' },
    exception: { values: [{ value: 'Request failed for 9876543210' }] },
    breadcrumbs: [{ message: 'GET /api/donor/requests/%2B919876543210' }],
    level: 'error',
  };
  const clean = scrubEvent(event);
  assert.equal(clean.user, undefined);
  assert.deepEqual(clean.request, { url: 'https://api/x/[phone]' });
  assert.equal(clean.exception.values[0].value, 'Request failed for [phone]');
  assert.equal(clean.breadcrumbs[0].message, 'GET /api/donor/requests/[phone]');
  assert.equal(clean.level, 'error');
  assert.equal(event.user.id, '9876543210', 'the original event is not modified');
});

test('console breadcrumbs are dropped, others scrubbed', () => {
  assert.equal(scrubBreadcrumb({ category: 'console', message: 'x' }), null);
  assert.deepEqual(scrubBreadcrumb({ category: 'xhr', data: { url: '/p/9876543210' } }), { category: 'xhr', data: { url: '/p/[phone]' } });
  assert.equal(scrubBreadcrumb(null), null);
});

test('reporting is off without a valid DSN and private when on', () => {
  for (const dsn of [undefined, '', 'not-a-dsn', 'http://k@o.ingest.sentry.io/1']) assert.equal(monitoringOptions(dsn), null);
  const options = monitoringOptions(' https://key@o1.ingest.sentry.io/123 ', 'staging', 'donor@1.2.0');
  assert.equal(options.dsn, 'https://key@o1.ingest.sentry.io/123');
  assert.equal(options.environment, 'staging');
  assert.equal(options.sendDefaultPii, false);
  assert.equal(options.attachScreenshot, false);
  assert.equal(options.beforeSend, scrubEvent);
  assert.equal(monitoringOptions('https://key@o1.ingest.sentry.io/123').environment, 'production');
});
