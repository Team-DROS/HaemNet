// App text in English, Hindi and Tamil.
//
// Every string the donor reads comes from the tables in ./i18n. English is the source and the
// fallback: a key missing from another table shows the English text rather than a raw key, and
// tests/i18n.test.js fails the build if any table drifts from English.
// Placeholders look like {name} and are filled from the params object.

import en from './i18n/en.js';
import hi from './i18n/hi.js';
import ta from './i18n/ta.js';

export const TABLES = { en, hi, ta };
export const DEFAULT_LANGUAGE = 'en';

// Shown in the language switcher, each in its own script.
export const APP_LANGUAGES = [
  { code: 'en', label: 'English', short: 'EN' },
  { code: 'hi', label: 'हिन्दी', short: 'हि' },
  { code: 'ta', label: 'தமிழ்', short: 'த' },
];

// Locale for dates and numbers in each language.
export const LOCALES = { en: 'en-IN', hi: 'hi-IN', ta: 'ta-IN' };

export function formatDate(language, date, options = { weekday: 'short', day: 'numeric', month: 'short' }) {
  const value = date instanceof Date ? date : new Date(date);
  if (Number.isNaN(value.getTime())) return '';
  try {
    return value.toLocaleDateString(LOCALES[language] || LOCALES.en, options);
  } catch {
    return value.toDateString();
  }
}

// The AI call language stored on the donor profile, matched to an app language.
const CALL_LANGUAGE_TO_APP = { English: 'en', Hindi: 'hi', Tamil: 'ta' };

export function isAppLanguage(code) {
  return Object.prototype.hasOwnProperty.call(TABLES, code);
}

export function appLanguageForCall(callLanguage) {
  return CALL_LANGUAGE_TO_APP[callLanguage] || DEFAULT_LANGUAGE;
}

export function placeholders(text) {
  return [...String(text).matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
}

export function translate(language, key, params) {
  const table = TABLES[language] || en;
  const text = table[key] ?? en[key] ?? key;
  if (!params) return text;
  return text.replace(/\{(\w+)\}/g, (whole, name) => (params[name] === undefined || params[name] === null ? whole : String(params[name])));
}

// `t('key', params)` bound to one language. Plural forms use separate keys chosen by the caller.
export function makeT(language) {
  const lang = isAppLanguage(language) ? language : DEFAULT_LANGUAGE;
  const t = (key, params) => translate(lang, key, params);
  t.language = lang;
  t.date = (date, options) => formatDate(lang, date, options);
  return t;
}
