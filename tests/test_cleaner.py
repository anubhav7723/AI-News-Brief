"""
tests/test_cleaner.py — Unit tests for the deduplication and normalization module.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.collector import RawArticle
from src.cleaner import (
    normalise_url,
    _normalise_title,
    _titles_similar,
    clean_and_deduplicate,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

_UNSET = object()


def _make_article(
    title: str = "Test Article",
    url: str = "https://example.com/article-1",
    source_name: str = "Test Source",
    category: str = "general_ai",
    priority: int = 2,
    description: str = "A description",
    published_at=_UNSET,
) -> RawArticle:
    if published_at is _UNSET:
        published_at = datetime(2026, 10, 17, 6, 0, 0, tzinfo=timezone.utc)
    return RawArticle(
        title=title,
        url=url,
        source_name=source_name,
        category=category,
        published_at=published_at,
        description=description,
        priority=priority,
    )


def _load_fixture_articles() -> list[RawArticle]:
    data = json.loads(Path("tests/fixtures/sample_articles.json").read_text(encoding="utf-8"))
    return [
        RawArticle(
            title=item["title"],
            url=item["url"],
            source_name=item["source_name"],
            category=item["category"],
            published_at=datetime.fromisoformat(item["published_at"]),
            description=item.get("description", ""),
            priority=item.get("priority", 3),
        )
        for item in data
    ]


# ─── URL Normalisation ────────────────────────────────────────────────────────

class TestNormaliseUrl:
    def test_strips_utm_params(self):
        url = "https://example.com/article?utm_source=twitter&utm_medium=social"
        assert normalise_url(url) == "https://example.com/article"

    def test_strips_fragment(self):
        url = "https://example.com/article#section"
        assert normalise_url(url) == "https://example.com/article"

    def test_strips_trailing_slash(self):
        url = "https://example.com/article/"
        assert normalise_url(url) == "https://example.com/article"

    def test_lowercases_host(self):
        url = "https://OpenAI.COM/blog/gpt-5"
        result = normalise_url(url)
        assert "openai.com" in result

    def test_preserves_non_tracking_params(self):
        url = "https://arxiv.org/abs/2410.12345?version=2"
        result = normalise_url(url)
        assert "version=2" in result

    def test_handles_malformed_url(self):
        # Should return original without raising
        result = normalise_url("not-a-url")
        assert result == "not-a-url"


# ─── Title Similarity ─────────────────────────────────────────────────────────

class TestTitlesSimilar:
    def test_identical_titles(self):
        assert _titles_similar("OpenAI releases GPT-5", "OpenAI releases GPT-5") is True

    def test_clearly_different(self):
        assert _titles_similar(
            "OpenAI releases GPT-5",
            "New RAG technique achieves high accuracy"
        ) is False

    def test_near_duplicate(self):
        # Same story, near-identical wording (high Jaccard overlap)
        assert _titles_similar(
            "OpenAI releases GPT-5 with improved reasoning capabilities benchmark",
            "OpenAI releases GPT-5 improved reasoning capabilities benchmark",
        ) is True

    def test_empty_titles(self):
        assert _titles_similar("", "") is False


# ─── Clean and Deduplicate ────────────────────────────────────────────────────

class TestCleanAndDeduplicate:
    def test_basic_clean(self):
        articles = _load_fixture_articles()
        result = clean_and_deduplicate(articles, frozenset(), [])
        assert len(result) == len(articles)

    def test_removes_url_duplicates(self):
        art = _make_article(url="https://example.com/article-1")
        # Same article twice
        articles = [art, _make_article(url="https://example.com/article-1", title="Same URL")]
        result = clean_and_deduplicate(articles, frozenset(), [])
        assert len(result) == 1

    def test_removes_history_urls(self):
        art = _make_article(url="https://example.com/article-1")
        sent_urls = frozenset(["https://example.com/article-1"])
        result = clean_and_deduplicate([art], sent_urls, [])
        assert len(result) == 0

    def test_removes_no_date_articles_by_default(self):
        art = _make_article(published_at=None)
        result = clean_and_deduplicate([art], frozenset(), [])
        assert len(result) == 0

    def test_keeps_no_date_when_disabled(self):
        art = _make_article(published_at=None)
        result = clean_and_deduplicate([art], frozenset(), [], drop_no_date=False)
        assert len(result) == 1

    def test_removes_near_duplicate_titles(self):
        art1 = _make_article(title="OpenAI releases GPT-5 with improved reasoning", url="https://a.com/1")
        art2 = _make_article(title="OpenAI releases GPT-5 improved reasoning capabilities", url="https://b.com/2")
        result = clean_and_deduplicate([art1, art2], frozenset(), [])
        assert len(result) == 1

    def test_result_sorted_by_score(self):
        # Priority 1 article should come before priority 3
        high_prio = _make_article(url="https://a.com/1", priority=1)
        low_prio  = _make_article(url="https://b.com/2", priority=3, title="Different Title")
        result = clean_and_deduplicate([low_prio, high_prio], frozenset(), [])
        assert result[0].priority == 1

    def test_utm_urls_deduplicated(self):
        art1 = _make_article(url="https://example.com/article")
        art2 = _make_article(url="https://example.com/article?utm_source=twitter", title="Same Article UTM")
        result = clean_and_deduplicate([art1, art2], frozenset(), [])
        assert len(result) == 1
