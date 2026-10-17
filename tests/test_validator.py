"""
tests/test_validator.py — Unit tests for Pydantic output validation schemas.
"""

import pytest
from pydantic import ValidationError

from src.validator import (
    RankedStory,
    BriefEdition,
    RankerOutput,
    RankerCandidateItem,
    StoryCategory,
    ConfidenceLevel,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _valid_story_data(**overrides) -> dict:
    base = {
        "rank": 1,
        "headline": "OpenAI releases GPT-5 with enhanced reasoning capabilities",
        "original_url": "https://openai.com/blog/gpt-5",
        "source_name": "OpenAI Blog",
        "published_at": "2026-10-17T06:00:00+00:00",
        "summary": "OpenAI today announced GPT-5, a major upgrade featuring 128k context "
                   "and state-of-the-art performance on MMLU and HumanEval benchmarks.",
        "why_it_matters": "GPT-5 sets a new baseline that downstream tool-builders must adapt to.",
        "technical_takeaway": "Try the new JSON mode and compare structured output quality to GPT-4o.",
        "category": "llm_releases",
        "confidence": "high",
    }
    base.update(overrides)
    return base


# ─── RankedStory ──────────────────────────────────────────────────────────────

class TestRankedStory:
    def test_valid_story(self):
        story = RankedStory.model_validate(_valid_story_data())
        assert story.rank == 1
        assert story.category == StoryCategory.LLM_RELEASES
        assert story.confidence == ConfidenceLevel.HIGH

    def test_invalid_url_raises(self):
        data = _valid_story_data(original_url="not-a-url")
        with pytest.raises(ValidationError):
            RankedStory.model_validate(data)

    def test_ftp_url_rejected(self):
        data = _valid_story_data(original_url="ftp://example.com/file")
        with pytest.raises(ValidationError):
            RankedStory.model_validate(data)

    def test_headline_too_short_raises(self):
        data = _valid_story_data(headline="Short")
        with pytest.raises(ValidationError):
            RankedStory.model_validate(data)

    def test_summary_identical_to_headline_raises(self):
        headline = "OpenAI releases GPT-5 with enhanced reasoning capabilities"
        data = _valid_story_data(headline=headline, summary=headline)
        with pytest.raises(ValidationError):
            RankedStory.model_validate(data)

    def test_invalid_category_raises(self):
        data = _valid_story_data(category="made_up_category")
        with pytest.raises(ValidationError):
            RankedStory.model_validate(data)

    def test_invalid_confidence_raises(self):
        data = _valid_story_data(confidence="excellent")
        with pytest.raises(ValidationError):
            RankedStory.model_validate(data)

    def test_rank_coercion(self):
        # Rank passed as string should be coerced to int
        data = _valid_story_data(rank="3")
        story = RankedStory.model_validate(data)
        assert story.rank == 3

    def test_technical_takeaway_is_optional(self):
        data = _valid_story_data(technical_takeaway=None)
        story = RankedStory.model_validate(data)
        assert story.technical_takeaway is None

    def test_strips_whitespace(self):
        data = _valid_story_data(headline="  Headline with spaces  ")
        story = RankedStory.model_validate(data)
        assert story.headline == "Headline with spaces"


# ─── BriefEdition ─────────────────────────────────────────────────────────────

class TestBriefEdition:
    def _make_edition(self, n_stories: int = 3) -> dict:
        stories = []
        for i in range(n_stories):
            d = _valid_story_data(
                rank=i + 1,
                original_url=f"https://example.com/article-{i}",
                headline=f"Story number {i + 1} about artificial intelligence developments",
            )
            stories.append(d)
        return {
            "edition_date": "17 October 2026",
            "stories": stories,
            "learn_today": "Try building a RAG pipeline with LangChain and FAISS.",
        }

    def test_valid_edition(self):
        data = self._make_edition(3)
        edition = BriefEdition.model_validate(data)
        assert len(edition.stories) == 3
        assert edition.edition_date == "17 October 2026"

    def test_stories_sorted_by_rank(self):
        data = self._make_edition(3)
        # Reverse the order
        data["stories"].reverse()
        edition = BriefEdition.model_validate(data)
        ranks = [s.rank for s in edition.stories]
        assert ranks == sorted(ranks)

    def test_empty_stories_raises(self):
        data = self._make_edition(0)
        with pytest.raises(ValidationError):
            BriefEdition.model_validate(data)

    def test_stories_by_category(self):
        data = self._make_edition(2)
        # Give different categories
        data["stories"][0]["category"] = "llm_releases"
        data["stories"][1]["category"] = "research"
        edition = BriefEdition.model_validate(data)
        by_cat = edition.stories_by_category()
        assert "llm_releases" in by_cat
        assert "research" in by_cat


# ─── RankerOutput ─────────────────────────────────────────────────────────────

class TestRankerOutput:
    def test_valid_ranker_output(self):
        data = {
            "selected": [
                {"candidate_index": 0, "relevance_score": 9.2, "reason": "Major model release"},
                {"candidate_index": 3, "relevance_score": 7.8, "reason": "Important open-source tool"},
            ]
        }
        output = RankerOutput.model_validate(data)
        assert len(output.selected) == 2
        assert output.selected[0].candidate_index == 0

    def test_score_coercion(self):
        data = {
            "selected": [
                {"candidate_index": 0, "relevance_score": "8.5", "reason": "Good story"}
            ]
        }
        output = RankerOutput.model_validate(data)
        assert output.selected[0].relevance_score == 8.5

    def test_out_of_range_score_raises(self):
        data = {
            "selected": [
                {"candidate_index": 0, "relevance_score": 11.0, "reason": "Over the limit"}
            ]
        }
        with pytest.raises(ValidationError):
            RankerOutput.model_validate(data)

    def test_empty_selected_raises(self):
        data = {"selected": []}
        with pytest.raises(ValidationError):
            RankerOutput.model_validate(data)
