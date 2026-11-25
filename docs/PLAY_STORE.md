# Google Play release kit (HaemNet Donor)

Everything needed to fill in Play Console for the donor app. Owner: Role 3. Items marked
**Decide** need the team before the first upload; items marked **Console** are clicks only a
Play Console account owner can do.

## Decisions before the first upload

| | Decision | Recommendation |
| --- | --- | --- |
| **Decide** | Personal or organisation developer account | Organisation if the team can get a D-U-N-S number in time (no 12-tester rule, shows a company name). Otherwise personal, and start the closed test by week 9. |
| **Decide** | Android package name. It **can never change** after the first upload. Today it is `com.pranko007.donormobile` (a personal handle). | Change to `in.haemnet.donor` in `app.json` before the first upload, then run `eas credentials` to create the upload key for it. |
| **Decide** | Expo account that owns the build (`owner` in `app.json` is `umasuthan`) | Move the project to an Expo organisation the whole team can access, or add the team to it. |
| **Decide** | Support email and website on your own domain | `support@haemnet.in`, `https://haemnet.in` |

## Store listing (Main store listing)

**App name** (30 max): `HaemNet: Blood Donor Alerts`

**Short description** (80 max):

| Language | Text |
| --- | --- |
| English (en-IN, default) | Get a call when a hospital near you needs your blood group. Help save a life. |
| Hindi (hi-IN) | पास के अस्पताल को आपके ब्लड ग्रुप की ज़रूरत हो, तो कॉल पाएँ। एक जान बचाएँ। |
| Tamil (ta-IN) | அருகிலுள்ள மருத்துவமனைக்கு உங்கள் இரத்த வகை தேவைப்பட்டால் அழைப்பு பெறுங்கள். |

**Full description, English** (4000 max):

```
When a patient needs blood urgently, every minute counts. HaemNet connects verified hospitals with nearby blood donors in minutes.

HOW IT WORKS
• Join with your mobile number, blood group and area.
• When a hospital within 10 km needs your blood group, you get an alert and a short automated call in English, Hindi or Tamil.
• Say yes on the call or in the app. The hospital sees that you are coming, and the app gives you directions.

BUILT AROUND YOUR HEALTH
• The 56-day recovery window after a donation is tracked for you. You are not called while you recover.
• A quick health check before you say yes, based on India's blood donor selection guidelines. The blood bank still screens every donor.

YOU ARE IN CONTROL
• Away for a few days? Pause calls for 3 days, a week or two weeks. They start again by themselves.
• Pause all automated calls at any time, or delete your account from the app.
• Hospitals see only your blood group and distance until you accept a request.

MADE FOR INDIA
• The whole app in English, हिन्दी and தமிழ்.
• Works on low-cost phones and poor connections, and shows what it saved while you are offline.

HaemNet helps hospitals find willing donors. It is not a medical service and does not test or cross-match blood.

Privacy policy: https://haemnet.in/privacy
```

**Full description, Hindi**:

```
जब किसी मरीज़ को तुरंत खून की ज़रूरत होती है, तो हर मिनट कीमती होता है। HaemNet सत्यापित अस्पतालों को मिनटों में पास के रक्तदाताओं से जोड़ता है।

यह कैसे काम करता है
• अपने मोबाइल नंबर, ब्लड ग्रुप और इलाके के साथ जुड़ें।
• जब 10 किमी के भीतर किसी अस्पताल को आपके ब्लड ग्रुप की ज़रूरत होती है, तो आपको अलर्ट और अंग्रेज़ी, हिन्दी या तमिल में एक छोटी स्वचालित कॉल मिलती है।
• कॉल पर या ऐप में हाँ कहें। अस्पताल देख पाता है कि आप आ रहे हैं, और ऐप आपको रास्ता दिखाता है।

आपकी सेहत सबसे पहले
• रक्तदान के बाद 56 दिनों की रिकवरी अवधि का हिसाब हम रखते हैं। उस दौरान आपको कॉल नहीं आती।
• हाँ कहने से पहले एक छोटी स्वास्थ्य जाँच, भारत के रक्तदाता चयन दिशानिर्देशों पर आधारित। ब्लड बैंक फिर भी हर रक्तदाता की जाँच करता है।

नियंत्रण आपके हाथ में
• कुछ दिनों के लिए बाहर हैं? 3 दिन, 1 हफ़्ते या 2 हफ़्ते के लिए कॉल रोकें। ये अपने आप फिर शुरू हो जाती हैं।
• कभी भी सभी स्वचालित कॉल रोकें, या ऐप से अपना खाता हटाएँ।
• जब तक आप अनुरोध स्वीकार नहीं करते, अस्पताल सिर्फ़ आपका ब्लड ग्रुप और दूरी देखते हैं।

HaemNet अस्पतालों को इच्छुक रक्तदाता ढूँढने में मदद करता है। यह कोई चिकित्सा सेवा नहीं है और खून की जाँच या क्रॉस-मैचिंग नहीं करता।

गोपनीयता नीति: https://haemnet.in/privacy
```

