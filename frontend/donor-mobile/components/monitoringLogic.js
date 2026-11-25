// Rules for error reports from the donor app, kept free of React Native so they can be tested.
//
// Donor phone numbers, push tokens and sign-in tokens are personal data under the DPDP Act and
// must never leave the phone inside an error report. Everything that goes to Sentry passes
// through scrubEvent first.

const PATTERNS = [
  [/Bearer\s+[A-Za-z0-9._~+/=-]+/g, 'Bearer [token]'],
  [/(?:ExponentPushToken|ExpoPushToken)\[[^\]]*\]/g, '[push-token]'],
  [/eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+/g, '[jwt]'],
  // Indian mobile numbers with or without +91 / 91 / 0, also URL-encoded (%2B91).
  [/(?:(?:%2B|\+)?91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}\b/g, '[phone]'],
];

export function scrubText(value) {
  if (typeof value !== 'string') return value;
  return PATTERNS.reduce((text, [pattern, replacement]) => text.replace(pattern, replacement), value);
}

function scrubDeep(value, depth = 0) {
  if (depth > 6) return '[trimmed]';
  if (typeof value === 'string') return scrubText(value);
  if (Array.isArray(value)) return value.map((item) => scrubDeep(item, depth + 1));
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, scrubDeep(item, depth + 1)]));
  }
  return value;
}

/** Sentry beforeSend: drop who the user is and what they sent, and scrub numbers and tokens. */
export function scrubEvent(event) {
  if (!event || typeof event !== 'object') return event;
  const clean = { ...event };
  delete clean.user;
  if (clean.request) {
    clean.request = { ...clean.request };
    delete clean.request.data;
    delete clean.request.cookies;
    delete clean.request.headers;
  }
  for (const key of ['message', 'exception', 'breadcrumbs', 'extra', 'contexts', 'tags', 'request', 'transaction']) {
    if (clean[key] !== undefined) clean[key] = scrubDeep(clean[key]);
  }
  return clean;
}

/** Sentry beforeBreadcrumb: keep navigation and errors, scrub request URLs, drop console noise. */
export function scrubBreadcrumb(breadcrumb) {
  if (!breadcrumb || breadcrumb.category === 'console') return null;
  return scrubDeep(breadcrumb);
}

/** Settings for Sentry.init, or null to leave error reporting off (no DSN in this build). */
export function monitoringOptions(dsn, environment, release) {
  const value = typeof dsn === 'string' ? dsn.trim() : '';
  if (!/^https:\/\/[^\s]+@[^\s]+\/\d+$/.test(value)) return null;
  return {
    dsn: value,
    environment: environment || 'production',
    release: release || undefined,
    sendDefaultPii: false,
    attachScreenshot: false,
    attachViewHierarchy: false,
    tracesSampleRate: 0,
    beforeSend: scrubEvent,
    beforeBreadcrumb: scrubBreadcrumb,
  };
}
