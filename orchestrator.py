"""
LinkedIn Leadership Post Orchestrator
--------------------------------------
Fully automated daily pipeline — no manual intervention required.

  1. Scanning       — fetch RSS sources, distil 3-5 topic candidates
  2. Selection      — pick the best topic with adaptive thinking
  3. Article Writer — ghostwrite the LinkedIn post
  4. Poster         — choose format, generate typography card image
  5. Red Team       — fact-check + client-lens + brief-compliance critique; iterate up to 3×
  6. Proofreading   — final spell/grammar check (Sonnet, low cost)
  7. Assessment     — critique the post, update learnings for tomorrow

Human steps (outside this pipeline):
  • Post the finished text + image manually on LinkedIn
  • Upload the weekly LinkedIn Analytics export to data/analytics/ on Fridays

Usage:
    python orchestrator.py                         # full pipeline (default)
    python orchestrator.py --from scan             # restart from scanning
    python orchestrator.py --from write            # restart from article writer
    python orchestrator.py --from redteam          # re-run red team + assessment only
    python orchestrator.py --only post             # regenerate image/assets only
    python orchestrator.py --only post --creative  # use DALL-E instead of typography card
    python orchestrator.py --only assess           # re-run assessment (e.g. after analytics upload)

Available agent names: scan, select, write, post, redteam, assess
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import anthropic

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent))

from config import DATA_DIR, VOICE_FILE, ANTHROPIC_API_KEY
from agents import scanning, selection, article_writer, poster, red_team, proofread, assessment
from agents.maintenance import rotate_articles_archive


# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

def preflight() -> None:
    """Validate critical dependencies before the pipeline starts."""
    errors = []

    # API key
    if not ANTHROPIC_API_KEY:
        errors.append("ANTHROPIC_API_KEY not set (check .env)")

    # voice.md must exist (all agents depend on it)
    if not VOICE_FILE.exists():
        errors.append(f"Missing {VOICE_FILE}")

    # Fonts required by image_generator
    fonts_dir = DATA_DIR / "fonts"
    required_fonts = ["PlayfairDisplay-Black.ttf"]
    for font in required_fonts:
        if not (fonts_dir / font).exists():
            errors.append(f"Missing font: {fonts_dir / font}")

    # Python dependencies
    for module in ["feedparser", "PIL", "anthropic"]:
        try:
            __import__(module)
        except ImportError:
            errors.append(f"Missing Python package: {module} (pip3 install {module})")

    if errors:
        print("\n❌ Pre-flight check failed:")
        for e in errors:
            print(f"   • {e}")
        print()
        raise SystemExit(1)


AGENTS = [
    ("scan",     "Scanning",        scanning.run),
    ("select",   "Selection",       selection.run),
    ("write",    "Article Writer",  article_writer.run),
    ("post",     "Poster",          poster.run),
    ("redteam",  "Red Team",        red_team.run),
    ("proof",    "Proofreading",    proofread.run),
    ("assess",   "Assessment",      assessment.run),
]

AGENT_NAMES = [name for name, _, _ in AGENTS]


def _notify(title: str, message: str) -> None:
    """Send a macOS notification. Silently skips on non-macOS or if osascript missing."""
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{message}" with title "{title}" sound name "Glass"'],
            check=False, capture_output=True,
        )
    except FileNotFoundError:
        pass


def _notify_whatsapp(message: str) -> None:
    """
    Send a WhatsApp message via CallMeBot (free, no app install needed).

    Setup (one-time):
      1. Add +34 644 52 74 86 to your contacts as "CallMeBot"
      2. Send this exact text via WhatsApp to that number:
             I allow callmebot to send me messages
      3. You'll receive an apikey back within seconds.
      4. Set these env vars (e.g. in .env):
             CALLMEBOT_PHONE=49176XXXXXXX   (country code, no +)
             CALLMEBOT_APIKEY=XXXXXXX
    """
    phone  = os.getenv("CALLMEBOT_PHONE")
    apikey = os.getenv("CALLMEBOT_APIKEY")
    if not phone or not apikey:
        return  # not configured — silently skip
    try:
        encoded = urllib.parse.quote(message)
        url = f"https://api.callmebot.com/whatsapp.php?phone={phone}&text={encoded}&apikey={apikey}"
        urllib.request.urlopen(url, timeout=10)  # noqa: S310
    except Exception as exc:
        print(f"  ⚠️  WhatsApp notification failed: {exc}")


def banner(text: str, width: int = 68) -> None:
    print("\n" + "═" * width)
    print(f"  {text}")
    print("═" * width)


def run_pipeline(start_from: str | None = None, only: str | None = None,
                 creative: bool = False) -> None:
    client = anthropic.Anthropic()

    if only:
        # Single-agent mode
        match = [(n, label, fn) for n, label, fn in AGENTS if n == only]
        if not match:
            print(f"Unknown agent '{only}'. Choose from: {', '.join(AGENT_NAMES)}")
            sys.exit(1)
        name, label, fn = match[0]
        banner(f"Running: {label}")
        t0 = time.time()
        # Pass creative flag to poster only
        if name == "post":
            fn(client, creative=creative)
        else:
            fn(client)
        banner(f"✅ {label} complete ({time.time() - t0:.1f}s)")
        return

    # Determine start index
    start_idx = 0
    if start_from:
        indices = [i for i, (n, _, _) in enumerate(AGENTS) if n == start_from]
        if not indices:
            print(f"Unknown agent '{start_from}'. Choose from: {', '.join(AGENT_NAMES)}")
            sys.exit(1)
        start_idx = indices[0]

    preflight()
    rotate_articles_archive()
    banner("LinkedIn Leadership Post Pipeline — starting")
    total_start = time.time()

    for i, (name, label, fn) in enumerate(AGENTS):
        if i < start_idx:
            print(f"  ⏭  Skipping {label}")
            continue

        banner(f"Step {i + 1}/{len(AGENTS)}: {label}")
        t0 = time.time()
        try:
            if name == "post":
                fn(client, creative=creative)
            else:
                fn(client)
        except Exception as exc:
            print(f"\n  ❌ {label} failed: {exc}")
            print(f"     Resume from this step with: python orchestrator.py --from {name}")
            _notify("LinkedIn Pipeline fehlgeschlagen ❌", f"{label} abgebrochen: {exc}")
            _notify_whatsapp(f"LinkedIn Agent: {label} fehlgeschlagen\n{exc}\nResume: python orchestrator.py --from {name}")
            sys.exit(1)
        print(f"\n  ✅ {label} done ({time.time() - t0:.1f}s)")

    elapsed = time.time() - total_start
    banner(f"🎉 Pipeline complete! Total time: {elapsed:.0f}s")
    _notify("LinkedIn Post Ready ✍️", "Post text + image are ready — open post_assets.md to review.")
    _notify_whatsapp("LinkedIn Agent: Post fertig! Bitte post_assets.md prüfen und manuell posten.")
    print("  Next steps:")
    print("  1. Review  : data/post_assets.md")
    if (Path(__file__).parent / "data" / "assets").exists():
        images = list((Path(__file__).parent / "data" / "assets").glob("*.png"))
        if images:
            newest = max(images, key=lambda p: p.stat().st_mtime)
            print(f"  2. Image   : {newest}")
    print("  3. Post manually on LinkedIn")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="LinkedIn Leadership post pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"Agent names: {', '.join(AGENT_NAMES)}",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--from", dest="start_from", metavar="AGENT",
        help="Start pipeline from this agent (inclusive)",
    )
    group.add_argument(
        "--only", metavar="AGENT",
        help="Run only this single agent",
    )
    parser.add_argument(
        "--creative", action="store_true",
        help="Use DALL-E for a creative AI image instead of the typography card (poster only)",
    )
    args = parser.parse_args()
    run_pipeline(start_from=args.start_from, only=args.only, creative=args.creative)


if __name__ == "__main__":
    main()
