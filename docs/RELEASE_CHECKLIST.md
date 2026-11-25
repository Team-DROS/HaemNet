# Release checklist

Tick every box in the PR description before tagging a release. How the pipeline works and
how to roll back: [RELEASING.md](RELEASING.md). Donor app phone checks:
[MOBILE_TEST_PLAN.md](MOBILE_TEST_PLAN.md).

## Before tagging
- [ ] CI is green on the pull request (backend, frontend, website)
- [ ] `pip-audit` reviewed; no new high severity finding without a written reason
- [ ] `/security-review` run on the diff
- [ ] Deployed to **staging** (separate Render service and database) and the test list below passed there
- [ ] Migrations or new env vars listed in the PR and set on staging, then production
- [ ] Release notes written (what changed for hospitals, donors, admins)

## Staging test list
- [ ] Hospital signs up, verifies email, uploads a document (it appears in the bucket, not on local disk), sees "under review"
- [ ] `/api/health/deep` shows `storage` and `storage_persistent` true, and `redis` true when `REDIS_URL` is set
- [ ] Admin approves it; the hospital reaches the dashboard
- [ ] Hospital sends a dispatch (confirm step shown); a test donor receives a real call
- [ ] Donor says yes then confirms: dashboard shows accepted. Donor says no: declined. Silence: not accepted
- [ ] Donation logged; donor cooldown starts
- [ ] Suspended hospital cannot dispatch; reinstated hospital can
- [ ] Staff login works; removed staff is signed out
- [ ] Donor app: sign-up shows the code field when `DONOR_OTP_REQUIRED=true`; the consent box blocks joining until ticked; Pause automated calls stops the next dispatch from matching this donor
- [ ] Donor phone verification: a code arrives by SMS, a wrong code is refused, the right one works once (and sign-up requires it if `DONOR_OTP_REQUIRED=true`)
- [ ] Contact form delivers an email; Turnstile blocks a bot
- [ ] Hospital export and deletion work; deletion page link works
- [ ] `/api/health` on `haemnet-api-staging` reports the commit you are about to tag

## Donor app (staging build, only when the app changed)
- [ ] `expo.version` bumped in `app.json` and `package.json`
- [ ] Push: a dispatch alerts the test donor with the app closed; tapping it opens that request
- [ ] Push: signing out stops alerts on that phone; `PUSH_REQUEST_ALERTS=false` stops all alerts while calls continue
- [ ] Health check: a "yes" to any deferral question blocks accepting; a recent donation shows the recovery days
- [ ] Availability: Pause for 1 week hides the donor from the next dispatch and shows the end date; I am available again restores it
- [ ] Offline: airplane mode shows the saved profile and requests, never the join form
- [ ] Languages: English, Hindi and Tamil switch everywhere, including alerts and errors
- [ ] Sentry test event from the staging build contains no phone number, token or name
- [ ] Every row of [MOBILE_TEST_PLAN.md](MOBILE_TEST_PLAN.md) passed on three phones, or has a written reason

## Release
- [ ] Tag the commit (`vX.Y.Z`), deploy production only from the tag
- [ ] Watch Sentry and `/api/health/deep` for 30 minutes
- [ ] Approve the `production` deployment; the Release run confirms `/api/health` reports the tagged commit
- [ ] Mobile: tag `donor-vX.Y.Z`; the AAB lands in Play internal testing as a draft
- [ ] Mobile: release notes in English, Hindi and Tamil; Data safety form still matches [PLAY_STORE.md](PLAY_STORE.md)
- [ ] Mobile: Production rollout starts at 20%; watch Sentry crash-free sessions and Play vitals for 48 hours before 100%

## Rollback
1. Actions > Release > Run workflow with the previous tag (or Render's Rollback button). Cloudflare Pages keeps deploy history for the website (Deployments tab, "Rollback to this deployment").
2. If a new env var caused it, unset it and redeploy.
3. Database changes are additive (new optional fields), so an older backend still works. Do not delete fields during a release.
4. Mobile: halt the staged rollout in Play Console; push the previous build as a new version code.
5. Practise this once on staging before the first production release.

## Drills

Run each before the first production release, then every three months. Record the date,
who ran it and how long it took. Steps are in [MONITORING.md](MONITORING.md).

| Drill | Last run | By | Time taken | Notes |
| --- | --- | --- | --- | --- |
| Roll back `haemnet-api-staging` to an earlier commit (Render > Manual Deploy > Deploy a specific commit) and back | | | | |
| Restore an Atlas backup into `haemnet_staging` | | | | |
| Uptime alert reaches the team chat (pause staging, wait for the alert) | | | | |
| Halt a staged rollout in Play Console (closed track) | | | | |
