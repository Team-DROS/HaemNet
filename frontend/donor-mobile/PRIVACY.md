# HaemNet Donor: data and privacy

This describes the current data flow in the donor app and its backend.
The app uses phone/password accounts. When the server requires it (`DONOR_OTP_REQUIRED`), sign-up first verifies the number with a one-time code sent by SMS; otherwise phone ownership is not verified.

| Data | Purpose | Storage or processing |
| --- | --- | --- |
| Phone number | Sign-in identifier, matching requests, telephone outreach | Backend MongoDB, local session/profile; Twilio when calls or SMS are sent |
| Password | Account authentication | Sent to the backend for hashing/verification; a bcrypt hash is stored in `donor_logins` |
| Consent to automated calls | Recorded when you join, with the time, so we only call donors who agreed | Backend MongoDB; you can pause calls in the app at any time (stored as an opt-out and respected by matching) |
| Name, blood group, preferred language | Profile, recruitment, localized calls | Backend and local profile; matched-request views expose selected donor details to the hospital |
| Registered location | Search for donors within a default 10 km radius | One MongoDB GeoJSON point; hospital views use distance rather than live donor coordinates |
| Profile photo | Personal profile display | Local device image; the current app does not upload it |
| Sign-in token | Authenticated requests and restoring a session | Expo SecureStore on supported devices; web preview falls back to app storage |
| Donation information | Last donation date, cooldown, request fulfillment | Backend records; the donor's displayed donation log is also maintained locally |
| Call audio | Speech recognition and conversation | Twilio streams audio to the backend; Sarvam processes speech/translation/TTS |
| Transcribed replies and conversation | AI interpretation and confirmation | In AI mode, bounded recent conversation is sent to Sarvam's chat API; transcripts are not written to application logs |
| Push token | Sending alerts about nearby requests to this phone | Backend MongoDB (one phone per token; set after joining, cleared on sign out or when Expo reports the app was uninstalled). Alerts go through Expo's push service and Google Firebase Cloud Messaging. Logs show only the last 4 characters |
| Request alert content | Telling the donor a request is near | Blood group, units, urgency and distance only. No hospital name, patient detail or donor detail is in the alert |
| Health check answers | Helping the donor decide whether it is safe to donate today | **Stay on the phone and are not saved or sent.** Only the resulting accept or decline reaches the backend |
| Pause until date | Skipping the donor in matching for a few days | Backend MongoDB (`calls_paused_until`, at most 30 days ahead) |
| App language | Showing the app in English, Hindi or Tamil | Local app storage only |
| Saved profile and requests (offline) | Showing the last known data without a connection | Local app storage on the phone, per account; requests older than 6 hours are not shown; removed on sign out and account deletion |
| Crash reports | Finding and fixing crashes | Sentry, only when a DSN is configured for the build. Before sending, the app removes phone numbers, sign-in and push tokens and JWTs from messages, URLs and breadcrumbs, and drops console logs. No name, location or health answers are attached |

## Device permissions

- Location is requested when the donor chooses GPS location or confirms a
  typed area. The app does not collect continuous background location.
- Camera/photo access is optional for the profile photo.
- Notifications (Android 13 and newer) are requested once after joining. Saying
  no only turns off app alerts; calls still arrive.
- The app blocks microphone permission. AI conversations use ordinary
  telephone calls through Twilio, not microphone recording inside the app.

## Voice decisions

In AI mode, initial agreement triggers a separate confirmation question.
Silence, uncertainty, or provider failure does not count as acceptance.
In-app accept/decline buttons are a separate response path. The backend can
be configured to use the retained legacy keyword interpreter instead.

## Sign-out and deletion

Signing out removes the app's sign-in session and the push token on the server,
so the phone stops receiving alerts. Deleting a donor profile removes
the donor profile and login credential from the backend and clears the app's
profile-related local data. Historical dispatch/call records and provider
records are separate from that profile operation; the repository does not
define a complete retention or provider-deletion policy.

Do not treat this implementation description as a claim that telephone
ownership, transcript retention, or all production privacy requirements have
been independently verified.
