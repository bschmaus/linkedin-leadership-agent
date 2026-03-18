"""
Scanning Agent
--------------
Pulls articles from RSS feeds, then uses Claude to distil 3-5 compelling
leadership angles for today's LinkedIn post.

Reads  : data/learnings.md       (style/topic feedback from past posts)
         data/daily_articles.md  (history — avoid repeating topics)
Writes : data/research_notes.md  (structured candidates for the Selection agent)

Run standalone:
    python -m agents.scanning
"""

import sys
import textwrap
from datetime import datetime
from pathlib import Path

import anthropic
import feedparser
import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import (
    RSS_FEEDS,
    EXTRA_SOURCES,
    LEARNINGS_FILE,
    DAILY_ARTICLES_FILE,
    RESEARCH_NOTES_FILE,
    BROWSER_HEADERS,
    read_file,
    ensure_data_dir,
)
from agents.utils import strip_html

# Scanning uses Sonnet to keep costs down — Opus is reserved for reasoning-heavy agents
MODEL = "claude-sonnet-4-6"

# Max characters of feed content to pass to Claude (keeps prompt cost reasonable)
MAX_FEED_CHARS = 28_000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def fetch_feed(url: str) -> list[dict]:
    """Fetch a single RSS feed with browser headers. Returns list of entry dicts."""
    try:
        resp = requests.get(url, headers=BROWSER_HEADERS, timeout=10)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
        entries = []
        for entry in feed.entries[:10]:
            title   = entry.get("title", "").strip()
            summary = strip_html(entry.get("summary", entry.get("description", "")))[:500]
            link    = entry.get("link", "")
            published = entry.get("published", entry.get("updated", ""))
            if title:
                entries.append({
                    "title":     title,
                    "summary":   summary,
                    "link":      link,
                    "published": published,
                })
        return entries
    except Exception as exc:
        print(f"  ⚠️  Could not fetch {url}: {exc}")
        return []


def fetch_extra_source(url: str) -> str:
    """
    Fetch a non-RSS page (e.g. Oliver Wyman Forum) and return its visible text.
    Used when no RSS feed is available.
    """
    try:
        resp = requests.get(url, headers=BROWSER_HEADERS, timeout=10)
        resp.raise_for_status()
        # Extract text from <article>, <main>, or <body> tags
        text = strip_html(resp.text)
        return text[:3000]
    except Exception as exc:
        print(f"  ⚠️  Could not scrape {url}: {exc}")
        return ""


def fetch_all_content(feeds: list[str], extra: list[str]) -> str:
    """Fetch RSS feeds + extra sources. Returns a formatted text block with full attribution."""
    sections = []

    # --- RSS feeds ---
    for url in feeds:
        print(f"  📡 RSS: {url}")
        entries = fetch_feed(url)
        if not entries:
            continue
        source_domain = url.split("/")[2]
        block = [f"### Source: {source_domain}"]
        for e in entries:
            block.append(f"**{e['title']}**")
            if e["published"]:
                block.append(f"_Published: {e['published']}_")
            if e["link"]:
                block.append(f"URL: {e['link']}")
            if e["summary"]:
                block.append(e["summary"])
            block.append("")
        sections.append("\n".join(block))

    # --- Extra / non-RSS sources ---
    for url in extra:
        print(f"  🌐 Scraping: {url}")
        text = fetch_extra_source(url)
        if text.strip():
            domain = url.split("/")[2]
            sections.append(f"### Source: {domain}\nURL: {url}\n{text}")

    combined = "\n\n".join(sections)
    return combined[:MAX_FEED_CHARS]


# ---------------------------------------------------------------------------
# Claude summarisation
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an expert content strategist specialising in leadership,
team collaboration, and organisational design.
Your task is to analyse raw content from publications and extract the most compelling
topics for a daily LinkedIn inspiration post.

Topic universe — give roughly equal weight to all three pillars:
1. Leadership: individual leader mindset, decision-making, vision, presence
2. Collaboration & co-creation: how teams work better and smarter together,
   psychological safety, collective intelligence, co-creation practices,
   and — in the most progressive cases — full self-organisation and distributed authority
3. Coaching & facilitation: techniques leaders and facilitators use to unlock
   team potential, powerful questions, workshop design, feedback loops

Guidelines:
- Ground every candidate in a real article or source from the content provided
- Always include the exact article title and URL so it can be referenced later
- Focus on actionable, timely insights with broad professional relevance
- Avoid topics already covered in the article history
- Incorporate style and topic feedback from past learnings
- NEVER use McKinsey, BCG, Bain, PwC, EY, Deloitte, or KPMG as a source or reference —
  these are direct competitors; citing them would be inappropriate
- Oliver Wyman Forum content is explicitly encouraged as a source
- Output ONLY structured markdown — no preamble, no commentary outside the format
"""


def build_user_message(feed_content: str, learnings: str, article_history: str) -> str:
    today = datetime.now().strftime("%A, %B %d, %Y")
    return textwrap.dedent(f"""
        Today is {today}.

        ## Past Learnings & Style Feedback
        {learnings or "_None yet._"}

        ## Recent Article History (avoid repeating these topics)
        {article_history or "_No history yet._"}

        ## Source Content
        {feed_content}

        ---

        Based on the source content above, identify exactly **3 to 5** compelling
        leadership topic candidates for today's LinkedIn post.

        For each candidate use this exact structure:

        ### Candidate N: [Short Title]
        **Angle:** [One sentence — the specific perspective or insight]
        **Why today:** [Why this resonates with professionals right now]
        **Key insights:**
        - [Insight 1]
        - [Insight 2]
        - [Insight 3]
        **Suggested hook:** [One punchy opening sentence for the LinkedIn post.
        Must be an observation, question, or provocation — NOT a personal claim
        like "The best leaders I know..." or "I've seen..." as the author may not
        have personal experience with this. Think contrarian insight, surprising
        stat, or a reframe of conventional wisdom.]
        **Source article:** [Exact article title]
        **Source URL:** [Full URL — use the URL from the content above, or omit if unavailable]
        **Source domain:** [e.g. fastcompany.com]
    """).strip()


def run(client: anthropic.Anthropic | None = None) -> str:
    """
    Run the scanning agent. Returns the research notes as a string.
    Pass an existing Anthropic client or one will be created.
    """
    ensure_data_dir()

    if client is None:
        client = anthropic.Anthropic()

    print("🔍 Scanning Agent starting...")

    # 1. Load shared context files
    learnings       = read_file(LEARNINGS_FILE)
    article_history = read_file(DAILY_ARTICLES_FILE)

    # 2. Pull feeds + extra sources
    print("\n  Fetching content...")
    feed_content = fetch_all_content(RSS_FEEDS, EXTRA_SOURCES)
    if not feed_content.strip():
        print("  ⚠️  No content retrieved — Claude will use general knowledge.")
        feed_content = "_No source content could be retrieved. Use current leadership knowledge._"

    # 3. Ask Claude to distil candidates
    print("\n  Analysing with Claude...\n")
    user_message = build_user_message(feed_content, learnings, article_history)

    collected = []
    with client.messages.stream(
        model=MODEL,
        max_tokens=3000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        for text in stream.text_stream:
            print(text, end="", flush=True)
            collected.append(text)

    print("\n")
    research_output = "".join(collected)

    # 4. Write research_notes.md (overwrite — fresh each day)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    notes = f"# Research Notes — {timestamp}\n\n{research_output}\n"
    RESEARCH_NOTES_FILE.write_text(notes, encoding="utf-8")
    print(f"  ✅ Research notes written to {RESEARCH_NOTES_FILE}")

    return research_output


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run()
