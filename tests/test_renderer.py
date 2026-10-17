"""
tests/test_renderer.py — Unit tests for the Jinja2 HTML renderer.
"""

import pytest

from src.validator import BriefEdition, RankedStory, StoryCategory, ConfidenceLevel
from src.renderer import render_email, CATEGORY_LABELS


# ─── Fixtures ─────────────────────────────────────────────────────────────────

def _make_story(
    rank: int = 1,
    category: str = "llm_releases",
    url: str = "https://openai.com/blog/gpt-5",
    headline: str = "OpenAI releases GPT-5 with enhanced reasoning capabilities",
    with_takeaway: bool = True,
) -> RankedStory:
    return RankedStory(
        rank=rank,
        headline=headline,
        original_url=url,
        source_name="OpenAI Blog",
        published_at="2026-10-17T06:00:00+00:00",
        summary="OpenAI today announced GPT-5 with a 128k context window and improved reasoning benchmarks.",
        why_it_matters="Sets a new baseline for LLM capabilities that affects API users and researchers alike.",
        technical_takeaway="Test the structured output JSON mode against GPT-4o on your current tasks." if with_takeaway else None,
        category=StoryCategory(category),
        confidence=ConfidenceLevel.HIGH,
    )


def _make_edition(n_stories: int = 3, with_learn_today: bool = True) -> BriefEdition:
    categories = ["llm_releases", "research", "open_source", "agents", "mlops"]
    stories = [
        _make_story(
            rank=i + 1,
            category=categories[i % len(categories)],
            url=f"https://example.com/article-{i}",
            headline=f"AI development story number {i + 1} about important developments",
        )
        for i in range(n_stories)
    ]
    return BriefEdition(
        edition_date="17 October 2026",
        stories=stories,
        learn_today="Build a small RAG pipeline using LangChain and ChromaDB today." if with_learn_today else None,
    )


# ─── Render Tests ─────────────────────────────────────────────────────────────

class TestRenderEmail:
    def test_produces_html(self):
        edition = _make_edition()
        html = render_email(edition, template_dir="templates")
        assert isinstance(html, str)
        assert len(html) > 1000
        assert "<html" in html.lower()

    def test_contains_edition_date(self):
        edition = _make_edition()
        html = render_email(edition, template_dir="templates")
        assert "17 October 2026" in html

    def test_contains_story_headlines(self):
        edition = _make_edition()
        html = render_email(edition, template_dir="templates")
        for story in edition.stories:
            assert story.headline in html

    def test_contains_story_links(self):
        edition = _make_edition()
        html = render_email(edition, template_dir="templates")
        for story in edition.stories:
            assert story.original_url in html

    def test_contains_source_attribution(self):
        edition = _make_edition()
        html = render_email(edition, template_dir="templates")
        assert "OpenAI Blog" in html

    def test_learn_today_present(self):
        edition = _make_edition(with_learn_today=True)
        html = render_email(edition, template_dir="templates")
        assert "RAG pipeline" in html

    def test_no_learn_today_when_absent(self):
        edition = _make_edition(with_learn_today=False)
        html = render_email(edition, template_dir="templates")
        # The learn-box section should be absent
        assert "What to learn or try today" not in html

    def test_top_stories_section_present(self):
        edition = _make_edition(n_stories=5)
        html = render_email(edition, template_dir="templates")
        assert "Today&#39;s Top Stories" in html or "Today's Top Stories" in html

    def test_confidence_dot_present(self):
        edition = _make_edition()
        html = render_email(edition, template_dir="templates")
        assert "confidence-dot" in html

    def test_takeaway_renders_when_present(self):
        story = _make_story(with_takeaway=True)
        edition = BriefEdition(
            edition_date="17 October 2026",
            stories=[story],
        )
        html = render_email(edition, template_dir="templates")
        assert "takeaway" in html.lower()

    def test_missing_template_dir_raises(self):
        edition = _make_edition()
        with pytest.raises(Exception):
            render_email(edition, template_dir="nonexistent_templates")

    def test_no_xss_from_headline(self):
        """Ensure Jinja2 autoescape prevents XSS via story fields."""
        story = _make_story(
            headline='<script>alert("xss")</script> AI story about model releases here now',
        )
        edition = BriefEdition(
            edition_date="17 October 2026",
            stories=[story],
        )
        html = render_email(edition, template_dir="templates")
        assert "<script>alert" not in html
        assert "&lt;script&gt;" in html
