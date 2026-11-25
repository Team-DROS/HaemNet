# HaemNet backend

FastAPI backend for hospital dispatches, donor accounts, multilingual voice
calls, and live hospital updates. MongoDB is the default data store; the
original Neo4j repository remains an optional legacy implementation.

## Responsibilities

| Area | Implementation |
| --- | --- |
| HTTP API | FastAPI routes and Pydantic request/response models |
| Hospital sign-in | Hospital ID/password, bcrypt, role-scoped JWT |
| Donor sign-in | Phone/password accounts, bcrypt, separate donor JWT role |
| Recruitment | MongoDB geospatial search, blood-group selection, cooldown |
| Dispatch launch | LangGraph and concurrent `asyncio` Twilio requests |
| Voice transport | Twilio callbacks and bidirectional audio WebSocket |
| AI interpretation | Sarvam-105B structured output and explicit confirmation |
| Dashboard events | Authenticated, hospital-scoped WebSocket connections |
| Operational history | MongoDB dispatch and call records; analytics endpoints |

## Dispatch orchestration versus conversation control

`orchestration/graph.py` defines `query_donors -> initiate_calls`, with
a conditional routing node. The graph launches calls; it does not wait
durably for every conversation or resume from a persisted LangGraph checkpoint.
Later outcomes are handled by `api/callbacks.py`, the voice session, and the
dispatch store.

Recruitment supports individual groups plus `All positive` and
`All negative`, expanded by `services/blood_groups.py`. Each group search
applies a default 10 km radius and 56-day cooldown. This recruits donors;
it does not perform clinical compatibility testing.

## Voice interpretation and rollback

| Setting | Behavior |
| --- | --- |
| `VOICE_INTENT_MODE=ai` | `services/ai_voice_pipeline.py`: model interpretation and separate confirmation |
| `VOICE_INTENT_MODE=legacy` | Original keyword session in `services/voice_pipeline.py` |
| `VOICE_INTENT_MODEL=sarvam-105b` | Chat model used by `services/voice_intent.py` |

The Python configuration defaults to `legacy`. The Render blueprint selects
`ai` explicitly. Select the mode in the environment and restart the backend;
each new call selects one session implementation.

In AI mode:

1. Decode Twilio's 8 kHz mu-law audio and wait for a speech pause.
2. Transcribe the buffered WAV through Sarvam STT.
3. Send the transcript and bounded recent conversation to Sarvam's chat API.
4. Validate structured output: intent, explicit consent, and confirmation.
5. Ask a separate confirmation question for initial agreement.
6. Wait for Twilio's playback acknowledgement before interpreting its answer.
7. Save acceptance only for explicit affirmative confirmation; refusal declines.
   Invalid responses, API failures, silence, and ambiguity never grant acceptance.
8. Generate the backend-selected reply using translation/TTS as needed.

Current speech integrations are STT `saarika:v2.5`, translation `mayura:v1`,
and TTS `bulbul:v3`. The new interpreter does not replace these speech models.
It uses the existing `SARVAM_API_KEY`; that key must have chat access.

The endpoint detector uses an energy threshold, not a trained VAD. Overlong
or unclear speech and idle limits can end a call without a decision. Such a
call retains its previous donor status. Audio during agent playback is
discarded. Test noise, echo, and long pauses on controlled calls.

Set `VOICE_INTENT_MODE=legacy` and restart to roll back. The legacy
classifier's known mixed-language/keyword limitations remain. AI failures
never switch a call to legacy automatically. Changing modes does not reverse
already saved donor decisions.

## Run from the repository root

Use Python 3.11 (the Docker/CI runtime):

```bash
python -m venv .venv
# Activate .venv, then:
pip install -r backend/requirements.txt
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000 --loop asyncio
```

First create a root `.env` from `.env.example`. Minimum local settings are
a JWT signing secret and a reachable MongoDB configuration. Add Twilio and
Sarvam keys for actual calls. The settings loader reads `.env` relative to
the process working directory, not automatically relative to this module.

Use `--loop asyncio` for the PyMongo async client. Both Dockerfiles specify
it. Open `http://localhost:8000/docs` for the exact API schema.

## Storage

| `DB_BACKEND` | Implementation | Notes |
| --- | --- | --- |
| `mongodb` (default) | `db_services/mongo_repo.py` | Async PyMongo, GeoJSON locations, startup indexes |
| `neo4j` | `db_services/neo4j_repo.py` | Retained original data layer |

Collections are `donors`, `hospitals`, `dispatches`, `calls`, and
`donor_logins`. See [the database guide](../database/README.md).

## Authentication

| Account | Sign-in | Token lifetime |
| --- | --- | --- |
| Hospital | `POST /api/auth/token`, form fields `username` and `password` | 24 hours |
| Donor | `POST /api/donor/auth/register` or `/login`, JSON `phone` and `password` | 30 days |

Hospital registration issues an ID. Donor passwords are bcrypt-hashed in
`donor_logins`, separate from profiles. Donor phone numbers are account
identifiers, not OTP-verified ownership. Hospital and donor tokens use
different roles.

