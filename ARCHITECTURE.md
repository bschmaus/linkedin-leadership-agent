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
RSS / web sources                                      voice.md
       │                                            (author persona)
       ▼
┌─────────────────┐    research_notes.md
│  Scanning Agent │ ──────────────────────► ┌──────────────────┐
│  (Sonnet 4.6)   │                         │ Selection Agent  │◄── identity/audience
└─────────────────┘                         │ (Opus 4.6+think) │
       ▲                                    └──────────────────┘
       │                                            │
       │                                   selection_notes.md
       │                                            │
       │                                            ▼
       │                         ┌─────────────────────────────────┐◄── voice.md (full)
       │          ◄──── REVISE ──│      Article Writer             │
       │          (with critique)│      (Opus 4.6)                 │
       │                         └─────────────────────────────────┘
       │                                            │
       │                                    daily_articles.md
       │                                            │
       │                                            ▼
       │                         ┌─────────────────────────────────┐◄── voice.md (full)
       │          ◄──── REVISE ──│      Poster Agent               │──► image card (.png)
       │        (format flagged) │      (Opus 4.6+think)           │
       │                         └─────────────────────────────────┘
       │                                            │
       │                                    post_assets.md
       │                                            │
       │                                            ▼
       │                         ┌─────────────────────────────────┐
       │          ◄──── REVISE ──│      Red Team Agent             │◄── live source fetch
       │                         │  (Opus 4.6+think) max 3 iter.   │
       │                         └─────────────────────────────────┘
       │                                  │         │
       │                         APPROVED │         │ REVISE → back to Article Writer
       │                                  │         │          (+ Poster if format flagged)
       │                                  ▼         │
       │                       redteam_notes.md     │
       │                                  │         │
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

Note: the Red Team → Article Writer → Poster loop runs up to 3 times. On `APPROVED` the loop exits early. If the iteration limit is reached, the best available version proceeds to posting.

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

**From v2:** Selection also reads the identity/audience sections of `voice.md` (stripped of writing style) so the editorial judgment is informed by who the author is and who they write for.

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

**From v2:** Poster reads `learnings.md` so accumulated format feedback (e.g. "polls underperform for analytical content") closes the feedback loop for format decisions.

---

### Agent 4.5 — Red Team (`claude-opus-4-6` + adaptive thinking)

**Why after Poster, not after Article Writer?** The Red Team needs both the post text and the format/asset decision to evaluate the full package. Challenging the text alone would miss format mismatches — a technically accurate post in the wrong format is still a weak post.

**Two-lens design:**

1. **Factual integrity** — structural, not web-search-based. The agent verifies internal consistency with the brief (are the claims in the post supported by the selection notes?) and uses a live fetch of the source article to add external grounding. This catches hallucinated statistics and claims that drift from the original source without requiring a general web search.

2. **Client perception** — the target audience is senior consulting clients: C-level, CHROs, transformation leads. This group has a fine-tuned bullshit detector for corporate jargon, vague assertions, and thought leadership clichés. The Red Team holds the post to the standard of "would a CHRO share this, or roll their eyes at it?"

**Iteration loop design:**
- `REVISE` verdict triggers an article_writer re-run with the critique injected as a mandatory section in the prompt
- Poster only re-runs if the format or assets are explicitly flagged — regenerating an image card on every text revision would be cost-disproportionate
- Maximum 3 iterations to prevent infinite loops

**Stop conditions:** `APPROVED` verdict exits the loop immediately. If the iteration limit is reached, the best available version (the most recently generated post) proceeds to the posting step. The full iteration history is preserved in `redteam_notes.md` for later review.

**Why adaptive thinking?** The dual-lens assessment requires holding two distinct audience perspectives simultaneously — one technical (fact verification), one political (executive perception) — and making a binary go/no-go judgment. This is reasoning-intensive: a straightforward generation task it is not.

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

## Reference files (static inputs)

Some files are not written by any agent — they are maintained manually and serve as stable context injected into specific agents.

| File | Read by | Purpose |
|---|---|---|
| data/learnings.md | all agents | accumulated style & topic feedback |
| data/voice.md | selection (identity/audience only), article_writer, poster | author tone, style, and audience |
| data/ow_brand_guidelines.md | poster | visual brand for image cards |

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

**5. Cost-proportionate model selection.** Sonnet for parsing and extraction. Opus for reasoning, judgement, and creative generation. Adaptive thinking only where it genuinely changes the output quality (Selection, Poster, Red Team — not Assessment).
