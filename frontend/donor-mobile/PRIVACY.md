# HaemNet Donor: data and privacy

What the donor app collects, why, and where it goes.

| Data | Why | Where it is stored | Shared with |
| --- | --- | --- | --- |
| Phone number | Your donor identity; hospitals' AI voice calls | HaemNet server (MongoDB); on the phone | The hospital that raises a request you are matched to, only while that request is open |
| Email address | Sending your sign-in codes | HaemNet server, linked to your phone number; sent to Brevo to deliver each code | Brevo (email delivery only). Never shown to hospitals |
| Name, blood group, call language | Matching you to requests and speaking to you in your language | HaemNet server and on the phone | Hospitals see name and blood group for requests you are matched to |
| Location (while the app is open) | Finding hospitals within 10 km | HaemNet server stores one point (your registered location) | Never shown to hospitals as coordinates; only the distance |
| Profile photo | Your own profile screen | Only on your phone; never uploaded | Nobody |
| Sign-in token | Keeping you signed in | Android Keystore through Expo SecureStore | Nobody |
| Donation history | Your recovery countdown | Server stores your last donation date; the list is on your phone | The hospital that recorded the donation |

Rules the app follows:

- No background location. Location is read only when you tap "Use my current
  location" or confirm a typed area.
- No microphone access.
- Sign-in codes and tokens are never written to logs; email addresses are logged masked (u***@gmail.com).
- Deleting your profile in the app removes your donor record and the linked
  email from the server, and clears the data stored on the phone.
- Signing out removes the sign-in token from the phone.
