"""
Image Generator
---------------
Renders brand-compliant LinkedIn assets with Pillow and local Inter fonts.

Two render paths:
  1. render_card()     — single typography card (1200×675) with rotating colour scheme
  2. render_carousel() — 6–8 slides (1080×1350 portrait — LinkedIn document carousel)

Colour schemes rotate per post to avoid visual monotony. Last-used scheme is
tracked in data/assets/.last_scheme so the next post picks a different one.

Centering logic (cards):
  Pass 1 measures visual height as bb[3]-bb[1] per text element (true glyph height,
  excluding Inter's ascender padding). Pass 2 tracks visual_y and draws at
  (x, visual_y - bb[1]) so the visible glyph top aligns precisely.
"""
from __future__ import annotations

import random
import re
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONTS_DIR  = Path(__file__).parent.parent / "data" / "fonts"
ASSETS_DIR = Path(__file__).parent.parent / "data" / "assets"
STATE_FILE = ASSETS_DIR / ".last_scheme"


# ---------------------------------------------------------------------------
# Colour schemes — all brand-compliant (see ow_brand_guidelines.md §6)
# ---------------------------------------------------------------------------

SCHEMES: dict[str, dict] = {
    "ow_blue": {
        "bg":       (43, 110, 242),   # #2B6EF2 Primary Blue
        "headline": (255, 255, 255),
        "accent":   (234, 242, 255),  # #EAF2FF Very Light Blue
        "body":     (255, 255, 255),
    },
    "near_black": {
        "bg":       (10, 10, 10),     # #0A0A0A
        "headline": (255, 255, 255),
        "accent":   (43, 110, 242),   # Primary Blue
        "body":     (204, 204, 204),  # Light Grey
    },
    "dark_grey": {
        "bg":       (51, 51, 51),     # #333333
        "headline": (255, 255, 255),
        "accent":   (43, 110, 242),
        "body":     (204, 204, 204),
    },
    "medium_grey": {
        "bg":       (102, 102, 102),  # #666666
        "headline": (255, 255, 255),
        "accent":   (43, 110, 242),
        "body":     (247, 247, 247),  # Off White
    },
    "light": {
        "bg":       (247, 247, 247),  # #F7F7F7
        "headline": (10, 10, 10),
        "accent":   (43, 110, 242),
        "body":     (51, 51, 51),
    },
    "very_light_blue": {
        "bg":       (234, 242, 255),  # #EAF2FF
        "headline": (30, 77, 183),    # #1E4DB7 Dark Blue
        "accent":   (43, 110, 242),
        "body":     (51, 51, 51),
    },
}

CARD_W, CARD_H = 1200, 675
CARD_PAD = 90

# Portrait carousel (LinkedIn document size) — 1080×1350 is optimal
SLIDE_W, SLIDE_H = 1080, 1350
SLIDE_PAD = 80


# ---------------------------------------------------------------------------
# Font + text helpers
# ---------------------------------------------------------------------------

def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS_DIR / name), size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    words, lines, line = text.split(), [], []
    for word in words:
        test = " ".join(line + [word])
        if draw.textbbox((0, 0), test, font=font)[2] <= max_w:
            line.append(word)
        else:
            if line:
                lines.append(" ".join(line))
            line = [word]
    if line:
        lines.append(" ".join(line))
    return lines or [""]


