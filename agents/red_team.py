"""
Red Team Agent
--------------
Challenges the post from two angles before it goes live:

  1. Factual integrity — verifies claims against the fetched source article;
     flags unverifiable stats, unsupported generalisations, and claims that
     contradict or go beyond the source material.

  2. Client lens — evaluates how a C-level executive, CHRO, or transformation
     lead would actually read this. High bar: would a senior client find genuine
     value here, or would it read as generic consulting content?

Iterates with article_writer (and optionally poster) up to 3 times until the
post is approved or the cap is reached.

Reads  : data/daily_articles.md   (current post draft)
         data/post_assets.md      (format + asset decision)
         data/selection_notes.md  (original brief + source URL)
         data/learnings.md        (accumulated feedback)
         data/voice.md            (author identity & audience)
         [source article]         (fetched live via requests)
Writes : data/redteam_notes.md   (full iteration history)
         [triggers article_writer and poster re-runs on REVISE]

Run standalone:
    python -m agents.red_team
"""
from __future__ import annotations

import re
import sys
import textwrap
from datetime import datetime
from pathlib import Path

import anthropic
import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import (
    MODEL,
    DAILY_ARTICLES_FILE,
    SELECTION_NOTES_FILE,
    LEARNINGS_FILE,
    VOICE_FILE,
    POST_ASSETS_FILE,
    REDTEAM_NOTES_FILE,
    BROWSER_HEADERS,
    read_file,
    ensure_data_dir,
)
from agents.utils import extract_latest_post, extract_source_url, strip_html, stream_to_stdout

MAX_ITERATIONS   = 3
SOURCE_MAX_CHARS = 6000   # chars of source article to pass as context


# ---------------------------------------------------------------------------
# Web fetch
# ---------------------------------------------------------------------------

def fetch_source(url: str) -> str:
    """Fetch and extract readable text from a URL. Returns empty string on failure."""
    if not url:
        return ""
    try:
        resp = requests.get(url, headers=BROWSER_HEADERS, timeout=12, allow_redirects=True)
        resp.raise_for_status()
        return strip_html(resp.text)[:SOURCE_MAX_CHARS]
    except Exception as exc:
        print(f"  ⚠️  Could not fetch source ({url}): {exc}")
        return ""


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a critical reviewer for a senior professional's LinkedIn content.

## Lens 1 — Factual integrity
Check every claim against the source article. Flag:
- Claims untraceable to the source, or that extrapolate beyond what it says
- Generalisations presented as fact ("most companies", "research shows") without a source citation
- Anything that contradicts the source
If the source could not be fetched, note this and flag unverifiable claims against the brief.

## Lens 2 — Client perception (HIGH BAR)
Read as a C-level executive, CHRO, or transformation lead with a finely tuned bullshit detector.
Flag anything that:
- Is generic enough to fit any post on this topic
- Uses consulting language or corporate register, even subtly
- Has a hook that doesn't earn the reader's commitment in the first two lines
- Delivers a conclusion the reader could have written themselves
- Centres on critique or abolition without naming the positive alternative — "weg von" not "hin zu".
  A post may criticise, but the positive aspiration must be the centre of gravity.
  Test: can the post be summarised as "more X, more Y" rather than "less A, less B"?

## Lens 3 — Brief compliance
- **Source attribution**: Correct author and article title from the brief? Wrong author = automatic REVISE.
- **Facilitation / coaching technique**: If the brief requires a specific method — is one described with who/what/when? A concept label does NOT count.
- **Professional example**: At least one concrete, anonymised professional example (not abstract commentary).
- **CTA alignment**: Does the closing question emerge from this post's sharpest reframe — or is it generic?

Missing brief requirements = REVISE. These are the channel's most persistent quality issues.

## Verdict
HIGH bar. REVISE unless the post genuinely earns its place in a senior professional's feed.

## Output format — use EXACTLY this structure, no preamble:

### Factual issues
[bullets — or "None identified."]

### Client perception issues
[bullets — or "None identified."]

### Brief compliance issues
[bullets — or "All requirements met."]

### Verdict
APPROVED or REVISE

### Poster revision needed
YES or NO
(YES only if format or visual assets need changing — not if only text changes)

### Revision instructions
[bullets if REVISE — concrete: "Replace X with Y", "Remove claim in para 3". Empty if APPROVED]
"""


def build_critique_prompt(post_text: str, assets: str, brief: str,
                          source_content: str, learnings: str, voice: str,
                          iteration: int) -> str:
    """Build the initial (iteration 1) critique prompt with full context."""
    source_section = (
        f"## Source article content (fetched)\n{source_content}"
        if source_content.strip()
        else "## Source article content\n_Could not be fetched — check claims against the brief only._"
    )
    return textwrap.dedent(f"""
        Iteration {iteration} of {MAX_ITERATIONS}.

        ## Original brief
        {brief or "_Not available._"}

        ## Author identity & audience
        {voice or "_Not provided._"}

        {source_section}

        ## Format & asset decision
        {assets or "_Not available._"}

        ## Accumulated learnings from past posts
        {learnings or "_None yet._"}

        ## Post to review
        {post_text}

        ---

        Review the post now using all three lenses. Apply the high bar.
    """).strip()


def build_revision_prompt(post_text: str, assets: str, iteration: int) -> str:
    """Build a follow-up prompt for iteration 2+. Only sends what changed."""
    return textwrap.dedent(f"""
        The post has been revised. This is iteration {iteration} of {MAX_ITERATIONS}.

        ## Updated format & asset decision
        {assets or "_Not available._"}

        ## Revised post
        {post_text}

        ---

        Re-review using all three lenses. Apply the same high bar.
    """).strip()


# ---------------------------------------------------------------------------
# Parse critique output
# ---------------------------------------------------------------------------

def _extract_section(text: str, heading: str) -> str:
    """Extract content under a ### heading."""
    pattern = rf"### {re.escape(heading)}\s*\n(.*?)(?=\n###|\Z)"
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1).strip() if match else ""


