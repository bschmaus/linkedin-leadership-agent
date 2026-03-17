"""
Assessment Agent
----------------
Reflects on the completed post, evaluates quality against goals, and writes
structured learnings to learnings.md so future agents improve over time.

Reads  : data/daily_articles.md   (the finished post)
         data/selection_notes.md  (the brief it was supposed to fulfil)
         data/post_assets.md      (format decision and assets)
         data/learnings.md        (existing accumulated learnings)
Writes : data/learnings.md        (appends new learnings entry)

Run standalone:
    python -m agents.assessment
"""

import re
import sys
import textwrap
from datetime import datetime

import anthropic

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

from config import (
    MODEL,
    DATA_DIR,
    DAILY_ARTICLES_FILE,
    SELECTION_NOTES_FILE,
    LEARNINGS_FILE,
    read_file,
    ensure_data_dir,
)

POST_ASSETS_FILE = DATA_DIR / "post_assets.md"


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a thoughtful editorial coach reviewing LinkedIn posts for a senior
professional. Your job is to assess post quality and extract
actionable lessons that will make future posts better.

Be honest and specific. Vague praise is useless. Vague criticism is useless.
Focus on what was done well (so it gets repeated), what missed (so it gets fixed),
and concrete instructions for future agents.

Tone: direct, collegial, constructive. Write as if briefing a skilled ghostwriter
who wants to improve."""

ASSESSMENT_SCHEMA = """\
## Assessment: {topic}
_Reviewed: {timestamp}_

### What worked
{what_worked}

### What could be stronger
{what_weaker}

### Style & voice notes
{style_notes}

### Format decision
{format_notes}

### Instructions for future posts
{future_instructions}

---
"""


def build_prompt(post_text: str, brief: str, assets_summary: str,
                 existing_learnings: str, analytics: str = "") -> str:
    analytics_section = (
        f"\n        ## Actual post performance (LinkedIn Analytics)\n        {analytics}\n"
        if analytics.strip() else ""
    )
    return textwrap.dedent(f"""
        ## The brief (what we were trying to achieve)
        {brief or "_No brief available._"}

        ## The post that was written
        {post_text or "_No post available._"}

        ## Format decision & assets
        {assets_summary or "_No asset notes available._"}
        {analytics_section}
        ## Existing learnings (for context — do not repeat what's already captured)
        {existing_learnings or "_None yet._"}

        ---

        Please assess the post against the brief. Structure your response as valid markdown
        using EXACTLY this format (fill in each section — use 2–4 bullet points per section):

        ### What worked
        - [specific strength]

        ### What could be stronger
        - [specific gap or missed opportunity]

        ### Style & voice notes
        - [observations on tone, rhythm, authenticity, word choice]

        ### Format decision
        - [was the format (text / poll / image / carousel) right for this content?]

        ### Instructions for future posts
        - [actionable rule: "Always...", "Never...", "When the post is about X, do Y"]

        Be concrete. Reference specific lines or phrases from the post where helpful.
        {"If analytics data is available, ground your conclusions in the actual numbers." if analytics.strip() else ""}
    """).strip()


# ---------------------------------------------------------------------------
# Extract post text from daily_articles.md
# ---------------------------------------------------------------------------

def extract_latest_post_and_topic(articles: str) -> tuple[str, str]:
    """Returns (topic_title, post_text) for the most recent entry."""
    import re
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


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

def run(client: anthropic.Anthropic | None = None) -> str:
    """
    Run the assessment agent. Returns the new learnings entry as a string.
    Pass an existing Anthropic client or one will be created.
    """
    ensure_data_dir()

    if client is None:
        client = anthropic.Anthropic()

    print("🔍 Assessment Agent starting...")

    articles        = read_file(DAILY_ARTICLES_FILE)
    brief           = read_file(SELECTION_NOTES_FILE)
    assets_summary  = read_file(POST_ASSETS_FILE)
    existing        = read_file(LEARNINGS_FILE)

    topic, post_text = extract_latest_post_and_topic(articles)

    if not post_text:
        print("  ⚠️  No post found in daily_articles.md. Run the full pipeline first.")
        return ""

    # Load analytics if available
    from agents.analytics_reader import load_latest_analytics, format_for_assessment
    analytics_data = load_latest_analytics()
    # Extract the date of the LATEST post (findall returns all matches; take the last)
    all_dates = re.findall(r"## (\d{4}-\d{2}-\d{2})", articles)
    article_date = all_dates[-1] if all_dates else None
    analytics_text = format_for_assessment(analytics_data, article_date)

    if analytics_data:
        print(f"  📊 Analytics loaded: {analytics_data['file']}")
        if analytics_text and "This post" in analytics_text:
            print(f"     ↳ Performance data matched for {article_date}")
        else:
            print(f"     ↳ No match for {article_date} — weekly overview included")
    else:
        print("  ℹ️  No analytics file found — qualitative assessment only")

    print(f"\n  Assessing: {topic}\n")
    print("-" * 60)

    prompt = build_prompt(post_text, brief, assets_summary, existing, analytics_text)
    collected = []

    with client.messages.stream(
        model=MODEL,
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for text in stream.text_stream:
            print(text, end="", flush=True)
            collected.append(text)

    print("\n" + "-" * 60 + "\n")
    assessment_body = "".join(collected).strip()

    # Build the full entry with header
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"\n---\n\n## Assessment: {topic}\n_Reviewed: {timestamp}_\n\n{assessment_body}\n"

    # Append to learnings.md
    current = read_file(LEARNINGS_FILE)
    if "_No learnings yet._" in current:
        # Replace placeholder content
        updated = f"# Learnings & Improvements\n{entry}"
    else:
        updated = current.rstrip() + "\n" + entry

    LEARNINGS_FILE.write_text(updated, encoding="utf-8")
    print(f"  ✅ Learnings updated in {LEARNINGS_FILE}")

    return assessment_body


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run()
