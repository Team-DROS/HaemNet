# HaemNet Donor (Android)

The donor application for HaemNet: phone-and-password accounts, secure session
storage, donor profiles, push alerts for nearby requests, a pre-donation health
check before saying yes, pausing calls for a few days, offline use with saved
data, and the whole app in English, Hindi and Tamil. The backend runs the AI
phone conversations independently; the app is a second, faster way to answer.

| | |
| --- | --- |
| App name | HaemNet Donor |
| Android package | `in.haemnet.donor` (permanent after the first Play upload) |
| Version | 1.2.0 (versionCode managed by EAS, see Versioning) |
| Supported Android | **Android 7.0 (API 24) and newer.** Android 6 and older cannot install it. |
| Expo SDK / React Native | 54 / 0.81.5 |
| Expo account / project | `haemnetais-team` (organisation owned by the team account) / `donor-mobile` ([project page](https://expo.dev/accounts/haemnetais-team/projects/donor-mobile)) |
| EAS project ID | `94b47c7d-1958-4896-a84a-193527c8b4b3` |
| Production API | `https://haemnet-api.onrender.com` |

The project lives on the team Expo account, not a personal one. All three team members
sign in to it (or are added as members of its organisation), and CI uses a robot user's
`EXPO_TOKEN`. The earlier personal project (`umasuthan/donor-mobile`, package
`com.pranko007.donormobile`) is retired: APKs built from it cannot update to this app
and must be uninstalled first.

## Sign-up, phone verification and call consent

- The app asks the backend (`GET /api/donor/auth/config`) whether a texted code is required. When it is, the sign-up form shows a verification code field with a Send code button (30 second resend); the code is checked just before the account is created.
- Joining the network needs a tick on the automated-calls consent box; the app sends `calls_consent: true`, and editing a profile never rewrites it.
- The profile card has a Pause / Resume automated calls button (`POST /api/donor/calls/preference`).
- Privacy policy and terms links sit next to the consent box and on the profile card (`LEGAL_LINKS` in `components/config.js`, from `EXPO_PUBLIC_WEBSITE_URL`, HTTPS only).

## Features and where they live

Business rules are kept in small pure modules with Node tests (`tests/*.test.js`);
`components/DonorApp.js` only wires them to the screen.

| Feature | Logic | Notes |
| --- | --- | --- |
| Push alerts | `pushLogic.js`, `push.js` | Channel `emergency-requests` (high importance, sound, lock screen). The Expo push token is sent to `POST /api/donor/push-token` after joining and cleared on sign out. Tapping an alert opens the dashboard with that request outlined. Calls stay the main channel; alerts are extra. |
| Health check | `eligibility.js` | Six yes/no questions (feeling well, age and weight, medication, alcohol in 24 h, recent procedure, pregnancy) before "Yes, I am ready to donate", plus the 56-day recovery period. Answers stay on the phone; only accept or decline is sent. A failed check only offers "Let the hospital know", which declines. |
| Availability | `availability.js` | Pause for 3 days, 1 week or 2 weeks (`POST /api/donor/availability`, 0 to 30 days). Matching skips the donor until then, retries included. Separate from the permanent Pause automated calls. |
| Offline | `network.js` | NetInfo banner; the saved profile and up to 6 hours of saved requests show with their age. A server outage never shows the join form. Polling stops while offline and requests refresh on reconnect. |
| Languages | `i18n.js`, `i18n/en.js`, `hi.js`, `ta.js` | Every string goes through `t()`. Picker on sign-in and the profile card; a fresh install follows the donor's AI call language. Dates use `en-IN`, `hi-IN`, `ta-IN`. A test checks the three tables have the same keys and placeholders. |
| Crash reporting | `monitoringLogic.js`, `monitoring.js`, `ErrorBoundary.js` | Sentry, only when `EXPO_PUBLIC_SENTRY_DSN` is set. Phone numbers, tokens and JWTs are scrubbed from every event and breadcrumb; console breadcrumbs are dropped. A crash shows a tap-to-retry screen in three languages. |

When you add a string, add it to all three tables. Hindi and Tamil wording needs a native
speaker's review before release ([MOBILE_TEST_PLAN.md](../../docs/MOBILE_TEST_PLAN.md), row 33).
- Pure helpers for this live in `components/donorAuth.js` with tests in `tests/donorAuth.test.js`.

## Local development

For Fast Refresh, SDK-compatible Expo Go, development APKs, and crash logs, see
[DEVELOPMENT.md](DEVELOPMENT.md). The project remains on **SDK 54**; a newer
Expo Go installation does not upgrade the app.

```bash
cd frontend/donor-mobile
npm ci
# Point the app at a backend your phone can reach (your computer's LAN IP, not localhost):
echo "EXPO_PUBLIC_API_URL=http://192.168.1.5:8000" > .env
node node_modules/expo/bin/cli start --go --port 8082
```

Checks before every release:

```bash
npm test          # unit tests for config, auth, push, health check, availability, offline, i18n, scrubbing
npm run lint      # expo lint
npm run doctor    # expo-doctor
npx expo export --platform android --output-dir .expo-export-check   # bundles the release JS
```

### API address rules

`components/config.js` decides where the app talks to:

- Development builds use `EXPO_PUBLIC_API_URL`, or `http://localhost:8000` if unset.
- Release builds (preview and production) only accept an HTTPS URL on a public
  host. If the variable is missing, not HTTPS, or points at localhost or a LAN
  address, the app uses `https://haemnet-api.onrender.com` instead. A release
  build can never silently fall back to localhost.
- `eas.json` sets `EXPO_PUBLIC_API_URL` for the preview and production profiles.
- Requests time out after 90 seconds, because a sleeping Render free instance
  can take close to a minute to wake.

No backend secret is ever embedded in the app.

## Build artifacts: which one to use

| Artifact | Built by | Signed with | Use it for |
| --- | --- | --- | --- |
| Test APK | GitHub Actions workflow "Android test APK (not for release)" on the fork | Android debug key | Quick tester installs. JavaScript is bundled, so it runs without Metro. Never hand it to donors or upload it to Play. |
| Debug APK | `npx expo run:android` on a developer machine | Android debug key | Development only. Has **no** JavaScript bundle and needs Metro running. |
| Preview APK | `eas build --platform android --profile preview` | EAS release keystore | Direct install on phones for testing and demos. |
| Staging APK | Actions > Donor app release > profile `staging` | EAS release keystore | Talks to `haemnet-api-staging`. Use it for [MOBILE_TEST_PLAN.md](../../docs/MOBILE_TEST_PLAN.md) before every release. |
| Production AAB | `eas build --platform android --profile production` | EAS release keystore (upload key) | Google Play upload only. An AAB cannot be installed directly. |

Build commands (run from `frontend/donor-mobile`, logged in with `eas login` as the team Expo account):

```bash
npm install -g eas-cli
eas login
eas credentials --platform android      # first time: let EAS generate the release keystore
eas build --platform android --profile preview      # installable APK
eas build --platform android --profile production   # AAB for Google Play
```

## Credentials

- The Android release keystore is generated and stored by EAS for the Expo
  project. It is never committed, never placed in `.env`, never pasted in chat
  or issues, and never printed in CI logs.
- Losing the keystore means Play can no longer accept updates for this app
  (unless Play App Signing is enabled). Download a backup only through
  `eas credentials` and keep it in a password manager.
- A CI build through EAS needs an `EXPO_TOKEN` GitHub secret. A team
  admin creates it for a robot user at expo.dev and adds it under
  Settings > Secrets and variables > Actions. Never put it in workflow YAML.

## Installing directly on a phone

1. Uninstall any older HaemNet Donor build that came from a **different signer**
   (for example the debug APK from GitHub Actions). Android refuses to update an
   app across signing keys. Uninstalling removes the app's local data; the
   donor profile on the server is kept and returns after signing in again.
2. Download the preview APK from the EAS build page on the phone.
3. Open it and allow "Install unknown apps" for the browser or file manager when asked.

## "There was a problem parsing the package"

This message is Android's generic installer error. Get the real reason with adb:

```bash
adb devices                                   # phone must show as "device" (enable USB debugging)
adb shell getprop ro.build.version.sdk        # must be 24 or higher
adb install -r HaemNet-Donor-v1.2.0-preview.apk
adb shell pm list packages | grep -E 'haemnet|donormobile' # is an older copy installed?
adb shell dumpsys package in.haemnet.donor | grep -E "versionCode|versionName|signatures"
```

| adb result | Meaning | Fix |
| --- | --- | --- |
| `INSTALL_FAILED_OLDER_SDK` | Phone runs Android 6 or older | Not supported |
| `INSTALL_FAILED_UPDATE_INCOMPATIBLE` | An older build signed with a different key is installed | Uninstall it first |
| `INSTALL_FAILED_VERSION_DOWNGRADE` | Installed versionCode is higher | Build a newer one; do not reuse versionCodes |
| `INSTALL_PARSE_FAILED_NOT_APK` / `INSTALL_PARSE_FAILED_NO_CERTIFICATES` | File is not the APK, or is truncated | Re-download; compare SHA-256 with the build page. Do not install the `.zip` artifact itself |
| `INSTALL_FAILED_INSUFFICIENT_STORAGE` | Not enough space (debug APK is about 130 MB) | Free space or use the preview APK |
| `INSTALL_FAILED_TEST_ONLY` | Test-only build | Use a preview APK |

### App installs but shows "Unable to load script ... index.android.bundle"

That is a **debug** APK. Debug builds do not contain the JavaScript bundle;
they load it from a Metro dev server on your computer. Install a preview APK
(`eas build --profile preview`) or the test APK from the "Android test APK"
workflow instead: both embed the bundle and run on their own.

Other common causes: installing from a messaging app that recompressed or
renamed the file, or opening the GitHub Actions `.zip` instead of the APK inside it.

## Versioning and release

- `eas.json` uses `"appVersionSource": "remote"` with `autoIncrement` on the
  preview and production profiles, so every EAS build gets a new versionCode
  and a Play versionCode can never be reused.
- `version` in `app.json` (versionName) and `package.json` stay in step; bump
  both for a user-visible release.
- Release procedure: see [docs/RELEASING.md](../../docs/RELEASING.md). In short: bump
  the version in a PR, test a staging build on three phones, merge, then push a
  `donor-vX.Y.Z` tag. The "Donor app release" workflow builds the AAB and submits
  it to Play internal testing as a draft. Store listing, Data safety answers and the
  closed test plan: [docs/PLAY_STORE.md](../../docs/PLAY_STORE.md).
- Push on Android needs Firebase: `google-services.json` comes from the EAS file
  variable `GOOGLE_SERVICES_JSON` (see `app.config.js`) and is never committed.

## Permissions

| Permission | Why |
| --- | --- |
| Location (coarse and fine, while in use) | Match the donor to hospitals within 10 km |
| Camera | Optional profile photo |
| Photos (Android 12 and older: storage read) | Optional profile photo from the gallery |
| Notifications (Android 13+ asks once after joining) | Alerts for nearby requests; can be turned on later from the profile card |

The app does not request background location or the microphone; both are
explicitly blocked in `app.json`. See [PRIVACY.md](PRIVACY.md).

## Sign-in

1. **Create account**: the mobile number hospitals should call, plus an
   8-to-72-character password, typed twice.
2. **Sign in**: the same number and password. The donor stays signed in for
   30 days; the token is kept in the Android Keystore.
3. **Forgot password**: the HaemNet team runs
   `python -m backend.tools.reset_donor_password <number>` after checking it
   is the real owner, and the donor creates the account again. The profile
   and donation history are kept.

Sign-up can require an SMS code when the server sets `DONOR_OTP_REQUIRED=true`
(see "Sign-up, phone verification and call consent" above). Sign-in always uses
the password.

## How the mobile app relates to AI calls

Voice processing runs on the backend, not on the phone. Twilio carries call
audio; Sarvam provides speech and translation, and AI mode uses Sarvam-105B
to interpret the response. Voice acceptance requires a separate confirmation.
The mobile app's accept/decline buttons are a distinct response path.

The app does not run a trained model on the device or need microphone
permission to receive ordinary telephone calls. Backend voice changes do not
require a new APK when the mobile API contract stays the same.

## Known limitations

- Unless `DONOR_OTP_REQUIRED=true`, the phone number is not verified, so someone
  could create an account for a number before its owner does. If that happens,
  the team can reset it with the tool above.
- The production API runs on Render's free tier and sleeps when idle. The first
  request after a sleep can take close to a minute.
- Requests are also polled every 15 seconds while the app is open. Push alerts
  depend on Firebase and Google Play services; aggressive battery savers on some
  phones delay them, which is why the voice call stays the main channel.
- Directions open an external maps application. There is no embedded
  `react-native-maps` screen or continuous live donor GPS tracking.
- Native crash investigation still needs device logs and reproduction steps;
  a successful JS export cannot prove that a release APK is crash-free.
