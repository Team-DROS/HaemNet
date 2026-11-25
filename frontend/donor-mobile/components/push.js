// Push alerts on the phone: permission, the Android channel, the Expo token and taps.
// The rules (what a tap means, when the server needs a new token) are in pushLogic.js.

import { Platform } from 'react-native';
import Constants from 'expo-constants';
import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';

import { ALERT_CHANNEL_ID, alertState } from './pushLogic';

let configured = false;

// Show alerts even while the app is open: an emergency request should never be silent.
export function configureAlerts() {
  if (configured) return;
  configured = true;
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowBanner: true,
      shouldShowList: true,
      shouldPlaySound: true,
      shouldSetBadge: false,
    }),
  });
  if (Platform.OS === 'android') {
    Notifications.setNotificationChannelAsync(ALERT_CHANNEL_ID, {
      name: 'Emergency blood requests',
      description: 'A nearby hospital needs your blood group.',
      importance: Notifications.AndroidImportance.MAX,
      vibrationPattern: [0, 400, 250, 400],
      sound: 'default',
      lockscreenVisibility: Notifications.AndroidNotificationVisibility.PUBLIC,
    }).catch(() => {});
  }
}

function projectId() {
  return Constants?.expoConfig?.extra?.eas?.projectId ?? Constants?.easConfig?.projectId ?? undefined;
}

/**
 * Ask for permission when `ask` is true, then fetch this phone's Expo push token.
 * Never throws: alerts are a bonus on top of the call, so failures only mean "off".
 *
 * @returns {Promise<{ state: 'on'|'off'|'blocked'|'pending'|'unsupported', token: string|null }>}
 */
export async function setUpAlerts({ ask }) {
  configureAlerts();
  if (!Device.isDevice || Platform.OS === 'web') return { state: 'unsupported', token: null };
  try {
    let { status, canAskAgain } = await Notifications.getPermissionsAsync();
    if (status !== 'granted' && ask && canAskAgain !== false) {
      ({ status, canAskAgain } = await Notifications.requestPermissionsAsync());
    }
    let token = null;
    if (status === 'granted') {
      try {
        token = (await Notifications.getExpoPushTokenAsync({ projectId: projectId() })).data;
      } catch {
        token = null; // no network or no FCM credentials in this build
      }
    }
    return { state: alertState({ isDevice: true, permission: status, canAskAgain, token }), token };
  } catch {
    return { state: 'off', token: null };
  }
}

// Calls `onTap(response)` when the donor taps an alert, including the one that opened the app.
export function listenForAlertTaps(onTap) {
  const sub = Notifications.addNotificationResponseReceivedListener(onTap);
  Notifications.getLastNotificationResponseAsync()
    .then((response) => {
      if (response) {
        onTap(response);
        Notifications.clearLastNotificationResponseAsync().catch(() => {});
      }
    })
    .catch(() => {});
  return () => sub.remove();
}

// Calls `onAlert(notification)` when an alert arrives while the app is open.
export function listenForAlerts(onAlert) {
  const sub = Notifications.addNotificationReceivedListener(onAlert);
  return () => sub.remove();
}
