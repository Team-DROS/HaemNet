// Runtime configuration for the donor app.
//
// The API address comes from EXPO_PUBLIC_API_URL, which Expo inlines at build
// time (eas.json sets it for the preview and production profiles). Release
// builds must never talk to localhost or plain HTTP: if the variable is
// missing or unsafe in a release build, the app uses the production API
// instead of silently failing against a development address.

export const PRODUCTION_API_URL = 'https://haemnet-api.onrender.com';
export const DEVELOPMENT_API_URL = 'http://localhost:8000';

// Render free instances can take close to a minute to wake from sleep.
export const REQUEST_TIMEOUT_MS = 90000;

const LOCAL_HOSTS = /^(localhost|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/;

/**
 * Decide which API base URL to use.
 * Pure function so it can be unit tested without a React Native runtime.
 *
 * @param {string|undefined} configured value of EXPO_PUBLIC_API_URL
 * @param {boolean} isDev true in development builds (__DEV__)
 * @returns {{ url: string, source: 'configured' | 'production-default' | 'development-default', warning?: string }}
 */
export function resolveApiUrl(configured, isDev) {
  const raw = typeof configured === 'string' ? configured.trim().replace(/\/+$/, '') : '';

  if (isDev) {
    return raw
      ? { url: raw, source: 'configured' }
      : { url: DEVELOPMENT_API_URL, source: 'development-default' };
  }

  if (!raw) {
    return { url: PRODUCTION_API_URL, source: 'production-default', warning: 'EXPO_PUBLIC_API_URL was not set for this release build' };
  }

  let parsed;
  try {
    parsed = new URL(raw);
  } catch {
    return { url: PRODUCTION_API_URL, source: 'production-default', warning: 'EXPO_PUBLIC_API_URL is not a valid URL' };
  }
  if (parsed.protocol !== 'https:' || LOCAL_HOSTS.test(parsed.hostname)) {
    return { url: PRODUCTION_API_URL, source: 'production-default', warning: 'Release builds only use HTTPS on a public host' };
  }
  return { url: raw, source: 'configured' };
}

const isDevRuntime = typeof __DEV__ !== 'undefined' ? __DEV__ : false;
const resolved = resolveApiUrl(process.env.EXPO_PUBLIC_API_URL, isDevRuntime);

if (resolved.warning && isDevRuntime) {
  // Only surfaced in development; release builds stay quiet.
  console.warn(`[config] ${resolved.warning}; using ${resolved.url}`);
}

export const API_URL = resolved.url;
export const API_URL_SOURCE = resolved.source;
