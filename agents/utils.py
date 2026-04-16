"""
Shared utilities used across multiple agents.
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from html.parser import HTMLParser

import anthropic

from config import (
    DAILY_ARTICLES_FILE,
    parse_post_blocks,
    read_file,
)


# ---------------------------------------------------------------------------
# Article parsing
# ---------------------------------------------------------------------------

def extract_latest_post(articles: str) -> tuple[str, str]:
    """Return (topic_title, post_text) for the most recent entry in daily_articles.md."""
    posts = parse_post_blocks(articles)
    for block in reversed(posts):
        block = block.strip()
        title_match = re.search(r"^## \d{4}-\d{2}-\d{2} — (.+)$", block, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else "Untitled"
        lines = [
            l for l in block.splitlines()
            if not l.startswith("## ") and not l.startswith("_Written:")
        ]
        return title, "\n".join(lines).strip()
    return "Untitled", ""


def extract_recent_history(articles: str, n: int = 14) -> str:
    """Return only the last *n* post entries from daily_articles.md.

    Used for topic-deduplication context. Keeps the token footprint bounded
    regardless of how many posts have accumulated over months.
    """
    posts = parse_post_blocks(articles)
    recent = posts[-n:] if len(posts) > n else posts
    return "\n---\n".join(recent)


def extract_source_frequency(articles: str, n: int = 14) -> str:
    """Count source domains across the last *n* posts.

    Scans for **Source domain:** or **Domain:** lines in daily_articles.md
    and returns a human-readable frequency summary for the Selection agent.
    """
    posts = parse_post_blocks(articles)
    recent = posts[-n:] if len(posts) > n else posts
    domain_counts: dict[str, int] = {}
    for block in recent:
        # Match patterns like "**Source domain:** fastcompany.com" or "Domain: mit.edu"
        matches = re.findall(r"(?:Source domain|Domain):\s*\**\s*(\S+)", block, re.IGNORECASE)
        for domain in matches:
            domain = domain.strip("*").strip("_").strip().lower()
            if domain:
                domain_counts[domain] = domain_counts.get(domain, 0) + 1
    if not domain_counts:
        return ""
    # Sort by count descending
    ranked = sorted(domain_counts.items(), key=lambda x: -x[1])
    lines = [f"- {domain}: {count}x" for domain, count in ranked]
    return "\n".join(lines)


def extract_post_date(block: str) -> str | None:
    """Extract the YYYY-MM-DD date from a post block header. Returns None if not found."""
    match = re.search(r"^## (\d{4}-\d{2}-\d{2}) —", block.strip(), re.MULTILINE)
    return match.group(1) if match else None


def replace_latest_entry(post_text: str, title: str, status: str = "draft") -> None:
    """Overwrite the most recent entry in daily_articles.md.

    Preserves the original post date from the existing entry to avoid
    midnight date-drift. Used by article_writer (revision) and proofread.
    """
    content = read_file(DAILY_ARTICLES_FILE)
    idx = content.rfind("\n---\n")
    base = content[:idx] if idx != -1 else content

    # Preserve original date from existing entry (avoid midnight drift)
    existing_block = content[idx:] if idx != -1 else ""
    original_date = extract_post_date(existing_block)
    date_str = original_date or datetime.now().strftime("%Y-%m-%d")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = (
        f"\n---\n\n"
        f"## {date_str} — {title}\n\n"
        f"_Written: {timestamp} | Status: {status}_\n\n"
        f"{post_text}\n"
    )
    DAILY_ARTICLES_FILE.write_text(base + entry, encoding="utf-8")


def update_post_status(new_status: str) -> None:
    """Update the status field of the latest entry in daily_articles.md."""
    content = read_file(DAILY_ARTICLES_FILE)
    # Find the last "Status: ..." within a _Written: ... | Status: ..._ line
    pattern = r"(Status: )[^_]+"
    matches = list(re.finditer(pattern, content))
    if not matches:
        return
    last = matches[-1]
    updated = content[:last.start()] + f"Status: {new_status}" + content[last.end():]
    DAILY_ARTICLES_FILE.write_text(updated, encoding="utf-8")


def stream_to_stdout(client: anthropic.Anthropic, *, verbose: bool = True,
                     retries: int = 2, retry_delay: float = 5.0,
                     **msg_kwargs) -> str:
    """Stream a Claude response, optionally printing tokens in real time.

    Accepts the same keyword arguments as ``client.messages.stream()``
    (model, max_tokens, system, messages, thinking, …).

    Retries on transient network errors (e.g. [Errno 54] Connection reset by peer).

    Returns the joined text output stripped of whitespace.
    """
    last_exc: Exception | None = None
    for attempt in range(1 + retries):
        if attempt > 0:
            print(f"\n  ⚠️  Network error, retrying ({attempt}/{retries})…")
            time.sleep(retry_delay)
        try:
            collected: list[str] = []
            with client.messages.stream(**msg_kwargs) as stream:
                for text in stream.text_stream:
                    if verbose:
                        print(text, end="", flush=True)
                    collected.append(text)
            if verbose:
                print("\n")
            return "".join(collected).strip()
        except Exception as exc:
            last_exc = exc
            if attempt == retries:
                raise
    raise last_exc  # unreachable, satisfies type checkers


def is_brand_configured(brand: str) -> bool:
    """Return True if brand guidelines contain real content (not a placeholder)."""
    return bool(brand.strip()) and "Fülle diese Datei" not in brand


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
