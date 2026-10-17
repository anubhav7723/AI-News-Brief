"""
src/ranker.py — Phase 4a: LLM Story Ranking

Sends the cleaned candidate article list to Gemini and asks it to:
  1. Score each article by novelty, technical impact, credibility, and
     practical usefulness for an AI/ML engineering audience.
  2. Return a ranked list of the top N candidates to summarise.

This is intentionally a separate LLM call from summarisation so that:
  - The ranking context window is smaller and faster.
  - Ranking failures don't discard already-generated summaries.
  - Each phase can be retried or replaced independently.

The LLM is prompted to return strict JSON; the response is validated
with Pydantic before being used.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Sequence

from groq import Groq
from pydantic import ValidationError

from src.collector import RawArticle
from src.validator import RankerOutput, RankerCandidateItem

logger = logging.getLogger(__name__)

# ─── Groq Client Setup ────────────────────────────────────────────────────────

def _get_client_and_model() -> tuple[Groq, str]:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise EnvironmentError("GROQ_API_KEY environment variable is not set.")
    # Default to OpenAI's GPT-OSS model on Groq
    model_name = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")
    client = Groq(api_key=api_key)
    return client, model_name


# ─── Prompt Builder ───────────────────────────────────────────────────────────

_RANKING_SYSTEM = """\
You are an editorial AI assistant for "AI Daily Brief", a daily newspaper targeting \
final-year B.Tech Computer Science students specialising in AI/ML who want to become \
AI/ML engineers.

Your job is to SELECT the most valuable stories from a list of candidates.

Scoring criteria (equal weight):
1. Novelty — Is this genuinely new? Not just a minor update or rehash.
2. Technical impact — Does it affect how AI/ML engineers build, deploy, or research?
3. Credibility — Is the source reputable? Is the claim verifiable?
4. Practical usefulness — Can a student learn from this, build with it, or use it in interviews?

Rules:
- Prefer: model releases, research breakthroughs, new open-source tools, benchmarks, \
  infrastructure changes, agentic AI, RAG/embeddings, MLOps.
- Avoid: pure opinion pieces, duplicate coverage of the same event, celebrity AI hype, \
  cryptocurrency/blockchain content, vague funding news with no technical substance.
- If multiple articles cover the same event, select only the best one (prefer primary source).
- You MUST return ONLY valid JSON — no markdown fences, no prose, no explanation outside JSON.
"""

_RANKING_USER_TEMPLATE = """\
Select the {n_select} most valuable stories from the candidates below.

Return JSON:
{{
  "selected": [
    {{
      "candidate_index": <int 0-based idx>,
      "relevance_score": <float 0.0-10.0>,
      "reason": "<short 1-line reason>"
    }}
  ]
}}

CANDIDATES:
{candidates_json}
"""


def _build_candidates_payload(articles: Sequence[RawArticle]) -> str:
    """Serialise articles into a compact JSON array for the prompt to conserve tokens."""
    items = []
    for i, art in enumerate(articles):
        items.append({
            "idx": i,
            "title": art.title,
            "source": art.source_name,
            "category": art.category,
            "desc": art.description[:180] if art.description else "",
        })
    return json.dumps(items, separators=(",", ":"), ensure_ascii=False)


# ─── LLM Call with Retry ──────────────────────────────────────────────────────

def _call_with_retry(client: Groq, model: str, system_prompt: str, user_prompt: str, max_retries: int = 3) -> str:
    """
    Call Groq (OpenAI-compatible) with exponential backoff retry on transient errors.
    Uses response_format={"type": "json_object"} for strict JSON generation.
    """
    for attempt in range(1, max_retries + 1):
        try:
            chat_completion = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_tokens=1024,
            )
            text = (chat_completion.choices[0].message.content or "").strip()
            logger.debug("Groq response (attempt %d, %d chars)", attempt, len(text))
            return text
        except Exception as exc:
            wait = 2 ** attempt
            logger.warning("Groq call failed (attempt %d/%d): %s. Retrying in %ds…",
                           attempt, max_retries, exc, wait)
            if attempt == max_retries:
                raise
            time.sleep(wait)
    raise RuntimeError("Unreachable")  # pragma: no cover


# ─── JSON Extraction ──────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict:
    """
    Extract the JSON object from the model's response.
    Handles markdown fences if returned despite json mode.
    """
    if "```" in text:
        lines = text.split("\n")
        clean_lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(clean_lines)
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError("No JSON object found in LLM response")
    return json.loads(text[start:end])


# ─── Public API ───────────────────────────────────────────────────────────────

def rank_articles(
    articles: Sequence[RawArticle],
    n_select: int | None = None,
) -> list[RawArticle]:
    """
    Use Groq (e.g. openai/gpt-oss-20b or openai/gpt-oss-120b) to rank articles.
    Falls back to the top-n by heuristic score if the LLM call fails.
    """
    if not articles:
        return []

    max_stories = int(os.environ.get("MAX_STORIES", "12"))
    n_select = n_select or max_stories

    # Cap at what we actually have
    n_select = min(n_select, len(articles))

    # Send only the top 25 candidates (pre-sorted by heuristic score) to conserve tokens
    candidates = list(articles[:25])

    logger.info("Ranking %d candidates → selecting %d via Groq", len(candidates), n_select)

    client, model = _get_client_and_model()
    candidates_json = _build_candidates_payload(candidates)
    user_prompt = _RANKING_USER_TEMPLATE.format(
        n_select=n_select,
        candidates_json=candidates_json,
    )

    try:
        raw_text = _call_with_retry(
            client=client,
            model=model,
            system_prompt=_RANKING_SYSTEM,
            user_prompt=user_prompt,
        )
        raw_dict = _extract_json(raw_text)
        ranked: RankerOutput = RankerOutput.model_validate(raw_dict)
    except (ValidationError, ValueError, json.JSONDecodeError) as exc:
        logger.error("Ranker output validation failed: %s. Using heuristic fallback.", exc)
        return list(candidates[:n_select])
    except Exception as exc:
        logger.error("Ranker LLM call failed: %s. Using heuristic fallback.", exc)
        return list(candidates[:n_select])

    # Map selected indices back to articles, sorted by score descending
    selected_items = sorted(ranked.selected, key=lambda x: x.relevance_score, reverse=True)
    result: list[RawArticle] = []
    for item in selected_items:
        if 0 <= item.candidate_index < len(candidates):
            art = candidates[item.candidate_index]
            logger.debug("Selected [%.1f] %s — %s", item.relevance_score, art.source_name, art.title)
            result.append(art)
        else:
            logger.warning("Ranker returned out-of-range index %d", item.candidate_index)

    logger.info("Ranker selected %d stories", len(result))
    return result