Failed login limits are 10 attempts per identifier in 15 minutes; donor
account creation is limited to 5 attempts per number per hour. These limits
are process-local, so multiple instances need a shared limiter.

Password recovery is an operator workflow: after verifying ownership, run
`python -m backend.tools.reset_donor_password <phone>`. The donor can then
create the login again; their profile and donation history are retained.

## API overview

| Method and path | Purpose |
| --- | --- |
| `POST /api/auth/register` | Hospital registration |
| `POST /api/dispatch` | Hospital recruitment and call launch |
| `GET /api/dispatches/active` | Restore the hospital's open dispatches |
| `POST /api/dispatches/{id}/close` | Close a dispatch |
| `GET /api/dispatches/history?days=30` | Server-backed outcome history |
| `GET /api/network/availability` | Eligible donor counts near the hospital |
| `POST /api/donate` | Record actual donation and update fulfillment |
| `POST /api/donor/register` | Create/update the signed-in donor's profile |
| `GET / DELETE /api/donor/profile/{phone}` | Read/delete the donor's own profile |
| `GET /api/donor/requests/{phone}` | Requests for the signed-in donor |
| `POST /api/donor/respond` | Donor app acceptance/decline |
| `GET /api/health` | Database connectivity and active data layer |
| `GET /` | Service identity and configured voice mode/model |

In-app responses are separate from the two-turn voice consent flow.
See `/docs` for payloads and auth requirements.

### Hospital WebSocket

Connect to `/ws/dashboard` and send the hospital token within 10 seconds:

```json
{"type": "auth", "token": "<hospital access token>"}
```

The server acknowledges `auth_ok` and streams only that hospital's events.
Authentication failures close with code `4401`. Send `ping` for `pong`.
Connections are kept in memory per backend process, not in a distributed broker.

### Twilio callbacks

The backend constructs call URLs from `SERVER_BASE_URL`. It must be the
public HTTPS origin of this backend, with the audio stream at
`wss://<API host>/ws/twilio/audio-stream`. Keep temporary local tunnel
addresses out of production settings. AI mode uses Twilio `mark` messages
to distinguish question playback from a new donor answer.

## Checks and helper commands

```bash
python -m pytest backend/tests -q
python -m backend.tools.check_config
```

Unit and voice-consent tests mock external services. MongoDB integration tests
need a dedicated test MongoDB (`MONGODB_TEST_URI`) and use `haemnet_test`;
they skip when it is unavailable. CI starts MongoDB.

The configuration checker probes configured providers, including a short TTS
request; it is not proof of chat-model access or real-call behavior.
Consent tests cover confirmation, refusal, uncertain replies, malformed model
output, provider timeouts, playback gating, and audio boundaries. They do not
establish multilingual model accuracy.

For isolated local demo data, `python -m backend.tools.seed_demo` creates a
demo hospital and donor records. It refuses `APP_ENV=production`, but still
writes to the configured database; use a separate development database.
Do not initiate calls to generated donor numbers.

For Render environment setup, live verification, and rollback, see
[DEPLOY.md](../DEPLOY.md).


## Hospital verification and admin review

New hospitals register as `pending` and must verify their official email, upload
registration documents and be approved by an admin before `POST /api/dispatch`
works (it returns 403 with code `hospital_pending`, `hospital_rejected` or
`hospital_suspended`). Hospital records created before this feature have no
status and count as approved.

- Hospital: `GET /api/hospitals/me`, `POST /api/hospitals/verify-email`,
  `POST /api/hospitals/resend-verification`, `POST /api/hospitals/me/documents`
  (PDF, JPG or PNG up to `MAX_UPLOAD_MB`, checked by file signature)
- Admin (token from `POST /api/admin/token`): `GET /api/admin/hospitals?status=`,
  `GET /api/admin/hospitals/{id}`, `GET /api/admin/hospitals/{id}/documents/{doc_id}`,
  `POST /api/admin/hospitals/{id}/decision` with `approve`, `reject`, `suspend` or `reinstate`
- Setup: set `ADMIN_USERNAME`, `ADMIN_PASSWORD_HASH`, `DASHBOARD_URL`, `UPLOAD_DIR` and the `SMTP_*`
  values (see `.env.example`). Without SMTP no email is sent. Documents go to local disk
  by default; set `S3_BUCKET` (see below) for production. Needs `DB_BACKEND=mongodb`.

Staff accounts: the hospital owner login can create staff (`POST /api/hospitals/me/staff`,
roles `admin` or `staff`, up to 20), list and remove them. Staff sign in through
`POST /api/auth/staff-token` with hospital ID, email and password. Staff admins can manage
staff; plain staff cannot. Removing someone revokes their access immediately.

Bot protection: set `TURNSTILE_SECRET` to require a Cloudflare Turnstile token on hospital sign-up and `/api/contact`
(clients send `turnstile_token`). Empty means the check is off. The dashboard reads `EXPO_PUBLIC_TURNSTILE_SITE_KEY`.
`POST /api/contact` emails `CONTACT_TO` via SMTP and is limited to 5 messages per IP per hour.

