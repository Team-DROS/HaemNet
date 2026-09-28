// Run with: npm test
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { DEVELOPMENT_API_URL, PRODUCTION_API_URL, resolveApiUrl } from '../components/config.js';

test('release builds use the configured HTTPS API', () => {
  assert.deepEqual(resolveApiUrl('https://haemnet-api.onrender.com/', false), {
    url: 'https://haemnet-api.onrender.com', source: 'configured',
  });
});

test('release builds never fall back to localhost', () => {
  for (const value of [undefined, '', '   ']) {
    const r = resolveApiUrl(value, false);
    assert.equal(r.url, PRODUCTION_API_URL);
    assert.equal(r.source, 'production-default');
  }
});

test('release builds reject plain HTTP, private hosts and garbage', () => {
  for (const value of ['http://haemnet-api.onrender.com', 'https://localhost:8000', 'https://192.168.1.5:8000', 'https://10.0.2.2', 'not a url']) {
    assert.equal(resolveApiUrl(value, false).url, PRODUCTION_API_URL, value);
  }
});

test('development builds accept a local API and default to localhost', () => {
  assert.equal(resolveApiUrl('http://192.168.1.5:8000', true).url, 'http://192.168.1.5:8000');
  assert.equal(resolveApiUrl(undefined, true).url, DEVELOPMENT_API_URL);
});
