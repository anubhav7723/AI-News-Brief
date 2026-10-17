"""
src/summarizer.py — Phase 4b: LLM Story Summarisation

Takes the ranked list of RawArticle objects and asks Gemini to generate
a full structured summary for each story.

The LLM receives articles in batches (currently all in one call to minimise
API requests while staying well within free-tier token limits).

Each summary includes:
  - A factual headline
  - A 2–4 sentence factual summary
  - Why it matters to an AI/ML engineer
  - An optional technical experiment/takeaway
  - Category and confidence labels

Output is validated against RankedStory (Pydantic) before use.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Sequence

from groq import Groq
from pydantic import ValidationError

from src.collector import RawArticle
from src.validator import RankedStory, StoryCategory, ConfidenceLevel, BriefEdition

logger = logging.getLogger(__name__)

# ─── Groq Client ──────────────────────────────────────────────────────────────

def _get_client_and_model() -> tuple[Groq, str]:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise EnvironmentError("GROQ_API_KEY is not set")
    model_name = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")
    client = Groq(api_key=api_key)
    return client, model_name


# ─── Prompts ──────────────────────────────────────────────────────────────────

_SUMMARISE_SYSTEM = """\
You are the editorial AI for "AI Daily Brief", a newspaper for final-year B.Tech \
Computer Science students specialising in AI/ML who want to become AI/ML engineers.

For each article provided, generate a structured summary following these rules:

1. headline: A clear, factual headline (max 120 chars). Do not embellish or sensationalise.
2. summary: 2–4 sentences. Factual. Report what happened, not what might happen.
   Distinguish facts reported by the source from your analysis.
3. why_it_matters: 1–2 sentences. Explain the engineering/career significance.
4. technical_takeaway: (optional) A concrete experiment, tool to try, or concept to study.
   Omit if the story has no actionable technical angle.
5. category: ONE of: llm_releases, agents, rag, research, open_source, mlops, industry, safety, general_ai
6. confidence: "high" if the source is primary and the claim is well-supported;
   "medium" if corroborated but indirect; "low" if unverified or speculative.

Critical rules:
- Never invent facts, benchmarks, quotations, or publication dates.
- Never produce summaries for articles whose descriptions are empty; mark confidence "low".
- If evidence is insufficient, say so explicitly in the summary.
- Return ONLY valid JSON — no markdown fences, no commentary outside JSON.
"""

_SUMMARISE_USER_TEMPLATE = """\
Summarise the following {n} articles. Return a JSON object matching this schema exactly:
{{
  "stories": [
    {{
      "rank": <integer starting from 1>,
      "headline": "<string>",
      "original_url": "<string — MUST match the url field exactly>",
      "source_name": "<string>",
      "published_at": "<ISO-8601 string or null>",
      "summary": "<string>",
      "why_it_matters": "<string>",
      "technical_takeaway": "<string or null>",
      "category": "<category enum value>",
      "confidence": "<high|medium|low>"
    }}
  ],
  "learn_today": "<one actionable sentence: what to read, build, or practise today>"
}}

