"""
Poster Agent
------------
1. Reads today's finished post from daily_articles.md
2. Uses Claude to decide the best LinkedIn format for the content
3. Prepares assets (poll options, image brief + OW-branded prompt, carousel outline)
4. Saves everything to post_assets.md and prints manual posting instructions

Posting is always manual — LinkedIn does not allow API writes to personal profiles.

Reads  : data/daily_articles.md       (latest post)
         data/voice.md                (author style)
         data/ow_brand_guidelines.md  (OW brand — applied to all visual briefs)
         data/learnings.md            (accumulated format & style feedback)
Writes : data/post_assets.md          (format decision + all assets for review)
         data/daily_articles.md       (updates status line)

Run standalone:
    python -m agents.poster
"""
from __future__ import annotations

import json
import re
import sys
import textwrap
import urllib.request
from datetime import datetime
from pathlib import Path

import anthropic

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import (
    MODEL,
    DATA_DIR,
    DAILY_ARTICLES_FILE,
    SELECTION_NOTES_FILE,
    LEARNINGS_FILE,
    VOICE_FILE,
    POST_ASSETS_FILE,
    ASSETS_DIR,
    GOOGLE_API_KEY,
    OPENAI_API_KEY,
    BRAND_FILE,
    read_file,
    ensure_data_dir,
)
from agents.utils import extract_latest_post, extract_source_url, make_date_slug, update_post_status, is_brand_configured


# ---------------------------------------------------------------------------
# Format + asset decision
# ---------------------------------------------------------------------------

FORMAT_SYSTEM = """You are a LinkedIn content strategist. Recommend the best post
format for the content, then prepare all required assets.

Available formats and TARGET DISTRIBUTION (aim across ~20 posts, not rigid quota):
- text_with_image  (~75%) — typography card with a sharp headline; default for
                            reflective / analytical content
- carousel         (~10%) — 6–8 slide document for structured content with 3–5
                            distinct insights, a framework, or step-by-step flow
- photo_briefing   (~10%) — author takes a personal photograph themselves;
                            pick for personal, human, "moment in time" posts
- poll             (~5%)  — only when the closing question has genuinely
                            distinct answerable options

**Important:** The channel has historically over-indexed on `text_with_image`.
Prefer `carousel` or `photo_briefing` whenever the content genuinely supports it.
Ask: does this post have a structured breakdown worth a carousel? Does the post
describe a personal moment, place, or scene that a real photo would elevate?

For ANY visual asset (text_with_image, carousel):
- This is a PERSONAL brand — no company names, logos, or employer branding
- Apply the Oliver Wyman visual style guidelines (Inter typography, OW Primary
  Blue #2B6EF2, neutral greys, one accent colour per asset, max 10% accent area)
- The typography card's colour scheme rotates automatically — do NOT specify it

Output valid JSON only — no markdown fences, no commentary outside the JSON.
"""

FORMAT_SCHEMA = """{
  "format": "text_with_image | carousel | photo_briefing | poll",
  "rationale": "2-3 sentences on why this format fits (and why the channel hasn't used it recently, if applicable)",
  "assets": {
    "poll_question": "max 140 chars — only if format=poll",
    "poll_options": ["A", "B", "C", "D"],
    "poll_duration": "ONE_DAY | THREE_DAYS | ONE_WEEK | TWO_WEEKS",

    "image_headline": "ONLY if format=text_with_image — short phrase or stat, max 3 words / ~20 chars (e.g. 'Wrong bottleneck.', '83%', 'The real obstacle'). Must render on 1–2 lines.",
    "image_subline":  "ONLY if format=text_with_image — one-line descriptor beneath headline, max 55 chars",
    "image_caption":  "ONLY if format=text_with_image — supporting sentence, max 80 chars / 1 line",

    "photo_subject":   "ONLY if format=photo_briefing — what the author should photograph (one concise phrase)",
    "photo_context":   "ONLY if format=photo_briefing — where/when to shoot",
    "photo_mood":      "ONLY if format=photo_briefing — mood/aesthetic (informal, natural light, not posed)",
    "photo_framing":   "ONLY if format=photo_briefing — framing hint (landscape 4:3 or 16:9 for LinkedIn)",

    "slide_count": 7,
    "slides": [
      {"slide": 1, "role": "hook",         "heading": "Short punchy hook", "body": ""},
      {"slide": 2, "role": "context",      "heading": "Why this matters now", "body": "One supporting sentence."},
      {"slide": 3, "role": "insight",      "heading": "First insight headline", "body": "8–15 words supporting."},
      {"slide": 4, "role": "insight",      "heading": "Second insight headline", "body": "8–15 words supporting."},
      {"slide": 5, "role": "insight",      "heading": "Third insight headline", "body": "8–15 words supporting."},
      {"slide": 6, "role": "implications", "heading": "What this means for leaders", "body": "2–3 handlungspunkte in einer Zeile."},
      {"slide": 7, "role": "conclusion",   "heading": "Sharp closing statement", "body": ""}
    ]
  }
}
For carousel: each slide's heading max 8–15 words, body max 1–2 lines. role ∈ {hook, context, insight, implications, conclusion, signature}."""


