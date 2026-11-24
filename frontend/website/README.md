# HaemNet public website

Static marketing and legal site (no build step). Deploy `frontend/website` on Vercel;
`vercel.json` serves `src/` and maps clean URLs to `src/pages/*.html`.

- Pages: Home, How it works, For hospitals, For donors, About, Contact, Privacy, Terms, Thank you, 404
- SEO: per-page title, description, canonical and Open Graph tags; `robots.txt`; `sitemap.xml`
- Preview locally: `cd frontend/website/src && python -m http.server 8080` (clean URLs need Vercel; open `/pages/index.html`)

Before launch confirm: domain (https://haemnet.in), contact email (contact@haemnet.in), the dashboard URL (https://app.haemnet.in),
the Play Store link on `for-donors`, and have the privacy policy and terms reviewed.
