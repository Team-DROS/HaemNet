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
