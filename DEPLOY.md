# Deploying HaemNet

Three pieces go live: the API, the hospital dashboard, and the donor app.
This guide uses MongoDB Atlas for the database and Render for hosting,
both of which have a free tier that is enough for a demo.

Everything here is a one-time setup of about an hour. After that, pushing to
`main` redeploys the API and the dashboard automatically.

## 1. What you need first

| Service | Used for | Free tier |
| --- | --- | --- |
| [MongoDB Atlas](https://www.mongodb.com/cloud/atlas) | donors, hospitals, dispatches, call sessions | M0 cluster, 512 MB |
| [Twilio](https://www.twilio.com/) | the AI voice calls and the donor sign-in codes | trial credit; trial accounts can only call verified numbers |
| [Sarvam AI](https://www.sarvam.ai/) | speech to text and text to speech in English, Hindi and Tamil | pay as you go |
| [Render](https://render.com/) | hosting the API and the dashboard | free instances that sleep when idle |

A trial Twilio account can only call and text numbers you have verified in
the Twilio console, so verify the phones you will demo with.

## 2. MongoDB Atlas

1. Create a free M0 cluster in the region closest to your users (`ap-south-1`
   for India).
2. Database Access: add a user with "Read and write to any database". Use a
   password without `@ : / ?` or URL-encode it.
3. Network Access: while Render's free tier has no fixed outbound IP, allow
   `0.0.0.0/0`. The database is still protected by the user and password.
4. Copy the connection string. It looks like
   `mongodb+srv://USER:PASSWORD@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority`.

The app creates its own collections and indexes on first start, including the
2dsphere index that makes "donors within 10 km" a single query.

## 3. The API on Render

1. Push this repository to GitHub (it is already there).
2. In Render: **New → Blueprint**, select the repository. `render.yaml`
   creates `haemnet-api` (Docker) and `haemnet-dashboard` (static site).
3. Render asks for the secret values. Fill in:

   | Variable | Value |
   | --- | --- |
   | `MONGODB_URI` | the Atlas connection string |
   | `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` | from the Twilio console |
   | `TWILIO_PHONE_NUMBER` | your Twilio number in E.164, e.g. `+12025550123` |
   | `SARVAM_API_KEY` | from the Sarvam dashboard |
   | `SENTRY_DSN` | optional, leave empty to disable error reporting |

   `JWT_SECRET` is generated for you. Leave `APP_ENV=production`.
4. When the API first deploys you learn its URL. Set the two that depend on it
   and redeploy:
   - `SERVER_BASE_URL` = `https://haemnet-api.onrender.com`
   - `CORS_ORIGINS` = `["https://haemnet-dashboard.onrender.com"]`
5. On the dashboard service set:
   - `EXPO_PUBLIC_API_URL` = `https://haemnet-api.onrender.com`
   - `EXPO_PUBLIC_WS_URL` = `wss://haemnet-api.onrender.com/ws/dashboard`

Render's health check hits `/api/health`, which reports whether the database
is reachable.

> The server must run with `--loop asyncio`. Both Dockerfiles already do.
> PyMongo's async client hangs on uvloop, which uvicorn picks by default.

## 4. Prove the keys work

From the Render shell of `haemnet-api` (or locally with the same `.env`):

```bash
python -m backend.tools.check_config
```

It checks the database, the Twilio credentials and number capabilities, the
Sarvam key (by synthesising one short sentence), geocoding, and the security
settings. It prints only the last four characters of any secret, so the
output is safe to share. Exit code 0 means everything needed is working.

## 5. First data

Create the first hospital from the dashboard's sign-in screen ("Register a
hospital"); the server issues the hospital ID. Donors register themselves in
the mobile app.

For a demo database you can seed a hospital and 96 donors around a point:

```bash
python -m backend.tools.seed_demo --lat 13.0626 --lng 80.2519
```

It refuses to run when `APP_ENV=production`, and every seeded donor's number
is in the reserved `+9190000…` test range, so nothing real is ever called.

## 6. Twilio callbacks

The backend tells Twilio where to send call events using `SERVER_BASE_URL`, so
once that is set to the public https URL there is nothing to configure in the
Twilio console. The audio stream uses `wss://<your API host>/ws/twilio/audio-stream`.

## 7. The donor app

The app is built with Expo. For a build your team can install:

```bash
cd frontend/donor-mobile
npm install
npx eas build --platform android --profile preview
```

Set `EXPO_PUBLIC_API_URL` to the public API URL in `eas.json` (or as an EAS
secret) before building, otherwise the app points at `localhost`.

## 8. After it is live

- `GET /api/health` should report `"status": "healthy"`.
- Register a hospital, trigger a request, and watch the console: donor events
  arrive over the WebSocket within seconds.
- Free Render instances sleep after 15 minutes of no traffic. The first
  request then takes several seconds and live updates stop while asleep, so
  use a paid instance for anything real.
- The sign-in code limits and the login throttle are kept in each instance's
  memory. If you scale to more than one instance, move them to a shared store
  (Redis or a Mongo collection) first.
