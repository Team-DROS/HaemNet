"""Fail if any internal link or asset in the static site points nowhere.

Run from the repo root:  python frontend/website/check_links.py
Checks every href/src that starts with "/" against vercel.json rewrites and
the files under src/, and that sitemap.xml lists only real pages.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
SRC = ROOT / "src"
rewrites = {r["source"]: r["destination"] for r in json.loads((ROOT / "vercel.json").read_text())["rewrites"]}


def exists(url: str) -> bool:
    path = url.split("#")[0].split("?")[0]
    if path in rewrites:
        return (SRC / rewrites[path].lstrip("/")).is_file()
    return (SRC / path.lstrip("/")).is_file()


problems = []
for page in [*SRC.glob("pages/*.html"), SRC / "404.html"]:
    html = page.read_text()
    for url in re.findall(r'(?:href|src)="(/[^"]*)"', html):
        if not exists(url):
            problems.append(f"{page.relative_to(ROOT)}: broken link {url}")
    if not re.search(r"<title>[^<]{5,}</title>", html) or 'name="description"' not in html:
        problems.append(f"{page.relative_to(ROOT)}: missing title or description")

for loc in re.findall(r"<loc>https?://[^/]+(/[^<]*)</loc>", (SRC / "sitemap.xml").read_text()):
    if not exists(loc):
        problems.append(f"sitemap.xml lists a missing page: {loc}")

print("\n".join(problems) if problems else "website links OK")
sys.exit(1 if problems else 0)
