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
| `SENTRY_DSN` | Optional error monitoring; `SENTRY_TRACES_SAMPLE_RATE` (default 0.1) sets how much is traced |
| `TELEPHONY_PROVIDER=twilio` | Which provider places calls and sends SMS (only Twilio is implemented) |

### Hospital platform, storage and scale

These are needed for hospital sign-up, admin review and more than one instance.
All are listed in `backend/.env.example` and, as secrets, in `render.yaml`.

| Variable | Purpose |
| --- | --- |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD_HASH` | Admin panel sign-in (off until both are set). Make the hash with `python -c "import bcrypt;print(bcrypt.hashpw(b'PASSWORD', bcrypt.gensalt()).decode())"` |
| `DASHBOARD_URL` | Public dashboard address, used in verification emails |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | Verification and decision emails. Without `SMTP_HOST` no email is sent |
| `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_REGION`, `S3_ENDPOINT_URL`, `S3_PREFIX` | Private bucket for licence documents (S3 or Cloudflare R2). **Required on Render**: local disk is wiped on every deploy |
| `REDIS_URL` | Shares rate limits, call quotas, OTP codes and live dashboard updates between instances. Needed for more than one instance or worker |
| `TURNSTILE_SECRET` | Cloudflare Turnstile check on hospital sign-up and the contact form (off when empty) |
| `CONTACT_TO` | Inbox that receives contact form messages |
| `DONOR_OTP_REQUIRED` | `true` makes donor sign-up need a verified phone. Turn on only after the donor app supports the code flow |
| `MAX_DONORS_PER_DISPATCH`, `MAX_DISPATCHES_PER_HOSPITAL_DAY`, `TWILIO_CALLS_PER_SECOND` | Cost and rate guards |
| `MONGODB_SERVER_SELECTION_TIMEOUT_MS`, `MONGODB_MAX_POOL_SIZE` | Database timeouts and pool size |
| `WEB_CONCURRENCY` | Uvicorn workers per container (above 1 needs `REDIS_URL`) |
| `LOG_FORMAT=json` | One JSON object per log line |

In production the backend refuses to start with a `JWT_SECRET` shorter than 32
characters or left at a placeholder.

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
   initialization, the active voice mode/model, and any warning about missing
   configuration (the backend says so for `S3_BUCKET`, Twilio and Sarvam).

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
- `GET /api/health/deep` reports `status: healthy` with `database`, `storage`,
  `storage_persistent` (must be true in production), `redis` when configured, and
  `sarvam` when configured.
- `/docs` and `/openapi.json` return 404 in production.
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

## Deploy the public website

`frontend/website/` is static HTML with no build step. On Vercel set the project
root to `frontend/website`; `vercel.json` serves `src/` with clean URLs.

1. Edit `src/assets/site-config.js`: set `apiUrl` to the backend and, if used,
   `turnstileSiteKey`. Add the website's origin to the backend `CORS_ORIGINS`.
2. Replace the assumed values with real ones: the domain (`haemnet.in`), the contact
   email, the dashboard address and the Play Store link on the donor page.
3. Run `python frontend/website/check_links.py` and submit `sitemap.xml` to Google Search Console.
4. Have the privacy policy and terms reviewed before launch.

The dashboard needs its own build variables as above, plus `EXPO_PUBLIC_SENTRY_DSN`
and `EXPO_PUBLIC_TURNSTILE_SITE_KEY` if you use them.

## First go-live checklist

Do these in order on staging, then production. See `docs/RELEASE_CHECKLIST.md` for the full test list.

1. Backend deployed with every variable above set and `/api/health/deep` healthy.
2. Create the admin password hash and sign in at `<dashboard>/admin`.
3. Register a test hospital, verify its email, upload a document, approve it from the admin panel.
4. Raise a dispatch to a test donor number you control and run the voice test plan in `docs/VOICE_TEST_PLAN.md`.
5. Confirm a forged Twilio callback is refused (403) and that `SERVER_BASE_URL` matches the URL Twilio calls exactly.
6. Check Sentry receives a test error, uptime monitoring is on, and an Atlas backup restore has been tried once.
7. Run the load test on staging only (`loadtest/locustfile.py`).

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
- Sign-in throttles, call quotas, OTP codes and live dashboard events are shared
  across instances only when `REDIS_URL` is set; without it they are per instance.
  Active voice sessions are always process-local (one call is one WebSocket on one
  instance). Persisted MongoDB call records do not make an in-progress call
  recoverable across an instance restart.
- Server startup creates indexes. Schema/data migration, backup restoration,
  and retention policies are separate operational tasks.
- Demo seeding writes to the configured database. Use an isolated development
  database; do not trigger calls to generated donor numbers.
- Keep test calls explicit and use the telephony account's permitted numbers.
