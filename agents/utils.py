"""
Shared utilities used across multiple agents.
"""

import re
from html.parser import HTMLParser


# ---------------------------------------------------------------------------
# Article parsing
# ---------------------------------------------------------------------------

def extract_latest_post(articles: str) -> tuple[str, str]:
    """Return (topic_title, post_text) for the most recent entry in daily_articles.md."""
    blocks = re.split(r"\n---\n", articles)
    for block in reversed(blocks):
        block = block.strip()
        if not block or block.startswith("# Daily"):
            continue
        title_match = re.search(r"^## \d{4}-\d{2}-\d{2} — (.+)$", block, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else "Untitled"
        lines = [
            l for l in block.splitlines()
            if not l.startswith("## ") and not l.startswith("_Written:")
        ]
        return title, "\n".join(lines).strip()
    return "Untitled", ""


def extract_source_url(text: str) -> str:
    """Extract the first https URL from a 'URL: ...' line."""
    match = re.search(r"URL:\s*(https?://\S+)", text)
    return match.group(1).strip() if match else ""


# ---------------------------------------------------------------------------
# Voice context
# ---------------------------------------------------------------------------

def extract_author_context(voice: str) -> str:
    """Return only identity/audience sections from voice.md, stripping writing style."""
    if not voice.strip():
        return ""
    skip_headers = {
        "## how i write",
        "## what i want readers to feel",
        "## sentence rhythm",
        "## things that feel authentic to me",
        "## things that feel fake",
    }
    lines, capture, result = voice.splitlines(), False, []
    for line in lines:
        if line.startswith("## "):
            capture = line.strip().lower() not in skip_headers
        if capture:
            result.append(line)
    return "\n".join(result).strip()


# ---------------------------------------------------------------------------
# File naming
# ---------------------------------------------------------------------------

def make_date_slug(title: str) -> str:
    """Convert a title to a lowercase URL-safe slug (max 50 chars) for file naming."""
    return re.sub(r"[^a-z0-9]+", "-", title.lower())[:50].strip("-")


# ---------------------------------------------------------------------------
# HTML stripping
# ---------------------------------------------------------------------------

class _StripHTML(HTMLParser):
    _SKIP = {"script", "style", "nav", "header", "footer", "aside", "noscript"}

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0 and data.strip():
            self._parts.append(data.strip())

    def get_text(self) -> str:
        return " ".join(self._parts)


def strip_html(html: str) -> str:
    """Strip HTML tags and return readable text. Skips script/style/nav content."""
    parser = _StripHTML()
    parser.feed(html)
    return parser.get_text()
