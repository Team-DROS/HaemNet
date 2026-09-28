// Donor session storage.
//
// The session holds the donor's phone (10 local digits) and their API token.
// Tokens live in the platform keystore through expo-secure-store. Builds up to
// v1.1 kept the session in AsyncStorage (plain app storage), so on first read
// the old value is moved into secure storage and the plain copy is deleted:
// existing donors stay signed in across the upgrade.

import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';

// SecureStore keys may only contain letters, digits, ".", "-" and "_".
export const SECURE_SESSION_KEY = 'haemnet.donor.session';
export const LEGACY_SESSION_KEY = '@donor_session';
const LEGACY_UNVERIFIED_KEY = '@current_user'; // pre-OTP builds; never trusted

export function isValidSession(value) {
  return Boolean(
    value
    && typeof value === 'object'
    && typeof value.token === 'string' && value.token.length > 0
    && typeof value.id === 'string' && /^\d{10}$/.test(value.id),
  );
}

function parse(raw) {
  if (!raw) return null;
  try {
    const value = JSON.parse(raw);
    return isValidSession(value) ? value : null;
  } catch {
    return null;
  }
}

async function secureAvailable() {
  try {
    return await SecureStore.isAvailableAsync();
  } catch {
    return false;
  }
}

export async function loadSession() {
  await AsyncStorage.removeItem(LEGACY_UNVERIFIED_KEY).catch(() => {});
  const secure = await secureAvailable();

  if (secure) {
    const stored = parse(await SecureStore.getItemAsync(SECURE_SESSION_KEY).catch(() => null));
    if (stored) return stored;
  }

  // One-time migration from the plain AsyncStorage copy.
  const legacy = parse(await AsyncStorage.getItem(LEGACY_SESSION_KEY).catch(() => null));
  if (legacy && secure) {
    try {
      await SecureStore.setItemAsync(SECURE_SESSION_KEY, JSON.stringify(legacy));
      await AsyncStorage.removeItem(LEGACY_SESSION_KEY);
    } catch {
      // Keep the legacy copy so the donor is not signed out; retried next launch.
    }
  }
  return legacy;
}

export async function saveSession(session) {
  if (!isValidSession(session)) throw new Error('Refusing to store an invalid session');
  const payload = JSON.stringify(session);
  if (await secureAvailable()) {
    await SecureStore.setItemAsync(SECURE_SESSION_KEY, payload);
    await AsyncStorage.removeItem(LEGACY_SESSION_KEY).catch(() => {});
  } else {
    // Web preview has no keystore; fall back so the preview still works.
    await AsyncStorage.setItem(LEGACY_SESSION_KEY, payload);
  }
}

export async function clearSession() {
  if (await secureAvailable()) {
    await SecureStore.deleteItemAsync(SECURE_SESSION_KEY).catch(() => {});
  }
  await AsyncStorage.multiRemove([LEGACY_SESSION_KEY, LEGACY_UNVERIFIED_KEY]).catch(() => {});
}
