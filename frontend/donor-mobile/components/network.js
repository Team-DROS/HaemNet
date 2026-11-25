// Offline and slow-network rules for the donor app, kept free of React so they can be tested
// with `npm test`. The aim: never a blank or misleading screen when the network is poor.

// Open requests saved on the phone are shown while offline, but only while they can still matter.
export const REQUESTS_CACHE_MAX_AGE_MS = 6 * 60 * 60 * 1000;

/**
 * From a NetInfo state. `isInternetReachable` is null while NetInfo is still checking,
 * so only a definite false counts as offline.
 * @returns {'online' | 'offline' | 'unknown'}
 */
export function connectionState(netInfo) {
  if (!netInfo || netInfo.isConnected === null || netInfo.isConnected === undefined) return 'unknown';
  if (netInfo.isConnected === false || netInfo.isInternetReachable === false) return 'offline';
  return 'online';
}

/**
 * Which screen a signed-in donor should see after trying to load their profile.
 * @param {{ hasSaved: boolean, server: 'found' | 'missing' | 'unreachable' }} result
 *   hasSaved: this phone has the profile from an earlier successful sign-up.
 * @returns {'dashboard' | 'join' | 'retry'}
 *   The join form is shown only when the server says there is no profile. If the server cannot
 *   be reached, a saved profile is shown as it was; without one the donor gets a retry screen
 *   rather than a sign-up form that would create a duplicate.
 */
export function profileView({ hasSaved, server }) {
  if (server === 'found') return 'dashboard';
  if (server === 'missing') return 'join';
  return hasSaved ? 'dashboard' : 'retry';
}

export function serializeRequests(requests, now = Date.now()) {
  return JSON.stringify({ savedAt: now, requests: Array.isArray(requests) ? requests : [] });
}

/** Requests saved by serializeRequests, or null when missing, damaged or too old to act on. */
export function readSavedRequests(raw, now = Date.now()) {
  if (!raw) return null;
  try {
    const value = JSON.parse(raw);
    if (!value || !Array.isArray(value.requests) || !Number.isFinite(value.savedAt)) return null;
    if (now - value.savedAt > REQUESTS_CACHE_MAX_AGE_MS || value.savedAt > now + 60000) return null;
    return { savedAt: value.savedAt, requests: value.requests.filter((r) => r && typeof r.dispatch_id === 'string') };
  } catch {
    return null;
  }
}

/** Minutes since a time, for "updated N min ago". */
export function minutesSince(time, now = Date.now()) {
  if (!Number.isFinite(time)) return null;
  return Math.max(0, Math.floor((now - time) / 60000));
}
