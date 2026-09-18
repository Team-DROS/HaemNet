# HaemNet Frontend

The HaemNet frontend ecosystem is built entirely on **Expo and React Native**, allowing us to maintain a single unified codebase that compiles to both a web-based dashboard for hospitals and a native mobile application for blood donors.

## Directory Structure

- **`donor-web/`**: The web application used by hospital administrators to trigger emergencies and monitor dispatches.
- **`donor-mobile/`**: The native mobile application installed by blood donors to receive route mapping and track their medical cooldown.

## 1. Hospital Web Dashboard (`donor-web`)
The web dashboard is the command center for the HaemNet system.

### Key Features
- **Emergency Trigger Form:** Hospitals can quickly broadcast a need for a specific blood type and urgency.
- **Live Dispatch Monitor:** Once an emergency is triggered, the dashboard connects to the backend via **WebSockets** (`ws://.../ws/dashboard`) to display real-time updates as the AI calls donors. Badges dynamically change state (`Ringing`, `Accepted`, `Declined`) as the AI conversations progress.
- **Donation Logging:** Hospitals can log successful donations, which triggers the backend to update the donor's `last_donated_date` in the database.

### Getting Started (Web)
```bash
cd donor-web
npm install
npx expo start --web
```

## 2. Donor Native App (`donor-mobile`)
The native mobile app is designed for zero-friction onboarding and immediate emergency routing.

### Key Features
- **Live Routing:** If a donor accepts an AI phone call and has the app installed, they instantly receive an Expo Push Notification containing dynamic map routing (`react-native-maps`) to the hospital.
- **Medical Cooldown Tracker:** The app features a visual progress bar that locks the donor out of donations for 56 days after a successful transfusion, ensuring strict medical compliance.
- **Native Integrations:** Utilizes device geolocation for spatial matching and camera/photo access for profile management.

### Getting Started (Mobile)
```bash
cd donor-mobile
npm install
npx expo start
```
You can scan the QR code with the Expo Go app on your physical device, or press `a` or `i` to launch an Android/iOS emulator.

## Tech Stack
- **Framework:** Expo, React Native
- **Styling:** NativeWind (Tailwind CSS for React Native)
- **Maps:** `react-native-maps`
- **Networking:** Axios, WebSockets

## Working on this codebase

Expo changed significantly in recent versions. Before writing code here, check the exact
versioned docs at https://docs.expo.dev/versions/v57.0.0/ rather than relying on older guides
or generated snippets.

The visual language both apps should follow lives in [`../design/`](../design): `tokens.json`
holds the colour, typography and spacing tokens, and `design/README.md` explains the colour
rules and the shared emergency lifecycle.
