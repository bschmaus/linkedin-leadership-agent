"""
Proofreading Agent
------------------
Lightweight final pass after the Red Team loop. Catches typos, grammar errors,
and formatting issues in the published-ready text without changing content or tone.

Uses Sonnet (fast + cheap) — this is a mechanical check, not a reasoning task.

Reads  : data/daily_articles.md   (latest post)
Writes : data/daily_articles.md   (overwrites latest entry with corrected text)

Run standalone:
    python -m agents.proofread
"""
from __future__ import annotations

import sys
from pathlib import Path

import anthropic

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import (
    DAILY_ARTICLES_FILE,
    read_file,
    ensure_data_dir,
)
from agents.utils import extract_latest_post, replace_latest_entry

# Use Sonnet — proofreading is mechanical, not reasoning-heavy
MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """\
You are a professional proofreader. Your ONLY job is to fix:
- Spelling errors (e.g. "risiing" → "rising", "yoursef" → "yourself")
- Grammar mistakes
- Punctuation errors
- Inconsistent capitalisation
- Missing or extra spaces

Rules:
- Do NOT change the content, meaning, tone, word choice, or structure
- Do NOT add or remove sentences
- Do NOT rephrase for style — the voice is intentional
- Do NOT change hashtags
- If the text has zero errors, return it UNCHANGED
- Output ONLY the corrected post text — no commentary, no "Here's the corrected version"
"""

USER_PROMPT = """\
Proofread this LinkedIn post. Fix only typos, spelling, grammar, and punctuation.
Do not change content, tone, or structure. Output the corrected text only.

---

{post_text}
"""


def run(client: anthropic.Anthropic | None = None) -> str:
    """
    Run the proofreading agent. Returns the (possibly corrected) post text.
    """
    ensure_data_dir()

    if client is None:
        client = anthropic.Anthropic()

    print("🔍 Proofreading Agent starting...")

    title, post_text = extract_latest_post(read_file(DAILY_ARTICLES_FILE))

    if not post_text:
        raise RuntimeError("No post found to proofread.")

    print(f"  Checking: {title}")

    response = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": USER_PROMPT.format(post_text=post_text)}],
    )
    corrected = response.content[0].text.strip()

    # Check if anything changed
    if corrected == post_text.strip():
        print("  ✅ No typos found — text unchanged")
        return post_text

    # Count changes (rough diff)
    original_words = post_text.split()
    corrected_words = corrected.split()
    changes = sum(1 for a, b in zip(original_words, corrected_words) if a != b)
    changes += abs(len(original_words) - len(corrected_words))

    print(f"  ✏️  {changes} correction(s) applied")
    replace_latest_entry(corrected, title, status="proofread")
    print(f"  ✅ Corrected text saved to {DAILY_ARTICLES_FILE}")

    return corrected


if __name__ == "__main__":
    run()
