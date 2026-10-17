"""
src/collector.py — Phase 2: RSS/Atom Feed Collector

Fetches articles from curated feeds defined in config/feeds.yaml.
Returns a list of RawArticle objects filtered to the configured time window.

Design principles:
- Each feed is fetched independently; a failure in one does not abort others.
- Publication dates are parsed strictly; articles with no parseable date are
  given a sentinel value of None and later filtered out by the cleaner.
- No article content is executed or trusted as instructions.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional
from urllib.parse import urlparse

import feedparser
import requests
import yaml

logger = logging.getLogger(__name__)

# ─── Data Model ───────────────────────────────────────────────────────────────

@dataclass
class RawArticle:
    """Immutable record produced by the collector."""
    title: str
    url: str
    source_name: str
    category: str
    published_at: Optional[datetime]   # None if not parseable
    description: str = ""
    priority: int = 3                  # 1=high, 3=low (from feed config)


# ─── Config Loader ────────────────────────────────────────────────────────────

def load_feed_config(path: str | None = None) -> dict:
    """Load and return the feeds YAML configuration."""
    config_path = path or os.getenv("FEEDS_CONFIG_PATH", "config/feeds.yaml")
    with open(config_path, "r", encoding="utf-8") as fh:
        config = yaml.safe_load(fh)
    logger.debug("Loaded feed config from %s (%d feeds)", config_path, len(config.get("feeds", [])))
    return config


# ─── Date Parsing ─────────────────────────────────────────────────────────────

def _parse_date(entry: feedparser.FeedParserDict) -> Optional[datetime]:
    """
    Try to extract a timezone-aware UTC datetime from a feedparser entry.
    Returns None if no valid date can be determined — never assumes 'now'.
    """
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        t = getattr(entry, attr, None)
        if t is not None:
            try:
                dt = datetime(*t[:6], tzinfo=timezone.utc)
                # Sanity check: reject dates in the far future or before 2020
                now = datetime.now(timezone.utc)
                if datetime(2020, 1, 1, tzinfo=timezone.utc) <= dt <= now + timedelta(hours=2):
                    return dt
            except (ValueError, TypeError, OverflowError):
                continue
    return None


# ─── URL Validation ───────────────────────────────────────────────────────────

def _is_valid_url(url: str) -> bool:
    """Return True if *url* looks like a syntactically valid http/https URL."""
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


# ─── Feed Fetcher ─────────────────────────────────────────────────────────────

def _fetch_feed(
    feed_cfg: dict,
    max_age_hours: int,
    max_per_feed: int,
    timeout: int,
    user_agent: str,
) -> list[RawArticle]:
    """
    Fetch a single RSS/Atom feed and return a list of RawArticle objects.
    Exceptions are caught here so one bad feed doesn't kill the pipeline.
    """
    url: str = feed_cfg["url"]
    name: str = feed_cfg["name"]
    category: str = feed_cfg.get("category", "general_ai")
    priority: int = feed_cfg.get("priority", 3)

    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

    try:
        # feedparser can handle redirects, ETag/Modified caching, and gzip
        d = feedparser.parse(
            url,
            agent=user_agent,
            request_headers={"Accept": "application/rss+xml, application/atom+xml, */*"},
        )

        if d.get("bozo") and not d.get("entries"):
            logger.warning("Feed %s: malformed or empty (%s)", name, url)
            return []

        articles: list[RawArticle] = []
        for entry in d.entries[:max_per_feed]:
            title = (entry.get("title") or "").strip()
            link = (entry.get("link") or entry.get("url") or "").strip()

            if not title or not link or not _is_valid_url(link):
                continue

            published_at = _parse_date(entry)

            # Filter by age — if no date, we keep it but mark it uncertain.
            # The cleaner will handle articles with None dates conservatively.
            if published_at is not None and published_at < cutoff:
                continue

            # Prefer summary over content for the description field
            description = ""
            for field_name in ("summary", "description", "content"):
                val = entry.get(field_name)
                if isinstance(val, list):
                    val = val[0].get("value", "") if val else ""
                if val:
                    # Truncate to avoid sending huge text blobs to the LLM
                    description = val[:1000]
                    break

            articles.append(RawArticle(
                title=title,
                url=link,
                source_name=name,
                category=category,
                published_at=published_at,
                description=description,
                priority=priority,
            ))

        logger.info("Feed %-35s → %d articles (of %d entries)", name, len(articles), len(d.entries))
        return articles

    except Exception as exc:
        logger.error("Failed to fetch feed '%s' (%s): %s", name, url, exc)
        return []


# ─── Public API ───────────────────────────────────────────────────────────────

def collect_articles(config_path: str | None = None) -> list[RawArticle]:
    """
    Main entry point for the collector phase.

    Loads feed config, fetches all feeds concurrently (with a small delay to
    be polite), applies exclusion keyword filtering, and returns all fresh
    RawArticle objects sorted by publication date descending.
    """
    config = load_feed_config(config_path)
    settings = config.get("settings", {})
    feeds = config.get("feeds", [])
    exclusion_kw = [kw.lower() for kw in config.get("exclusion_keywords", [])]

    max_age_hours: int = int(settings.get("max_age_hours", 36))
    max_per_feed: int = int(settings.get("max_per_feed", 30))
    timeout: int = int(settings.get("request_timeout", 15))
    user_agent: str = settings.get(
        "user_agent",
        "AI-Daily-Brief/1.0 (automated newsletter)",
    )

    all_articles: list[RawArticle] = []

    for feed_cfg in feeds:
        articles = _fetch_feed(
            feed_cfg=feed_cfg,
            max_age_hours=max_age_hours,
            max_per_feed=max_per_feed,
            timeout=timeout,
            user_agent=user_agent,
        )

        # Apply exclusion keyword filter
        filtered = []
        for art in articles:
            combined = (art.title + " " + art.description).lower()
            if any(kw in combined for kw in exclusion_kw):
                logger.debug("Excluded by keyword: %s", art.title)
            else:
                filtered.append(art)

        all_articles.extend(filtered)
        # Small delay between feeds to avoid hammering servers
        time.sleep(0.3)

    # Sort by date descending (None dates go last)
    all_articles.sort(
        key=lambda a: a.published_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    logger.info("Collector complete: %d articles from %d feeds", len(all_articles), len(feeds))
    return all_articles