def _vis(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    """(visual_height, bb1) — visual_height = bb[3]-bb[1], bb1 = invisible top offset.
    Draw at (x, visual_y - bb1) so the visible glyph top aligns with visual_y."""
    bb = draw.textbbox((0, 0), text, font=font)
    return bb[3] - bb[1], bb[1]


# ---------------------------------------------------------------------------
# Scheme picker (random, excluding last used)
# ---------------------------------------------------------------------------

def pick_scheme() -> tuple[str, dict]:
    """Return (name, colours). Excludes the previously used scheme if known."""
    last = ""
    if STATE_FILE.exists():
        try:
            last = STATE_FILE.read_text().strip()
        except Exception:
            pass
    candidates = [n for n in SCHEMES if n != last] or list(SCHEMES)
    name = random.choice(candidates)
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(name)
    return name, SCHEMES[name]


# ---------------------------------------------------------------------------
# Card renderer (1200×675 landscape)
# ---------------------------------------------------------------------------

def _measure_card(draw, headline, subline, caption, f_head, f_sub, f_cap, max_w, spacing):
    head_lines = _wrap(draw, headline, f_head, max_w)
    cap_lines  = _wrap(draw, caption,  f_cap,  max_w) if caption else []
    h = spacing["BAR_H"] + spacing["BAR_TO_HEAD"]
    for i, ln in enumerate(head_lines):
        vh, _ = _vis(draw, ln, f_head); h += vh
        if i < len(head_lines) - 1: h += spacing["HEAD_LINE_GAP"]
    h += spacing["HEAD_TO_DIV"] + spacing["DIV_H"] + spacing["DIV_TO_SUB"]
    if subline:
        vh, _ = _vis(draw, subline, f_sub); h += vh + spacing["SUB_TO_CAP"]
    for i, ln in enumerate(cap_lines):
        vh, _ = _vis(draw, ln, f_cap); h += vh
        if i < len(cap_lines) - 1: h += spacing["CAP_LINE_GAP"]
    return h, head_lines, cap_lines


def render_card(headline: str, subline: str, caption: str, dest: Path,
                scheme_name: str | None = None) -> tuple[Path, str]:
    """Render a single typography card. Returns (path, scheme_name_used)."""
    if scheme_name and scheme_name in SCHEMES:
        scheme = SCHEMES[scheme_name]
    else:
        scheme_name, scheme = pick_scheme()

    img  = Image.new("RGB", (CARD_W, CARD_H), scheme["bg"])
    draw = ImageDraw.Draw(img)

    head_size = 140
    f_head = _font("Inter-Bold.ttf",     head_size)
    f_sub  = _font("Inter-SemiBold.ttf", 38)
    f_cap  = _font("Inter-Regular.ttf",  28)

    max_w = CARD_W - CARD_PAD * 2
    spacing = dict(
        BAR_H=6, BAR_TO_HEAD=28, HEAD_LINE_GAP=8,
        HEAD_TO_DIV=24, DIV_H=3, DIV_TO_SUB=22,
        SUB_TO_CAP=16, CAP_LINE_GAP=8,
    )

    # Pass 1 — measure, shrink headline if it overflows
    h, head_lines, cap_lines = _measure_card(
        draw, headline, subline, caption, f_head, f_sub, f_cap, max_w, spacing,
    )
    MIN_HEAD, BOTTOM_RESERVE = 72, 30
    max_content_h = CARD_H - CARD_PAD - BOTTOM_RESERVE
    while h > max_content_h and head_size > MIN_HEAD:
        head_size = max(head_size - 8, MIN_HEAD)
        f_head = _font("Inter-Bold.ttf", head_size)
        h, head_lines, cap_lines = _measure_card(
            draw, headline, subline, caption, f_head, f_sub, f_cap, max_w, spacing,
        )
    if head_size < 140:
        print(f"  ⚠️  Headline scaled down to {head_size}px to fit canvas")

    y_bar = max(CARD_PAD, (CARD_H - h) // 2)

    # Pass 2 — render
    draw.rectangle([(CARD_PAD, y_bar), (CARD_PAD + 56, y_bar + spacing["BAR_H"])], fill=scheme["accent"])
    visual_y = y_bar + spacing["BAR_H"] + spacing["BAR_TO_HEAD"]

    for i, ln in enumerate(head_lines):
        vh, bb1 = _vis(draw, ln, f_head)
        draw.text((CARD_PAD, visual_y - bb1), ln, font=f_head, fill=scheme["headline"])
        visual_y += vh
        if i < len(head_lines) - 1:
            visual_y += spacing["HEAD_LINE_GAP"]

    visual_y += spacing["HEAD_TO_DIV"]
    draw.rectangle([(CARD_PAD, visual_y), (CARD_PAD + 140, visual_y + spacing["DIV_H"])], fill=scheme["accent"])
    visual_y += spacing["DIV_H"] + spacing["DIV_TO_SUB"]

    if subline:
        vh, bb1 = _vis(draw, subline, f_sub)
        draw.text((CARD_PAD, visual_y - bb1), subline, font=f_sub, fill=scheme["accent"])
        visual_y += vh + spacing["SUB_TO_CAP"]

    for i, ln in enumerate(cap_lines):
        vh, bb1 = _vis(draw, ln, f_cap)
        draw.text((CARD_PAD, visual_y - bb1), ln, font=f_cap, fill=scheme["body"])
        visual_y += vh
        if i < len(cap_lines) - 1:
            visual_y += spacing["CAP_LINE_GAP"]

    # Bottom-right anchor bar — subtle brand marker
    draw.rectangle(
        [(CARD_W - CARD_PAD - 56, CARD_H - CARD_PAD - 6),
         (CARD_W - CARD_PAD,       CARD_H - CARD_PAD)],
        fill=scheme["accent"],
    )

    ASSETS_DIR.mkdir(exist_ok=True)
    dest.parent.mkdir(exist_ok=True)
    img.save(dest, "PNG")
    return dest, scheme_name


# ---------------------------------------------------------------------------
# Carousel renderer (1080×1350 portrait, 6–8 slides)
# ---------------------------------------------------------------------------

# Carousels use the two lightest schemes per brand guidelines (§7.4)
CAROUSEL_SCHEMES = ("light", "very_light_blue")


def _render_slide(slide_num: int, total: int, heading: str, body: str,
                  scheme: dict, dest: Path, role: str) -> Path:
    """Render a single carousel slide. role ∈ {hook, context, insight, implications,
    conclusion, signature} — used to vary layout slightly."""
    img  = Image.new("RGB", (SLIDE_W, SLIDE_H), scheme["bg"])
    draw = ImageDraw.Draw(img)

    # Font sizing by role
    if role == "hook":
        head_size = 96
        body_size = 36
    elif role == "signature":
        head_size = 56
        body_size = 32
    else:
        head_size = 72
        body_size = 32

    f_head = _font("Inter-Bold.ttf",    head_size)
    f_body = _font("Inter-Regular.ttf", body_size)
    f_meta = _font("Inter-Medium.ttf",  22)

    max_w = SLIDE_W - SLIDE_PAD * 2

    # Shrink headline if too large
    head_lines = _wrap(draw, heading, f_head, max_w)
    MIN_HEAD = 44
    while len(head_lines) > 5 and head_size > MIN_HEAD:
        head_size = max(head_size - 6, MIN_HEAD)
        f_head = _font("Inter-Bold.ttf", head_size)
        head_lines = _wrap(draw, heading, f_head, max_w)

    body_lines = _wrap(draw, body, f_body, max_w) if body else []

    # Layout: slide counter top-left, accent bar, heading block, body block
    y = SLIDE_PAD

    # Slide counter (except signature slide)
    if role != "signature":
        counter = f"{slide_num} / {total}"
        draw.text((SLIDE_PAD, y), counter, font=f_meta, fill=scheme["accent"])
        y += 32

    # Accent bar
    y += 20
    draw.rectangle([(SLIDE_PAD, y), (SLIDE_PAD + 48, y + 4)], fill=scheme["accent"])
    y += 40

    # Heading
    for i, ln in enumerate(head_lines):
        vh, bb1 = _vis(draw, ln, f_head)
        draw.text((SLIDE_PAD, y - bb1), ln, font=f_head, fill=scheme["headline"])
        y += vh + 10

    # Body (with gap after heading)
    if body_lines:
        y += 40
        for ln in body_lines:
            vh, bb1 = _vis(draw, ln, f_body)
            draw.text((SLIDE_PAD, y - bb1), ln, font=f_body, fill=scheme["body"])
            y += vh + 14

    # Bottom-right anchor bar
    draw.rectangle(
        [(SLIDE_W - SLIDE_PAD - 48, SLIDE_H - SLIDE_PAD - 4),
         (SLIDE_W - SLIDE_PAD,       SLIDE_H - SLIDE_PAD)],
        fill=scheme["accent"],
    )

    img.save(dest, "PNG")
    return dest


def render_carousel(slides: list[dict], title: str,
                    scheme_name: str | None = None) -> list[Path]:
    """
    Render 6–8 carousel slides as individual PNGs.

    Each slide dict: {"slide": int, "heading": str, "body": str, "role": str}
    role ∈ {"hook", "context", "insight", "implications", "conclusion", "signature"}
    """
    if scheme_name not in CAROUSEL_SCHEMES:
        scheme_name = random.choice(CAROUSEL_SCHEMES)
    scheme = SCHEMES[scheme_name]

    ASSETS_DIR.mkdir(exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    slug     = re.sub(r"[^a-z0-9]+", "-", title.lower())[:40].strip("-")
    carousel_dir = ASSETS_DIR / f"{date_str}-{slug}-carousel"
    carousel_dir.mkdir(exist_ok=True)

    total = len(slides)
    paths: list[Path] = []
    for s in slides:
        n     = s.get("slide", len(paths) + 1)
        head  = s.get("heading", "")
        body  = s.get("body", "")
        role  = s.get("role", "insight")
        dest  = carousel_dir / f"slide-{n:02d}.png"
        _render_slide(n, total, head, body, scheme, dest, role)
        paths.append(dest)

    print(f"  ✅ Carousel rendered: {len(paths)} slides in {carousel_dir} ({scheme_name})")
    return paths


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def generate_card(headline: str, subline: str, caption: str, title: str,
                  scheme_name: str | None = None) -> tuple[Path, str]:
    date_str = datetime.now().strftime("%Y-%m-%d")
    slug     = re.sub(r"[^a-z0-9]+", "-", title.lower())[:50].strip("-")
    dest     = ASSETS_DIR / f"{date_str}-{slug}.png"
    print(f"  🎨 Rendering card with Pillow...")
    path, used_scheme = render_card(headline, subline, caption, dest, scheme_name)
    print(f"  ✅ Image saved to {path} ({used_scheme})")
    return path, used_scheme


def generate_carousel(slides: list[dict], title: str,
                      scheme_name: str | None = None) -> list[Path]:
    print(f"  🎨 Rendering carousel with Pillow ({len(slides)} slides)...")
    return render_carousel(slides, title, scheme_name)