def decide_format(client: anthropic.Anthropic, post_text: str, voice: str, brand: str,
                  learnings: str) -> dict:
    brand_section = (
        f"## Personal Visual Style\n{brand}"
        if is_brand_configured(brand)
        else "## Personal Visual Style\n_Not yet provided — use clean, modern editorial aesthetic._"
    )
    prompt = textwrap.dedent(f"""
        ## Author voice
        {voice or "_Not provided._"}

        {brand_section}

        ## Accumulated format learnings (apply to format & asset decisions)
        {learnings or "_None yet._"}

        ## Post text
        {post_text}

        ---

        Recommend the best LinkedIn format and prepare all assets.
        Apply the personal visual style to any image briefs or prompts.
        IMPORTANT: This is a personal brand — never include company names, employer
        names, or logos in any visual brief or image prompt.
        Schema:
        {FORMAT_SCHEMA}

        Return valid JSON only.
    """).strip()

    # Format decision is structured JSON generation — Sonnet handles this cheaper than Opus.
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        system=FORMAT_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = "".join(b.text for b in response.content if b.type == "text").strip()
    raw = re.sub(r"^```(?:json)?\n?", "", raw).rstrip("`").strip()
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Save assets to post_assets.md
# ---------------------------------------------------------------------------

def save_assets(title: str, fmt: str, rationale: str, post_text: str, assets: dict,
                image_path: Path | None = None, carousel_paths: list[Path] | None = None,
                scheme: str = "", source_url: str = "") -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# Post Assets — {timestamp}",
        f"\n## Post: {title}",
        f"**Format:** {fmt}",
        f"**Rationale:** {rationale}",
    ]
    if scheme:
        lines.append(f"**Colour scheme:** {scheme}")
    lines += ["\n---\n", "## Post Text\n", post_text, "\n---\n"]

    if fmt == "poll":
        lines += [
            "## Poll\n",
            f"**Question:** {assets.get('poll_question', '')}",
            f"**Duration:** {assets.get('poll_duration', 'THREE_DAYS')}\n",
        ]
        for i, opt in enumerate(assets.get("poll_options", []), 1):
            lines.append(f"- Option {i}: {opt}")

    elif fmt == "text_with_image":
        lines += [
            "## Image Asset (typography card)\n",
            f"**Headline:** {assets.get('image_headline', '')}",
            f"**Subline:**  {assets.get('image_subline', '')}",
            f"**Caption:**  {assets.get('image_caption', '')}\n",
        ]
        if image_path:
            lines += [
                f"**Generated image:** `{image_path}`",
                "_Open this file to review before uploading to LinkedIn._\n",
            ]

    elif fmt == "carousel":
        slide_count = assets.get('slide_count', len(assets.get('slides', [])))
        lines += [f"## Carousel ({slide_count} slides)\n"]
        if carousel_paths:
            lines.append(f"**Generated slides:** `{carousel_paths[0].parent}`")
            lines.append("_Upload as a LinkedIn document (PDF) — combine the PNGs in order._\n")
        for slide in assets.get("slides", []):
            lines.append(f"### Slide {slide.get('slide','?')}: {slide.get('heading','')}")
            if slide.get("role"):
                lines.append(f"_Role: {slide['role']}_")
            lines.append(slide.get("body", "") + "\n")

    elif fmt == "photo_briefing":
        lines += [
            "## Photo Briefing — you take this one yourself\n",
            f"**Subject:**  {assets.get('photo_subject', '')}",
            f"**Context:**  {assets.get('photo_context', '')}",
            f"**Mood:**     {assets.get('photo_mood', '')}",
            f"**Framing:**  {assets.get('photo_framing', '')}\n",
            "_Shoot it on your phone. Informal beats polished. Upload it directly to LinkedIn with the post text above._\n",
        ]

    lines += [
        "\n---\n",
        "## First Comment (post immediately after publishing)\n",
    ]
    if source_url:
        lines.append(f"Source: {source_url}")
    else:
        lines.append("_No source URL found in selection_notes.md_")

    POST_ASSETS_FILE.write_text("\n".join(lines), encoding="utf-8")
    print(f"  ✅ Assets saved to {POST_ASSETS_FILE}")


