"""Fail if any internal link or asset in the static site points nowhere.

Run from the repo root:  python frontend/website/check_links.py
Checks every href/src that starts with "/" against the files under src/ (a clean URL
such as /about is valid when src/pages/about.html exists, as on Cloudflare Pages), and
that sitemap.xml lists only real pages. It also fails on mismatched structural tags (for example
an <ol> closed with </ul>), which browsers forgive but screen readers do not.
"""

import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).parent
SRC = ROOT / "src"


def exists(url: str) -> bool:
    path = url.split("#")[0].split("?")[0]
    if path == "/":
        return (SRC / "pages" / "index.html").is_file()
    relative = path.lstrip("/")
    return (SRC / relative).is_file() or (SRC / "pages" / f"{relative}.html").is_file()


# Tags the pages always close explicitly. Checking only these avoids false alarms from
# tags HTML lets you leave open, such as <p> and <li>.
STRUCTURAL = {"ol", "ul", "main", "section", "nav", "header", "footer", "div", "form", "table"}


class TagBalance(HTMLParser):
    """Collect places where a structural tag is closed by the wrong tag, or never closed."""

    def __init__(self):
        super().__init__()
        self.stack, self.errors = [], []

    def handle_starttag(self, tag, attrs):
        if tag in STRUCTURAL:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag not in STRUCTURAL:
            return
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        else:
            opened = self.stack[-1] if self.stack else "nothing"
            self.errors.append(f"</{tag}> closes <{opened}> (line {self.getpos()[0]})")

    def close(self):
        super().close()
        self.errors.extend(f"<{tag}> is never closed" for tag in self.stack)


def tag_problems(html: str) -> list:
    parser = TagBalance()
    parser.feed(html)
    parser.close()
    return parser.errors


problems = []
for page in [*SRC.glob("pages/*.html"), SRC / "404.html"]:
    html = page.read_text()
    for url in re.findall(r'(?:href|src)="(/[^"]*)"', html):
        if not exists(url):
            problems.append(f"{page.relative_to(ROOT)}: broken link {url}")
    if not re.search(r"<title>[^<]{5,}</title>", html) or 'name="description"' not in html:
        problems.append(f"{page.relative_to(ROOT)}: missing title or description")
    problems.extend(f"{page.relative_to(ROOT)}: {message}" for message in tag_problems(html))

for loc in re.findall(r"<loc>https?://[^/]+(/[^<]*)</loc>", (SRC / "sitemap.xml").read_text()):
    if not exists(loc):
        problems.append(f"sitemap.xml lists a missing page: {loc}")

print("\n".join(problems) if problems else "website links OK")
sys.exit(1 if problems else 0)
