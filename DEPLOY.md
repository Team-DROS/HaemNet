# Deploying HaemNet

HaemNet deploys as a FastAPI backend, a static hospital dashboard, and a
separately built donor mobile application. The checked-in Render blueprint
describes the backend and dashboard; mobile builds use Expo/EAS.

## Services and source

| Component | Source | Deployment configuration |
| --- | --- | --- |
| Backend | `backend/` | Root Dockerfile; `render.yaml` service `haemnet-api` |
| Hospital dashboard | `frontend/donor-web/` | Expo static export; Render static service or existing frontend host |
| Donor mobile | `frontend/donor-mobile/` | EAS development, preview APK, and production AAB profiles |
| Database | MongoDB / Atlas | Connection supplied to the backend; not provisioned by the blueprint |

The documented API address is `https://haemnet-api.onrender.com`. Use the
actual service address if it differs. Confirm which repository/branch each
service deploys; if a service builds a fork, sync the required changes first.
Auto-deployment depends on the hosting service's repository settings, not just
the presence of a blueprint.

## Backend environment

Configure secrets in the hosting environment. Do not commit real `.env`
files or put server secrets in `EXPO_PUBLIC_*` variables.

| Variable | Purpose |
| --- | --- |
| `APP_ENV=production` | Production configuration checks |
| `DB_BACKEND=mongodb` | Default data layer |
| `MONGODB_URI` | Database connection string, including protected credentials |
| `MONGODB_DATABASE=haemnet` | Application database name |
| `JWT_SECRET` | Existing signing secret; preserve it across normal redeployments |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER` | Outbound calls and directions SMS |
| `SARVAM_API_KEY` | Speech, translation, and chat-model access |
| `SARVAM_BASE_URL=https://api.sarvam.ai` | Sarvam API origin |
| `VOICE_INTENT_MODE=ai` | New model interpretation and explicit confirmation |
| `VOICE_INTENT_MODEL=sarvam-105b` | Interpretation model |
| `SERVER_BASE_URL` | This backend's public HTTPS origin |
| `CORS_ORIGINS` | JSON array of allowed dashboard origins |
| `SENTRY_DSN` | Optional error monitoring |

The blueprint selects AI mode. The Python settings default remains `legacy`
when the mode is omitted. Existing services outside blueprint management
need the voice variables set explicitly.

Keep current MongoDB, JWT, Twilio, Sarvam, and frontend-origin settings when
redeploying an existing service. A normal code deployment does not require
new credentials or another database.

## Deploy the API

1. Configure Atlas/database access and network connectivity for the backend.
   Scope permissions and allowed networks to the deployment's requirements.
   URL-encode credentials when constructing a connection string.
2. Connect the hosting service to the intended GitHub repository and branch,
   or create the two services using `render.yaml` for a new environment.
3. Configure environment values. The root Dockerfile runs:
   `uvicorn backend.main:app --host 0.0.0.0 --port $PORT --loop asyncio`.
4. Ensure `SERVER_BASE_URL` is the deployed API's HTTPS origin, never localhost
   or a temporary local tunnel address.
5. Deploy the desired commit and inspect startup logs for database index
   initialization and the active voice mode/model.

The PyMongo async setup uses the standard asyncio loop. Both Dockerfiles
already specify `--loop asyncio`.

## Deploy the hospital dashboard

Set these public build variables using the actual API host:

```dotenv
EXPO_PUBLIC_API_URL=https://haemnet-api.onrender.com
EXPO_PUBLIC_WS_URL=wss://haemnet-api.onrender.com/ws/dashboard
```

The blueprint builds from `frontend/donor-web/` with `npm ci` followed by
an Expo web export to `dist`, and rewrites routes to `index.html`.
Allow the dashboard's actual origin in the backend's `CORS_ORIGINS`.
Frontend variables are bundled at build time; changing them requires a
fresh export/deployment.

## Voice callbacks and verification

Twilio receives per-call URLs generated from `SERVER_BASE_URL`.
The audio endpoint is:

```text
wss://<API host>/ws/twilio/audio-stream
```

Verify the deployment rather than assuming a successful Git push means it is live:

- The hosting service shows the expected commit and successful startup.
- `GET /` reports `voice_intent_mode: ai` and
  `voice_intent_model: sarvam-105b`.
- `GET /api/health` reports `status: healthy`, `database: mongodb`,
  and `mongodb: connected`.
- `GET /api/twilio/twiml` references the deployed WSS audio endpoint.
- Dashboard sign-in and its authenticated WebSocket work from the allowed origin.

`python -m backend.tools.check_config` checks configured services, including
a short Sarvam TTS request. It does not validate Sarvam chat access or a real
conversation. Test chat access from a secure backend shell with synthetic
text and the existing environment key; do not print credentials or add an
unauthenticated diagnostic endpoint.

Before wider use, coordinate a controlled call to an agreed test number.
Verify refusal, tentative responses, silence, initial yes, and yes-then-no at
confirmation. Only a separate explicit affirmative confirmation should record
voice acceptance. Health checks and mocked tests do not prove audio accuracy.

## Rollback

Set `VOICE_INTENT_MODE=legacy` and restart/redeploy the existing backend.
The original keyword session is retained; its known classification limitations
remain. Rollback does not reverse decisions already recorded in the database.
There is no automatic keyword fallback after an AI request fails.

## Donor mobile releases

Follow the [mobile release guide](frontend/donor-mobile/README.md). The existing
EAS profiles target `https://haemnet-api.onrender.com`; confirm the actual
API origin before building. Preview creates an installable APK; production
creates an AAB for store upload. A backend-only voice update does not require
a new mobile binary.

Everyday JS/UI work uses an installed development build and Fast Refresh.
Rebuild native binaries for SDK, native dependency, or permission changes.

## Operational boundaries

- Free-tier hosting may sleep; allow for cold starts and interrupted connections.
- Login throttles, dashboard sockets, and active voice-session objects are
  process-local. Persisted MongoDB call records do not make all runtime work
  recoverable across instance restarts.
- Server startup creates indexes. Schema/data migration, backup restoration,
  and retention policies are separate operational tasks.
- Demo seeding writes to the configured database. Use an isolated development
  database; do not trigger calls to generated donor numbers.
- Keep test calls explicit and use the telephony account's permitted numbers.
