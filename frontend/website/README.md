# HaemNet public website

Static marketing and legal site. The source in `src/` has no build step; a small script
prepares it for Cloudflare Pages.

- Pages: Home, How it works, For hospitals, For donors, About, Contact, Privacy, Terms, Delete account, Thank you, 404
- SEO: per-page title, description, canonical and Open Graph tags; `robots.txt`; `sitemap.xml`
- Security headers and caching: written to `dist/_headers` by the build script

## Deploy on Cloudflare Pages

1. In the Cloudflare dashboard open Workers & Pages, create a Pages project and connect this GitHub repository.
2. Settings: framework preset **None**, root directory `frontend/website`, build command `python3 build_cloudflare.py`, build output directory `dist`.
3. Add the custom domain under Custom domains. A domain from any registrar works: point its nameservers to Cloudflare.
4. Optional and free: Cloudflare Email Routing can forward `contact@your-domain` to the team's inboxes.
5. Submit `/sitemap.xml` in Google Search Console.

Cloudflare serves `about.html` at `/about` and uses `404.html` for missing pages. The security policy in
`build_cloudflare.py` allows scripts only from the site itself and Cloudflare Turnstile, so adding any other
script or an inline script needs a matching change there.

## Preview locally

```bash
python3 frontend/website/build_cloudflare.py
cd frontend/website/dist && python3 -m http.server 8080
```

Open `http://localhost:8080/index.html`. Extensionless URLs such as `/about` need Cloudflare, or open `/about.html`.

## Before launch

Confirm the domain (`https://haemnet.in`), contact email (`contact@haemnet.in`), the dashboard URL
(`https://app.haemnet.in`), the Play Store link on `for-donors`, and have the privacy policy and terms reviewed.

Contact form: edit `src/assets/site-config.js` with the API URL (and Turnstile site key). With an API URL the form posts to
`/api/contact` (backend needs `CONTACT_TO`, `SMTP_*` and the site origin in `CORS_ORIGINS`); without it the form opens the
visitor's email app.

## Checks

`python3 frontend/website/check_links.py` fails on a broken internal link, a missing title or description,
or a sitemap entry that points nowhere. CI runs it on every push.
