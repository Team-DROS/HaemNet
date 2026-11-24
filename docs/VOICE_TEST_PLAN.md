# Controlled voice test plan

Run with test donor phones (never real donors) on staging. Record every result; a pass needs the exact expected outcome.

| # | Scenario | Say / do | Expected | EN | HI | TA |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Clear yes | "Yes, I can come" then "Yes, I confirm" | accepted | | | |
| 2 | Clear no | "No, I cannot donate" | declined | | | |
| 3 | Maybe | "Maybe", "I am not sure" | not accepted; asked again, then unconfirmed | | | |
| 4 | Silence | say nothing | not accepted, no answer recorded as yes | | | |
| 5 | Yes then no | "Yes" then at confirmation "No" | declined | | | |
| 6 | Conditional | "Yes if you pay for travel" | not accepted | | | |
| 7 | Mixed language | "Haan, I will come" | accepted after confirmation | | | |
| 8 | Hang up mid call | end call after the question | not accepted | | | |
| 9 | Busy / no answer | reject the call | no_answer, retry rule applies | | | |
| 10 | Voicemail | let it go to voicemail | not accepted | | | |
| 11 | Speech cut off | keep talking past the limit | not classified as yes | | | |
| 12 | Sarvam error | block Sarvam on staging | failure state, never accepted | | | |

Also verify: no transcript text appears in logs, a forged Twilio callback gets 403, the hospital's daily limit returns 429 with `Retry-After`.