**Full description, Tamil**:

```
ஒரு நோயாளிக்கு அவசரமாக இரத்தம் தேவைப்படும்போது, ஒவ்வொரு நிமிடமும் முக்கியம். HaemNet சரிபார்க்கப்பட்ட மருத்துவமனைகளை அருகிலுள்ள இரத்த தானம் செய்பவர்களுடன் நிமிடங்களில் இணைக்கிறது.

இது எப்படி வேலை செய்கிறது
• உங்கள் மொபைல் எண், இரத்த வகை மற்றும் பகுதியுடன் சேருங்கள்.
• 10 கி.மீ.க்குள் உள்ள மருத்துவமனைக்கு உங்கள் இரத்த வகை தேவைப்படும்போது, உங்களுக்கு ஒரு அறிவிப்பும், ஆங்கிலம், இந்தி அல்லது தமிழில் ஒரு சிறிய தானியங்கி அழைப்பும் வரும்.
• அழைப்பிலோ செயலியிலோ சம்மதம் சொல்லுங்கள். நீங்கள் வருவதை மருத்துவமனை பார்க்கும், செயலி உங்களுக்கு வழி காட்டும்.

உங்கள் ஆரோக்கியம் முதலில்
• தானம் செய்த பிறகு 56 நாள் மீட்பு காலத்தை நாங்கள் கணக்கிடுகிறோம். அந்த நேரத்தில் அழைப்புகள் வராது.
• சம்மதம் சொல்வதற்கு முன், இந்திய இரத்த தானம் வழிகாட்டுதல்களின் அடிப்படையில் ஒரு சிறிய உடல்நலச் சரிபார்ப்பு. இரத்த வங்கி ஒவ்வொருவரையும் மீண்டும் பரிசோதிக்கும்.

கட்டுப்பாடு உங்கள் கையில்
• சில நாட்கள் வெளியே இருக்கிறீர்களா? 3 நாட்கள், 1 வாரம் அல்லது 2 வாரங்களுக்கு அழைப்புகளை நிறுத்துங்கள். அவை தானாகவே மீண்டும் தொடங்கும்.
• எப்போது வேண்டுமானாலும் எல்லா தானியங்கி அழைப்புகளையும் நிறுத்தலாம், அல்லது செயலியிலிருந்தே உங்கள் கணக்கை நீக்கலாம்.
• நீங்கள் ஒரு கோரிக்கையை ஏற்கும் வரை, மருத்துவமனைகள் உங்கள் இரத்த வகையையும் தூரத்தையும் மட்டுமே பார்க்கும்.

HaemNet மருத்துவமனைகள் விருப்பமுள்ள இரத்த தானம் செய்பவர்களைக் கண்டறிய உதவுகிறது. இது மருத்துவ சேவை அல்ல; இரத்தப் பரிசோதனையோ குறுக்குப் பொருத்தமோ செய்வதில்லை.

தனியுரிமைக் கொள்கை: https://haemnet.in/privacy
```

Have a native Hindi and a native Tamil speaker read both before publishing.

**App category**: Medical. **Tags**: Blood donation, Health. **Contact**: support email, website
`https://haemnet.in`. **Privacy policy URL**: `https://haemnet.in/privacy`.

## Graphics

| Asset | Requirement | File |
| --- | --- | --- |
| App icon | 512 x 512 PNG | [play-store/icon-512.png](play-store/icon-512.png) |
| Feature graphic | 1024 x 500 PNG or JPG, no transparency | [play-store/feature-graphic.png](play-store/feature-graphic.png) |
| Phone screenshots | 4 to 8, PNG or JPG, 9:16, at least 1080 px on the short side for promotion | Take on a real phone from a **staging** build with test data (no real donor names or numbers) |

Screenshot list (caption in brackets, add the same set per language if you can):
1. Request card with the distance and "I can donate" [A hospital near you needs your blood group]
2. Health check before saying yes [A quick health check first]
3. Trip card with directions [The hospital knows you are coming]
4. Readiness card with the recovery countdown [Your recovery is tracked for you]
5. Profile card with the pause options [Away? Pause calls for a week]
6. Sign-in screen in हिन्दी or தமிழ் [In English, हिन्दी and தமிழ்]
7. Lock screen with an alert [Alerts even when the app is closed]

## App content (Policy > App content)

**Privacy policy**: `https://haemnet.in/privacy`. Before submitting, make sure the policy
mentions push notification tokens, the optional crash reports and that health-check answers
stay on the phone (see "Data the app handles" in `frontend/donor-mobile/PRIVACY.md`).

**App access**: some features need an account. Give reviewers a test donor on production
with a password, and say a texted code is required if `DONOR_OTP_REQUIRED=true` (then give a
number the team can read codes for, or turn it off for the review window).

**Ads**: No ads.

