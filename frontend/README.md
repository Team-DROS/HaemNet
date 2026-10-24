# HaemNet frontend

HaemNet has **two separate Expo applications**: a hospital web console and
a donor mobile app. They have independent dependencies, entry points, and
build profiles.

## Hospital dashboard — `donor-web/`

The dashboard uses Expo Web, React Native Web, React, Expo Router, SVG icons,
and style objects/theme tokens. It is not a Next.js or NativeWind application.

- Hospital registration and hospital-ID/password sign-in.
- Command Center for blood group, units, urgency, address, and donor responses.
- Individual groups plus All positive / All negative recruitment options.
- Authenticated, hospital-scoped events and restoration of open dispatches.
- Dispatch Map with hospital location and donor distance bands.
- Network Intelligence using server history and donor availability.
- Donation logging, request fulfillment, and light/dark themes.

The map does not track moving donor GPS markers. Reference screen HTML may
contain sample data; the running dashboard reads operational data from the API.

### Run the dashboard

Create `donor-web/.env`:

```dotenv
EXPO_PUBLIC_API_URL=http://localhost:8000
EXPO_PUBLIC_WS_URL=ws://localhost:8000/ws/dashboard
```

From this directory:

```bash
cd donor-web
npm ci
node node_modules/expo/bin/cli start --web --port 8081
```

The backend and database must be reachable, and backend `CORS_ORIGINS`
must allow `http://localhost:8081`. The dashboard authenticates its
WebSocket using a hospital token in the first message. Restart Metro after
editing environment variables.

From `donor-web/`, export a static build:

```bash
node node_modules/expo/bin/cli export --platform web --output-dir dist
```

## Donor mobile app — `donor-mobile/`

The app currently uses **Expo SDK 54 / React Native 0.81.5**. It provides
phone/password accounts, SecureStore sessions, donor profiles, optional
location capture and profile photos, request responses, external map directions,
and a 56-day cooldown display.

Requests are polled every 15 seconds while the app is open. Backend push
helpers exist, but mobile push registration and handling are not wired end
to end. The app does not provide background GPS tracking or an embedded
`react-native-maps` screen.

See the [donor README](donor-mobile/README.md) for Fast Refresh, development
APKs, Android release artifacts, and troubleshooting; see the
[privacy description](donor-mobile/PRIVACY.md) for data flows.

## Configuration boundaries

`EXPO_PUBLIC_*` values are bundled into client code and must contain only
public configuration. Database passwords, JWT signing secrets, and Twilio or
Sarvam API keys belong on the backend.

For physical phones, localhost refers to the phone itself. Use a reachable
API URL. Mobile release builds require public HTTPS; development permits
local addresses. The mobile app uses Axios; the dashboard uses fetch and
WebSockets.

## Visual references

[`../design/`](../design/) contains original tokens and HTML screen
references. Runtime light/dark palettes live in each app's
`components/theme.js`. The HTML files are design sources, not a substitute
for the connected applications.

Consult documentation matching the installed Expo version (currently SDK 54).
An SDK 57 Expo Go installation does not upgrade or run an SDK 54 project.
