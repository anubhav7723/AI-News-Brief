"""
src/validator.py — Pydantic schemas for LLM output validation.

All LLM responses are treated as untrusted data.  Before any LLM output
reaches the renderer or history store it must pass through these validators.

Schemas:
  - StoryCategory       : Enum of allowed story categories.
  - ConfidenceLevel     : Enum of allowed confidence labels.
  - RankedStory         : One fully processed story ready for rendering.
  - BriefEdition        : The complete collection of stories for one edition.
  - RankerOutput        : Raw ranking-phase LLM response.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional
from urllib.parse import urlparse

from pydantic import BaseModel, field_validator, model_validator, Field


# ─── Enums ────────────────────────────────────────────────────────────────────

class StoryCategory(str, Enum):
    LLM_RELEASES = "llm_releases"
    AGENTS       = "agents"
    RAG          = "rag"
    RESEARCH     = "research"
    OPEN_SOURCE  = "open_source"
    MLOPS        = "mlops"
    INDUSTRY     = "industry"
    SAFETY       = "safety"
    GENERAL_AI   = "general_ai"


class ConfidenceLevel(str, Enum):
    HIGH   = "high"
    MEDIUM = "medium"
    LOW    = "low"


# ─── Story Schema ─────────────────────────────────────────────────────────────

class RankedStory(BaseModel):
    """
    One selected, summarised, and validated story for inclusion in the brief.
    All string fields are stripped of leading/trailing whitespace.
    """
    rank: int = Field(..., ge=1, le=20, description="Position in the edition (1 = top story)")
    headline: str = Field(..., min_length=10, max_length=200)
    original_url: str = Field(..., description="Original article URL, preserved unchanged")
    source_name: str = Field(..., min_length=1, max_length=100)
    published_at: Optional[str] = Field(None, description="ISO-8601 date string or None")
    summary: str = Field(..., min_length=40, max_length=800)
    why_it_matters: str = Field(..., min_length=20, max_length=400)
    technical_takeaway: Optional[str] = Field(None, max_length=400)
    category: StoryCategory
    confidence: ConfidenceLevel

    @field_validator("headline", "summary", "why_it_matters", "technical_takeaway", mode="before")
    @classmethod
    def strip_strings(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("original_url", mode="before")
    @classmethod
    def validate_url(cls, v):
        if not isinstance(v, str):
            raise ValueError("URL must be a string")
        v = v.strip()
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(f"Invalid URL: {v!r}")
        return v

    @field_validator("rank", mode="before")
    @classmethod
    def coerce_rank(cls, v):
        try:
            return int(v)
        except (TypeError, ValueError):
            raise ValueError(f"rank must be an integer, got {v!r}")

    @model_validator(mode="after")
    def summary_not_identical_to_headline(self) -> "RankedStory":
        if self.summary.strip().lower() == self.headline.strip().lower():
            raise ValueError("summary must not be identical to headline")
        return self


# ─── Edition Schema ───────────────────────────────────────────────────────────

class BriefEdition(BaseModel):
    """
    The complete validated output for one edition of AI Daily Brief.
    Stories are guaranteed to be sorted by rank ascending.
    """
    edition_date: str = Field(..., description="Date string, e.g. '17 October 2026'")
    stories: list[RankedStory] = Field(..., min_length=1)
    learn_today: Optional[str] = Field(None, max_length=600,
        description="A short 'What to learn or try today' suggestion")

    @model_validator(mode="after")
    def sort_stories_by_rank(self) -> "BriefEdition":
        self.stories = sorted(self.stories, key=lambda s: s.rank)
        return self

    def stories_by_category(self) -> dict[str, list[RankedStory]]:
        """Return stories grouped by category, preserving rank order."""
        groups: dict[str, list[RankedStory]] = {}
        for story in self.stories:
            groups.setdefault(story.category.value, []).append(story)
        return groups


# ─── Ranker Output Schema (partial — before summarisation) ────────────────────

class RankerCandidateItem(BaseModel):
    """
    One item in the LLM's ranking response (before full summarisation).
    Contains only the index into the candidate list plus a priority score.
    """
    candidate_index: int = Field(..., ge=0)
    relevance_score: float = Field(..., ge=0.0, le=10.0)
    reason: str = Field(..., min_length=5, max_length=200)

    @field_validator("relevance_score", mode="before")
    @classmethod
    def coerce_score(cls, v):
        try:
            return float(v)
        except (TypeError, ValueError):
            raise ValueError(f"relevance_score must be numeric, got {v!r}")


class RankerOutput(BaseModel):
    """Full response from the ranking prompt."""
    selected: list[RankerCandidateItem] = Field(..., min_length=1)