# ---------------------------------------------------------------------------
# Image generation — Imagen 3 (preferred) or DALL-E 3 (fallback)
# ---------------------------------------------------------------------------

def _save_image_bytes(data: bytes, title: str) -> Path:
    """Write raw image bytes to data/assets/ and return the path."""
    dest = ASSETS_DIR / f"{datetime.now().strftime('%Y-%m-%d')}-{make_date_slug(title)}.png"
    dest.write_bytes(data)
    return dest


def _generate_google(prompt: str, title: str) -> Path | None:
    """
    Generate with Google AI Studio — tries Imagen 3 first, then Gemini 2.0 Flash.
    Imagen 3 requires allowlist access; Gemini Flash is available to all AI Studio keys.
    """
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GOOGLE_API_KEY)

    # --- Try Imagen 4 models (best quality) ---
    for model in ("imagen-4.0-generate-001", "imagen-4.0-fast-generate-001"):
        try:
            print(f"  🎨 Trying {model}...")
            response = client.models.generate_images(
                model=model,
                prompt=prompt,
                config=types.GenerateImagesConfig(
                    number_of_images=1,
                    aspect_ratio="16:9",
                    safety_filter_level="block_low_and_above",
                ),
            )
            dest = _save_image_bytes(response.generated_images[0].image.image_bytes, title)
            print(f"  ✅ Image saved to {dest}")
            return dest
        except Exception as exc:
            print(f"  ⚠️  {model} unavailable: {exc}")

    return None


def _generate_dalle3(prompt: str, title: str) -> Path | None:
    """Generate with DALL-E 3 via OpenAI."""
    try:
        import ssl
        import certifi
        import urllib.request
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        print("  🎨 Generating image with DALL-E 3...")
        response = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size="1792x1024",
            quality="hd",
            n=1,
        )
        image_url = response.data[0].url
        dest = ASSETS_DIR / f"{datetime.now().strftime('%Y-%m-%d')}-{make_date_slug(title)}.png"
        ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(image_url, context=ssl_ctx) as r:
            dest.write_bytes(r.read())
        print(f"  ✅ Image saved to {dest}")
        return dest
    except Exception as exc:
        print(f"  ⚠️  DALL-E 3 failed: {exc}")
        return None


def generate_image_creative(prompt: str, title: str) -> Path | None:
    """
    Generate a creative AI image via DALL-E 3 (primary) or Imagen 4 (fallback).
    Use when you want an artistic/illustrative visual instead of a typography card.
    """
    if OPENAI_API_KEY:
        result = _generate_dalle3(prompt, title)
        if result:
            return result
        print("  DALL-E 3 failed, trying Google...")

    if GOOGLE_API_KEY:
        return _generate_google(prompt, title)

    print("  ⚠️  No image API key available for creative mode.")
    return None


# ---------------------------------------------------------------------------
# Print manual posting instructions
# ---------------------------------------------------------------------------

