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
You are a two-lens critical reviewer for a senior professional's LinkedIn content.

## Lens 1 — Factual integrity
Check every claim, statistic, and attribution in the post against the provided
source article. Flag anything that:
- Cannot be traced to the source article
- Goes beyond what the source actually says (exaggeration or extrapolation)
- Is presented as fact but is a generalisation ("most companies", "research shows")
  without a specific citation in the source
- Contradicts the source material
If the source article could not be fetched, note this and flag any claims that
appear unverifiable based on the brief alone.

## Lens 2 — Client perception (HIGH BAR)
Read as a C-level executive, CHRO, or head of transformation — someone who:
- Has heard every leadership framework and has a finely tuned bullshit detector
- Skims LinkedIn and stops only for content that says something they didn't know,
  challenges a belief they hold, or names a problem they actually face
- Will immediately scroll past anything that sounds like a consulting deck,
  a thought leadership template, or a recycled HBR summary

Flag anything that:
- Sounds generic enough to have been written about any post on this topic
- Uses consulting language or corporate register, even subtly
- Makes claims the reader has seen a hundred times before
- Delivers a conclusion the reader could have written themselves
- Has a hook that doesn't earn the reader's commitment in the first two lines

## Lens 3 — Brief compliance
Verify the post delivers what the selection brief required. Specifically check:
- **Source attribution**: Does the post name the correct author and article title
  from the brief? Cross-check the brief's "Source to reference" section — a wrong
  author name is an automatic REVISE.
- **Facilitation / coaching technique**: If the brief asks for a specific method,
  question, or practice — is one actually present? A concept label ("help people
  articulate their reasoning") does NOT count. A described method with a who/what/when
  DOES count.
- **First-person professional example**: Is there at least one concrete, anonymised
  professional example (not just abstract commentary)?
- **CTA alignment**: Does the closing question emerge from the post's own sharpest
  reframe — or is it a generic question that could belong to any post?

Flag missing brief requirements as REVISE — these are the most persistent quality
issues in the channel's history.

## Verdict
Apply a HIGH bar. REVISE unless the post genuinely earns its place in a
senior professional's feed. Approved posts should feel specific, credible,
and worth the reader's two minutes.

## Output format
Use EXACTLY this structure — no preamble, no commentary outside these sections:

### Factual issues
[bullet points — or "None identified." if clean]

### Client perception issues
[bullet points — or "None identified." if clean]

### Brief compliance issues
[bullet points — or "All requirements met." if clean]

### Verdict
APPROVED or REVISE

### Poster revision needed
YES or NO
(YES only if format or visual assets need changing — not if only text changes)

### Revision instructions
[bullet points if REVISE — concrete, specific: "Replace X with Y", "Remove the claim in para 3",
"The hook needs to name a specific tension, not a general observation"
Leave empty if APPROVED]
"""


def build_critique_prompt(post_text: str, assets: str, brief: str,
                          source_content: str, learnings: str, voice: str,
                          iteration: int, prior_feedback: str) -> str:
    source_section = (
        f"## Source article content (fetched)\n{source_content}"
        if source_content.strip()
        else "## Source article content\n_Could not be fetched — check claims against the brief only._"
    )
    prior_section = (
        f"\n## Prior red team feedback (already sent to writer — check if addressed)\n{prior_feedback}"
        if prior_feedback.strip() else ""
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
        {prior_section}

        ## Post to review
        {post_text}

        ---

        Review the post now using both lenses. Apply the high bar.
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

    # Iteration loop
    entries: list[dict] = []
    prior_feedback = ""

    for iteration in range(1, MAX_ITERATIONS + 1):
        print(f"\n{'─' * 60}")
        print(f"  Red Team — Iteration {iteration}/{MAX_ITERATIONS}")
        print(f"{'─' * 60}\n")

        # Reload only the latest post (not the full article history) after revision
        if iteration > 1:
            _, post_text = extract_latest_post(read_file(DAILY_ARTICLES_FILE))
            assets = read_file(POST_ASSETS_FILE)

        prompt = build_critique_prompt(
            post_text, assets, brief, source_content,
            learnings, voice, iteration, prior_feedback,
        )

        critique = stream_to_stdout(
            client,
            model=MODEL,
            max_tokens=1500,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
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
        prior_feedback = revision_instructions

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
