# Architecture

A technical deep-dive into how the pipeline is designed, why each decision was made, and how the components fit together.

---

## The core idea

This is not a chatbot or a single API call. It is a **pipeline of specialised agents**, each with a narrow responsibility, passing structured artefacts to the next agent via shared files.

The key design insight: **writing quality compounds over time**. A single Claude call produces a generic post. Five agents — each informed by what the previous ones learned — produce a post that sounds like a specific person, avoids topics already covered, and gets better every week through a closed feedback loop.

---

## Data flow

Every agent communicates through files in `data/`. No agent calls another directly.

```
RSS / web sources
       │
       ▼
┌─────────────────┐    research_notes.md
│  Scanning Agent │ ──────────────────────► ┌──────────────────┐
│  (Sonnet 4.6)   │                         │ Selection Agent  │
└─────────────────┘                         │ (Opus 4.6+think) │
       ▲                                    └──────────────────┘
       │                                            │
       │                                   selection_notes.md
       │                                            │
       │                                            ▼
       │                                   ┌─────────────────┐
       │                                   │  Article Writer │
       │                                   │  (Opus 4.6)     │
       │                                   └─────────────────┘
       │                                            │
       │                                    daily_articles.md
       │                                            │
       │                                            ▼
       │                                   ┌─────────────────┐
       │                                   │  Poster Agent   │
       │                                   │  (Opus 4.6)     │──► image card (.png)
       │                                   └─────────────────┘
       │                                            │
       │                                    post_assets.md
       │                                            │
       │                               [manual: post on LinkedIn]
       │                                            │
       │                               [weekly: upload analytics]
       │                                            │
       │                                            ▼
       │                                   ┌─────────────────┐
       │     learnings.md                  │ Assessment Agent│
       └────────────────────────────────── │  (Opus 4.6)     │
                                           └─────────────────┘
```

`learnings.md` is the **system's long-term memory**. It is the only file that persists across days and grows indefinitely. Every agent that involves creative judgement reads it as context.

---

## Agent design rationale

### Agent 1 — Scanning (`claude-sonnet-4-6`)

**Why Sonnet, not Opus?** Scanning is a parsing and summarisation task — it reads raw feed content and extracts structured candidates. It does not require complex reasoning. Using Sonnet reduces cost by ~80% for a step that runs daily.

**Why separate from Selection?** A single agent doing "find and pick the best topic" produces different results than two agents in sequence. Scanning produces 3–5 candidates without editorial judgement. Selection then applies that judgement against history, learnings, and pillar balance. Separating the two allows each to be optimised independently.

**Competitor source rule:** McKinsey, BCG, Bain, PwC, EY, Deloitte, and KPMG are explicitly excluded as sources. Citing competitor research would be professionally inappropriate. This rule is embedded in both the Scanning and Selection prompts as a hard constraint.

---

### Agent 2 — Selection (`claude-opus-4-6` + adaptive thinking)

**Why adaptive thinking?** Selection is the highest-stakes editorial judgement in the pipeline — the wrong topic leads to a wasted post. Adaptive thinking allows the model to reason through topic history, pillar rotation, source quality, and audience fit before committing. The thinking is not streamed to the user; only the final output is printed.

**Why Opus?** This is the "editor-in-chief" decision. It requires nuanced reasoning about freshness, relevance, and accumulated style feedback. Sonnet would produce acceptable selections; Opus produces better ones consistently.

**Output contract:** The selection agent always writes a full writing brief — not just a topic title. This brief (`selection_notes.md`) includes the core message, angle, tone, key points to hit, a suggested hook, and a CTA. The article writer treats this as a creative brief, not a topic prompt.

---

### Agent 3 — Article Writer (`claude-opus-4-6`)

**The ghostwriting problem:** LinkedIn posts that sound like AI are ignored. The system prompt is explicitly designed to produce *human* writing — with sentence rhythm, acknowledged uncertainty, concrete detail, and an ending that asks a genuine question.

**Hard rules enforced in the prompt:**
- 250–400 words (not counting hashtags)
- No bullet-point listicles — flowing paragraphs only
- No hollow corporate phrases ("leverage", "synergy", "game-changer")
- No unverifiable first-person claims ("I've seen...", "In my experience...")
- Never mention the author's employer or any company name they work for
- Do not invent statistics — only use figures from the brief

