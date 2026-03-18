# LinkedIn Leadership Inspiration Agent — Project Spec

## Overview
A daily automated pipeline that researches, selects, writes, posts, and assesses
LinkedIn leadership inspiration posts. Agents communicate via shared markdown files
and are orchestrated sequentially.

## Tech Stack
- Python 3.11+
- Anthropic SDK (`anthropic`) — model: `claude-opus-4-6`
- Notion MCP for saving articles and learnings
- RSS feeds for research input (via `feedparser`)
- LinkedIn API (or manual posting fallback)

---

## Folder Structure

```
linkedin-leadership-agent/
├── PROJECT_SPEC.md
├── orchestrator.py           # Runs all agents in sequence
├── config.py                 # Paths, model name, env vars
├── requirements.txt
├── .env.example
├── agents/
│   ├── __init__.py
│   ├── scanning.py           # Scans RSS feeds → research_notes.md
│   ├── selection.py          # Selects best topic → selection_notes.md
│   ├── article_writer.py     # Writes LinkedIn post → daily_articles.md
│   ├── poster.py             # Posts to LinkedIn (or prints for manual posting)
│   ├── red_team.py           # Critiques post → redteam_notes.md; triggers re-runs
│   ├── assessment.py         # Assesses post quality → learnings.md
│   ├── image_generator.py    # Generates image cards (Pillow / DALL-E)
│   ├── analytics_reader.py   # Reads LinkedIn analytics export
│   └── utils.py              # Shared utilities
└── data/
    ├── learnings.md           # Assessment writes; ALL agents read at start
    ├── daily_articles.md      # Article writer appends; all agents read
    ├── research_notes.md      # Scanning writes; selection reads
    ├── selection_notes.md     # Selection writes; article_writer reads
    ├── voice.md               # Manual; selection/article_writer/poster read
    ├── post_assets.md         # Poster writes; red_team/assessment read
    └── redteam_notes.md       # Red team writes; review only
```

---

## Shared Files (Agent Memory)

| File                    | Written by    | Read by    | Purpose                                      |
|-------------------------|---------------|------------|----------------------------------------------|
| data/learnings.md       | assessment    | all agents | Accumulated feedback & style improvements    |
| data/daily_articles.md  | article_writer| all agents | History of past posts (avoid repetition)     |
| data/research_notes.md  | scanning      | selection  | Today's research findings                    |
| data/selection_notes.md | selection     | article_writer | Chosen topic, angle, key points          |
| data/voice.md           | (manual)      | selection, article_writer, poster | Author identity, audience, and writing style |
| data/post_assets.md     | poster        | red_team, assessment | Format decision and image asset path  |
| data/redteam_notes.md   | red_team      | (review only) | Iteration history per post               |

---

## Agent Descriptions

### 1. Scanning Agent (`agents/scanning.py`)
**Input:** RSS feeds list, `data/learnings.md`, `data/daily_articles.md`
**Output:** `data/research_notes.md`

- Fetches latest articles from a curated list of RSS feeds (leadership, management, business)
- Uses Claude to extract and summarize 3–5 compelling leadership angles from the feed content
- Avoids topics already covered (checks `daily_articles.md`)
- Considers style feedback from `learnings.md`
- Default RSS feeds:
  - https://hbr.org/rss/topic/leadership
  - https://feeds.feedburner.com/mckinsey/all
  - https://www.forbes.com/leadership/feed/
- Writes structured markdown to `research_notes.md`

### 2. Selection Agent (`agents/selection.py`)
**Input:** `data/research_notes.md`, `data/daily_articles.md`, `data/learnings.md`, `data/voice.md` (identity/audience sections only)
**Output:** `data/selection_notes.md`

- Reviews all research candidates
- Picks the single best topic for today's post
- Considers: recency, uniqueness vs. past articles, engagement potential, learnings
- Reads the identity and audience sections of `voice.md` so editorial judgement is informed by who the author is and who they write for
- Writes: chosen topic, angle, 3–5 key talking points, suggested hook/opening line

### 3. Article Writer Agent (`agents/article_writer.py`)
**Input:** `data/selection_notes.md`, `data/learnings.md`
**Output:** Appends new entry to `data/daily_articles.md`

- Writes a full LinkedIn post (250–400 words)
- LinkedIn format: strong hook, 3–5 insight paragraphs, CTA, 5 hashtags
- Uses `learnings.md` to improve tone, style, structure over time
- Appends the post with date/topic header to `daily_articles.md`

### 4. Poster Agent (`agents/poster.py`)
**Input:** Latest entry from `data/daily_articles.md`, `data/learnings.md`, `data/voice.md`
**Output:** Posts to LinkedIn OR prints formatted post for manual copy-paste; writes `data/post_assets.md`

