# HaemNet Donor (Android)

The donor app: sign in with a phone number and password, keep a donor profile,
see nearby emergency blood requests and accept or decline them.

| | |
| --- | --- |
| App name | HaemNet Donor |
| Android package | `com.pranko007.donormobile` |
| Version | 1.2.0 (versionCode managed by EAS, see Versioning) |
| Supported Android | **Android 7.0 (API 24) and newer.** Android 6 and older cannot install it. |
| Expo SDK / React Native | 54 / 0.81.5 |
| Expo account / project | `umasuthan` / `donor-mobile` ([project page](https://expo.dev/accounts/umasuthan/projects/donor-mobile)) |
| EAS project ID | `20aa94d4-5db2-49b8-b6f4-fa87e226806b` |
| Production API | `https://haemnet-api.onrender.com` |

The Expo project is linked to the personal fork
`umasuthanpalaniappan/HaemNet`, because an Expo personal account cannot connect
directly to the Team-DROS organisation repository. Releases are built from the
fork after changes are merged into Team-DROS `main` and synced.

## Local development

```bash
cd frontend/donor-mobile
npm ci
# Point the app at a backend your phone can reach (your computer's LAN IP, not localhost):
echo "EXPO_PUBLIC_API_URL=http://192.168.1.5:8000" > .env
npx expo start
```

Checks before every release:

```bash
npm test          # config unit tests
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
| Production AAB | `eas build --platform android --profile production` | EAS release keystore (upload key) | Google Play upload only. An AAB cannot be installed directly. |

Build commands (run from `frontend/donor-mobile`, logged in with `eas login` as `umasuthan`):

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
- A CI build through EAS needs an `EXPO_TOKEN` GitHub secret on the fork. The
  owner creates the token at expo.dev and adds it under
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
adb shell pm list packages | grep donormobile # is an older copy installed?
adb shell dumpsys package com.pranko007.donormobile | grep -E "versionCode|versionName|signatures"
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
- Release procedure: merge to Team-DROS `main` > sync the fork > run the checks
  above > build preview > install and test on a phone > build production >
  upload to Play (owner only).

## Permissions

| Permission | Why |
| --- | --- |
| Location (coarse and fine, while in use) | Match the donor to hospitals within 10 km |
| Camera | Optional profile photo |
| Photos (Android 12 and older: storage read) | Optional profile photo from the gallery |

The app does not request background location or the microphone; both are
explicitly blocked in `app.json`. See [PRIVACY.md](PRIVACY.md).

## Sign-in

1. **Create account**: the mobile number hospitals should call, plus a
   password (8 characters or more), typed twice.
2. **Sign in**: the same number and password. The donor stays signed in for
   30 days; the token is kept in the Android Keystore.
3. **Forgot password**: the HaemNet team runs
   `python -m backend.tools.reset_donor_password <number>` after checking it
   is the real owner, and the donor creates the account again. The profile
   and donation history are kept.

SMS and email codes were removed in 1.2.0: the Twilio trial could not deliver
SMS to Indian numbers, and free email services were not worth the setup.
Twilio is still used for the AI voice calls.

## Known limitations

- The phone number is not verified (no SMS), so someone could create an
  account for a number before its owner does. If that happens, the team can
  reset it with the tool above.
- The production API runs on Render's free tier and sleeps when idle. The first
  request after a sleep can take close to a minute.
- New requests are found by polling every 15 seconds while the app is open.
  Push notifications are not wired end to end.