ARTICLES:
{articles_json}
"""


def _build_articles_payload(articles: Sequence[RawArticle]) -> str:
    items = []
    for i, art in enumerate(articles):
        items.append({
            "rank": i + 1,
            "title": art.title,
            "url": art.url,
            "source": art.source_name,
            "category": art.category,
            "desc": art.description[:250] if art.description else "",
        })
    return json.dumps(items, separators=(",", ":"), ensure_ascii=False)


# ─── JSON Extraction ──────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict:
    if "```" in text:
        lines = text.split("\n")
        text = "\n".join(l for l in lines if not l.strip().startswith("```"))
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError("No JSON object found in summariser response")
    return json.loads(text[start:end])


# ─── Retry Wrapper ────────────────────────────────────────────────────────────

def _call_with_retry(client: Groq, model: str, system_prompt: str, user_prompt: str, max_retries: int = 3) -> str:
    for attempt in range(1, max_retries + 1):
        try:
            chat_completion = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                max_tokens=3072,
            )
            return (chat_completion.choices[0].message.content or "").strip()
        except Exception as exc:
            wait = 2 ** attempt
            logger.warning("Summariser call failed (attempt %d/%d): %s. Retry in %ds…",
                           attempt, max_retries, exc, wait)
            if attempt == max_retries:
                raise
            time.sleep(wait)
    raise RuntimeError("Unreachable")  # pragma: no cover


# ─── Fallback Story Builder ───────────────────────────────────────────────────

def _make_fallback_story(article: RawArticle, rank: int) -> RankedStory:
    """
    Build a minimal RankedStory from the raw article when the LLM fails.
    Marks confidence 'low' so the renderer can optionally flag it.
    """
    return RankedStory(
        rank=rank,
        headline=article.title[:120],
        original_url=article.url,
        source_name=article.source_name,
        published_at=article.published_at.isoformat() if article.published_at else None,
        summary=article.description[:400] if article.description else "No description available.",
        why_it_matters="See original article for context.",
        technical_takeaway=None,
        category=StoryCategory(article.category) if article.category in StoryCategory._value2member_map_ else StoryCategory.GENERAL_AI,
        confidence=ConfidenceLevel.LOW,
    )


# ─── Public API ───────────────────────────────────────────────────────────────

def summarise_stories(
    articles: Sequence[RawArticle],
    edition_date: str | None = None,
) -> BriefEdition:
    """
    Generate full structured summaries for the given ranked articles via Groq.

    Returns a validated BriefEdition. If the LLM call or validation fails,
    falls back to raw descriptions with confidence='low'.
    """
    if not articles:
        raise ValueError("No articles provided to summariser")

    if edition_date is None:
        now_ist = datetime.now(timezone.utc)
        edition_date = now_ist.strftime("%d %B %Y").lstrip("0")  # e.g. "17 October 2026"

    client, model = _get_client_and_model()
    articles_json = _build_articles_payload(articles)
    user_prompt = _SUMMARISE_USER_TEMPLATE.format(
        n=len(articles),
        articles_json=articles_json,
    )

    logger.info("Summarising %d articles via Groq (%s)…", len(articles), model)
    raw_stories: list[RankedStory] = []
    learn_today: str | None = None

    try:
        raw_text = _call_with_retry(
            client=client,
            model=model,
            system_prompt=_SUMMARISE_SYSTEM,
            user_prompt=user_prompt,
        )
        raw_dict = _extract_json(raw_text)
        learn_today = raw_dict.get("learn_today")

        stories_data = raw_dict.get("stories", [])
        if not stories_data:
            raise ValueError("LLM returned empty 'stories' list")

        for story_data in stories_data:
            try:
                story = RankedStory.model_validate(story_data)
                # Safety check: ensure URL matches a real article
                matching = next(
                    (a for a in articles if a.url == story.original_url), None
                )
                if matching is None:
                    logger.warning("LLM invented URL %s — skipping story", story.original_url)
                    continue
                raw_stories.append(story)
            except ValidationError as ve:
                logger.warning("Story validation failed: %s", ve)

    except Exception as exc:
        logger.error("Summariser failed: %s. Falling back to raw descriptions.", exc)

    # Fallback: for any article not yet summarised, use raw description
    summarised_urls = {s.original_url for s in raw_stories}
    for rank, article in enumerate(articles, start=1):
        if article.url not in summarised_urls:
            raw_stories.append(_make_fallback_story(article, rank))

    # Re-rank to ensure consistent ordering
    raw_stories.sort(key=lambda s: s.rank)

    edition = BriefEdition(
        edition_date=edition_date,
        stories=raw_stories,
        learn_today=learn_today,
    )
    logger.info("Summariser complete: %d stories in edition '%s'", len(edition.stories), edition_date)
    return edition
