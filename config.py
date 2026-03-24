"""Shared configuration, file paths, and sentinel constants."""
import os
import re
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(override=True)

BASE_DIR             = Path(__file__).parent
DATA_DIR             = BASE_DIR / "data"
ASSETS_DIR           = DATA_DIR / "assets"
ARTICLES_ARCHIVE_DIR = DATA_DIR / "archive"

LEARNINGS_FILE       = DATA_DIR / "learnings.md"
DAILY_ARTICLES_FILE  = DATA_DIR / "daily_articles.md"
RESEARCH_NOTES_FILE  = DATA_DIR / "research_notes.md"
SELECTION_NOTES_FILE = DATA_DIR / "selection_notes.md"
VOICE_FILE           = DATA_DIR / "voice.md"
POST_ASSETS_FILE     = DATA_DIR / "post_assets.md"
REDTEAM_NOTES_FILE   = DATA_DIR / "redteam_notes.md"
BRAND_FILE           = DATA_DIR / "ow_brand_guidelines.md"

# Sentinel strings used as placeholders in data files.
# All guards should reference these constants — never hardcode the strings.
EMPTY_LEARNINGS  = "_No learnings yet._"
EMPTY_ARTICLES   = "_No articles yet._"
EMPTY_RESEARCH   = "_No research yet._"
EMPTY_SELECTION  = "_No selection yet._"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

MODEL = "claude-opus-4-6"

RSS_FEEDS = [
    # English — US
    "https://www.fastcompany.com/leadership/rss",
    "https://sloanreview.mit.edu/feed/",
    "https://knowledge.wharton.upenn.edu/feed/",       # Wharton — peer of HBR quality
    "https://www.worklife.news/feed/",                 # Work Life News — future of work

    # German-language
    "https://www.personalwirtschaft.de/feed/",         # Personalwirtschaft — HR & leadership
]

# Fallback: pages to scrape when no RSS is available
EXTRA_SOURCES = [
    "https://www.oliverwymanforum.com",                # Oliver Wyman Forum (employer — good to reference)
    "https://www.gallup.com/workplace/insights.aspx",  # Gallup workplace research
    "https://hbr.org/topic/subject/managing-people",   # HBR — killed RSS, scrape topic page instead
]

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY")   # optional: DALL-E 3 (--creative mode)
GOOGLE_API_KEY    = os.getenv("GOOGLE_API_KEY")   # optional: Imagen 4 fallback (--creative mode)


# ---------------------------------------------------------------------------
# Low-level helpers (no agent dependencies — safe to import everywhere)
# ---------------------------------------------------------------------------

def read_file(path: Path) -> str:
    """Read a shared data file. Returns empty string if missing."""
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def parse_post_blocks(articles: str) -> list[str]:
    """Split daily_articles.md content into individual post blocks.

    Skips the file header and empty blocks. Used by utils.py helpers
    and by rotate_articles_archive.
    """
    blocks = re.split(r"\n---\n", articles)
    return [b for b in blocks if b.strip() and not b.strip().startswith("# Daily")]


def ensure_data_dir() -> None:
    """Create data/ and initialise empty shared files if they don't exist."""
    DATA_DIR.mkdir(exist_ok=True)
    ASSETS_DIR.mkdir(exist_ok=True)
    ARTICLES_ARCHIVE_DIR.mkdir(exist_ok=True)
    defaults = {
        LEARNINGS_FILE:       f"# Learnings & Improvements\n\n{EMPTY_LEARNINGS}\n",
        DAILY_ARTICLES_FILE:  f"# Daily LinkedIn Articles\n\n{EMPTY_ARTICLES}\n",
        RESEARCH_NOTES_FILE:  f"# Research Notes\n\n{EMPTY_RESEARCH}\n",
        SELECTION_NOTES_FILE: f"# Selection Notes\n\n{EMPTY_SELECTION}\n",
    }
    for path, content in defaults.items():
        if not path.exists():
            path.write_text(content, encoding="utf-8")
