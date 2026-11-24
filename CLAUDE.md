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
| `docs/` | Runbook, release checklist, voice test plan | Markdown |
| `.github/workflows/` | CI: backend tests, frontend builds, link check | GitHub Actions |

Three owners: Role 1 backend and voice, Role 2 web and hospital platform, Role 3 mobile
and release. Do not merge into another role's folders without that owner's review.

## Commands

```bash
python -m pytest backend/tests -q                      # backend tests (JWT_SECRET needs 32+ chars outside tests)
cd frontend/donor-web && node node_modules/expo/bin/cli export --platform web --output-dir dist
cd frontend/donor-mobile && npm run lint && npm test
python frontend/website/check_links.py                 # public site links
pip-audit -r backend/requirements.txt --no-deps --disable-pip
```

## Rules

- Work on a branch, never on `main`. Commit style: `feat:`, `fix:`, `docs:`, `test:`, `chore:`.
- Every change comes with a test. Show the plan before a large change.
- Never log or print donor speech, transcripts, phone numbers or tokens. Donor speech is personal data under the DPDP Act.
- A silent, unclear or failed call is never consent. Acceptance needs an explicit yes plus a separate confirmation.
- Only `approved` hospitals can dispatch. Records with no status are legacy and count as approved.
- Never put secrets in code, chat or `EXPO_PUBLIC_*` variables. Use `.env` files and the host dashboard.
- Twilio webhooks must pass signature verification. Do not add unsigned callback routes.
- Fail 3 times on the same bug: stop, summarise, start fresh.

## Gotchas

- PyMongo's async client hangs on uvloop: run uvicorn with `--loop asyncio`.
- Python 3.13 removed `audioop`; install `audioop-lts` there (CI uses 3.11).
- Uploaded licence files live in `UPLOAD_DIR` on local disk and vanish on Render's free tier.
- Rate limiters and call quotas are in process memory, so they are per instance until moved to Redis.
