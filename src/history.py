"""
src/history.py — Phase 7: Persistent Story Memory

Maintains a lightweight JSON file that records every story ever sent.
Used by the cleaner to prevent re-featuring the same story in consecutive editions.

Design:
- Storage: data/sent_stories.json (configurable via env var)
- Retention: configurable number of days (default 7) — older entries are pruned
  on each write to keep the file small.
- Records: {url, normalised_url, title, send_date, edition_date}

Thread safety: Not required — the pipeline is single-threaded.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from src.cleaner import normalise_url

logger = logging.getLogger(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────

DEFAULT_HISTORY_PATH = "data/sent_stories.json"
DEFAULT_RETENTION_DAYS = 7


def _history_path() -> Path:
    return Path(os.environ.get("HISTORY_FILE_PATH", DEFAULT_HISTORY_PATH))


def _retention_days() -> int:
    return int(os.environ.get("HISTORY_RETENTION_DAYS", str(DEFAULT_RETENTION_DAYS)))


# ─── Load / Save ──────────────────────────────────────────────────────────────

def load_history() -> list[dict[str, Any]]:
    """
    Load the history file.  Returns an empty list if the file doesn't exist
    or cannot be parsed — history loss is recoverable (worst case: a story
    re-appears in the next edition).
    """
    path = _history_path()
    if not path.exists():
        logger.info("No history file found at %s — starting fresh.", path)
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, list):
            logger.warning("History file has unexpected format — resetting.")
            return []
        logger.info("Loaded %d history records from %s", len(data), path)
        return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read history file (%s) — starting fresh.", exc)
        return []


def save_history(records: list[dict[str, Any]]) -> None:
    """
    Prune old entries and save the history file.
    Old entries (beyond retention window) are dropped before saving.
    """
    path = _history_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    cutoff = datetime.now(timezone.utc) - timedelta(days=_retention_days())
    pruned = []
    for rec in records:
        send_date_str = rec.get("send_date")
        if send_date_str:
            try:
                send_date = datetime.fromisoformat(send_date_str)
                if send_date.tzinfo is None:
                    send_date = send_date.replace(tzinfo=timezone.utc)
                if send_date >= cutoff:
                    pruned.append(rec)
                continue
            except ValueError:
                pass
        # Keep records without a parseable date to avoid data loss
        pruned.append(rec)

    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(pruned, fh, indent=2, ensure_ascii=False, default=str)
        logger.info("Saved %d history records to %s (pruned %d old entries)",
                    len(pruned), path, len(records) - len(pruned))
    except OSError as exc:
        logger.error("Could not save history file: %s", exc)


# ─── Query Helpers ────────────────────────────────────────────────────────────

def get_sent_urls(records: list[dict[str, Any]]) -> frozenset[str]:
    """Return the set of normalised URLs from history records."""
    urls = set()
    for rec in records:
        norm = rec.get("normalised_url") or normalise_url(rec.get("url", ""))
        if norm:
            urls.add(norm)
    return frozenset(urls)


def get_sent_titles(records: list[dict[str, Any]]) -> list[str]:
    """Return the list of titles from history records."""
    return [rec["title"] for rec in records if rec.get("title")]


# ─── Update Helper ────────────────────────────────────────────────────────────

def add_sent_stories(
    records: list[dict[str, Any]],
    stories: list,               # list[RankedStory]
    edition_date: str,
) -> list[dict[str, Any]]:
    """
    Append the newly sent stories to the history records list and return
    the updated list.  Does not save to disk — call save_history() separately.
    """
    now = datetime.now(timezone.utc).isoformat()
    new_records = list(records)  # shallow copy

    for story in stories:
        new_records.append({
            "url": story.original_url,
            "normalised_url": normalise_url(story.original_url),
            "title": story.headline,
            "send_date": now,
            "edition_date": edition_date,
        })

    logger.info("Added %d new stories to history (%d total)", len(stories), len(new_records))
    return new_records


# ─── Edition Guard ────────────────────────────────────────────────────────────

def edition_already_sent(records: list[dict[str, Any]], edition_date: str) -> bool:
    """
    Return True if a record with this exact edition_date already exists.
    Used to prevent duplicate sends for the same edition.
    """
    return any(rec.get("edition_date") == edition_date for rec in records)
