# HaemNet

![HaemNet Logo](assets/logo.png)

**Emergency blood donor coordination with multilingual AI voice calls.**

HaemNet helps hospital teams find nearby donors, contact them concurrently,
and follow their responses from a live dashboard. Donors manage profiles and
respond to requests through an Expo mobile app. MongoDB stores donor records,
dispatch history, and call state.

[![Backend CI](https://github.com/Team-DROS/HaemNet/actions/workflows/main.yml/badge.svg)](https://github.com/Team-DROS/HaemNet/actions/workflows/main.yml)
[Live website](https://haemnet-dashboard.onrender.com/) ·
[API health](https://haemnet-api.onrender.com/api/health) ·
[API documentation](https://haemnet-api.onrender.com/docs) ·
[Deployment guide](DEPLOY.md) · [MIT license](LICENSE)

## What HaemNet does

- **Hospital command center:** create requests with blood group, units, urgency,
  and location; monitor donor responses; record donations and request fulfillment.
- **Nearby donor recruitment:** MongoDB geospatial queries select donors within
  a default 10 km radius and outside the configured 56-day donation cooldown.
- **Concurrent outreach:** LangGraph coordinates recruitment and launches calls
  through Twilio, with English, Hindi, and Tamil voice workflows.
- **Explicit voice consent:** AI mode interprets responses with Sarvam-105B and
  asks a separate confirmation question before recording acceptance.
- **Live operations:** authenticated WebSockets deliver hospital-specific
  events; server history supports dashboard analytics.
- **Donor mobile app:** phone-and-password accounts, secure session storage,
  profiles, location capture, request responses, external map directions, and
  a cooldown view. Both applications include light and dark themes.

## How an emergency request works

1. A signed-in hospital submits a request and its location or address.
2. The backend searches for donors by group, distance, and cooldown. Individual
   groups are supported alongside **All positive** and **All negative**, which
   expand recruitment to the four blood groups of that Rh sign.
3. LangGraph launches concurrent Twilio calls. MongoDB persists the dispatch
   roster and call state.
4. Twilio streams donor audio to FastAPI. Sarvam transcribes it; in AI mode,
   Sarvam-105B interprets the completed response and recent conversation.
5. Initial agreement prompts a separate confirmation. Explicit confirmation
   records acceptance and starts directions delivery. A refusal records decline.
6. Hospital staff record actual donations separately, updating the last
   donation date and tracking whether the request's units have been fulfilled.

Blood-group selection controls recruitment; it is not clinical cross-matching.
The 56-day cooldown is an application rule, not a complete medical eligibility
assessment.

## AI voice pipeline

```text
Twilio donor audio
  -> speech-pause detection and WAV conversion
  -> Sarvam speech-to-text
  -> Sarvam-105B: accepted / declined / unclear
  -> backend confirmation rules and selected reply
  -> translation when needed -> text-to-speech -> Twilio playback
```

| Responsibility | Current implementation |
| --- | --- |
| Speech recognition | Sarvam `saarika:v2.5` |
| Response interpretation | Sarvam `sarvam-105b`, configurable with `VOICE_INTENT_MODEL` |
| Translation | Sarvam `mayura:v1` |
| Speech synthesis | Sarvam `bulbul:v3` |
| Conversation control | Backend voice session, explicit confirmation, Twilio playback acknowledgements |
| Dispatch orchestration | LangGraph `StateGraph` and Python `asyncio` |

HaemNet is an **AI-assisted workflow using pretrained models**. It does not
train or fine-tune a model. The model interprets language; backend code controls
confirmation, persistence, and notifications. LangGraph starts dispatches;
voice sessions and Twilio callbacks handle ongoing conversations. The current
graph is not a durable autonomous agent managing every conversation turn.

`VOICE_INTENT_MODE=ai` selects the new interpreter; `legacy` preserves the
original keyword pipeline for rollback. The Python default remains `legacy`;
the Render blueprint explicitly selects `ai`. Provider errors never cause
automatic fallback to keyword acceptance in AI mode.

## Architecture

![System Architecture](assets/architecture.png)

*The original illustration is preserved as a project reference. Any Neo4j
labels or older workflow details reflect the earlier design; the current
implementation described here uses MongoDB by default.*

| Layer | Technology and role |
| --- | --- |
| Hospital dashboard | Expo Web, React Native Web, authenticated WebSockets |
| Donor app | Expo SDK 54, React Native 0.81.5, Expo Router, SecureStore |
| API | Python 3.11, FastAPI, Uvicorn with the `asyncio` loop |
| Database | MongoDB / Atlas, PyMongo async API, GeoJSON `2dsphere` indexing |
| Voice transport | Twilio outbound calls, status callbacks, bidirectional audio WebSockets |
| AI services | Sarvam speech, translation, and chat APIs |
| Hosting and checks | Docker backend, static dashboard, Render blueprint, GitHub Actions |

The original Neo4j repository remains selectable with `DB_BACKEND=neo4j`.
It is an optional legacy implementation, not the default data store.

## Explore the repository

| Directory | Contents |
| --- | --- |
| [Backend](backend/README.md) | API, authentication, voice sessions, orchestration, tests |
| [Frontend](frontend/README.md) | Hospital dashboard and separate donor mobile workspace |
| [Donor app](frontend/donor-mobile/README.md) | Development, Android builds, sign-in, troubleshooting |
| [Database](database/README.md) | Collections, indexes, recruitment queries, configuration |
| [Design](design/README.md) | Visual tokens and original screen references |
| [Deployment](DEPLOY.md) | Render setup, environment settings, verification, rollback |

For AI evaluation, start with
[`sarvam_service.py`](backend/services/sarvam_service.py),
[`voice_intent.py`](backend/services/voice_intent.py),
[`ai_voice_pipeline.py`](backend/services/ai_voice_pipeline.py),
[`graph.py`](backend/orchestration/graph.py), and
[`test_voice_consent.py`](backend/tests/test_voice_consent.py).

## Run locally

Use Python 3.11, a Node.js version compatible with Expo SDK 54, and MongoDB.
Twilio and Sarvam credentials are required for actual voice calls.

### Backend

From the repository root:

```bash
python -m venv .venv
# Activate .venv using your shell, then:
pip install -r backend/requirements.txt
```

Copy [`.env.example`](.env.example) to a root `.env`. Set `JWT_SECRET`,
`DB_BACKEND=mongodb`, `MONGODB_URI`, and `MONGODB_DATABASE`. Enable AI
mode and supply Sarvam/Twilio credentials for voice testing. Settings read
`.env` relative to the process's working directory.

```bash
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000 --loop asyncio
```

Docs: `http://localhost:8000/docs`. Health: `/api/health`.
Twilio requires a public HTTPS `SERVER_BASE_URL` reaching this backend and
its WSS audio endpoint; localhost cannot receive Twilio callbacks.

### Hospital dashboard

In `frontend/donor-web/.env`:

```dotenv
EXPO_PUBLIC_API_URL=http://localhost:8000
EXPO_PUBLIC_WS_URL=ws://localhost:8000/ws/dashboard
```

```bash
cd frontend/donor-web
npm ci
node node_modules/expo/bin/cli start --web --port 8081
```

Allow `http://localhost:8081` in backend `CORS_ORIGINS`. Register a hospital
from the sign-in screen; the server issues its hospital ID.

### Donor app

Set `EXPO_PUBLIC_API_URL` in `frontend/donor-mobile/.env` to an API the
phone can reach. For local development use the computer's LAN IP, not localhost.

```bash
cd frontend/donor-mobile
npm ci
node node_modules/expo/bin/cli start --go --port 8082
```

Use an Expo Go build compatible with **SDK 54**, or an installed development
build with `--dev-client`. JS and style edits use Fast Refresh; native
dependency and permission changes require a new native build.
See the [mobile guide](frontend/donor-mobile/README.md).

## Verification and current limits

```bash
python -m pytest backend/tests -q
```

Tests cover authentication, hospital isolation, dispatches, voice consent,
and MongoDB operations. Database integration tests use a separate
`haemnet_test` database and skip when no test MongoDB is available; CI
provides MongoDB. Consent tests mock provider output and do not measure
real-world speech or classification accuracy.

- AI endpoint detection uses an audio-energy threshold and pauses, not a
  trained VAD. Noise, echo, long pauses, and mixed speech need controlled
  phone evaluation. Audio during agent playback is discarded in AI mode.
- The existing STT model is retained; an interpreter cannot repair an
  incorrect transcript.
- Unconfirmed voice calls retain their existing donor state. In-app acceptance
  is a separate interaction from the voice confirmation flow.
- Push helpers exist, but mobile push registration and handling are not wired
  end to end. The mobile app polls while open and launches external maps;
  it does not provide live donor GPS tracking.
- Donor numbers are not verified by OTP. Login throttles and dashboard
  connections are held per process; multiple instances need shared coordination.
- Hosting can sleep. A healthy API/database does not by itself validate
  provider access, call audio, or donor consent on a real call.

## License

Released under the [MIT License](LICENSE). Copyright (c) 2026 Team DROS.
The frontend directories retain their Expo starter-template MIT notices.
