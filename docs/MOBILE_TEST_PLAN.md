# Donor app test plan

Run on a **staging** build (Actions > Donor app release > profile `staging`) before every
donor app release, on the three phones below. Use test phone numbers the team owns, never
real donors. Record results in a copy of the tables in the release PR; a release needs every
row to pass or a written reason.

## Devices (at least three real Android phones)

| Slot | Example | Why |
| --- | --- | --- |
| Low-end | 2 to 3 GB RAM, Android 10 to 12 (Redmi A-series, Samsung Galaxy A0x/M0x, itel, Lava) | Most donors; catches slow start, memory kills and layout overflow |
| Mid-range, current Android | Android 14 or 15 (Samsung A-series, Redmi Note, realme) | Notification permission prompt (Android 13+), battery savers |
| Large font or small screen | Any phone with Settings > Display > Font size at maximum | Text wrapping in Hindi and Tamil |

Record for each: model, Android version, RAM, app version and build number.

| Phone | Model | Android | RAM | Build | Tester | Date |
| --- | --- | --- | --- | --- | --- | --- |
| Low-end | | | | | | |
| Mid-range | | | | | | |
| Large font | | | | | | |

## Core flows

| # | Flow | Steps | Expected | Low | Mid | Font |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Install and first start | Install the APK, open | Sign-in screen in under 5 s on the low-end phone; no blank screen | | | |
| 2 | Sign up with code | Create account, Send code, enter the SMS code | Code arrives; wrong code refused; right code creates the account | | | |
| 3 | Consent | Join without ticking the consent box | Blocked with a clear message; privacy policy link opens the website | | | |
| 4 | Join | Fill the profile with GPS location, tick consent, Join | Dashboard shows; profile card shows Automated calls On | | | |
| 5 | Location typed | Edit profile, type an area, Confirm this area | Area found, or a clear message to add the city and postcode | | | |
| 6 | Sign out and in | Sign out, sign in again | Dashboard returns with the same profile | | | |
| 7 | Delete account | Profile card > Delete > confirm | Removed; joining again starts from an empty form | | | |

## Push alerts

| # | Flow | Steps | Expected | Low | Mid | Font |
| --- | --- | --- | --- | --- | --- | --- |
| 8 | Permission | After joining | Android asks for notifications once; profile shows Request alerts On | | | |
| 9 | Alert, app closed | Close the app; raise a staging dispatch for the test donor's group within 10 km | Alert "Urgent: <group> blood needed" with the distance within a minute, with sound, even on the lock screen | | | |
| 10 | Tap the alert | Tap it | App opens on the dashboard with that request outlined | | | |
| 11 | Alert, app open | Keep the app open, raise a dispatch | Banner shows and the request appears without pulling to refresh | | | |
| 12 | Permission denied | Deny notifications, then tap Turn on request alerts | Asks again, or explains how to allow it in Settings | | | |
| 13 | Sign out stops alerts | Sign out, raise a dispatch | No alert on this phone | | | |
| 14 | Battery saver | Turn on battery saver / "deep sleep" for the app, raise a dispatch | Note whether the alert arrives and how late; the call must still arrive | | | |

## Saying yes or no

| # | Flow | Steps | Expected | Low | Mid | Font |
| --- | --- | --- | --- | --- | --- | --- |
| 15 | Health check pass | I can donate > answer all six safely > Yes, I am ready to donate | Request accepted; trip card with directions; dashboard shows accepted | | | |
| 16 | Health check fail | Answer "Yes" to alcohol in the last 24 hours | "Please do not donate today" with the reason; only "Let the hospital know" is offered; it declines | | | |
| 17 | Incomplete | Leave one question unanswered | Confirm button disabled; "Answer every question" shown | | | |
| 18 | Recovering | Log a donation for the donor on staging, then open a request | Recovery message with days left; only "Let the hospital know" | | | |
| 19 | Decline | I can't make it | Request removed; thank-you message | | | |
| 20 | Already filled | Accept a request another donor filled first | "already been filled or closed" | | | |

## Availability

| # | Flow | Steps | Expected | Low | Mid | Font |
| --- | --- | --- | --- | --- | --- | --- |
| 21 | Pause a week | Profile card > 1 week | Shows "Calls paused until <date>"; a staging dispatch does not call or alert this donor | | | |
| 22 | Resume early | I am available again | Calls On; the next dispatch reaches the donor | | | |
| 23 | Pause all calls | Pause automated calls | Automated calls: Paused; no calls until resumed | | | |

## Offline and slow network

| # | Flow | Steps | Expected | Low | Mid | Font |
| --- | --- | --- | --- | --- | --- | --- |
| 24 | Offline start | Airplane mode, open the app | Offline banner; saved profile and saved requests with their age; no blank screen, no join form | | | |
| 25 | Reconnect | Turn airplane mode off | Banner goes; requests refresh by themselves | | | |
| 26 | Sleeping server | Open the app after staging has slept 15+ minutes | Loading card mentions waking up; dashboard appears within about a minute | | | |
| 27 | Answer offline | Airplane mode, tap I can donate and confirm | Clear "could not send" message; nothing recorded | | | |
| 28 | Slow 2G | Developer options or a hotspot throttled to 2G | Every screen shows a spinner or message while waiting | | | |

## Languages

| # | Flow | Steps | Expected | Low | Mid | Font |
| --- | --- | --- | --- | --- | --- | --- |
| 29 | Switch | Pick हिन्दी, then தமிழ் on sign-in and on the profile card | All text changes at once, including alerts and errors; choice kept after restart | | | |
| 30 | Follows call language | Fresh install, join with AI call language Tamil, without picking an app language | App switches to Tamil | | | |
| 31 | Layout | Walk every screen in Hindi and Tamil at the largest font | No cut-off or overlapping text; buttons still tappable | | | |
| 32 | Dates | Recovery date and pause end date in each language | Readable date in that language | | | |
| 33 | Review | A native Hindi and a native Tamil speaker read every screen | Note any wording to change in `components/i18n/hi.js` / `ta.js` | | | |

## Privacy and safety

| # | Check | Expected | Result |
| --- | --- | --- | --- |
| 34 | Sentry test error (staging DSN) | Event arrives with no phone number, token or name in it | |
| 35 | Permissions screen (Android Settings > Apps) | Only Location, Camera (optional), Notifications | |
| 36 | `adb logcat` during sign-in, alert and accept | No phone numbers, tokens or transcripts in logs | |
