// Pure rules for push alerts, kept free of React Native so they can be tested with `npm test`.
// The native calls live in push.js.

// Android channel for emergency requests. The backend sends every alert on this channel
// (backend/services/push_service.py), so the id must match there.
export const ALERT_CHANNEL_ID = 'emergency-requests';

// Notification types the backend sends, and what a tap on each should do.
const TAP_ACTIONS = {
  new_request: 'show-request',
  dispatch_accepted: 'show-trip',
};

const EXPO_TOKEN = /^(?:ExponentPushToken|ExpoPushToken)\[[A-Za-z0-9_-]{8,200}\]$/;

export function isExpoPushToken(token) {
  return typeof token === 'string' && EXPO_TOKEN.test(token);
}

/**
 * What a notification (or a tap on one) asks the app to do.
 * Accepts either a notification or a notification response from expo-notifications.
 *
 * @returns {{ action: 'show-request' | 'show-trip', dispatchId: string } | null}
 */
export function alertTarget(notificationOrResponse) {
  const notification = notificationOrResponse?.notification ?? notificationOrResponse;
  const data = notification?.request?.content?.data;
  if (!data || typeof data !== 'object') return null;
  const action = TAP_ACTIONS[data.type];
  const dispatchId = typeof data.dispatch_id === 'string' ? data.dispatch_id.trim() : '';
  if (!action || !dispatchId) return null;
  return { action, dispatchId };
}

/**
 * Whether the token stored on the server has to change.
 * `saved` is what this phone last sent for this donor; `current` is the token Expo gives now
 * (null when alerts are off or unavailable).
 */
export function tokenUpdate(saved, current) {
  const next = isExpoPushToken(current) ? current : null;
  const previous = isExpoPushToken(saved) ? saved : null;
  if (next === previous) return { needed: false, token: next };
  return { needed: true, token: next };
}

/**
 * Plain-language state of alerts on this phone, for the settings card.
 * `permission` is the expo-notifications status: 'granted' | 'denied' | 'undetermined'.
 */
export function alertState({ isDevice, permission, canAskAgain, token }) {
  if (!isDevice) return 'unsupported';
  if (permission === 'granted') return isExpoPushToken(token) ? 'on' : 'pending';
  if (permission === 'denied' && canAskAgain === false) return 'blocked';
  return 'off';
}
