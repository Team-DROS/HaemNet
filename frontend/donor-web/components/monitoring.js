// Sentry error tracking for the dashboard. Off unless EXPO_PUBLIC_SENTRY_DSN is
// set. Personal data is not sent: no default PII and request bodies are dropped.
//
// Sentry is about 30% of the dashboard's JavaScript, so it is loaded on demand with a
// dynamic import: builds without a DSN never download it, and builds with one fetch it
// after the first screen is drawn instead of before. Errors reported while it is still
// loading are queued and sent as soon as it is ready.

const DSN = process.env.EXPO_PUBLIC_SENTRY_DSN || '';

let sentry = null;
let pending = [];

export function initMonitoring() {
  if (!DSN || typeof window === 'undefined') return false;
  import('@sentry/react')
    .then((Sentry) => {
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
      sentry = Sentry;
      pending.forEach((error) => Sentry.captureException(error));
      pending = [];
    })
    .catch(() => { pending = []; }); // monitoring must never break the app
  return true;
}

export const reportError = (error) => {
  if (!DSN) return;
  if (sentry) sentry.captureException(error);
  else if (pending.length < 20) pending.push(error);
};
