"""
Assessment Agent
----------------
Reflects on the completed post, evaluates quality against goals, and writes
structured learnings to learnings.md so future agents improve over time.

Reads  : data/daily_articles.md   (the finished post)
         data/selection_notes.md  (the brief it was supposed to fulfil)
         data/post_assets.md      (format decision and assets)
         data/learnings.md        (existing structured learnings)
Writes : data/learnings.md        (maintains 3-layer structure: Prinzipien → Issues → Last Assessment → Archiv)

Run standalone:
    python -m agents.assessment
"""
from __future__ import annotations

import re
import sys
import textwrap
from datetime import datetime
from pathlib import Path

import anthropic

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import (
    MODEL,
    DAILY_ARTICLES_FILE,
    SELECTION_NOTES_FILE,
    LEARNINGS_FILE,
    POST_ASSETS_FILE,
    EMPTY_LEARNINGS,
    read_file,
    ensure_data_dir,
)
from agents.utils import extract_latest_post, stream_to_stdout


# ---------------------------------------------------------------------------
# Helpers: extract context sections from structured learnings.md
# ---------------------------------------------------------------------------

def extract_active_context(learnings: str) -> str:
    """
    Return only the sections the assessment agent needs:
    Destillierte Prinzipien + Recurring Issues + Letztes Assessment.
    Skip the Archiv to keep context window lean.
    """
    if not learnings or EMPTY_LEARNINGS in learnings:
        return "_None yet._"

    # Find the Archiv section and cut it off
    archiv_match = re.search(r"^## Archiv", learnings, re.MULTILINE)
    if archiv_match:
        return learnings[:archiv_match.start()].strip()
    return learnings.strip()


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an editorial coach and knowledge base maintainer for a LinkedIn content agent.
Complete two tasks in a single response.

## Task 1 — Post Assessment
Assess the post against its brief. Be honest and specific — vague praise or criticism is useless.
Focus on what worked (so it repeats), what missed (so it gets fixed), and concrete rules for future agents.
Tone: direct, collegial. Write as if briefing a skilled ghostwriter who wants to improve.

Structure the assessment with these sections (2–4 bullets each):
### What worked / ### What could be stronger / ### Style & voice notes / ### Format decision / ### Instructions for future posts

## Task 2 — Learnings Update
Rewrite the full learnings.md with these changes:
1. **## Letztes Assessment** — replace with the new assessment (full text, with ## Assessment header and _Reviewed_ line).
2. **## Recurring Issues** — update the table: increment counter for flagged issues, add new rows, update Status emoji (🔴 unresolved, 🟡 watch, 🟢 resolved not flagged in last 2).
3. **## Destillierte Prinzipien** — update ONLY for genuinely new patterns. Keep stable and concise.
4. **## Archiv** — prepend a compressed entry for the post previously in "Letztes Assessment" (3 bullets: strength, weakness, style note).

Preserve the header comment block at the top of learnings.md exactly.

## Output format — use these exact delimiters, no content outside them:

<assessment>
[assessment markdown]
</assessment>

<learnings>
[complete updated learnings.md]
</learnings>
"""


def _extract_tag(text: str, tag: str) -> str:
    """Extract content between <tag>...</tag> delimiters."""
    match = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL)
    return match.group(1).strip() if match else ""


def build_merged_prompt(post_text: str, brief: str, assets_summary: str,
                        current_learnings: str, topic: str, timestamp: str,
                        analytics: str = "") -> str:
    analytics_section = (
        f"\n## Actual post performance (LinkedIn Analytics)\n{analytics}\n"
        if analytics.strip() else ""
    )
    return textwrap.dedent(f"""
        ## The brief
        {brief or "_No brief available._"}

        ## The post
        {post_text or "_No post available._"}

        ## Format decision & assets
        {assets_summary or "_No asset notes available._"}
        {analytics_section}
        ## Current learnings.md
        {current_learnings or "_None yet._"}

        ---

        Topic: {topic}
        Reviewed: {timestamp}

        {"Ground your assessment conclusions in the actual analytics numbers." if analytics.strip() else ""}
        Complete Task 1 and Task 2 now.
    """).strip()


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
    current_learnings = read_file(LEARNINGS_FILE)

    topic, post_text = extract_latest_post(articles)

    if not post_text:
        raise RuntimeError("No post found in daily_articles.md. Run the full pipeline first.")

    # Load analytics if available
    from agents.analytics_reader import load_latest_analytics, format_for_assessment
    analytics_data = load_latest_analytics()
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

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    if EMPTY_LEARNINGS in current_learnings or not current_learnings.strip():
        # First-time initialisation: assessment only (no existing structure to update)
        analytics_section = (
            f"\n## Actual post performance\n{analytics_text}\n" if analytics_text.strip() else ""
        )
        first_run_prompt = textwrap.dedent(f"""
            ## The brief
            {brief or "_No brief available._"}

            ## The post
            {post_text or "_No post available._"}

            ## Format decision & assets
            {assets_summary or "_No asset notes available._"}
            {analytics_section}
            ---

            Assess the post against the brief (2–4 bullets per section):
            ### What worked / ### What could be stronger / ### Style & voice notes / ### Format decision / ### Instructions for future posts
        """).strip()
        assessment_body = stream_to_stdout(
            client,
            model=MODEL,
            max_tokens=3000,
            system="You are a thoughtful editorial coach reviewing LinkedIn posts. Be honest and specific. Tone: direct, collegial.",
            messages=[{"role": "user", "content": first_run_prompt}],
        )
        print("-" * 60 + "\n")
        entry = (
            f"# Learnings & Improvements\n\n"
            f"---\n\n"
            f"## Letztes Assessment (vollständig)\n\n"
            f"## Assessment: {topic}\n_Reviewed: {timestamp}_\n\n{assessment_body}\n\n"
            f"---\n\n## Archiv\n\n_No archived assessments yet._\n"
        )
        LEARNINGS_FILE.write_text(entry, encoding="utf-8")
    else:
        # Single merged call: assessment + learnings update in one shot
        merged_prompt = build_merged_prompt(
            post_text, brief, assets_summary, current_learnings, topic, timestamp, analytics_text
        )
        raw_output = stream_to_stdout(
            client,
            verbose=False,
            model=MODEL,
            max_tokens=8000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": merged_prompt}],
        )

        assessment_body = _extract_tag(raw_output, "assessment")
        updated_learnings = _extract_tag(raw_output, "learnings")

        if assessment_body:
            print(assessment_body)
        print("-" * 60 + "\n")

        print("  🔄 Updating learnings structure...")
        if updated_learnings and ("## Destillierte Prinzipien" in updated_learnings or "## Letztes Assessment" in updated_learnings):
            LEARNINGS_FILE.write_text(updated_learnings, encoding="utf-8")
        else:
            # Fallback: append assessment to avoid data loss
            print("  ⚠️  Could not parse learnings from output — falling back to append.")
            fallback = (
                current_learnings.rstrip()
                + f"\n\n---\n\n## Assessment: {topic}\n_Reviewed: {timestamp}_\n\n{assessment_body or raw_output}\n"
            )
            LEARNINGS_FILE.write_text(fallback, encoding="utf-8")

    print(f"  ✅ Learnings updated in {LEARNINGS_FILE}")

    return assessment_body


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run()