**Why streaming?** The article writer streams its output to the terminal. This is intentional — it gives the operator a sense of progress during the longest generation step, and allows interruption if the post goes in the wrong direction.

---

### Agent 4 — Poster (`claude-opus-4-6`)

**Format decision:** The poster agent chooses between `text`, `poll`, `text_with_image`, and `carousel`. This is a strategic decision — polls work for genuinely binary questions, carousels for step-by-step content, images for stat-heavy or single-insight posts. Most analytical posts default to `text`.

**Image generation — two paths:**

| Mode | Method | When to use |
|---|---|---|
| Default | Pillow typography card | Always — no API cost, pixel-perfect, instant |
| `--creative` | DALL-E 3 → Imagen 4 fallback | When an illustrative visual adds genuine value |

**Why Pillow as default?** The typography card is more reliable, cheaper, and consistent. Creative AI images require careful prompting and produce unpredictable results. The typography card — navy background, Playfair Display headline, gold accents — is a recognisable personal brand element.

**Image card fields:** The poster agent extracts three structured fields for the card:
- `image_headline` — the dominant stat or key phrase (max 30 chars, e.g. "36 → 6")
- `image_subline` — one-line descriptor (max 55 chars)
- `image_caption` — supporting sentence (max 110 chars, can wrap)

---

### Agent 5 — Assessment (`claude-opus-4-6`)

**The feedback loop:** The assessment agent is what makes the system improve over time. Without it, the pipeline produces posts of consistent but static quality. With it, each post is critiqued against its brief, and the lessons are written to `learnings.md` — which every future agent reads.

**Structure enforced:** The assessment always produces five sections:
1. **What worked** — to be repeated
2. **What could be stronger** — to be fixed
3. **Style & voice notes** — tone, rhythm, word choice
4. **Format decision** — was the format right?
5. **Instructions for future posts** — actionable rules ("Always...", "Never...", "When X, do Y")

**Analytics enrichment:** When a LinkedIn Analytics Excel export is present in `data/analytics/`, the assessment gains quantitative grounding — impressions, engagement rate, rank against other posts that week. This allows conclusions like: *"The hook was strong — this post captured 45% of all weekly impressions."*

**Date matching:** The assessment matches the latest post in `daily_articles.md` to analytics data by publish date. The analytics export covers a rolling 7-day window.

---

## The memory system

`learnings.md` is the only file that compounds. Every other data file is overwritten daily (research, selection) or appended with dated entries (articles, assets). `learnings.md` only grows.

Over time it accumulates:
- Voice patterns that worked ("punchy four-word sentence in paragraph 2")
- Topics that resonated vs. fell flat
- Format patterns ("polls underperform for analytical content")
- Structural rules the ghostwriter follows next time

This is the architectural equivalent of **in-context fine-tuning** — not model weights, but accumulated editorial experience encoded in plain text.

---

## Scheduling

Both jobs are managed by macOS `launchd` — the system-native scheduler, running at user login level.

```
~/Library/LaunchAgents/
├── com.bene.linkedin-daily.plist   # Mon–Fri 06:47 → full pipeline
└── com.bene.linkedin-assess.plist  # Friday 21:05 → assessment only
```

**Why launchd over cron?** macOS's cron runs via a compatibility shim. launchd is the native mechanism, survives reboots without configuration, handles missed jobs, and inherits a predictable environment. For a daily job that must be reliable, launchd is the correct choice.

---

## Design principles

**1. Files as contracts.** Agents communicate through structured markdown files, not function calls or shared state. This means any agent can be run in isolation, debugged independently, or replaced without touching the others.

**2. Narrow responsibilities.** Each agent does one thing. Scanning does not select. Selection does not write. Writing does not format. This makes each agent easier to prompt, easier to test, and easier to replace with a better version.

**3. Fail loudly at the boundary.** If an upstream file is missing or empty, the agent prints a clear warning and exits rather than producing garbage output. The orchestrator prints the resume command on failure.

**4. Human stays in the loop at the right points.** The pipeline is fully automated for the mechanical steps. The two steps that require human judgement or access (posting on LinkedIn, providing real performance data) are explicitly left to the human. The pipeline produces the best possible input for those steps and gets out of the way.

**5. Cost-proportionate model selection.** Sonnet for parsing and extraction. Opus for reasoning, judgement, and creative generation. Adaptive thinking only where it genuinely changes the output quality (Selection).