def print_manual_instructions(post_text: str, fmt: str, assets: dict,
                              image_path: Path | None = None,
                              carousel_paths: list[Path] | None = None,
                              source_url: str = "") -> None:
    w = 68
    print("\n" + "═" * w)
    print("  READY TO POST — copy the text below into LinkedIn")
    print("═" * w + "\n")
    print(post_text)
    print()

    if fmt == "poll":
        print("─" * w)
        print("  ADD POLL:")
        print(f"  Question : {assets.get('poll_question', '')}")
        for i, opt in enumerate(assets.get("poll_options", []), 1):
            print(f"  Option {i}  : {opt}")
        print(f"  Duration : {assets.get('poll_duration', 'THREE_DAYS')}")

    elif fmt == "text_with_image":
        print("─" * w)
        if image_path:
            print(f"  ADD IMAGE: {image_path}")
        else:
            print("  ADD IMAGE: (no headline provided — see data/post_assets.md)")

    elif fmt == "carousel":
        print("─" * w)
        count = len(carousel_paths) if carousel_paths else assets.get('slide_count', '?')
        print(f"  ADD CAROUSEL — {count} slides")
        if carousel_paths:
            print(f"  Folder: {carousel_paths[0].parent}")
            print("  Combine PNGs into a PDF and upload as a LinkedIn document.")
        else:
            print("  (see data/post_assets.md for slide texts)")

    elif fmt == "photo_briefing":
        print("─" * w)
        print("  📸 TAKE THIS PHOTO YOURSELF:")
        print(f"  Subject : {assets.get('photo_subject', '')}")
        print(f"  Context : {assets.get('photo_context', '')}")
        print(f"  Mood    : {assets.get('photo_mood', '')}")
        print(f"  Framing : {assets.get('photo_framing', '')}")

    print("─" * w)
    if source_url:
        print(f"  FIRST COMMENT: {source_url}")
    else:
        print("  FIRST COMMENT: (no source URL — add manually if referencing an article)")
    print("\n" + "═" * w + "\n")


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

def run(client: anthropic.Anthropic | None = None, creative: bool = False) -> None:
    """
    Run the Poster agent.

    Parameters
    ----------
    creative : bool
        False (default) — render a clean typography card with Pillow (pixel-perfect fonts).
        True            — generate a creative AI image via DALL-E 3 / Imagen 4.
    """
    ensure_data_dir()

    if client is None:
        client = anthropic.Anthropic()

    mode_label = "creative (DALL-E)" if creative else "typography card (Pillow)"
    print(f"📤 Poster Agent starting... [image mode: {mode_label}]")

    voice      = read_file(VOICE_FILE)
    brand      = read_file(BRAND_FILE)
    selection  = read_file(SELECTION_NOTES_FILE)
    learnings  = read_file(LEARNINGS_FILE)
    source_url = extract_source_url(selection)
    title, post_text = extract_latest_post(read_file(DAILY_ARTICLES_FILE))

    if not post_text:
        raise RuntimeError("No post found. Run the Article Writer agent first.")

    has_brand = is_brand_configured(brand)
    print(f"\n  Post  : {title}")
    print(f"  Brand : {'style guidelines loaded' if has_brand else 'using default style'}")

    # 1. Decide format + prepare assets
    print("\n  Deciding format and preparing assets (adaptive thinking)...")
    decision = decide_format(client, post_text, voice, brand, learnings)
    fmt    = decision.get("format", "text")
    assets = decision.get("assets", {})

    print(f"\n  ✦ Format: {fmt.upper()}")
    print(f"  {decision.get('rationale', '')}\n")

    # 2. Generate visual asset based on format
    image_path: Path | None = None
    carousel_paths: list[Path] | None = None
    scheme_used = ""

    if fmt == "text_with_image":
        if creative:
            image_path = generate_image_creative(assets.get("image_prompt", ""), title)
        else:
            from agents.image_generator import generate_card
            headline = assets.get("image_headline", title)
            subline  = assets.get("image_subline", "")
            caption  = assets.get("image_caption", "")
            if headline:
                image_path, scheme_used = generate_card(headline, subline, caption, title)
            else:
                print("  ⚠️  No image_headline in assets — skipping card generation.")

    elif fmt == "carousel":
        from agents.image_generator import generate_carousel
        slides = assets.get("slides", [])
        if slides:
            carousel_paths = generate_carousel(slides, title)
        else:
            print("  ⚠️  No slides in assets — skipping carousel generation.")

    elif fmt == "photo_briefing":
        print("  📸 Photo briefing prepared — take the photo yourself and upload it.")

    # 3. Save to post_assets.md
    save_assets(
        title, fmt, decision.get("rationale", ""), post_text, assets,
        image_path=image_path, carousel_paths=carousel_paths,
        scheme=scheme_used, source_url=source_url,
    )

    # 4. Print manual instructions
    print_manual_instructions(post_text, fmt, assets, image_path, carousel_paths, source_url)
    update_post_status(f"ready for manual posting | format: {fmt}")


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run()
