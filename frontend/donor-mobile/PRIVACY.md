# HaemNet Donor: data and privacy

What the donor app collects, why, and where it goes.

| Data | Why | Where it is stored | Shared with |
| --- | --- | --- | --- |
| Phone number | Your donor identity; hospitals' AI voice calls | HaemNet server (MongoDB); on the phone | The hospital that raises a request you are matched to, only while that request is open |
| Password | Signing in | HaemNet server stores only a bcrypt hash, never the password itself | Nobody |
| Name, blood group, call language | Matching you to requests and speaking to you in your language | HaemNet server and on the phone | Hospitals see name and blood group for requests you are matched to |
| Location (while the app is open) | Finding hospitals within 10 km | HaemNet server stores one point (your registered location) | Never shown to hospitals as coordinates; only the distance |
| Profile photo | Your own profile screen | Only on your phone; never uploaded | Nobody |
| Sign-in token | Keeping you signed in | Android Keystore through Expo SecureStore | Nobody |
| Donation history | Your recovery countdown | Server stores your last donation date; the list is on your phone | The hospital that recorded the donation |

Rules the app follows:

- No background location. Location is read only when you tap "Use my current
  location" or confirm a typed area.
- No microphone access.
- Passwords and sign-in tokens are never written to logs.
- Deleting your profile in the app removes your donor record and your
  password from the server, and clears the data stored on the phone.
- Signing out removes the sign-in token from the phone.
