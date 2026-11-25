import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  APP_LANGUAGES, DEFAULT_LANGUAGE, LOCALES, TABLES, appLanguageForCall, formatDate, isAppLanguage, makeT, placeholders, translate,
} from '../components/i18n.js';

const english = TABLES.en;

test('every language has exactly the English keys', () => {
  for (const [code, table] of Object.entries(TABLES)) {
    const missing = Object.keys(english).filter((k) => !(k in table));
    const extra = Object.keys(table).filter((k) => !(k in english));
    assert.deepEqual(missing, [], `${code} is missing keys`);
    assert.deepEqual(extra, [], `${code} has keys English does not`);
  }
});

test('translations keep the same placeholders and are never blank', () => {
  for (const [code, table] of Object.entries(TABLES)) {
    for (const [key, text] of Object.entries(table)) {
      assert.equal(typeof text, 'string', `${code}.${key}`);
      assert.ok(text.trim().length > 0, `${code}.${key} is blank`);
      assert.deepEqual(placeholders(text), placeholders(english[key]), `${code}.${key} placeholders`);
    }
  }
});

test('Hindi and Tamil are actually translated, in their own scripts', () => {
  const devanagari = /[ऀ-ॿ]/;
  const tamil = /[஀-௿]/;
  const keys = Object.keys(english);
  const hindiShare = keys.filter((k) => devanagari.test(TABLES.hi[k])).length / keys.length;
  const tamilShare = keys.filter((k) => tamil.test(TABLES.ta[k])).length / keys.length;
  // A few strings are numbers, units or brand names and stay in Latin script.
  assert.ok(hindiShare > 0.9, `only ${Math.round(hindiShare * 100)}% of Hindi strings use Devanagari`);
  assert.ok(tamilShare > 0.9, `only ${Math.round(tamilShare * 100)}% of Tamil strings use Tamil script`);
});

test('placeholders are filled, and missing values stay visible', () => {
  const key = Object.keys(english).find((k) => placeholders(english[k]).length > 0);
  const names = placeholders(english[key]);
  const filled = translate('en', key, Object.fromEntries(names.map((n) => [n, 'X'])));
  assert.ok(!/\{\w+\}/.test(filled));
  assert.match(translate('en', key, {}), /\{\w+\}/);
});

test('unknown languages and keys fall back safely', () => {
  const key = Object.keys(english)[0];
  assert.equal(translate('fr', key), english[key]);
  assert.equal(translate('en', 'no.such.key'), 'no.such.key');
  assert.equal(makeT('xx').language, DEFAULT_LANGUAGE);
  assert.equal(makeT('ta').language, 'ta');
});

test('language codes', () => {
  assert.deepEqual(APP_LANGUAGES.map((l) => l.code), Object.keys(TABLES));
  assert.equal(isAppLanguage('hi'), true);
  assert.equal(isAppLanguage('toString'), false);
  assert.equal(appLanguageForCall('Tamil'), 'ta');
  assert.equal(appLanguageForCall('Hindi'), 'hi');
  assert.equal(appLanguageForCall('Bengali'), 'en');
});

test('dates use the locale of the chosen language and tolerate bad input', () => {
  assert.deepEqual(Object.keys(LOCALES), Object.keys(TABLES));
  const day = new Date(2026, 11, 2);
  assert.match(formatDate('en', day), /2/);
  assert.equal(typeof makeT('ta').date(day), 'string');
  assert.equal(formatDate('en', 'nonsense'), '');
});
