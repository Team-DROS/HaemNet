// Sentry error tracking for the dashboard. Off unless EXPO_PUBLIC_SENTRY_DSN is
// set. Personal data is not sent: no default PII and request bodies are dropped.

import * as Sentry from '@sentry/react';

const DSN = process.env.EXPO_PUBLIC_SENTRY_DSN || '';

export function initMonitoring() {
  if (!DSN || typeof window === 'undefined') return false;
  Sentry.init({
    dsn: DSN,
    environment: process.env.EXPO_PUBLIC_APP_ENV || 'production',
    sendDefaultPii: false,
    tracesSampleRate: 0,
    beforeSend(event) {
      if (event.request) { delete event.request.data; delete event.request.cookies; }
      return event;
    },
  });
  return true;
}

export const reportError = (error) => { if (DSN) Sentry.captureException(error); };
