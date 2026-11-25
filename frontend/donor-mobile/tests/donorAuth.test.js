// Run with: npm test
import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  callsConsentField, codeErrorMessage, consentRequired, digitsOnly, isValidCode, isValidPhone,
  registerBody, resendCountdown,
} from '../components/donorAuth.js';

test('phone and code validation', () => {
  assert.equal(isValidPhone('9876543210'), true);
  for (const bad of ['', '98765', '98765432101', '98765abcde', null, undefined]) assert.equal(isValidPhone(bad), false);
  assert.equal(isValidCode('123456'), true);
  assert.equal(isValidCode(' 123456 '), true);
  for (const bad of ['12345', '1234567', 'abcdef', '', null]) assert.equal(isValidCode(bad), false);
});

test('digitsOnly keeps only digits and caps the length', () => {
  assert.equal(digitsOnly('12 34-56789'), '123456');
  assert.equal(digitsOnly('98765 43210', 10), '9876543210');
  assert.equal(digitsOnly(undefined), '');
});

test('the proof token is sent only when there is one', () => {
  assert.deepEqual(registerBody('9876543210', 'pw'), { phone: '9876543210', password: 'pw' });
  assert.deepEqual(registerBody('9876543210', 'pw', 'tok'), { phone: '9876543210', password: 'pw', otp_token: 'tok' });
});

test('failed code requests and checks get a plain message, never a raw error', () => {
  const at = (status) => ({ response: { status } });
  assert.match(codeErrorMessage({}, 'send'), /connection/);
  assert.match(codeErrorMessage(at(429), 'verify'), /wrong codes/);
  assert.match(codeErrorMessage(at(429), 'send'), /requested/);
  assert.match(codeErrorMessage(at(400), 'verify'), /wrong or has expired/);
  assert.match(codeErrorMessage(at(503), 'send'), /right now/);
  assert.match(codeErrorMessage(at(418), 'send'), /Could not send/);
});

test('the resend countdown runs down to zero and never goes negative', () => {
  assert.equal(resendCountdown(null, 1000), 0);
  assert.equal(resendCountdown(0, 0), 0);
  assert.equal(resendCountdown(1000, 1000, 30), 30);
  assert.equal(resendCountdown(1000, 11000, 30), 20);
  assert.equal(resendCountdown(1000, 99000, 30), 0);
});

test('call consent is needed to join, and only sent when joining', () => {
  assert.equal(consentRequired(false), true);
  assert.equal(consentRequired(true), false);
  assert.deepEqual(callsConsentField(false, true), { calls_consent: true });
  assert.deepEqual(callsConsentField(false, false), { calls_consent: false });
  assert.deepEqual(callsConsentField(true, true), {}); // editing a profile must not rewrite consent
});

test('code errors follow the donor\'s language', () => {
  const t = (key) => `[${key}]`;
  assert.equal(codeErrorMessage({ response: { status: 400 } }, 'verify', t), '[otp.wrongOrExpired]');
  assert.equal(codeErrorMessage({}, 'send', t), '[otp.noConnection]');
});
