"""
src/cleaner.py — Phase 3: Deduplication & Normalization

Takes the raw list of RawArticle objects from the collector and:
1. Normalises each URL (strips tracking params, fragments, trailing slashes).
2. Deduplicates within the current batch (same URL or near-identical title).
3. Filters against the sent-stories history to prevent repeat coverage.
4. Drops articles with no parseable date (conservative: assume stale).
5. Scores articles using a simple heuristic to boost high-priority/recent items.

Returns a sorted list of cleaned RawArticle objects ready for LLM ranking.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Sequence
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

from src.collector import RawArticle

logger = logging.getLogger(__name__)

# ─── URL Normalisation ────────────────────────────────────────────────────────

# Query parameters that are purely tracking and carry no semantic value
_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "referrer", "fbclid", "gclid", "yclid", "mc_cid", "mc_eid",
    "source", "via", "_r",
})


def normalise_url(url: str) -> str:
    """
    Return a canonical form of *url* by:
    - Lowercasing the scheme and host.
    - Removing fragment identifiers (#...).
    - Stripping known tracking query parameters.
    - Removing trailing slashes from the path.
    """
    try:
        parsed = urlparse(url.strip())
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        path = parsed.path.rstrip("/") or "/"
        # Filter tracking params
        qs = parse_qs(parsed.query, keep_blank_values=False)
        clean_qs = {k: v for k, v in qs.items() if k.lower() not in _TRACKING_PARAMS}
        query = urlencode(clean_qs, doseq=True)
        return urlunparse((scheme, netloc, path, parsed.params, query, ""))
    except Exception:
        return url


# ─── Title Normalisation ──────────────────────────────────────────────────────

_NON_ALPHA = re.compile(r"[^a-z0-9\s]")
_WHITESPACE = re.compile(r"\s+")


def _normalise_title(title: str) -> str:
    """
    Return a cleaned, lowercase version of *title* for fuzzy comparison.
    Strips punctuation and collapses whitespace.
    """
    lower = title.lower()
    stripped = _NON_ALPHA.sub(" ", lower)
    return _WHITESPACE.sub(" ", stripped).strip()


def _titles_similar(a: str, b: str, threshold: float = 0.70) -> bool:
    """
    Return True if two normalised titles share more than *threshold* of their
    words (Jaccard similarity on unigrams).  This catches near-identical
    headlines without requiring an embedding model.
    """
    words_a = set(_normalise_title(a).split())
    words_b = set(_normalise_title(b).split())
    if not words_a or not words_b:
        return False
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union) >= threshold


# ─── Boost Scoring ────────────────────────────────────────────────────────────

# Words in title/description that hint at high AI-engineering value
_BOOST_WORDS = frozenset({
    "open source", "open-source", "released", "launches", "launch",
    "benchmark", "state-of-the-art", "sota", "research", "paper",
    "agentic", "multimodal", "fine-tuning", "fine tuning", "inference",
    "rag", "embedding", "embeddings", "model", "llm", "agent", "mcp",
    "langgraph", "transformer", "diffusion", "quantization", "gguf",
    "lora", "rlhf", "dpo", "sft", "gpu", "tpu", "mlops",
})


def _heuristic_score(article: RawArticle) -> float:
    """
    Compute a simple pre-LLM relevance score in [0, 1] based on:
    - Source priority (1 = 0.4 bonus, 2 = 0.2, 3 = 0)
    - Recency (decays over 36 hours)
    - Keyword boosts (+0.05 per keyword hit, max 0.3)

    Lower priority number = more important source.
    """
    score = 0.0

    # Source priority bonus
    priority_bonus = {1: 0.4, 2: 0.2}.get(article.priority, 0.0)
    score += priority_bonus

    # Recency bonus
    if article.published_at:
        age_hours = (datetime.now(timezone.utc) - article.published_at).total_seconds() / 3600
        recency = max(0.0, 1.0 - age_hours / 36.0) * 0.3
        score += recency

    # Keyword boost
    combined = (article.title + " " + article.description).lower()
    hits = sum(1 for kw in _BOOST_WORDS if kw in combined)
    score += min(hits * 0.05, 0.3)

    return min(score, 1.0)


# ─── Main Cleaning Function ────────────────────────────────────────────────────

def clean_and_deduplicate(
    articles: Sequence[RawArticle],
    sent_urls: frozenset[str],
    sent_titles: list[str],
    drop_no_date: bool = True,
) -> list[RawArticle]:
    """
    Clean, deduplicate, and score a list of RawArticle objects.

    Parameters
    ----------
    articles      : Raw articles from the collector.
    sent_urls     : Normalised URLs of previously sent stories.
    sent_titles   : Titles of previously sent stories (for fuzzy dedup).
    drop_no_date  : If True, articles without a parseable date are dropped.

    Returns
    -------
    Cleaned articles sorted by heuristic score descending.
    """
    seen_urls: set[str] = set()
    seen_titles: list[str] = []
    result: list[RawArticle] = []

    dropped_stats = {"no_date": 0, "dup_url": 0, "dup_title": 0, "history": 0}

    for art in articles:
        # 1. Drop articles with no parseable date
        if drop_no_date and art.published_at is None:
            dropped_stats["no_date"] += 1
            continue

        norm_url = normalise_url(art.url)

        # 2. Deduplicate by URL within current batch
        if norm_url in seen_urls:
            dropped_stats["dup_url"] += 1
            continue

        # 3. Check against sent history by URL
        if norm_url in sent_urls:
            dropped_stats["history"] += 1
            continue

        # 4. Fuzzy title dedup within current batch
        is_dup_title = any(_titles_similar(art.title, t) for t in seen_titles)
        if is_dup_title:
            dropped_stats["dup_title"] += 1
            continue

        # 5. Fuzzy title dedup against history
        is_in_history = any(_titles_similar(art.title, t) for t in sent_titles)
        if is_in_history:
            dropped_stats["history"] += 1
            continue

        seen_urls.add(norm_url)
        seen_titles.append(art.title)
        result.append(art)

    logger.info(
        "Cleaner: %d → %d articles. Dropped: no_date=%d dup_url=%d dup_title=%d history=%d",
        len(articles),
        len(result),
        dropped_stats["no_date"],
        dropped_stats["dup_url"],
        dropped_stats["dup_title"],
        dropped_stats["history"],
    )

    # Sort by heuristic score descending for better LLM context ordering
    result.sort(key=_heuristic_score, reverse=True)
    return result
