"""
src/renderer.py — Phase 5: Jinja2 HTML Email Renderer

Takes a validated BriefEdition and renders it to a responsive HTML email
using the Jinja2 template in templates/email.html.j2.

Design:
- The template is the single source of visual truth.
- The renderer only passes data; it never applies business logic.
- Output is a complete HTML string ready for the mailer.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.validator import BriefEdition, StoryCategory

logger = logging.getLogger(__name__)

# ─── Category Labels ──────────────────────────────────────────────────────────

CATEGORY_LABELS: dict[str, str] = {
    StoryCategory.LLM_RELEASES.value: "🧠 LLM & Foundation Models",
    StoryCategory.AGENTS.value:       "🤖 Agents & Automation",
    StoryCategory.RAG.value:          "🔍 RAG, Embeddings & Vector DBs",
    StoryCategory.RESEARCH.value:     "📄 Research & Papers",
    StoryCategory.OPEN_SOURCE.value:  "🛠️ Open-Source & Developer Tools",
    StoryCategory.MLOPS.value:        "⚙️ MLOps & Infrastructure",
    StoryCategory.INDUSTRY.value:     "🏢 Industry & Funding",
    StoryCategory.SAFETY.value:       "🛡️ AI Safety & Policy",
    StoryCategory.GENERAL_AI.value:   "🌐 General AI",
}

# Section ordering for the email (categories are rendered in this order)
SECTION_ORDER = [
    StoryCategory.LLM_RELEASES.value,
    StoryCategory.AGENTS.value,
    StoryCategory.RESEARCH.value,
    StoryCategory.OPEN_SOURCE.value,
    StoryCategory.RAG.value,
    StoryCategory.MLOPS.value,
    StoryCategory.INDUSTRY.value,
    StoryCategory.SAFETY.value,
    StoryCategory.GENERAL_AI.value,
]


# ─── Renderer ─────────────────────────────────────────────────────────────────

def render_email(edition: BriefEdition, template_dir: str | None = None) -> str:
    """
    Render *edition* to an HTML string using the Jinja2 email template.

    Parameters
    ----------
    edition      : Validated BriefEdition from the summariser.
    template_dir : Path to the templates directory (default: 'templates/').

    Returns
    -------
    A complete HTML document string.
    """
    tmpl_dir = template_dir or os.environ.get("TEMPLATE_DIR", "templates")
    env = Environment(
        loader=FileSystemLoader(tmpl_dir),
        autoescape=select_autoescape(["html", "j2"]),
    )

    template = env.get_template("email.html.j2")

    # Build ordered sections — only include categories that have stories
    by_category = edition.stories_by_category()
    sections = []
    for cat_value in SECTION_ORDER:
        if cat_value in by_category:
            sections.append({
                "label": CATEGORY_LABELS.get(cat_value, cat_value),
                "stories": by_category[cat_value],
            })
    # Any categories not in SECTION_ORDER (shouldn't happen, but be safe)
    for cat_value, stories in by_category.items():
        if cat_value not in SECTION_ORDER:
            sections.append({
                "label": CATEGORY_LABELS.get(cat_value, cat_value),
                "stories": stories,
            })

    # Top stories = top 3 by rank
    top_stories = sorted(edition.stories, key=lambda s: s.rank)[:3]

    context = {
        "edition_date": edition.edition_date,
        "generated_at": datetime.now(timezone.utc).strftime("%H:%M UTC"),
        "total_stories": len(edition.stories),
        "top_stories": top_stories,
        "sections": sections,
        "learn_today": edition.learn_today,
        "confidence_colors": {
            "high": "#22c55e",
            "medium": "#f59e0b",
            "low": "#ef4444",
        },
    }

    html = template.render(**context)
    logger.info("Rendered HTML email (%d bytes) for edition '%s'", len(html), edition.edition_date)
    return html
