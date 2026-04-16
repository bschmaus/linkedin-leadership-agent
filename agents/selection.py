"""
Selection Agent
---------------
Reads today's research candidates and picks the single best topic
for today's LinkedIn post.

Reads  : data/research_notes.md   (candidates from the Scanning agent)
         data/daily_articles.md   (history — avoid repetition)
         data/learnings.md        (accumulated style & topic feedback)
         data/voice.md            (author identity & audience — identity/audience sections only)
Writes : data/selection_notes.md  (chosen topic + full brief for the Article Writer)

Uses adaptive thinking — this is the reasoning-heavy judgement call in the pipeline.

Run standalone:
    python -m agents.selection
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
    RESEARCH_NOTES_FILE,
    DAILY_ARTICLES_FILE,
    LEARNINGS_FILE,
    SELECTION_NOTES_FILE,
    VOICE_FILE,
    EMPTY_RESEARCH,
    read_file,
    ensure_data_dir,
)
from agents.utils import extract_author_context, extract_recent_history, extract_source_frequency, stream_to_stdout


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a senior editorial strategist for a LinkedIn thought
leadership channel focused on leadership, team collaboration, co-creation, and
coaching & facilitation.

Your job is to review a shortlist of research candidates and select exactly ONE
topic for today's post. You are the final editorial filter before writing begins.

Selection criteria (in order of priority):
1. Freshness — not covered in recent article history
2. Relevance — resonates with today's professional landscape
3. Pillar balance — over a week, posts should rotate across:
   • Individual leadership
   • Team collaboration / co-creation / self-organisation
   • Coaching & facilitation techniques
4. Source diversity — check the source frequency data below. If one source
   (e.g. fastcompany.com) has been used 3+ times recently, **strongly prefer**
   a candidate from an underrepresented source, even if the overused source's
   candidate is slightly stronger editorially. Source balance matters for
   credibility and breadth of perspective.
5. Depth potential — enough substance for a 200–290 word LinkedIn post
6. Source quality — grounded in a real, citable article
7. Positive framing potential — prefer candidates where a concrete positive alternative exists
   (what becomes possible, what the better version looks like). If the only available angle
   is "X is broken / should be abolished", pass unless you can identify a clear "hin zu" reframe.
   Critique is allowed as an enabler, not as the centre of gravity.

Hard rule: NEVER select a candidate sourced from McKinsey, BCG, Bain, PwC, EY,
Deloitte, or KPMG — these are direct competitors. If a candidate's only source is
a competitor firm, reject it regardless of content quality.
Oliver Wyman Forum is an approved and preferred source.

Output ONLY the structured brief. No preamble. No "I chose this because..." outside
the designated fields.
"""


def build_user_message(research: str, history: str, learnings: str,
                       author_context: str, source_freq: str) -> str:
    today = datetime.now().strftime("%A, %B %d, %Y")
    author_section = (
        f"## Author Identity & Audience\n{author_context}"
        if author_context else ""
    )
    freq_section = (
        f"## Source Frequency (last 14 posts)\n{source_freq}\n\n"
        "_Use this to avoid over-reliance on any single source. "
        "Prefer candidates from underrepresented sources when quality is comparable._"
        if source_freq else ""
    )
    return textwrap.dedent(f"""
        Today is {today}.

        {author_section}

        ## Accumulated Learnings & Style Feedback
        {learnings or "_None yet._"}

        ## Recent Article History (check for repetition)
        {history or "_No history yet._"}

        {freq_section}

        ## Today's Research Candidates
        {research}

        ---

        Review the candidates above and select the single best topic for today's post.

        Output this exact structure:

        ## Selected Topic: [Title]

        **Pillar:** [Individual Leadership | Team Collaboration & Co-Creation | Coaching & Facilitation]
        **Why this one today:** [2-3 sentences — editorial rationale, why now, why it fits the rotation]
        **Rejected candidates:** [One line per rejected candidate explaining why it was passed over]

        ---

        ## Brief for the Article Writer

        **Core message:** [The single insight the post must land — one sentence]
        **Angle:** [The specific perspective or framing]
        **Target reader:** [Who specifically this will resonate with]
        **Tone:** [e.g. Provocative / Warm & practical / Data-driven / Reflective]

        **Key points to cover:** (3-5 bullets the writer must hit)
        - ...

        **Suggested hook:** [Opening sentence — observation, question, or contrarian take.
        No personal claims like "I've seen..." or "The best leaders I know..."]

        **Suggested CTA:** [One closing question or call-to-action for LinkedIn comments]

        **Source to reference:**
        - Article: [title]
        - URL: [url]
        - Domain: [domain]

        **Hashtag territory:** [5 relevant hashtags]
    """).strip()


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

def run(client: anthropic.Anthropic | None = None) -> str:
    """
    Run the selection agent. Returns the selection notes as a string.
    Pass an existing Anthropic client or one will be created.
    """
    ensure_data_dir()

    if client is None:
        client = anthropic.Anthropic()

    print("🎯 Selection Agent starting...")

    research       = read_file(RESEARCH_NOTES_FILE)
    articles_raw   = read_file(DAILY_ARTICLES_FILE)
    history        = extract_recent_history(articles_raw, n=14)
    source_freq    = extract_source_frequency(articles_raw, n=14)
    learnings      = read_file(LEARNINGS_FILE)
    author_context = extract_author_context(read_file(VOICE_FILE))

    if not research.strip() or EMPTY_RESEARCH in research:
        raise RuntimeError("No research notes found. Run the Scanning agent first.")

    if source_freq:
        print(f"\n  📊 Source frequency (last 14 posts):\n{source_freq}\n")

    print("\n  Selecting best topic with Claude (adaptive thinking)...\n")
    user_message = build_user_message(research, history, learnings, author_context, source_freq)

    selection_output = stream_to_stdout(
        client,
        model=MODEL,
        max_tokens=3500,
        thinking={"type": "adaptive"},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    notes = f"# Selection Notes — {timestamp}\n\n{selection_output}\n"
    SELECTION_NOTES_FILE.write_text(notes, encoding="utf-8")
    print(f"  ✅ Selection notes written to {SELECTION_NOTES_FILE}")

    return selection_output


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run()
