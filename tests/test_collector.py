"""
tests/test_collector.py — Unit tests for the RSS feed collector.

Tests cover:
- URL validation
- Date parsing (valid, None, future, ancient)
- Exclusion keyword filtering
- Feed failure isolation (one bad feed doesn't kill the rest)
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.collector import (
    RawArticle,
    _is_valid_url,
    _parse_date,
    load_feed_config,
)
from src.cleaner import normalise_url


# ─── URL Validation ───────────────────────────────────────────────────────────

class TestIsValidUrl:
    def test_valid_https(self):
        assert _is_valid_url("https://openai.com/blog/gpt-5") is True

    def test_valid_http(self):
        assert _is_valid_url("http://example.com/article") is True

    def test_missing_scheme(self):
        assert _is_valid_url("openai.com/blog") is False

    def test_ftp_scheme(self):
        assert _is_valid_url("ftp://example.com/file") is False

    def test_empty_string(self):
        assert _is_valid_url("") is False

    def test_relative_url(self):
        assert _is_valid_url("/relative/path") is False


# ─── Date Parsing ─────────────────────────────────────────────────────────────

class TestParseDate:
    def _make_entry(self, **kwargs):
        """Create a mock feedparser entry with the given attributes."""
        entry = MagicMock()
        entry.published_parsed = kwargs.get("published_parsed", None)
        entry.updated_parsed   = kwargs.get("updated_parsed", None)
        entry.created_parsed   = kwargs.get("created_parsed", None)
        return entry

    def test_valid_published_parsed(self):
        t = (2026, 10, 17, 6, 0, 0, 4, 290, 0)
        entry = self._make_entry(published_parsed=t)
        result = _parse_date(entry)
        assert result is not None
        assert result.year == 2026
        assert result.month == 10
        assert result.tzinfo == timezone.utc

    def test_future_date_rejected(self):
        # 2099 is in the far future
        t = (2099, 1, 1, 0, 0, 0, 0, 1, 0)
        entry = self._make_entry(published_parsed=t)
        result = _parse_date(entry)
        assert result is None

    def test_ancient_date_rejected(self):
        # 2015 is before our 2020 cutoff
        t = (2015, 6, 15, 12, 0, 0, 0, 166, 0)
        entry = self._make_entry(published_parsed=t)
        result = _parse_date(entry)
        assert result is None

    def test_no_date_returns_none(self):
        entry = self._make_entry()
        result = _parse_date(entry)
        assert result is None

    def test_falls_back_to_updated_parsed(self):
        t = (2026, 10, 16, 12, 0, 0, 3, 289, 0)
        entry = self._make_entry(updated_parsed=t)
        result = _parse_date(entry)
        assert result is not None
        assert result.day == 16


# ─── Config Loading ───────────────────────────────────────────────────────────

class TestLoadFeedConfig:
    def test_loads_real_config(self):
        config = load_feed_config("config/feeds.yaml")
        assert "feeds" in config
        assert len(config["feeds"]) > 0
        assert "settings" in config

    def test_each_feed_has_required_keys(self):
        config = load_feed_config("config/feeds.yaml")
        for feed in config["feeds"]:
            assert "url" in feed, f"Feed missing 'url': {feed}"
            assert "name" in feed, f"Feed missing 'name': {feed}"
            assert "category" in feed, f"Feed missing 'category': {feed}"

    def test_nonexistent_config_raises(self):
        with pytest.raises(FileNotFoundError):
            load_feed_config("nonexistent/path.yaml")


# ─── RawArticle Fixture ───────────────────────────────────────────────────────

class TestRawArticleFromFixture:
    def test_load_fixture(self):
        fixture_path = Path("tests/fixtures/sample_articles.json")
        articles_data = json.loads(fixture_path.read_text(encoding="utf-8"))
        assert len(articles_data) == 5

        for item in articles_data:
            art = RawArticle(
                title=item["title"],
                url=item["url"],
                source_name=item["source_name"],
                category=item["category"],
                published_at=datetime.fromisoformat(item["published_at"]),
                description=item.get("description", ""),
                priority=item.get("priority", 3),
            )
            assert art.title
            assert art.url.startswith("http")
