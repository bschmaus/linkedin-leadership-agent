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

SYSTEM_PROMPT = """You are a thoughtful editorial coach reviewing LinkedIn posts for a senior
professional. Your job is to assess post quality and extract
actionable lessons that will make future posts better.

Be honest and specific. Vague praise is useless. Vague criticism is useless.
Focus on what was done well (so it gets repeated), what missed (so it gets fixed),
and concrete instructions for future agents.

Tone: direct, collegial, constructive. Write as if briefing a skilled ghostwriter
who wants to improve."""

CONSOLIDATION_SYSTEM = """You are maintaining a structured knowledge base for a LinkedIn content agent.
Your job is to update learnings.md after each new post assessment.
Be precise and concise. Update counters accurately. Compress fairly."""


def build_assessment_prompt(post_text: str, brief: str, assets_summary: str,
                            active_context: str, analytics: str = "") -> str:
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
        {active_context or "_None yet._"}

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


def build_consolidation_prompt(current_learnings: str, new_assessment: str,
                                topic: str, timestamp: str) -> str:
    return textwrap.dedent(f"""
        You are updating the structured learnings.md file after a new post assessment.

        ## Current learnings.md content
        {current_learnings}

        ## New assessment to integrate
        Topic: {topic}
        Reviewed: {timestamp}

        {new_assessment}

        ---

        Your task: rewrite the full learnings.md with these changes:

        1. **## Letztes Assessment (vollständig)** — replace with the new assessment above (full text, including the ## Assessment header and _Reviewed_ line).

        2. **## Recurring Issues** — update the table:
           - If the new assessment flags an issue already in the table, increment its counter by 1 and update "Last flagged" to {timestamp[:10]}.
           - If the new assessment flags a NEW issue not yet in the table, add a row.
           - Update the Status emoji based on trajectory:
             🔴 = unresolved / recurring
             🟡 = partially resolved or watch
             🟢 = resolved (not flagged in last 2 assessments)

        3. **## Destillierte Prinzipien** — update ONLY if the new assessment reveals a genuinely new pattern not already captured. Do not add minor variations. Keep it stable and concise.

        4. **## Archiv** — prepend a new compressed entry for the post that was previously in "Letztes Assessment". Format:
           ### YYYY-MM-DD — "Topic title"
           - [3 bullet points: one strength, one weakness, one style/voice note]

        Output the complete updated learnings.md. Preserve the header comment block at the top exactly.
        Do not add commentary before or after the file content.
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

    # Step 1: Generate the assessment (lean context — no Archiv)
    active_context = extract_active_context(current_learnings)
    assessment_prompt = build_assessment_prompt(
        post_text, brief, assets_summary, active_context, analytics_text
    )

    assessment_body = stream_to_stdout(
        client,
        model=MODEL,
        max_tokens=3000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": assessment_prompt}],
    )
    print("-" * 60 + "\n")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Step 2: Consolidate into structured learnings.md
    print("  🔄 Consolidating learnings structure...")

    if EMPTY_LEARNINGS in current_learnings or not current_learnings.strip():
        # First-time initialisation: simple write
        entry = (
            f"# Learnings & Improvements\n\n"
            f"---\n\n"
            f"## Letztes Assessment (vollständig)\n\n"
            f"## Assessment: {topic}\n_Reviewed: {timestamp}_\n\n{assessment_body}\n\n"
            f"---\n\n## Archiv\n\n_No archived assessments yet._\n"
        )
        LEARNINGS_FILE.write_text(entry, encoding="utf-8")
    else:
        # Structured consolidation via Claude
        consolidation_prompt = build_consolidation_prompt(
            current_learnings, assessment_body, topic, timestamp
        )

        updated = stream_to_stdout(
            client,
            verbose=False,
            model=MODEL,
            max_tokens=6000,
            system=CONSOLIDATION_SYSTEM,
            messages=[{"role": "user", "content": consolidation_prompt}],
        )

        # Safety check: ensure the file looks valid before writing
        if "## Destillierte Prinzipien" in updated or "## Letztes Assessment" in updated:
            LEARNINGS_FILE.write_text(updated, encoding="utf-8")
        else:
            # Fallback: simple append to avoid data loss
            print("  ⚠️  Consolidation produced unexpected output — falling back to append.")
            fallback = (
                current_learnings.rstrip()
                + f"\n\n---\n\n## Assessment: {topic}\n_Reviewed: {timestamp}_\n\n{assessment_body}\n"
            )
            LEARNINGS_FILE.write_text(fallback, encoding="utf-8")

    print(f"  ✅ Learnings updated in {LEARNINGS_FILE}")

    return assessment_body


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run()
