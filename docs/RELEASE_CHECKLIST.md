# Release checklist

Tick every box in the PR description before tagging a release.

## Before tagging
- [ ] CI is green on the pull request (backend, frontend, website)
- [ ] `pip-audit` reviewed; no new high severity finding without a written reason
- [ ] `/security-review` run on the diff
- [ ] Deployed to **staging** (separate Render service and database) and the test list below passed there
- [ ] Migrations or new env vars listed in the PR and set on staging, then production
- [ ] Release notes written (what changed for hospitals, donors, admins)

## Staging test list
- [ ] Hospital signs up, verifies email, uploads a document, sees "under review"
- [ ] Admin approves it; the hospital reaches the dashboard
- [ ] Hospital sends a dispatch (confirm step shown); a test donor receives a real call
- [ ] Donor says yes then confirms: dashboard shows accepted. Donor says no: declined. Silence: not accepted
- [ ] Donation logged; donor cooldown starts
- [ ] Suspended hospital cannot dispatch; reinstated hospital can
- [ ] Staff login works; removed staff is signed out
- [ ] Contact form delivers an email; Turnstile blocks a bot
- [ ] Hospital export and deletion work; deletion page link works

## Release
- [ ] Tag the commit (`vX.Y.Z`), deploy production only from the tag
- [ ] Watch Sentry and `/api/health/deep` for 30 minutes
- [ ] Mobile: EAS production build (AAB), version code bumped, uploaded to the closed or production track

## Rollback
1. Redeploy the previous tag on Render and Vercel (both keep deploy history).
2. If a new env var caused it, unset it and redeploy.
3. Database changes are additive (new optional fields), so an older backend still works. Do not delete fields during a release.
4. Mobile: halt the staged rollout in Play Console; push the previous build as a new version code.
5. Practise this once on staging before the first production release.

## Backups
Confirm an Atlas backup can be restored into the staging database, and record the date it was tested here: ____
