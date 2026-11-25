# Monitoring, alerts and backup drills

Owner: Role 3. The goal is simple: if donors cannot be reached, a person on the team knows
within five minutes, before a hospital calls to say so.

## What to watch

Use one free uptime service (UptimeRobot or Better Stack). Check every 5 minutes (1 minute on
paid plans), alert after 2 failures in a row, from at least two regions.

| Monitor | URL | Type | Healthy when | Severity |
| --- | --- | --- | --- | --- |
| API | `https://<api>/api/health` | Keyword | Body contains `"status":"healthy"` | S1 |
| API deep | `https://<api>/api/health/deep` | Keyword | Body contains `"status":"healthy"` (database, storage, Sarvam, Redis) | S1 |
| Dashboard | `https://<dashboard>/` | HTTP | Status 200 | S2 |
| Website | `https://haemnet.in/` and `/privacy` | HTTP | Status 200 (Play rejects the app if the privacy link is down) | S2 |
| API staging | `https://haemnet-api-staging.onrender.com/api/health` | Keyword | `"status":"healthy"`; alert to chat only, no phone call | S3 |

Both health endpoints answer 200 even when degraded, so a plain status check misses a
database outage. Always use the keyword check.

The deep check calls Sarvam and the storage bucket. Run it every 5 minutes, not every minute,
to stay well inside their rate limits.

**Free Render plans sleep** after 15 minutes without traffic. The uptime check keeps
production awake. That is useful (a donor's first request is fast), but it counts toward
Render's free hours. Leave staging to sleep: its monitor tolerates a slow first answer (set
the timeout to 60 s).

## Where alerts go

1. Team chat channel `#haemnet-alerts` (Slack or Discord webhook, or Telegram bot) for every
   monitor.
2. A phone call or SMS from the uptime service to the on-call person, for S1 monitors only.
   Name that person in the [RUNBOOK.md](RUNBOOK.md) contact table.
3. Sentry: add the same channel as an alert action for "new issue" and for "crash-free
   sessions below 99%" on the donor app project.

A status page from the uptime service (`status.haemnet.in`) lets hospitals see an outage
without calling. Show API and Dashboard only.

When an alert fires, follow [RUNBOOK.md](RUNBOOK.md), "First five minutes".

## Donor app health

| Signal | Where | Act when |
| --- | --- | --- |
| Crash-free users | Sentry > Releases, and Play Console > Android vitals | Below 99%, or Play's "bad behaviour" threshold (1.09% user-perceived crash rate) |
| ANRs (app not responding) | Play Console > Android vitals | Above 0.47%, Play's threshold |
| Push alerts reaching donors | API logs: `push` lines with receipt errors | Many `DeviceNotRegistered` after a release means tokens broke |
| Ratings and reviews | Play Console > Ratings | Any one-star review that mentions missed alerts or calls |

During a staged rollout, check these daily. Halt the rollout (RELEASING.md, Rolling back)
if crash-free users drop by more than 0.5 percentage points from the previous version.

## Backup restore drill

Atlas backups only count once a restore has worked. Run this on staging before the first
production release, then every three months, and record it in
[RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) under Drills.

On the free M0 tier Atlas does not take snapshots, so use `mongodump` instead:

```bash
# 1. Export production (read-only user). Keep the file off shared drives: it holds donor data.
mongodump --uri "$PROD_READONLY_URI" --db haemnet --gzip --archive=haemnet-$(date +%F).gz

# 2. Restore into staging under the staging database name.
mongorestore --uri "$STAGING_URI" --gzip --archive=haemnet-$(date +%F).gz \
  --nsFrom 'haemnet.*' --nsTo 'haemnet_staging.*' --drop

# 3. Delete the archive when done.
shred -u haemnet-$(date +%F).gz
```

On M10 and above, use Atlas > Backup > Restore > "Restore to a different cluster or
database", targeting `haemnet_staging`.

Then check:

- [ ] `https://haemnet-api-staging.onrender.com/api/health/deep` reports `database: true`.
- [ ] Sign in to the staging dashboard with a hospital account and see its dispatch history.
- [ ] The donor count on the admin panel matches production at the time of the export.
- [ ] Note how long the restore took. That is the real recovery time if production is lost.

Restored staging holds real donor phone numbers. Before raising any test dispatch, set
`TWILIO_*` on staging to test credentials and set
`PUSH_REQUEST_ALERTS=false`, so no real donor is called or alerted. Drop the restored database
when the drill is done.

## Alert drill

Prove the alert path works at least once:

1. Pause the `haemnet-api-staging` service on Render (Settings > Suspend).
2. Wait for the staging monitor to alert in the team chat. Note the delay.
3. Resume the service and wait for the recovery message.

Record it under Drills in [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md).
