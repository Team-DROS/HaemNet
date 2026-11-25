"""Build the Cloudflare Pages output for the public website.

Cloudflare Pages settings:
  Root directory:         frontend/website
  Build command:          python3 build_cloudflare.py
  Build output directory: dist

The source keeps pages in src/pages/. Cloudflare serves clean URLs only for files at the
output root (about.html becomes /about, index.html becomes /), so this script flattens the
pages into dist/ and writes the security headers file. The source files are not changed.
"""

import shutil
from pathlib import Path

ROOT = Path(__file__).parent
SRC = ROOT / "src"
DIST = ROOT / "dist"

# The site loads no external fonts or scripts apart from Cloudflare Turnstile, and has no
# inline scripts or styles, so the policy can be strict. connect-src allows any HTTPS API
# because the contact form posts to the backend URL set in src/assets/site-config.js.
HEADERS = """\
/*
  X-Content-Type-Options: nosniff
  X-Frame-Options: DENY
  Referrer-Policy: strict-origin-when-cross-origin
  Strict-Transport-Security: max-age=31536000; includeSubDomains
  Permissions-Policy: camera=(), microphone=(), geolocation=()
  Content-Security-Policy: default-src 'self'; script-src 'self' https://challenges.cloudflare.com; style-src 'self'; img-src 'self' data:; font-src 'self'; frame-src https://challenges.cloudflare.com; connect-src 'self' https:; frame-ancestors 'none'; base-uri 'self'; form-action 'self' mailto:

/assets/*
  Cache-Control: public, max-age=3600, must-revalidate

/assets/site.webmanifest
  Content-Type: application/manifest+json
"""


def main() -> None:
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()
    pages = sorted((SRC / "pages").glob("*.html"))
    for page in pages:
        shutil.copy2(page, DIST / page.name)
    for name in ("404.html", "robots.txt", "sitemap.xml"):
        shutil.copy2(SRC / name, DIST / name)
    shutil.copytree(SRC / "assets", DIST / "assets")
    (DIST / "_headers").write_text(HEADERS)
    print(f"Built {len(pages)} pages into {DIST.relative_to(ROOT.parent.parent)}")


if __name__ == "__main__":
    main()
