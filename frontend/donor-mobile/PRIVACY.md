# HaemNet Donor: data and privacy

This describes the current data flow in the donor app and its backend.
The app uses phone/password accounts; phone ownership is not verified by OTP.

| Data | Purpose | Storage or processing |
| --- | --- | --- |
| Phone number | Sign-in identifier, matching requests, telephone outreach | Backend MongoDB, local session/profile; Twilio when calls or SMS are sent |
| Password | Account authentication | Sent to the backend for hashing/verification; a bcrypt hash is stored in `donor_logins` |
| Name, blood group, preferred language | Profile, recruitment, localized calls | Backend and local profile; matched-request views expose selected donor details to the hospital |
| Registered location | Search for donors within a default 10 km radius | One MongoDB GeoJSON point; hospital views use distance rather than live donor coordinates |
| Profile photo | Personal profile display | Local device image; the current app does not upload it |
| Sign-in token | Authenticated requests and restoring a session | Expo SecureStore on supported devices; web preview falls back to app storage |
| Donation information | Last donation date, cooldown, request fulfillment | Backend records; the donor's displayed donation log is also maintained locally |
| Call audio | Speech recognition and conversation | Twilio streams audio to the backend; Sarvam processes speech/translation/TTS |
| Transcribed replies and conversation | AI interpretation and confirmation | In AI mode, bounded recent conversation is sent to Sarvam's chat API; current speech code also logs transcripts on the backend |

## Device permissions

- Location is requested when the donor chooses GPS location or confirms a
  typed area. The app does not collect continuous background location.
- Camera/photo access is optional for the profile photo.
- The app blocks microphone permission. AI conversations use ordinary
  telephone calls through Twilio, not microphone recording inside the app.

## Voice decisions

In AI mode, initial agreement triggers a separate confirmation question.
Silence, uncertainty, or provider failure does not count as acceptance.
In-app accept/decline buttons are a separate response path. The backend can
be configured to use the retained legacy keyword interpreter instead.

## Sign-out and deletion

Signing out removes the app's sign-in session. Deleting a donor profile removes
the donor profile and login credential from the backend and clears the app's
profile-related local data. Historical dispatch/call records and provider
records are separate from that profile operation; the repository does not
define a complete retention or provider-deletion policy.

Do not treat this implementation description as a claim that telephone
ownership, transcript retention, or all production privacy requirements have
been independently verified.
