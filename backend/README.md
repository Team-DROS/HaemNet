# HaemNet Backend

The backend of HaemNet is the brain of the emergency blood dispatch system. It is responsible for orchestrating real-time AI voice calls, communicating with the graph database, and managing the live WebSocket dashboard for hospitals.

## Tech Stack
- **Framework:** Python FastAPI
- **AI Orchestration:** LangGraph (StateGraph) & LangChain
- **Telephony & Voice AI:** Twilio + Sarvam AI (Streaming WebSockets)
- **Database Connectivity:** Neo4j Python Driver
- **Concurrency:** `asyncio` for parallel outbound dialing

## System Architecture

### 1. The Dispatch Engine (`orchestration/graph.py`)
At the core of the backend is a state machine built with LangGraph. When a hospital triggers an emergency dispatch, the graph:
1. Initiates concurrent Twilio calls to all eligible donors.
2. Tracks the state of each call (`RINGING` -> `ANSWERED` -> `ACCEPTED`/`DECLINED`).
3. Streams the ongoing state changes back to the frontend via WebSockets.

### 2. Conversational Voice AI (`api/callbacks.py` & `services/`)
When a donor answers the phone, Twilio connects via WebSocket to our FastAPI server. The backend intercepts the raw audio stream, pipes it through Sarvam AI for low-latency Speech-to-Text and Text-to-Speech in the donor's native language (e.g., Hindi, Tamil, English), and streams the AI's response back to Twilio.

### 3. Spatial & Temporal Constraints (`db_services/`)
The backend interfaces with Neo4j to enforce strict medical guidelines:
- **Spatial:** Donors must be within a 10km radius of the hospital's coordinates.
- **Temporal:** Donors are mathematically locked out of the query if their `last_donated_date` is less than 56 days ago.

## Getting Started

### Prerequisites
- Python 3.9+
- Neo4j AuraDB credentials
- Twilio Account SID, Auth Token, and Phone Number
- Sarvam AI API Key

### Installation

1. Create a virtual environment and install dependencies:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. Configure your environment variables:
   Copy `.env.example` to `.env` and fill in your API keys.

3. Run the development server from the repository root (the code imports `backend.*`):
   ```bash
   uvicorn backend.main:app --reload
   ```
   The API will be available at `http://localhost:8000` and the interactive docs at `http://localhost:8000/docs`.

4. Run the tests (no Neo4j, Twilio or Sarvam needed; everything external is faked):
   ```bash
   python -m pytest backend/tests -q
   ```

## Authentication

Hospitals and donors sign in differently, and their tokens are not interchangeable (a `role` claim is checked on every request).

| Who | How | Token lifetime |
| --- | --- | --- |
| Hospital staff | `POST /api/auth/token` with hospital ID and password (form fields `username`, `password`). 10 failed attempts per ID in 15 minutes returns `429`. | 24 hours |
| Donor | `POST /api/donor/auth/request {phone}` texts a 6-digit code, then `POST /api/donor/auth/verify {phone, code}` returns the token. Codes last 5 minutes, allow 5 guesses, can be resent after 30 seconds and at most 5 times an hour. | 30 days |

When Twilio is not configured and `APP_ENV=development`, the request endpoint returns the code as `dev_code` so the app can be tested locally. In any other environment it refuses (`503`) instead.

OTP state and rate limits live in process memory. If you run more than one backend instance, move them to a shared store first.

## API overview

Hospital endpoints (hospital token):

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/dispatch` | Match donors and start the AI calls. The dispatch is always recorded against the signed-in hospital. |
| `GET` | `/api/dispatches/active` | Open dispatches with live donor states (restores the console after a reload). |
| `POST` | `/api/dispatches/{id}/close` | Stop a request. |
| `GET` | `/api/dispatches/history?days=30` | Outcome counts per request for analytics (1 to 365 days, no donor details). |
| `GET` | `/api/network/availability` | Eligible donors per blood group within 10 km of the hospital. |
| `POST` | `/api/donate` | Record a donation. Closes the request as fulfilled once all units are in. |

Donor endpoints (donor token; a donor can only reach their own records):

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/donor/register` | Create or update the profile for the verified phone. |
| `GET` / `DELETE` | `/api/donor/profile/{phone}` | Read or delete the profile. |
| `GET` | `/api/donor/requests/{phone}` | Open requests this donor was matched to, with distance and ETA. |
| `POST` | `/api/donor/respond` | Accept or decline `{dispatch_id, accept}`. Accepting marks the donor en route. |

### Dashboard WebSocket

Connect to `/ws/dashboard` and send the hospital token as the first message within 10 seconds:

```json
{"type": "auth", "token": "<hospital access token>"}
```

The server replies `{"type": "auth_ok", "hospital_id": "HOSP-1234"}` and then streams only that hospital's dispatch events (donor status updates, `dispatch_fulfilled`, `dispatch_closed`). A bad or missing token gets `auth_error` and close code `4401`. Send `ping` to receive `{"type": "pong"}`. The token is sent as a message, not in the URL, so it never appears in access logs.

## Deployment
This backend is designed to be dockerized and deployed to platforms like Render or Google Cloud Run. Ensure that your deployment platform supports WebSocket connections for the Twilio audio streams and the frontend dashboard.
