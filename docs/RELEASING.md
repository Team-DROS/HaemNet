# Releasing HaemNet

Owner: Role 3 (mobile, release and quality). Nothing reaches hospitals or donors without
passing CI, the staging test list and a tagged release.

```
pull request ──CI──▶ main ──auto──▶ staging ──test list──▶ tag vX.Y.Z ──CI + approval──▶ production
                                                              tag donor-vX.Y.Z ──▶ EAS build ──▶ Play internal (draft)
```

## The pieces

| Stage | What runs | Where it is defined |
| --- | --- | --- |
| Pull request | Backend ruff, mypy, pytest (with MongoDB), pip-audit; dashboard lint and build; donor app lint, tests and Android bundle; website links | `.github/workflows/main.yml`, `frontend.yml` |
| Merge to `main` | Render deploys `haemnet-api-staging` and `haemnet-dashboard-staging` | `render.yaml` (`autoDeploy: true`, `branch: main`) |
| Tag `vX.Y.Z` | CI again on the tagged commit, approval, Render deploy hooks at that commit, wait for `/api/health` to report it, release notes | `.github/workflows/release.yml` |
| Tag `donor-vX.Y.Z` | Donor app lint and tests, EAS production build (AAB), submit to Play internal track as a draft | `.github/workflows/donor-app-release.yml` |

Production services have `autoDeploy: false`: a merge never changes production by itself.

## One-time setup (repository admin)

1. **Protect `main`** (Settings > Branches > Add rule, or Rulesets):
   - Require a pull request before merging, with 1 approval, and dismiss stale approvals.
   - Require status checks: `test` (Python Backend CI), `Hospital dashboard lint and build`,
     `Donor app lint and tests`, `Public website links`.
   - Require branches to be up to date before merging. Block force pushes and deletion.
   - Optional: add a `CODEOWNERS` file so each role reviews its own folders.
2. **Production environment** (Settings > Environments > New environment `production`):
   add required reviewers (at least one person other than the releaser) and allow only
   tags matching `v*` to deploy.
3. **Secrets and variables** (Settings > Secrets and variables > Actions):

   | Name | Kind | Where to get it |
   | --- | --- | --- |
   | `RENDER_DEPLOY_HOOK_API` | secret | Render > `haemnet-api` > Settings > Deploy Hook |
   | `RENDER_DEPLOY_HOOK_DASHBOARD` | secret | Render > `haemnet-dashboard` > Settings > Deploy Hook |
   | `PRODUCTION_API_URL` | variable | Public API origin, for example `https://api.haemnet.in` (defaults to `https://haemnet-api.onrender.com`) |
   | `EXPO_TOKEN` | secret | expo.dev > Account settings > Access tokens (a robot user is best) |

4. **Render staging**: after syncing the blueprint, fill in the `sync: false` values for the
   two `-staging` services. Use the same Atlas cluster with database `haemnet_staging`
   (or a separate free cluster), and Twilio test credentials or a single team phone.
5. **EAS**: `eas env:create --name GOOGLE_SERVICES_JSON --type file --visibility secret` with
   the Firebase `google-services.json` (push on Android), upload the FCM V1 service account
   key with `eas credentials`, and upload the Google Play service account key for submits.
   Optional: `EXPO_PUBLIC_SENTRY_DSN` per profile, and `SENTRY_ORG`, `SENTRY_PROJECT`,
   `SENTRY_AUTH_TOKEN` for readable crash stack traces.

## Releasing the backend and dashboard

1. Merge the changes. Wait for staging to deploy, then run the staging part of
   [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md). Copy the checklist into the release PR or issue.
2. Pick the version: `MAJOR.MINOR.PATCH` (a breaking API change bumps MINOR until 1.0 of the
   public API; fixes bump PATCH).
3. Tag the commit that passed on staging and push the tag:
   ```bash
   git fetch origin main
   git tag -a v1.4.0 -m "v1.4.0" <sha-that-passed-on-staging>
   git push origin v1.4.0
   ```
4. Approve the `production` deployment in the Actions run. The run fails if production
   does not report the tagged commit as healthy within 20 minutes.
5. Watch Sentry and `/api/health/deep` for 30 minutes (checklist, Release section).

## Releasing the donor app

1. In a PR, bump `expo.version` in `frontend/donor-mobile/app.json` (and the version in
   `package.json`). The Android `versionCode` is managed by EAS (`appVersionSource: remote`).
2. Test a staging build on real phones: Actions > Donor app release > Run workflow >
   profile `staging`. Install the APK from the EAS build page and run
   [MOBILE_TEST_PLAN.md](MOBILE_TEST_PLAN.md).
3. After merge, tag and push: `git tag -a donor-v1.3.0 -m "Donor app 1.3.0" && git push origin donor-v1.3.0`.
   The workflow refuses a tag that does not match `app.json`.
4. The AAB lands in Play Console > Internal testing as a **draft**. Add release notes
   (English, Hindi, Tamil) and roll it out to internal, then promote to Closed testing
   (or run the workflow by hand with submit `closed-test`), then to Production with a
   staged rollout (start at 20%).

The very first upload of a new app must be done by hand in Play Console (Google does not
allow the API to create the first release). Download the AAB from the EAS build page.

## Rolling back

| What | How | Time |
| --- | --- | --- |
| Backend or dashboard | Actions > Release > Run workflow with the previous tag (for example `v1.3.2`). It skips CI and redeploys that commit. Render's own "Rollback" button on the deploy list works too. | ~5 min |
| A bad setting | Unset or fix the environment variable on Render and redeploy the same tag. | ~3 min |
| AI voice misbehaving | `VOICE_INTENT_MODE=legacy` and redeploy (see RUNBOOK.md). | ~3 min |
| Donor app | Play Console > Production > halt the staged rollout. Then build the previous code as a new version (bump PATCH) and release it; Play never accepts a lower version code. | hours |
| Push alerts flooding donors | `PUSH_REQUEST_ALERTS=false` on the API and redeploy. Calls keep working. | ~3 min |

Database changes in this project are additive (new optional fields), so an older backend
keeps working against newer data. Never remove or rename a field in the same release that
stops writing it.

Practise a rollback on staging once before the first production release and record it in
[RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) (Drills).
