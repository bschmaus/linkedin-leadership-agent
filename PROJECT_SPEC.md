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
│   └── assessment.py         # Assesses post quality → learnings.md
└── data/
    ├── learnings.md           # Assessment writes; ALL agents read at start
    ├── daily_articles.md      # Article writer appends; all agents read
    ├── research_notes.md      # Scanning writes; selection reads
    └── selection_notes.md     # Selection writes; article_writer reads
```

---

## Shared Files (Agent Memory)

| File                    | Written by    | Read by    | Purpose                                      |
|-------------------------|---------------|------------|----------------------------------------------|
| data/learnings.md       | assessment    | all agents | Accumulated feedback & style improvements    |
| data/daily_articles.md  | article_writer| all agents | History of past posts (avoid repetition)     |
| data/research_notes.md  | scanning      | selection  | Today's research findings                    |
| data/selection_notes.md | selection     | article_writer | Chosen topic, angle, key points          |

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
**Input:** `data/research_notes.md`, `data/daily_articles.md`, `data/learnings.md`
**Output:** `data/selection_notes.md`

- Reviews all research candidates
- Picks the single best topic for today's post
- Considers: recency, uniqueness vs. past articles, engagement potential, learnings
- Writes: chosen topic, angle, 3–5 key talking points, suggested hook/opening line

### 3. Article Writer Agent (`agents/article_writer.py`)
**Input:** `data/selection_notes.md`, `data/learnings.md`
**Output:** Appends new entry to `data/daily_articles.md`

- Writes a full LinkedIn post (250–400 words)
- LinkedIn format: strong hook, 3–5 insight paragraphs, CTA, 5 hashtags
- Uses `learnings.md` to improve tone, style, structure over time
- Appends the post with date/topic header to `daily_articles.md`

### 4. Poster Agent (`agents/poster.py`)
**Input:** Latest entry from `data/daily_articles.md`
**Output:** Posts to LinkedIn OR prints formatted post for manual copy-paste

- Primary: LinkedIn API via `requests` (requires LINKEDIN_ACCESS_TOKEN env var)
- Fallback: Pretty-prints the post to console with copy instructions
- Records posting status back into `daily_articles.md`

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
python orchestrator.py                   # Full pipeline
python orchestrator.py --skip-posting    # Stop before posting (draft mode)
python orchestrator.py --assess-only     # Run only assessment agent
python orchestrator.py --from selection  # Resume from a specific step
```

---

## config.py

```python
from pathlib import Path

BASE_DIR            = Path(__file__).parent
DATA_DIR            = BASE_DIR / "data"

LEARNINGS_FILE      = DATA_DIR / "learnings.md"
DAILY_ARTICLES_FILE = DATA_DIR / "daily_articles.md"
RESEARCH_NOTES_FILE = DATA_DIR / "research_notes.md"
SELECTION_NOTES_FILE = DATA_DIR / "selection_notes.md"

MODEL = "claude-opus-4-6"

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
5. `agents/assessment.py` — quality assessment + learnings
6. `orchestrator.py` — wire everything together
7. `config.py` + data file initialization

---

## Notes
- All agents read `learnings.md` first — this is the continuous improvement loop
- `daily_articles.md` is append-only — full history, never overwritten
- `research_notes.md` and `selection_notes.md` are overwritten daily
- Agents should be independently runnable (not just via orchestrator)
- Use streaming for all Claude calls
- Use `thinking: {"type": "adaptive"}` for selection and assessment agents