def parse_verdict(critique: str) -> str:
    section = _extract_section(critique, "Verdict")
    return "APPROVED" if "APPROVED" in section.upper() else "REVISE"


def parse_poster_flag(critique: str) -> bool:
    section = _extract_section(critique, "Poster revision needed")
    return "YES" in section.upper()


def parse_revision_instructions(critique: str) -> str:
    factual  = _extract_section(critique, "Factual issues")
    client   = _extract_section(critique, "Client perception issues")
    instruct = _extract_section(critique, "Revision instructions")
    parts = []
    if factual and "none identified" not in factual.lower():
        parts.append(f"**Factual issues to fix:**\n{factual}")
    if client and "none identified" not in client.lower():
        parts.append(f"**Client perception issues to fix:**\n{client}")
    if instruct:
        parts.append(f"**Specific revision instructions:**\n{instruct}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Persist red team notes
# ---------------------------------------------------------------------------

def save_redteam_notes(title: str, entries: list[dict]) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"# Red Team Notes — {timestamp}", f"\n## Post: {title}\n"]
    for e in entries:
        lines += [
            f"---\n",
            f"### Iteration {e['iteration']}",
            f"\n{e['critique']}\n",
        ]
    if entries:
        last = entries[-1]
        verdict = parse_verdict(last["critique"])
        if verdict == "APPROVED":
            lines.append(f"\n✅ Approved after {len(entries)} iteration(s).")
        else:
            lines.append(f"\n⚠️  Max iterations reached — proceeding with best available version.")
    REDTEAM_NOTES_FILE.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

def run(client: anthropic.Anthropic | None = None) -> str:
    """
    Run the Red Team agent loop. Returns the final approved (or best) post text.
    Pass an existing Anthropic client or one will be created.
    """
    ensure_data_dir()

    if client is None:
        client = anthropic.Anthropic()

    print("🔴 Red Team Agent starting...")

    # Load inputs (only extract latest post — not the full article history)
    title, post_text = extract_latest_post(read_file(DAILY_ARTICLES_FILE))
    assets    = read_file(POST_ASSETS_FILE)
    brief     = read_file(SELECTION_NOTES_FILE)
    learnings = read_file(LEARNINGS_FILE)
    voice     = read_file(VOICE_FILE)
    if not post_text:
        raise RuntimeError("No post found. Run the Article Writer agent first.")

    # Fetch source article
    source_url = extract_source_url(brief)
    print(f"\n  Post    : {title}")
    if source_url:
        print(f"  Fetching source: {source_url}")
        source_content = fetch_source(source_url)
        if source_content:
            print(f"  ✅ Source fetched ({len(source_content)} chars)")
        else:
            print("  ⚠️  Source fetch failed — fact-checking against brief only")
    else:
        source_content = ""
        print("  ⚠️  No source URL found in selection notes")

    # Iteration loop — uses multi-turn conversation so static context
    # (brief, voice, source, learnings) is only sent once on iteration 1.
    entries: list[dict] = []
    messages: list[dict] = []

    for iteration in range(1, MAX_ITERATIONS + 1):
        print(f"\n{'─' * 60}")
        print(f"  Red Team — Iteration {iteration}/{MAX_ITERATIONS}")
        print(f"{'─' * 60}\n")

        # Reload only the latest post (not the full article history) after revision
        if iteration > 1:
            _, post_text = extract_latest_post(read_file(DAILY_ARTICLES_FILE))
            assets = read_file(POST_ASSETS_FILE)
            # Append previous critique + new revision request (no static context repeat)
            messages.append({"role": "assistant", "content": entries[-1]["critique"]})
            messages.append({"role": "user", "content": build_revision_prompt(post_text, assets, iteration)})
        else:
            # First iteration: send full context once
            messages = [{"role": "user", "content": build_critique_prompt(
                post_text, assets, brief, source_content, learnings, voice, iteration,
            )}]

        critique = stream_to_stdout(
            client,
            model=MODEL,
            max_tokens=1500,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            messages=messages,
        )

        # Guard: empty critique (e.g. API timeout) — skip iteration, don't trigger false REVISE
        if not critique:
            print(f"  ⚠️  Iteration {iteration} returned empty critique — skipping")
            break

        entries.append({"iteration": iteration, "critique": critique})
        save_redteam_notes(title, entries)

        verdict = parse_verdict(critique)

        if verdict == "APPROVED":
            print(f"  ✅ APPROVED on iteration {iteration}")
            break

        if iteration == MAX_ITERATIONS:
            print(f"  ⚠️  Max iterations reached — proceeding with current version")
            break

        # REVISE — re-run article_writer (and poster if flagged)
        revision_instructions = parse_revision_instructions(critique)
        poster_needs_revision = parse_poster_flag(critique)

        print(f"\n  ↩️  REVISE — re-running Article Writer (iteration {iteration + 1})...")
        from agents.article_writer import run as write_article
        write_article(client, redteam_feedback=revision_instructions, revision=True)

        if poster_needs_revision:
            print(f"  ↩️  Re-running Poster (format/assets flagged)...")
            from agents.poster import run as run_poster
            run_poster(client)

    print(f"\n  ✅ Red Team notes saved to {REDTEAM_NOTES_FILE}")
    _, final_post = extract_latest_post(read_file(DAILY_ARTICLES_FILE))
    return final_post


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run()
