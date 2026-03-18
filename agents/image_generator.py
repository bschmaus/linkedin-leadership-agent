"""
Image Generator
---------------
Renders branded LinkedIn card images using Pillow and local fonts.
Default image generation method — pixel-perfect typography, no API cost.

Centering logic:
  - Pass 1 measures visual height as bb[3]-bb[1] per text element (true glyph
    height, excluding Playfair Display's large invisible top padding ~53px).
  - Pass 2 tracks visual_y and draws at (x, visual_y - bb[1]) so the visible
    glyph top aligns precisely. Works correctly for 1 or 2+ headline lines.
"""

import re
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONTS_DIR = Path(__file__).parent.parent / "data" / "fonts"
ASSETS_DIR = Path(__file__).parent.parent / "data" / "assets"

# Palette
NAVY  = (13,  27,  42)
WHITE = (255, 255, 255)
GOLD  = (197, 164, 78)
MUTED = (155, 180, 200)

W, H  = 1200, 675
PAD   = 90


# ---------------------------------------------------------------------------
# Helpers
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
    Draw text at (x, visual_y - bb1) so the visible glyph top aligns with visual_y."""
    bb = draw.textbbox((0, 0), text, font=font)
    return bb[3] - bb[1], bb[1]


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

def render_card(headline: str, subline: str, caption: str, dest: Path) -> Path:
    img  = Image.new("RGB", (W, H), NAVY)
    draw = ImageDraw.Draw(img)

    f_head = _font("PlayfairDisplay-Black.ttf", 148)
    f_sub  = _font("NotoSans-Bold.ttf",          38)
    f_cap  = _font("NotoSans-Regular.ttf",        28)

    max_w = W - PAD * 2

    head_lines = _wrap(draw, headline, f_head, max_w)
    cap_lines  = _wrap(draw, caption,  f_cap,  max_w) if caption else []

    # Spacing constants
    BAR_H         = 8
    BAR_TO_HEAD   = 32
    HEAD_LINE_GAP = 4
    HEAD_TO_DIV   = 28
    DIV_H         = 4
    DIV_TO_SUB    = 24
    SUB_TO_CAP    = 18
    CAP_LINE_GAP  = 8

    # --- Pass 1: measure VISUAL content height ---
    # Uses bb[3]-bb[1] (true glyph height) so invisible font padding doesn't
    # distort the centre calculation — critical for multi-line headlines.
    h = BAR_H + BAR_TO_HEAD
    for i, ln in enumerate(head_lines):
        vh, _ = _vis(draw, ln, f_head)
        h += vh
        if i < len(head_lines) - 1:
            h += HEAD_LINE_GAP
    h += HEAD_TO_DIV + DIV_H + DIV_TO_SUB
    if subline:
        vh, _ = _vis(draw, subline, f_sub)
        h += vh + SUB_TO_CAP
    for i, ln in enumerate(cap_lines):
        vh, _ = _vis(draw, ln, f_cap)
        h += vh
        if i < len(cap_lines) - 1:
            h += CAP_LINE_GAP

    y_bar = max(PAD, (H - h) // 2)

    # --- Pass 2: render ---
    # visual_y tracks the VISUAL top of the next element.
    # Text is drawn at (x, visual_y - bb1) so the visible glyph aligns exactly.

    # Top-left gold accent bar
    draw.rectangle([(PAD, y_bar), (PAD + 64, y_bar + BAR_H)], fill=GOLD)

    visual_y = y_bar + BAR_H + BAR_TO_HEAD

    # Headline
    for i, ln in enumerate(head_lines):
        vh, bb1 = _vis(draw, ln, f_head)
        draw.text((PAD, visual_y - bb1), ln, font=f_head, fill=WHITE)
        visual_y += vh
        if i < len(head_lines) - 1:
            visual_y += HEAD_LINE_GAP

    # Gold divider
    visual_y += HEAD_TO_DIV
    draw.rectangle([(PAD, visual_y), (PAD + 160, visual_y + DIV_H)], fill=GOLD)
    visual_y += DIV_H + DIV_TO_SUB

    # Subline
    if subline:
        vh, bb1 = _vis(draw, subline, f_sub)
        draw.text((PAD, visual_y - bb1), subline, font=f_sub, fill=GOLD)
        visual_y += vh + SUB_TO_CAP

    # Caption
    for i, ln in enumerate(cap_lines):
        vh, bb1 = _vis(draw, ln, f_cap)
        draw.text((PAD, visual_y - bb1), ln, font=f_cap, fill=MUTED)
        visual_y += vh
        if i < len(cap_lines) - 1:
            visual_y += CAP_LINE_GAP

    # Bottom-right anchor bar
    draw.rectangle([(W - PAD - 64, H - PAD - 8), (W - PAD, H - PAD)], fill=GOLD)

    ASSETS_DIR.mkdir(exist_ok=True)
    dest.parent.mkdir(exist_ok=True)
    img.save(dest, "PNG")
    return dest


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_card(headline: str, subline: str, caption: str, title: str) -> Path:
    date_str = datetime.now().strftime("%Y-%m-%d")
    slug     = re.sub(r"[^a-z0-9]+", "-", title.lower())[:50].strip("-")
    dest     = ASSETS_DIR / f"{date_str}-{slug}.png"
    print(f"  🎨 Rendering card with Pillow...")
    path = render_card(headline, subline, caption, dest)
    print(f"  ✅ Image saved to {path}")
    return path
