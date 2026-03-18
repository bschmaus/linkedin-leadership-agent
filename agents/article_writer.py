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
    read_file,
    ensure_data_dir,
)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a ghostwriter for a senior professional who wants to
sound like themselves — not like a consultant, not like a TED talk, not like HBR.

Your job is to write a LinkedIn post that feels like it was written by a real person
who thinks carefully, cares about the topic, and isn't performing expertise.

## What makes it feel human
- Sentence rhythm that breathes: mix short punchy sentences with longer ones.
  One sentence can be four words. Let it sit.
- Name the tension before you resolve it. Good thinking acknowledges complexity.
- One small, concrete detail or scenario that makes the abstract feel real.
- A moment of genuine uncertainty is more credible than false confidence.
- It's okay to start a sentence with "And" or "But" when it fits.
- The ending question should feel like genuine curiosity, not a fishing hook.

## What kills the human feeling
- Smooth, essay-style transitions ("This distinction matters.", "Therefore,")
- Building to a polished conclusion — real thinking has edges
- Abstract nouns stacked on each other (organisational leadership capability frameworks)
- Sounding like you have all the answers
- Any sentence that could appear in a McKinsey deck without edits

## Hard rules
- 250–400 words (not counting hashtags)
- No bullet-point listicles — flowing paragraphs only
- No hollow phrases: "In today's fast-paced world", "As leaders, we must...",
  "It's more important than ever", "game-changer", "leverage", "synergy"
- No unverifiable first-person claims ("I've seen...", "In my experience...")
- Do not invent statistics — only use figures from the brief
- Never mention the author's employer or any company name they work for
- 5 hashtags at the very end
- Output the post text ONLY — no title, no "Here's the post:", no commentary
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
# Helpers
# ---------------------------------------------------------------------------

def _replace_latest_entry(post: str, topic_title: str) -> None:
    """Overwrite the most recent post entry — used during red team revision iterations."""
    content = read_file(DAILY_ARTICLES_FILE)
    idx = content.rfind("\n---\n")
    base = content[:idx] if idx != -1 else content
    today_str  = datetime.now().strftime("%Y-%m-%d")
    timestamp  = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = (
        f"\n---\n\n"
        f"## {today_str} — {topic_title}\n\n"
        f"_Written: {timestamp} | Status: draft_\n\n"
        f"{post}\n"
    )
    DAILY_ARTICLES_FILE.write_text(base + entry, encoding="utf-8")


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

    if not selection.strip() or "_No selection yet._" in selection:
        print("  ⚠️  No selection notes found. Run the Selection agent first.")
        return ""

    print("\n  Writing LinkedIn post with Claude...\n")
    print("-" * 60)

    user_message = build_user_message(selection, learnings, voice, redteam_feedback)
    collected = []

    with client.messages.stream(
        model=MODEL,
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        for text in stream.text_stream:
            print(text, end="", flush=True)
            collected.append(text)

    print("\n" + "-" * 60 + "\n")
    post = "".join(collected).strip()

    # Extract topic title from selection notes for the log header
    topic_title = "Untitled"
    for line in selection.splitlines():
        if line.startswith("## Selected Topic:"):
            topic_title = line.replace("## Selected Topic:", "").strip()
            break

    if revision:
        _replace_latest_entry(post, topic_title)
        print(f"  ✅ Post revised in {DAILY_ARTICLES_FILE}")
    else:
        today_str = datetime.now().strftime("%Y-%m-%d")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = (
            f"\n---\n\n"
            f"## {today_str} — {topic_title}\n\n"
            f"_Written: {timestamp} | Status: draft_\n\n"
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
