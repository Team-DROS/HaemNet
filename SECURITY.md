# Security Policy

HaemNet handles donor phone numbers, locations and hospital accounts, so we
take security reports seriously.

## Reporting a vulnerability

Please **do not open a public issue** for security problems.

Report privately through GitHub:
**Security → Advisories → Report a vulnerability** on this repository
(private vulnerability reporting). Include:

- the affected component (API, hospital dashboard, donor app)
- steps to reproduce, or a proof of concept
- the impact you expect (data exposure, account takeover, fake call outcomes, ...)

We aim to acknowledge a report within **3 working days** and to share a fix
plan within **10 working days**. We will credit you in the release notes
unless you prefer otherwise.

## Supported versions

Only the latest commit on `main` (what is deployed) receives security fixes.

## What is in scope

- Authentication and authorisation for hospitals and donors (JWT roles)
- Twilio webhooks (`/api/twilio/*`), which must reject unsigned requests in production
- Exposure of donor personal data through the API or WebSockets
- Injection into database queries, TwiML or voice prompts

Out of scope: denial of service through sheer traffic volume, findings that
need a compromised device, and reports from automated scanners without a
demonstrated impact.

## Security measures in place

- bcrypt password hashing, rate-limited sign-in, role-separated tokens
- Twilio request signature validation (`X-Twilio-Signature`)
- Strict request schemas with length and range limits
- HTTP security headers and HSTS in production; CORS limited to listed origins
- Secrets only in environment variables (`.env` is git-ignored)
- Dependabot updates and CI linting and tests on every pull request
