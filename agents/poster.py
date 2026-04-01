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

Available formats:
- text            — pure text (default; great for analytical, reflective content)
- poll            — text + 4-option poll (only when the closing question has
                    genuinely distinct answerable options)
- text_with_image — text + one visual (when a diagram or image strongly reinforces
                    the hook or a key data point)
- carousel        — multi-slide document (only for structured step-by-step content)

For ANY format that involves a visual asset (text_with_image, carousel):
- This is a PERSONAL brand — never include any company name, company logo, or
  employer branding in visuals or prompts
- Apply the personal visual style guidelines provided
- If no style guidelines are available, use a clean, modern, editorial aesthetic:
  dark navy or charcoal background, white headline typography, one warm accent
  colour (gold or amber), minimal layout, no decorative flourishes

Output valid JSON only — no markdown fences, no commentary outside the JSON.
"""

FORMAT_SCHEMA = """{
  "format": "text | poll | text_with_image | carousel",
  "rationale": "2-3 sentences on why this format fits",
  "assets": {
    "poll_question": "max 140 chars — only if format=poll",
    "poll_options": ["A", "B", "C", "D"],
    "poll_duration": "ONE_DAY | THREE_DAYS | ONE_WEEK | TWO_WEEKS",

    "image_brief": "what the image must convey — only if format=text_with_image",

    "image_headline": "short phrase or stat, max 3 words / ~20 chars — e.g. 'Belief gap.', '83%', 'The real obstacle'; never a full sentence; must render on 1–2 lines",
    "image_subline":  "one-line descriptor beneath the headline, max 55 chars (e.g. 'months to develop a new product')",
    "image_caption":  "supporting sentence, max 80 chars / 1 line (e.g. '83% faster — by moving decisions closer to the work')",

    "image_prompt": "full DALL-E / Midjourney prompt for a CREATIVE visual — personal brand style, no company names or logos",

    "slide_count": 5,
    "slides": [{"slide": 1, "heading": "...", "body": "..."}]
  }
}"""


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

    response = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        thinking={"type": "adaptive"},
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
                image_path: Path | None = None, source_url: str = "") -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# Post Assets — {timestamp}",
        f"\n## Post: {title}",
        f"**Format:** {fmt}",
        f"**Rationale:** {rationale}",
        "\n---\n",
        "## Post Text\n",
        post_text,
        "\n---\n",
    ]

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
            "## Image Asset\n",
            f"**Brief:** {assets.get('image_brief', '')}",
            f"**Style:** {assets.get('image_style', '')}\n",
        ]
        if image_path:
            lines += [
                f"**Generated image:** `{image_path}`",
                "_Open this file to review before uploading to LinkedIn._\n",
            ]
        else:
            lines += [
                "**Status:** Not auto-generated — use prompt below in DALL-E or Midjourney\n",
            ]
        lines += [
            "**DALL-E / Midjourney prompt:**\n",
            f"> {assets.get('image_prompt', '')}",
        ]

    elif fmt == "carousel":
        lines += [f"## Carousel ({assets.get('slide_count', '?')} slides)\n"]
        for slide in assets.get("slides", []):
            lines.append(f"### Slide {slide['slide']}: {slide['heading']}")
            lines.append(slide.get("body", "") + "\n")

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
            print("  ADD IMAGE (see data/post_assets.md for full prompt):")
            print(f"  Brief : {assets.get('image_brief', '')}")
            print(f"  Style : {assets.get('image_style', '')}")

    elif fmt == "carousel":
        print("─" * w)
        print(f"  ADD CAROUSEL — {assets.get('slide_count', '?')} slides")
        print("  (see data/post_assets.md for full slide content)")

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

    # 2. Generate image if needed
    image_path = None
    if fmt == "text_with_image":
        if creative:
            # Creative mode — AI-generated visual via DALL-E / Imagen
            image_path = generate_image_creative(assets.get("image_prompt", ""), title)
        else:
            # Default mode — clean typography card rendered with Pillow
            from agents.image_generator import generate_card
            headline = assets.get("image_headline", title)
            subline  = assets.get("image_subline", "")
            caption  = assets.get("image_caption", "")
            if headline:
                image_path = generate_card(headline, subline, caption, title)
            else:
                print("  ⚠️  No image_headline in assets — skipping card generation.")

    # 3. Save to post_assets.md
    save_assets(title, fmt, decision.get("rationale", ""), post_text, assets, image_path, source_url)

    # 4. Print manual instructions
    print_manual_instructions(post_text, fmt, assets, image_path, source_url)
    update_post_status(f"ready for manual posting | format: {fmt}")


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run()
