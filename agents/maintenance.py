"""
Maintenance tasks — housekeeping that runs before the daily pipeline.
"""

import re
from datetime import datetime, timedelta

from config import (
    DAILY_ARTICLES_FILE,
    ARTICLES_ARCHIVE_DIR,
    read_file,
    parse_post_blocks,
)
from agents.utils import extract_post_date


def rotate_articles_archive() -> None:
    """Move posts older than 30 days from daily_articles.md to monthly archive files.

    Keeps daily_articles.md lean (~30 entries max). Archived posts go to
    data/archive/articles-YYYY-MM.md and remain available for reference.
    """
    content = read_file(DAILY_ARTICLES_FILE)
    if not content.strip():
        return

    posts = parse_post_blocks(content)
    if not posts:
        return

    cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    # Split the file: everything before the first post block is the header
    first_post_idx = content.find(posts[0].strip()[:40])
    header = content[:first_post_idx].rstrip("\n-— \t") if first_post_idx > 0 else "# Daily LinkedIn Articles"

    keep: list[str] = []
    archive: dict[str, list[str]] = {}  # "YYYY-MM" → list of blocks

    for block in posts:
        block_stripped = block.strip()
        post_date = extract_post_date(block_stripped)

        if post_date and post_date < cutoff:
            month_key = post_date[:7]  # "YYYY-MM"
            archive.setdefault(month_key, []).append(block_stripped)
        else:
            keep.append(block_stripped)

    if not archive:
        return  # nothing to archive

    # Write archive files (append to existing monthly files)
    for month_key, entries in archive.items():
        archive_path = ARTICLES_ARCHIVE_DIR / f"articles-{month_key}.md"
        existing = read_file(archive_path)
        if not existing:
            existing = f"# Archived Articles — {month_key}\n"
        new_content = existing.rstrip() + "\n\n---\n\n" + "\n\n---\n\n".join(entries) + "\n"
        archive_path.write_text(new_content, encoding="utf-8")

    # Rewrite daily_articles.md with only recent posts
    if keep:
        new_content = header + "\n\n---\n\n" + "\n\n---\n\n".join(keep) + "\n"
    else:
        new_content = header + "\n"
    DAILY_ARTICLES_FILE.write_text(new_content, encoding="utf-8")

    total_archived = sum(len(v) for v in archive.values())
    print(f"  📦 Archived {total_archived} post(s) older than 30 days")
