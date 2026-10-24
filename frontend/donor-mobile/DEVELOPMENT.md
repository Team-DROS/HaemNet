# Fast mobile development and debugging

The app currently uses **Expo SDK 54**. Its JavaScript can refresh on a phone
without rebuilding the APK after each edit.

## Expo Go preview

From `frontend/donor-mobile/`, install dependencies with `npm ci`, then:

```bash
node node_modules/expo/bin/cli start --go --port 8082
```

Use an Android Expo Go build compatible with SDK 54, available from
[expo.dev/go](https://expo.dev/go?platform=android&device=true&sdkVersion=54).
Keep the phone and computer on the same Wi-Fi and scan Metro's QR code.
Enable Fast Refresh in the developer menu. Use a development build to test
native configuration and investigate device-specific failures.

The direct Node command also avoids npm launcher issues in Windows paths
containing `&`. The hospital web app can run separately on port 8081.

## Development APK

The project already includes `expo-dev-client` and an EAS development profile.
With access to the configured Expo project, build a development APK once:

```bash
npx eas-cli build --platform android --profile development
```

Install the development build and run:

```bash
node node_modules/expo/bin/cli start --dev-client --port 8082
```

JS, screen, and style edits use Fast Refresh. Expo SDK upgrades, native
dependencies, permissions, and config plugins require a new native build.
Also verify a preview release build before distribution.

## API connection

Set the ignored local `.env` to a reachable API:

```dotenv
EXPO_PUBLIC_API_URL=http://192.168.1.5:8000
```

Replace the sample IP with the computer's LAN address. Bind the backend to
`0.0.0.0`; localhost on a physical phone refers to the phone. Restart Metro
after changing environment settings. If Metro advertises the wrong network
adapter, set `REACT_NATIVE_PACKAGER_HOSTNAME` to the Wi-Fi adapter's LAN IP
for that terminal session before launching Expo.

Backend/database connectivity and app runtime failures are distinct checks.
An API timeout alone does not demonstrate a native crash.

## Capture a failure

- Keep Metro's terminal open and retain the first error and stack trace.
- Press `j` with a compatible development app connected for React Native
  DevTools.
- For a process crash, enable Android USB debugging and use platform-tools:

```bash
adb devices
adb logcat -b crash -v time
```

Reproduce the failure with the log stream running. Record the device/Android
version, build type, action that triggered it, and exception. Do not share
tokens, passwords, or donor records with logs.

Before releasing, use the checks in [README.md](README.md) and manually
exercise cold start, sign-in, denied location, camera cancellation, offline
requests, background/resume, and sign-out.
