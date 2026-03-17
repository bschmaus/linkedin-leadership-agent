"""
Image Generator
---------------
Renders branded LinkedIn card images using Pillow and local fonts.
Default image generation method — pixel-perfect typography, no API cost.

Centering logic:
  - Content height is measured using bb[3] (draw-origin → glyph bottom) so
    descenders never overlap the next element.
  - Invisible top padding (bb[1]) is excluded from the centering calculation
    so the visual block is truly centred on the canvas.
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


def _adv(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    """Pixels from draw origin to glyph bottom (used to advance y)."""
    return draw.textbbox((0, 0), text, font=font)[3]


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
    BAR_H        = 8
    BAR_TO_HEAD  = 32
    HEAD_LINE_GAP = 4
    HEAD_TO_DIV  = 28
    DIV_H        = 4
    DIV_TO_SUB   = 24
    SUB_TO_CAP   = 18
    CAP_LINE_GAP = 8

    # --- Pass 1: measure VISIBLE content height (exclude invisible top padding) ---
    h = BAR_H + BAR_TO_HEAD
    for i, ln in enumerate(head_lines):
        h += _adv(draw, ln, f_head)
        if i < len(head_lines) - 1:
            h += HEAD_LINE_GAP
    h += HEAD_TO_DIV + DIV_H + DIV_TO_SUB
    if subline:
        h += _adv(draw, subline, f_sub) + SUB_TO_CAP
    for i, ln in enumerate(cap_lines):
        h += _adv(draw, ln, f_cap)
        if i < len(cap_lines) - 1:
            h += CAP_LINE_GAP

    # True vertical centre (no bias — the invisible head padding creates
    # natural visual weight at the top, so pure centre looks balanced)
    y_bar = max(PAD, (H - h) // 2)

    # --- Pass 2: render ---

    # Top-left gold accent bar
    draw.rectangle([(PAD, y_bar), (PAD + 64, y_bar + BAR_H)], fill=GOLD)

    y = y_bar + BAR_H + BAR_TO_HEAD

    # Headline
    for i, ln in enumerate(head_lines):
        draw.text((PAD, y), ln, font=f_head, fill=WHITE)
        y += _adv(draw, ln, f_head)
        if i < len(head_lines) - 1:
            y += HEAD_LINE_GAP

    # Gold divider
    y += HEAD_TO_DIV
    draw.rectangle([(PAD, y), (PAD + 160, y + DIV_H)], fill=GOLD)
    y += DIV_H + DIV_TO_SUB

    # Subline
    if subline:
        draw.text((PAD, y), subline, font=f_sub, fill=GOLD)
        y += _adv(draw, subline, f_sub) + SUB_TO_CAP

    # Caption
    for i, ln in enumerate(cap_lines):
        draw.text((PAD, y), ln, font=f_cap, fill=MUTED)
        y += _adv(draw, ln, f_cap)
        if i < len(cap_lines) - 1:
            y += CAP_LINE_GAP

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
