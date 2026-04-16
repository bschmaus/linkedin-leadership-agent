"""
Article Writer Agent
--------------------
Turns the selection brief into a fully-formed LinkedIn post and appends
it to the article history.

Reads  : data/selection_notes.md  (topic brief from the Selection agent)
         data/learnings.md        (accumulated style & tone feedback)
Writes : data/daily_articles.md   (appends today's post with metadata)

Run standalone:
    python -m agents.article_writer
"""
from __future__ import annotations

import sys
import textwrap
from datetime import datetime
from pathlib import Path

import anthropic

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import (
    MODEL,
    SELECTION_NOTES_FILE,
    LEARNINGS_FILE,
    DAILY_ARTICLES_FILE,
    VOICE_FILE,
    EMPTY_SELECTION,
    read_file,
    ensure_data_dir,
)
from agents.utils import replace_latest_entry, extract_source_url, stream_to_stdout


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a ghostwriter for a senior professional who wants to sound like
themselves — not like a consultant, not like a TED talk, not like HBR.

## Voice
- Mix short punchy sentences with longer ones. One sentence can be four words. Let it sit.
- Name the tension before resolving it. A moment of genuine uncertainty beats false confidence.
- One concrete detail or scenario that makes the abstract real.
- CTA question MUST emerge from this post's sharpest insight — not the brief's suggestion.
  Ask: "What's the most specific question only THIS post could ask?" Generic CTA = rewrite it.

## What kills the human feeling
- Smooth transitions ("This distinction matters.", "Therefore,") and polished conclusions
- Abstract noun stacks (organisational leadership capability frameworks)
- Any sentence that could appear in a McKinsey deck without edits

## Framing direction — hin zu, not weg von
- Lead with the positive alternative: what becomes possible, what the better version looks like.
- Critique is the *enabler*, not the argument. "When you build toward X, Y naturally falls away" — not "Y is broken, let's fix it."
- Never open with or centre on what's broken. Centre on what opens up.
- Test: could the post be summarised as "more X, more Y" rather than "less A, less B"? If not, reframe.

## Hard rules
- 200–290 words (not counting hashtags)
- No bullet-point listicles — flowing paragraphs only
- No hollow phrases: "In today's fast-paced world", "As leaders, we must...", "game-changer", "leverage", "synergy"
- No unverifiable first-person claims ("I've seen...", "In my experience...")
- Do not invent statistics — only use figures from the brief
- Never mention the author's employer or any company name
- 5 hashtags at the very end
- Output the post text ONLY — no title, no commentary
"""


def build_user_message(selection: str, learnings: str, voice: str,
                       redteam_feedback: str = "") -> str:
    today = datetime.now().strftime("%A, %B %d, %Y")
    redteam_section = (
        f"\n        ## Red Team Feedback (mandatory — address every point)\n        {redteam_feedback}"
        if redteam_feedback.strip() else ""
    )
    return textwrap.dedent(f"""
        Today is {today}.

        ## Author's Voice & Style Guide
        {voice or "_No voice guide yet — apply the system prompt guidelines._"}

        ## Feedback from Past Posts (apply these lessons)
        {learnings or "_None yet._"}
        {redteam_section}

        ## Article Brief
        {selection}

        ---

        Write the LinkedIn post now. Follow the brief and the voice guide.
        The post should sound like this specific person — thoughtful, direct,
        a little warm, never corporate. Output the post text only.
    """).strip()


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

def run(client: anthropic.Anthropic | None = None,
        redteam_feedback: str = "",
        revision: bool = False) -> str:
    """
    Run the article writer agent. Returns the finished post as a string.
    Pass an existing Anthropic client or one will be created.
    """
    ensure_data_dir()

    if client is None:
        client = anthropic.Anthropic()

    print("✍️  Article Writer Agent starting...")

    selection = read_file(SELECTION_NOTES_FILE)
    learnings = read_file(LEARNINGS_FILE)
    voice     = read_file(VOICE_FILE)

    if not selection.strip() or EMPTY_SELECTION in selection:
        raise RuntimeError("No selection notes found. Run the Selection agent first.")

    print("\n  Writing LinkedIn post with Claude...\n")
    print("-" * 60)

    user_message = build_user_message(selection, learnings, voice, redteam_feedback)

    post = stream_to_stdout(
        client,
        model=MODEL,
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    print("-" * 60 + "\n")

    # Extract topic title from selection notes for the log header
    topic_title = "Untitled"
    for line in selection.splitlines():
        if line.startswith("## Selected Topic:"):
            topic_title = line.replace("## Selected Topic:", "").strip()
            break

    # Extract source domain from selection notes for tracking
    import re as _re
    source_domain = ""
    for line in selection.splitlines():
        m = _re.search(r"\*\*(?:Source )?[Dd]omain:\*\*\s*(\S+)", line)
        if m:
            source_domain = m.group(1).strip("*").strip()
            break

    if revision:
        replace_latest_entry(post, topic_title, status="draft")
        print(f"  ✅ Post revised in {DAILY_ARTICLES_FILE}")
    else:
        today_str = datetime.now().strftime("%Y-%m-%d")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        source_tag = f" | Source domain: {source_domain}" if source_domain else ""
        entry = (
            f"\n---\n\n"
            f"## {today_str} — {topic_title}\n\n"
            f"_Written: {timestamp} | Status: draft{source_tag}_\n\n"
            f"{post}\n"
        )
        with open(DAILY_ARTICLES_FILE, "a", encoding="utf-8") as f:
            f.write(entry)
        print(f"  ✅ Post appended to {DAILY_ARTICLES_FILE}")
    return post


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run()
