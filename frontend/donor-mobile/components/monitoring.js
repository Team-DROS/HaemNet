// Sentry error tracking for the donor app. Off unless EXPO_PUBLIC_SENTRY_DSN is set at build time
// (a DSN only allows sending events, so it is safe in the bundle). Every event and breadcrumb is
// scrubbed of phone numbers and tokens first; see monitoringLogic.js.

import * as Sentry from '@sentry/react-native';
import Constants from 'expo-constants';

import { monitoringOptions } from './monitoringLogic';

let enabled = false;

export function initMonitoring() {
  if (enabled) return true;
  const version = Constants?.expoConfig?.version;
  const options = monitoringOptions(
    process.env.EXPO_PUBLIC_SENTRY_DSN,
    process.env.EXPO_PUBLIC_APP_ENV,
    version ? `donor-mobile@${version}` : undefined,
  );
  if (!options) return false;
  try {
    Sentry.init(options);
    enabled = true;
  } catch {
    enabled = false; // reporting must never stop the app from starting
  }
  return enabled;
}

export function reportError(error, context) {
  if (!enabled) return;
  try {
    Sentry.captureException(error, context ? { extra: context } : undefined);
  } catch {
    // ignore
  }
}

// Wraps the root component so native crashes and touch breadcrumbs are captured when enabled.
export function withMonitoring(Component) {
  return enabled ? Sentry.wrap(Component) : Component;
}
