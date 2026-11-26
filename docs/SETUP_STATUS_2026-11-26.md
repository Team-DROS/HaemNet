# HaemNet setup status — 26 November 2026

This records the setup session, not a certification that the application is production-ready.
No API keys, passwords, Turnstile secrets, or database credentials belong in this file.

## Hosting and accounts

| Component | Current setup | Evidence / remaining work |
| --- | --- | --- |
| Public website | https://haemnet.pages.dev on Cloudflare Pages | Screenshot confirmed successful production deployment of 731d740; later changes trigger Git deployments. Verify the latest deployed revision. |
| API | https://haemnet-api.onrender.com on Render Free | User reported successful redeployment after email configuration; health logs previously showed HTTP 200. Verify deployed commit when troubleshooting. |
| Hospital dashboard | https://haemnet-dashboard.onrender.com on Render | Existing service retained. |
| Database | Existing MongoDB Atlas cluster retained | Organization Owner invitation sent to team Gmail. Acceptance has not been independently confirmed. |
| Team email | haemnetai@gmail.com | Public website email links updated, including legal and deletion pages. |
| Render access | Existing account retained | Hobby workspace does not allow additional members. No Pro upgrade purchased. Another non-HaemNet service shares this workspace. |
| Domain | pages.dev address for now | No ownership of haemnet.in confirmed. Domain purchase / redemption deferred. |
| Cloudflare Turnstile | Public website key configured; backend secret entered by user | Browser challenge showed success. An API rejection on retry revealed single-use token handling; fixes committed. |
| Brevo | User created account and reported entering Render settings | HTTPS delivery adapter committed. Sender verification, provider activation, and inbox delivery still require confirmation. |
| Sentry / R2 | Not verified or configured in this session | No matching environment variable names found in the two inspected Render services before setup; this does not prove accounts/resources do not exist. |

## Website deployment settings

- Repository: Team-DROS/HaemNet; production branch: main.
- Root: frontend/website.
- Framework preset: None.
- Build: python3 build_cloudflare.py.
- Output: dist.
- Public configuration: frontend/website/src/assets/site-config.js.
- An earlier Worker named haemnet failed with a static-directory detection error.
  It is separate from the working Pages project; do not retry that Worker to deploy Pages.

## Backend settings entered during setup

Preserve existing values and credentials. These values are configuration, not proof of successful delivery:

~~~dotenv
CORS_ORIGINS=["https://haemnet-dashboard.onrender.com","https://haemnet.pages.dev"]
SMTP_FROM=haemnetai@gmail.com
CONTACT_TO=haemnetai@gmail.com
~~~

Set TURNSTILE_SECRET and BREVO_API_KEY privately in Render; never copy their values into GitHub.
Use the Turnstile secret paired with the public website's site key.
The Brevo API key needs transactional-email sending permission. Other permissions are unnecessary.
SMTP_FROM must be a verified sender accepted by Brevo.

## Changes already committed to main during setup

- 731d740: public website API URL and Turnstile site key.
- f5c0e20 through 3364bd1: replace placeholder contact email across eleven HTML pages.
- 29c4455, daeae68, 67d68af: Brevo setting, HTTPS delivery, and contact readiness check.
- 23552f2: consume Turnstile token once and reset verification after an API rejection.
- Follow-up PR adds network-error reset, regression tests, and these deployment notes.

## Contact form troubleshooting

1. "The contact form is not available" means CONTACT_TO or email-provider configuration
   is absent. With Brevo, set BREVO_API_KEY and SMTP_FROM; SMTP_HOST is not required.
2. "Please complete the spam check and try again" is a backend Turnstile rejection,
   not an email-provider error. Refresh and use a fresh challenge. If persistent, check
   matching site/secret keys and allowed hostname without exposing either secret.
3. A Turnstile token is single-use, including a request whose later email step fails.
   The frontend must clear it and reset verification after failed requests.
4. "Could not send your message" means the email adapter failed. Inspect Render's
   HTTP-status-only Brevo log and Brevo transactional logs. Check API permissions,
   verified sender, provider account activation, and quota. Do not log message bodies
   or keys.
5. Render Free blocks standard SMTP ports. This integration uses Brevo HTTPS instead;
   installing SMTP credentials alone does not resolve that restriction.

## Outstanding verification and launch tasks

- Confirm latest Pages and API deployments and complete one synthetic contact submission.
- Confirm thank-you navigation AND actual email receipt in team inbox/spam;
  provider acceptance alone is not proof of inbox delivery.
- Accept and verify MongoDB organization invitation on the team account.
- Check hospital registration separately: TURNSTILE_SECRET also protects that endpoint,
  so dashboard site-key/hostname configuration must match before testing sign-up.
- Confirm backend email links use the real DASHBOARD_URL.
- Custom domain, custom-domain email/DNS, and Search Console remain deferred.
- Audit remaining assumed app.haemnet.in links and canonical/sitemap URLs before launch.
- Storage persistence, Sentry, backups, monitoring, and legal review remain unverified.

## Local regression test

With Node.js installed:

~~~sh
node --test frontend/website/tests/contact.test.cjs
~~~

Covers failed-request token renewal, network-error renewal, successful redirect,
and preventing requests with an expired challenge. These mocked tests do not
verify live Cloudflare or Brevo credentials.
