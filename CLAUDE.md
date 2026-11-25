# HaemNet

Emergency blood donor dispatch for Indian hospitals. A verified hospital raises a
request, nearby donors get an AI voice call (English, Hindi, Tamil), and answers
appear live on the hospital dashboard.

## Stack and folders

| Folder | What | Stack |
| --- | --- | --- |
| `backend/` | API, voice pipeline, hospital verification, admin API | FastAPI, MongoDB (Atlas), Twilio, Sarvam AI |
| `frontend/donor-web/` | Hospital dashboard, `/admin` panel, `/verify-email` | Expo web, React Native Web, expo-router |
| `frontend/donor-mobile/` | Donor Android app | Expo SDK 54, React Native |
| `frontend/website/` | Public marketing and legal site | Static HTML, deployed on Vercel |
| `docs/` | Runbook, releasing, release checklist, monitoring, voice and mobile test plans, Play Store kit | Markdown |
| `.github/workflows/` | CI (backend tests, frontend builds, link check), tagged releases, donor app builds | GitHub Actions |

Three owners: Role 1 backend and voice, Role 2 web and hospital platform, Role 3 mobile
and release. Do not merge into another role's folders without that owner's review.

## Commands

```bash
make check                                             # everything CI runs: ruff, format check, mypy, tests, website links
make help                                              # list the individual commands (lint, format, typecheck, test)
python -m pytest backend/tests -q                      # backend tests (JWT_SECRET needs 32+ chars outside tests)
cd frontend/donor-web && node node_modules/expo/bin/cli export --platform web --output-dir dist
cd frontend/donor-mobile && npm run lint && npm test
python frontend/website/check_links.py                 # public site links
pip-audit -r backend/requirements.txt --no-deps --disable-pip
```

## Backend architecture

Layers, from the outside in. Dependencies point inward only: an API module may import services, never the reverse.

| Layer | Where | Responsibility |
| --- | --- | --- |
| API | `backend/api/*.py` | HTTP only: parse the request, call a service, shape the response. Routers: `dispatches` (hospital), `donors`, `health`, `admin`, `hospital_account`, `hospital_staff`, `contact`, `auth`, `callbacks` (Twilio), `websockets` |
| Services | `backend/services/*.py` | Business rules, no HTTP. They raise `DomainError` subclasses (`services/errors.py`); `api/errors.py` turns them into responses in one place |
| Data | `backend/db_services/`, `backend/dispatch_store.py` | MongoDB (default) or Neo4j behind one function surface |
| Cross-cutting | `observability.py`, `hardening.py`, `config.py` | Request IDs and logs, security headers and size limits, settings |

New endpoint checklist: put the rule in a service and raise a domain error, keep the handler a few lines, add a service-level test and an API-level test.

## Rules

- Code must pass `make check` (ruff, ruff format, mypy, tests). Install the hooks with `pip install pre-commit && pre-commit install`.
- Work on a branch, never on `main`. Commit style: `feat:`, `fix:`, `docs:`, `test:`, `chore:`.
- Every change comes with a test. Show the plan before a large change.
- Never log or print donor speech, transcripts, phone numbers or tokens. Donor speech is personal data under the DPDP Act.
- A silent, unclear or failed call is never consent. Acceptance needs an explicit yes plus a separate confirmation.
- Only `approved` hospitals can dispatch. Records with no status are legacy and count as approved.
- Never put secrets in code, chat or `EXPO_PUBLIC_*` variables. Use `.env` files and the host dashboard.
- Twilio webhooks must pass signature verification. Do not add unsigned callback routes.
- Place calls and send SMS only through `get_telephony()` in `backend/services/telephony.py`, never by importing a provider module directly.
- Every donor app string goes through `t()` with a key in all three of `components/i18n/en.js`, `hi.js` and `ta.js`; `npm test` fails when the tables differ.
- Donor app logic goes in a small pure module with a Node test (`frontend/donor-mobile/tests/`); `DonorApp.js` only wires it to the screen.
- Health check answers never leave the donor's phone. Push alerts carry blood group, units, urgency and distance only.
- Production deploys only from a `vX.Y.Z` tag and the app only from a `donor-vX.Y.Z` tag (`docs/RELEASING.md`). Merges to `main` reach staging only.
- Fail 3 times on the same bug: stop, summarise, start fresh.

## Gotchas

- PyMongo's async client hangs on uvloop: run uvicorn with `--loop asyncio`.
- Python 3.13 removed `audioop`; install `audioop-lts` there (CI uses 3.11).
- Licence documents live in a private S3 or R2 bucket when `S3_BUCKET` is set; otherwise in `UPLOAD_DIR` on local disk, which vanishes on every Render deploy. Use `backend/services/file_storage.py`, never write upload paths yourself.
- Rate limits, call quotas and live dashboard events are shared across instances only when `REDIS_URL` is set. Without it they are per instance. Use the async `Limiter` in `backend/services/rate_limit.py`, never a bare in-process counter, and take slots with `try_acquire` (atomic) instead of `allowed()` then `hit()`, which races under concurrent requests.