**Content rating** (IARC questionnaire): category "Reference, news, or educational" or
"All other app types"; no violence, sexual content, gambling, drugs or user-to-user chat.
Users share location with hospitals (answer Yes to "shares the user's physical location
with other users" only if hospitals count as users in the form; the app shows hospitals a
distance, not coordinates). Expected rating: Everyone / 3+.

**Target audience**: 18 and over only (donors must be adults). This keeps the app out of
the Families programme.

**Health apps declaration**: the app connects donors with hospitals and tracks a
recovery window. It does not diagnose, treat or give medical advice, and is not a medical
device. Choose the categories that describe donation and health information management, not
"medical device" or "clinical decision support".

**Government apps**: No. **Financial features**: None. **News app**: No.

**Account deletion**: in-app (Profile > Delete) and on the web at
`https://haemnet.in/delete-account`.

## Data safety form

Answers match the current code (see `frontend/donor-mobile/PRIVACY.md`). Re-check them
whenever a release adds a field, an SDK or a permission.

- Does the app collect or share any of the required user data types? **Yes**
- Is all user data encrypted in transit? **Yes** (HTTPS only; release builds refuse plain HTTP)
- Do you provide a way for users to request that their data be deleted? **Yes** (in-app and web)

| Data type | Collected | Shared | Optional? | Purposes | Notes |
| --- | --- | --- | --- | --- | --- |
| Location > Approximate location | Yes | No | Required | App functionality | One saved point to find donors within 10 km; hospitals see distance only |
| Location > Precise location | Yes | No | Optional (can type an area instead) | App functionality | GPS only while the app is open; no background location |
| Personal info > Name | Yes | Yes (with the hospital, after the donor accepts) | Required | App functionality, Account management | |
| Personal info > Phone number | Yes | Yes (with the hospital, after the donor accepts) | Required | App functionality, Account management | Sign-in and the AI call |
| Health and fitness > Health info | Yes | Yes (blood group, with matched hospitals) | Required | App functionality | Blood group, last donation date. Health-check answers are **not** collected: they never leave the phone |
| App activity > App interactions | Yes | Yes (accept or decline goes to that hospital) | Required | App functionality | |
| App info and performance > Crash logs, Diagnostics | Yes, only in builds with a Sentry DSN | No | Required when on | App functionality, Analytics | Scrubbed of phone numbers and tokens before sending |
| Device or other IDs | Yes | No | Optional (alerts can be turned off) | App functionality | Expo push token, to deliver request alerts |
| Photos | No | | | | The profile photo stays on the phone |
| Audio | No | | | | AI calls are ordinary phone calls, not recorded by the app |

Service providers that process data on HaemNet's behalf (Twilio, Sarvam AI, Expo push,
MongoDB Atlas, Sentry, Render) do not count as "sharing" in this form.

## Permissions and their reasons

| Permission | Why (paste where Play asks) |
| --- | --- |
| `ACCESS_FINE_LOCATION`, `ACCESS_COARSE_LOCATION` | "HaemNet uses your location only while the app is open, when you choose 'Use my current location' or confirm a typed area, to match you with hospitals within 10 km that need your blood group. Location is never collected in the background." No background location declaration is needed (it is blocked in `app.json`). |
| `POST_NOTIFICATIONS` | Alerts when a nearby hospital needs your blood group. |
| `CAMERA` | Optional profile photo; the photo stays on the phone. |

`RECORD_AUDIO`, background location, overlay and storage permissions are blocked in `app.json`.

## Closed test (personal accounts: at least 12 testers for 14 days in a row)

Start by week 9 so production access is possible by week 11.

1. **Console**: create a Google Group (for example `haemnet-testers@googlegroups.com`) and
   add 15 to 20 testers. Aim above 12: anyone who opts out resets nothing, but you need 12
   opted in for the whole 14 days.
2. **Console**: Testing > Closed testing > create track, add the group, copy the opt-in link.
3. Upload the first AAB by hand (later ones: `donor-vX.Y.Z` tag, or Actions > Donor app
   release > submit `closed-test`).
4. Send testers the opt-in link and [the tester guide](#tester-guide) below. Ask them to keep
   the app installed and open it every day or two.
5. Keep a list of testers and the date each opted in. Day 14 counts from when the 12th
   tester opted in.
6. After 14 days, **Console**: Dashboard > Apply for production, with the answers about what
   testers found and what changed.

### Tester guide

> Thanks for testing HaemNet. 1) Open the opt-in link on your Android phone and join the test.
> 2) Install "HaemNet: Blood Donor Alerts" from Play. 3) Create an account with your own
> number and join with any blood group; this is a test network, no real hospital will call
> you. 4) Keep the app installed for 14 days and open it every couple of days. 5) Tell us
> anything confusing or broken at support@haemnet.in, with your phone model. Thank you!

## Pre-launch checks

- Play Console > Testing > Pre-launch report: fix crashes and accessibility warnings
  (touch targets, contrast) before promoting.
- Android vitals after release: user-perceived crash rate below 1.09% and ANR rate below
  0.47% (Play's bad-behaviour thresholds).