## Redis (running more than one instance)

Set `REDIS_URL` to share, across all backend instances:
- rate limits (sign-in lockouts, sign-up and upload limits, contact form) and the per-hospital daily call quota, kept as sorted sets under `rl:*`
- live dashboard events: every event is published on the `haemnet:dashboard-events` channel and each instance delivers it to its own sockets, so a Twilio callback on instance B reaches a dashboard connected to instance A

With `REDIS_URL` empty everything stays in process memory, which is fine for one instance. If Redis fails, limits fall back to per-instance counters and events are delivered locally, with a warning in the logs, so an outage weakens limits but never blocks sign-in. `GET /api/health/deep` reports `redis`. Voice sessions stay in process on purpose: one call is one audio WebSocket on one instance. Dispatch state already lives in MongoDB.

Locally: `docker compose up redis`, then `REDIS_URL=redis://localhost:6379`.

## Document storage (S3 or Cloudflare R2)

Hospital licence documents are private. With `S3_BUCKET` empty they go to `UPLOAD_DIR` on local disk, which is wiped on every
redeploy on Render. In production set a bucket:

1. Create a **private** bucket. Turn on "Block all public access". No bucket CORS is needed: admins read files through
   `GET /api/admin/hospitals/{id}/documents/{doc_id}`, which checks the admin token.
2. Create an access key limited to that bucket (read, write, list, delete). On AWS you can leave the keys empty and use an instance role.
3. Set `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, and `S3_PREFIX` (default `hospital-documents/`).
   - AWS: also `S3_REGION`. Files are encrypted with AES256.
   - Cloudflare R2: `S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com` and `S3_REGION=auto` (R2 encrypts at rest itself).
4. Check `GET /api/health/deep`: `storage: true` and `storage_persistent: true`.
5. Moving existing files: `python -m backend.tools.migrate_uploads_to_s3 --dry-run`, then without `--dry-run`. Keys are the same, so no database change is needed.

Uploads are limited to PDF, JPG and PNG up to `MAX_UPLOAD_MB`, checked by file signature. Deleting a hospital account deletes its files; if the
bucket cannot be reached the account is kept and the caller gets a 503 so it can retry.

## Scale and safety limits

- **Concurrency-safe limits:** sign-in lockouts, sign-up and upload limits, and the daily call quota reserve their slot atomically (`Limiter.try_acquire`), so a burst of simultaneous requests cannot slip past a limit. A request that ends up placing no calls gives its daily slot back.
- **Call pacing:** call starts are spaced by `TWILIO_CALLS_PER_SECOND` per instance; Twilio 429s are retried (never after a timeout, so a donor is never rung twice). Sarvam speech, TTS and translation calls retry on throttling, 5xx and timeouts.
- **Database:** `MONGODB_SERVER_SELECTION_TIMEOUT_MS` (default 5000) makes an outage fail in seconds, `MONGODB_MAX_POOL_SIZE` sizes the pool. Hospital review, audit and token lookups are indexed.
- **API hardening:** security headers on every response (HSTS in staging and production), JSON bodies over `MAX_REQUEST_BODY_KB` get 413 (uploads use `MAX_UPLOAD_MB`), `/docs` and `/openapi.json` are off in production, and unexpected errors return a generic 500 with a `request_id`.
- **Workers:** `WEB_CONCURRENCY` sets uvicorn workers per container. Above 1, set `REDIS_URL`.
- **Audit trail:** each request raised, closed and donation logged writes an audit entry with the acting staff member (visible to admins and in the hospital export). A failed audit write never blocks a request.
- **Donor calls:** `POST /api/donor/calls/preference` opts a donor out of (or back into) automated calls; opted-out donors are never matched. The mobile app should send `calls_consent: true` at sign-up; the time is stored.
- **Load test:** `loadtest/locustfile.py` (staging only, it refuses to run without an explicit opt-in because dispatches place real calls).

## Donor phone verification and telephony

- `POST /api/donor/auth/otp/request` texts a 6-digit code (3 per number and 10 per client per hour). `POST /api/donor/auth/otp/verify` exchanges it for a 30-minute `otp_token` that is neither a donor nor a hospital token. Codes are stored as keyed hashes, expire after `OTP_TTL_SECONDS`, work once, and allow `OTP_MAX_ATTEMPTS` wrong guesses. With `DONOR_OTP_REQUIRED=true`, `POST /api/donor/auth/register` needs the `otp_token`. The donor app must be updated before turning this on. Use `REDIS_URL` when running more than one instance.
- Calls and SMS go through `TelephonyProvider` (`services/telephony.py`). To add a provider, implement `start_call`, `send_sms` and `close`, register it in `_PROVIDERS`, set `TELEPHONY_PROVIDER`, and add that provider's webhook verification (`services/twilio_signature.py` covers Twilio only). A misspelt provider name stops the backend at startup.
- A call that fails to start, or that the provider reports as failed or cancelled, is recorded as "no answer", never as a decline.
