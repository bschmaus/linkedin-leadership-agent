# Adapting This Pipeline

This document explains how to adapt the LinkedIn Leadership Agent for different content domains, different authors, or entirely different use cases.

There are three levels of adaptation — each progressively deeper.

---

## Level 1 — Config changes only (15 minutes)

Same pipeline, same code, different author and topic domain.

### What to change

**`data/voice.md`** — the most important file.

Write it in first person as a briefing to a ghostwriter. Include:
- Who you are and what you're known for
- Who your audience is
- The three topics you write about most
- Your sentence rhythm (examples from your past writing help enormously)
- Words and phrases you would never use
- What you want readers to feel after reading a post

**`config.py` — `RSS_FEEDS`**

Replace with feeds relevant to your domain. Any RSS feed works.

```python
RSS_FEEDS = [
    "https://your-domain-publication.com/feed",
    "https://industry-journal.com/rss",
]
```

**`config.py` — `EXTRA_SOURCES`**

Pages to scrape when no RSS is available (your employer's thought-leadership site, relevant research organisations).

```python
EXTRA_SOURCES = [
    "https://your-firm.com/insights",
]
```

**`agents/scanning.py` — Topic pillars**

In the `SYSTEM_PROMPT`, replace the three content pillars with your own:

```python
# Current:
# 1. Leadership: individual leader mindset, decision-making, vision, presence
# 2. Collaboration & co-creation: how teams work better...
# 3. Coaching & facilitation: techniques leaders and facilitators use...

# Replace with your pillars, e.g. for a finance professional:
# 1. Capital allocation: investment frameworks, portfolio construction...
# 2. Risk & resilience: tail risk, scenario planning...
# 3. Markets & macro: interest rate dynamics, central bank policy...
```

**`data/ow_brand_guidelines.md`** — personal visual style

Describe your preferred image aesthetic: background colour, accent colour, typography preferences. Used by the Poster agent when generating image briefs.

### What you do NOT need to change

- The pipeline logic (`orchestrator.py`)
- All agent `run()` functions
- The image generator (unless you want different colours — see `image_generator.py` palette constants)
- The analytics reader
- The scheduler plist files (just update the path to your project)

---

## Level 2 — Prompt-level adaptation (2–4 hours)

Same architecture, adjusted for a different content format or audience.

### Use case examples

**Weekly newsletter instead of daily LinkedIn posts**
- `scanning.py`: change cadence language ("this week's" vs "today's")
- `article_writer.py` SYSTEM_PROMPT: change length to 600–900 words, allow subheadings
- `poster.py`: remove format decision (newsletters don't need LinkedIn format logic); replace with subject line generation
- Orchestrator: change scheduler to weekly

**Podcast episode notes / talking points**
- `article_writer.py` SYSTEM_PROMPT: output bullet-point talking points instead of prose
- `poster.py`: generate chapter titles and timestamps instead of image card
- Assessment: evaluate listener value, not reader engagement

**Sales enablement content (B2B)**
- `scanning.py` SYSTEM_PROMPT: add "commercial relevance" as a fourth selection criterion
- `selection.py` SYSTEM_PROMPT: add ICP (ideal customer profile) fit as a selection criterion
- `article_writer.py` SYSTEM_PROMPT: add CTA towards a commercial action, allow case study format
- Assessment: add conversion intent as an evaluation dimension

### Key prompt variables to adapt

| Prompt location | What it controls | Change for |
|---|---|---|
| `scanning.py` SYSTEM_PROMPT | Topic universe, source priorities, banned sources | Different industry, different competitive context |
| `selection.py` SYSTEM_PROMPT | Selection criteria, pillar rotation rules | Different strategic goals, audience mix |
| `article_writer.py` SYSTEM_PROMPT | Word count, format rules, banned phrases, hard constraints | Different platform (newsletter, blog, Twitter/X) |
| `poster.py` FORMAT_SYSTEM | Available formats, visual style rules | Different platform formats |
| `assessment.py` SYSTEM_PROMPT | Evaluation dimensions, tone of feedback | Different quality criteria |

---

## Level 3 — Pattern-level reuse (1–2 days)

Use the same five-stage architecture for a completely different content domain.

### The abstract pattern

This system implements a **5-stage content pipeline with feedback memory**:

```
DISCOVER → SELECT → CREATE → PUBLISH → EVALUATE → (back to DISCOVER)
```

This pattern works for any recurring content creation task where:
- Sources change daily/weekly
- Quality should improve over time
- A consistent voice matters
- The output has a defined format

### Analogous use cases

| Use case | DISCOVER | SELECT | CREATE | PUBLISH | EVALUATE |
|---|---|---|---|---|---|
| LinkedIn thought leadership | RSS feeds | Best topic for today | LinkedIn post | Post manually | Analytics + quality |
| Company blog | Research papers, news | Most relevant to ICP | Blog article | CMS upload | Page views, leads |
| Investor newsletter | SEC filings, earnings | Key theme this week | Newsletter issue | Email platform | Open rate, clicks |
| Executive briefing | News, reports | Top 5 stories | 1-page brief | Email/Slack | Relevance rating |
| Sales outreach | CRM signals, news | Best timing per account | Personalised email | CRM send | Reply rate |
| Product changelog | Git commits, tickets | User-facing changes | Release notes | GitHub/Docs | User reactions |

### What to keep from this codebase

**`orchestrator.py`** — the pipeline runner is domain-agnostic. The `--from`, `--only` flags and the failure handling work for any pipeline.

**`config.py`** — the pattern of centralised file paths and shared config is reusable as-is.

**`assessment.py`** — the feedback loop structure (5 sections + append to learnings.md) works for any content type. Only the SYSTEM_PROMPT and evaluation criteria need changing.

**`analytics_reader.py`** — replace with whatever performance data source exists for your domain (email open rates, CRM data, web analytics).

**`image_generator.py`** — the Pillow typography card is domain-agnostic. Change the palette constants and font sizes for a different visual identity.

### What to rebuild

**`scanning.py`** — the source types determine everything here. If you're monitoring SEC filings, you need a different fetcher than RSS. If you're monitoring a database, replace feedparser with a SQL query.

**`poster.py`** — format decisions are platform-specific. LinkedIn has text/poll/image/carousel. An email newsletter has subject line/hero image/sections.

### Recommended sequence for a new domain

1. Copy this repo, rename it
2. Write `data/voice.md` for the new author/brand
3. Adapt `config.py` sources
4. Change the topic pillars in `scanning.py`
5. Run `python3 orchestrator.py --only scan` and inspect `data/research_notes.md`
6. Adapt `selection.py` criteria until selections feel right
7. Run `python3 orchestrator.py --from select` and inspect `data/daily_articles.md`
8. Tune `article_writer.py` until the voice is right
9. Run the full pipeline once and assess the output
10. Set up the scheduler — the feedback loop will handle the rest

---

## Guardrails to preserve in any adaptation

These are not LinkedIn-specific — they are good defaults for any automated content system:

**Source hygiene**
- Always maintain a list of banned sources (competitors, unreliable domains)
- Ground every output in a real, citable source — never let the model invent facts
- Track article history to avoid topic repetition

**Voice consistency**
- Keep a single `voice.md` as the source of truth for every writing agent
- Never describe the author's employer or company in the post unless it is strategically intentional
- Run the assessment against real performance data, not just subjective quality

**Human checkpoints**
- Keep at least one human step before anything goes to an external audience
- Give the human everything they need to decide in one place (the equivalent of `post_assets.md`)

**The feedback loop**
- Do not skip the assessment step — it is what makes the system compound in value
- Keep `learnings.md` as an append-only log, not an overwritten config file
- Feed learnings into every creative agent, not just the writer
