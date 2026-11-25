# Incident runbook

Fill in the contact table before launch. Severity: **S1** donors cannot be reached or wrong answers are being recorded, **S2** a feature is broken, **S3** cosmetic.

| Role | Name | Phone | Backup |
| --- | --- | --- | --- |
| Backend and voice (Role 1) | | | |
| Web and hospital (Role 2) | | | |
| Mobile and release (Role 3) | | | |

## First five minutes

1. Open `GET /api/health/deep` (uptime monitors and alert routing: [MONITORING.md](MONITORING.md)). `database: false` means MongoDB Atlas, `sarvam: false` means Sarvam is unreachable.
2. Search logs for the request ID: every response has an `X-Request-ID`, and each log line carries it.
3. Check Sentry for new errors, then the status pages of Twilio, Sarvam, Render and Atlas.
4. Post in the team chat: what is broken, severity, who is on it.

## Playbooks

**Calls are not going out.** Check Twilio credentials and balance, then `TWILIO_*` env values. A hospital stuck at `403 hospital_pending` is not approved, not a telephony fault. If `429 Daily request limit` appears, raise `MAX_DISPATCHES_PER_HOSPITAL_DAY` for a real emergency.

**Donors say they were called twice, or retries are not happening.** Retries come from `CALL_MAX_RETRIES` and `CALL_RETRY_DELAY_SECONDS`. They are held in memory, so a restart inside the delay drops them. Set `CALL_MAX_RETRIES=0` to stop retrying while you investigate.

**Donors answer but the answer is wrong or missing.** Switch `VOICE_INTENT_MODE=legacy` (keyword mode) and redeploy. Never mark a donor accepted by hand without a call recording from the donor.

**Sarvam is down.** The pipeline must not record acceptance on error. Tell hospitals to use the in-app or phone fallback and set `VOICE_INTENT_MODE=legacy` if keyword mode still works.

**Dashboard shows "Live updates are disconnected".** The WebSocket dropped: use Reconnect. If it keeps failing, check the backend is awake (free Render sleeps) and `CORS_ORIGINS`.

**Webhooks rejected (403 Invalid Twilio signature).** `SERVER_BASE_URL` must exactly match the public URL Twilio calls, including `https`. Wrong `TWILIO_AUTH_TOKEN` gives the same error.

**Dashboards miss live updates only sometimes, or limits behave oddly with several instances.** Check `redis` in `/api/health/deep`. If Redis is down the backend falls back to per-instance behaviour (events reach only dashboards on the same instance) and logs `Redis ... unavailable`. Restore Redis; the subscriber reconnects by itself within 30 seconds.

**Admins cannot open documents, or uploads fail with 503.** Check `storage` in `/api/health/deep`. Usual causes: expired or wrong `S3_*` keys, a deleted bucket, or R2 `S3_ENDPOINT_URL` typos. Hospitals can retry once it is fixed; no data is lost because failed uploads are not recorded. If `storage_persistent` is false in production, set `S3_BUCKET` before the next deploy.

**Suspected data leak.** Rotate `JWT_SECRET`, Twilio, Sarvam, SMTP and Mongo credentials, revoke sessions, then follow the DPDP breach steps: notify affected users and the Data Protection Board as the law requires.

## After the incident

Write a short blameless note: timeline, cause, what detected it, what changes so it cannot repeat. File follow-ups as GitHub issues labelled `blocker` if they affect launch.

## Donor app playbooks

**Donors say they get no app alerts.** Calls are the main channel, so first confirm calls went out. Then check the API logs for `push` receipt errors. `DeviceNotRegistered` clears that donor's token and they must open the app once to register again. If the Expo push service or FCM credentials are failing for everyone, check the Expo status page and the FCM key in `eas credentials`.

**Alerts are going to the wrong people or flooding donors.** Set `PUSH_REQUEST_ALERTS=false` on the API and redeploy. Calls keep working. Then investigate.

**The app crashes on start after a release.** Halt the staged rollout in Play Console (Production > Halt rollout). Look up the crash in Sentry by release. Fix forward with a PATCH version; Play never accepts a lower version code.

**New donors cannot sign up (code never arrives).** This is SMS delivery through Twilio: check the balance and the SMS logs. Existing donors sign in with their password and are not affected. As a stopgap during a recruitment drive, `DONOR_OTP_REQUIRED=false` lets sign-up go ahead without a code; turn it back on once SMS works.
