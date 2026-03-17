"""Shared configuration and file paths."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR             = Path(__file__).parent
DATA_DIR             = BASE_DIR / "data"

LEARNINGS_FILE       = DATA_DIR / "learnings.md"
DAILY_ARTICLES_FILE  = DATA_DIR / "daily_articles.md"
RESEARCH_NOTES_FILE  = DATA_DIR / "research_notes.md"
SELECTION_NOTES_FILE = DATA_DIR / "selection_notes.md"

MODEL = "claude-opus-4-6"

RSS_FEEDS = [
    "https://www.fastcompany.com/leadership/rss",
    "https://sloanreview.mit.edu/feed/",
    "https://hbr.org/feed",                            # Harvard Business Review
]

# Fallback: homepages to scrape when no RSS is available
EXTRA_SOURCES = [
    "https://www.oliverwymanforum.com",                # Oliver Wyman Forum (employer — good to reference)
    "https://www.gallup.com/workplace/insights.aspx",  # Gallup workplace research
]

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY")   # optional: DALL-E 3 (--creative mode)
GOOGLE_API_KEY    = os.getenv("GOOGLE_API_KEY")   # optional: Imagen 4 fallback (--creative mode)


def read_file(path: Path) -> str:
    """Read a shared data file. Returns empty string if missing."""
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def ensure_data_dir() -> None:
    """Create data/ and initialise empty shared files if they don't exist."""
    DATA_DIR.mkdir(exist_ok=True)
    defaults = {
        LEARNINGS_FILE:       "# Learnings & Improvements\n\n_No learnings yet._\n",
        DAILY_ARTICLES_FILE:  "# Daily LinkedIn Articles\n\n_No articles yet._\n",
        RESEARCH_NOTES_FILE:  "# Research Notes\n\n_No research yet._\n",
        SELECTION_NOTES_FILE: "# Selection Notes\n\n_No selection yet._\n",
    }
    for path, content in defaults.items():
        if not path.exists():
            path.write_text(content, encoding="utf-8")