- Primary: LinkedIn API via `requests` (requires LINKEDIN_ACCESS_TOKEN env var)
- Fallback: Pretty-prints the post to console with copy instructions
- Records posting status back into `daily_articles.md`
- Reads `learnings.md` for format decisions (e.g. accumulated feedback on which formats work for which content types)
- Writes `post_assets.md` with the chosen format and image asset path

### 4.5. Red Team Agent (`agents/red_team.py`)
**Input:** `data/daily_articles.md`, `data/post_assets.md`, `data/selection_notes.md`, `data/learnings.md`, `data/voice.md`, source article (fetched live)
**Output:** `data/redteam_notes.md` (critique history); triggers article_writer and poster re-runs

- Evaluates the post through two lenses:
  1. **Factual integrity** — verifies claims against the live-fetched source article; checks internal consistency with the brief
  2. **Client perception** — applies a high bar: C-level, CHRO, and transformation leads are the intended audience; senior consulting clients have a fine-tuned bullshit detector
- Issues a verdict: `APPROVED` or `REVISE`
- On `REVISE`: always triggers an article_writer re-run with critique injected as a mandatory section; triggers a poster re-run only if format or assets are flagged (cost-proportionate)
- Maximum 3 iterations; on reaching the limit, outputs the best available version
- `APPROVED` verdict exits the loop early
- Appends full critique and verdict to `redteam_notes.md` for each iteration

### 5. Assessment Agent (`agents/assessment.py`)
**Input:** Latest entry from `data/daily_articles.md`, optional engagement metrics
**Output:** Appends to `data/learnings.md`

- Qualitatively assesses the post: hook strength, clarity, CTA, LinkedIn best practices
- If engagement metrics provided (likes, comments, shares), incorporates them
- Extracts 2–3 concrete improvement rules for future posts
- Appends dated entry to `learnings.md`

---

## Orchestrator (`orchestrator.py`)

```bash
python3 orchestrator.py                         # full pipeline
python3 orchestrator.py --from scan             # restart from scanning
python3 orchestrator.py --from write            # restart from article writer
python3 orchestrator.py --from redteam          # re-run red team + assessment only
python3 orchestrator.py --only post             # regenerate image/assets only
python3 orchestrator.py --only post --creative  # use DALL-E instead of typography card
python3 orchestrator.py --only assess           # re-run assessment after analytics upload
Available agent names: scan, select, write, post, redteam, assess
```

---

## config.py

```python
from pathlib import Path

BASE_DIR            = Path(__file__).parent
DATA_DIR            = BASE_DIR / "data"
ASSETS_DIR          = BASE_DIR / "assets"

LEARNINGS_FILE       = DATA_DIR / "learnings.md"
DAILY_ARTICLES_FILE  = DATA_DIR / "daily_articles.md"
RESEARCH_NOTES_FILE  = DATA_DIR / "research_notes.md"
SELECTION_NOTES_FILE = DATA_DIR / "selection_notes.md"
VOICE_FILE           = DATA_DIR / "voice.md"
POST_ASSETS_FILE     = DATA_DIR / "post_assets.md"
REDTEAM_NOTES_FILE   = DATA_DIR / "redteam_notes.md"

MODEL = "claude-opus-4-6"

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

RSS_FEEDS = [
    "https://hbr.org/rss/topic/leadership",
    "https://feeds.feedburner.com/mckinsey/all",
    "https://www.forbes.com/leadership/feed/",
]
```

---

## Environment Variables (`.env`)

```
ANTHROPIC_API_KEY=sk-ant-...
LINKEDIN_ACCESS_TOKEN=          # Optional: for auto-posting
LINKEDIN_PERSON_URN=            # Optional: urn:li:person:...
```

---

## requirements.txt

```
anthropic
feedparser
requests
python-dotenv
```

---

## Build Order

1. `agents/scanning.py` — RSS feed scanning + Claude summarization
2. `agents/selection.py` — topic selection
3. `agents/article_writer.py` — LinkedIn post writing
4. `agents/poster.py` — posting / manual fallback
5. `agents/red_team.py` — factual + client-perception critique loop
6. `agents/utils.py` — shared utilities (file I/O, HTTP helpers)
7. `agents/assessment.py` — quality assessment + learnings
8. `orchestrator.py` — wire everything together
9. `config.py` + data file initialization

---

## Notes
- All agents read `learnings.md` first — this is the continuous improvement loop
- `daily_articles.md` is append-only — full history, never overwritten
- `research_notes.md` and `selection_notes.md` are overwritten daily
- Agents should be independently runnable (not just via orchestrator)
- Use streaming for all Claude calls
- Use `thinking: {"type": "adaptive"}` for selection, poster, and red_team agents (not assessment)
