"""
src/pipeline.py — Phase 8: Pipeline Orchestrator

Wires together all phases in order:
  1. Collect   — fetch RSS articles
  2. Load history — get previously sent story records
  3. Clean     — deduplicate and normalise
  4. Rank      — LLM selects the top N stories
  5. Summarise — LLM generates full structured summaries
  6. Render    — Jinja2 → HTML email
  7. Send      — Gmail SMTP delivery
  8. Save history — persist newly sent stories

Each phase is isolated; exceptions abort the current phase and are logged
with enough context to debug without leaking secrets.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone

from src import collector, cleaner, ranker, summarizer, renderer, mailer, history

logger = logging.getLogger(__name__)


def _setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )


def run(*, dry_run: bool = False, force: bool = False, log_level: str = "INFO") -> bool:
    """
    Execute the full AI Daily Brief pipeline.

    Parameters
    ----------
    dry_run  : If True, render the email and save preview but do NOT send it.
    force    : If True, bypass the 'already sent today' duplicate check.
    log_level: Logging verbosity (DEBUG / INFO / WARNING / ERROR).

    Returns
    -------
    True if the pipeline completed successfully, False on failure.
    """
    _setup_logging(log_level)
    logger.info("=" * 60)
    logger.info("AI Daily Brief pipeline starting")
    logger.info("=" * 60)

    # ── Determine edition date ────────────────────────────────────────────────
    now_utc = datetime.now(timezone.utc)
    # Show date in IST (UTC+5:30) for the newspaper header
    from datetime import timedelta
    ist_offset = timedelta(hours=5, minutes=30)
    now_ist = now_utc + ist_offset
    # strftime %d gives zero-padded day; lstrip("0") gives "1" not "01"
    edition_date = now_ist.strftime("%d %B %Y").lstrip("0")

    # ── Phase 1: Load history ─────────────────────────────────────────────────
    logger.info("Phase 1/8 — Loading history…")
    try:
        history_records = history.load_history()
    except Exception as exc:
        logger.error("History load failed: %s", exc)
        history_records = []

    # Guard against duplicate sends for the same edition
    if history.edition_already_sent(history_records, edition_date):
        if not dry_run and not force:
            logger.warning(
                "Edition '%s' was already sent today. Aborting to prevent duplicate. (Use --force to override)",
                edition_date,
            )
            return True  # Not an error — expected idempotent behaviour
        else:
            logger.info("Edition '%s' already recorded, but continuing due to dry-run or force mode.", edition_date)

    sent_urls = history.get_sent_urls(history_records)
    sent_titles = history.get_sent_titles(history_records)

    # ── Phase 2: Collect ──────────────────────────────────────────────────────
    logger.info("Phase 2/8 — Collecting articles…")
    try:
        raw_articles = collector.collect_articles()
    except Exception as exc:
        logger.error("Collector failed: %s", exc)
        return False

    if not raw_articles:
        logger.error("No articles collected — aborting pipeline.")
        return False

    # ── Phase 3: Clean ────────────────────────────────────────────────────────
    logger.info("Phase 3/8 — Cleaning and deduplicating…")
    try:
        cleaned = cleaner.clean_and_deduplicate(
            articles=raw_articles,
            sent_urls=sent_urls,
            sent_titles=sent_titles,
        )
    except Exception as exc:
        logger.error("Cleaner failed: %s", exc)
        return False

    if not cleaned:
        logger.warning("No articles survived deduplication. Nothing new to report today.")
        # Do NOT send an email; mark the edition as sent to prevent retry spam
        updated_records = history.add_sent_stories(history_records, [], edition_date)
        history.save_history(updated_records)
        return True

    # ── Phase 4: Rank ─────────────────────────────────────────────────────────
    logger.info("Phase 4/8 — Ranking articles with LLM…")
    try:
        ranked = ranker.rank_articles(cleaned)
    except Exception as exc:
        logger.error("Ranker failed: %s", exc)
        return False

    if not ranked:
        logger.error("Ranker returned no articles.")
        return False

    # ── Phase 5: Summarise ────────────────────────────────────────────────────
    logger.info("Phase 5/8 — Summarising stories with LLM…")
    try:
        edition = summarizer.summarise_stories(ranked, edition_date=edition_date)
    except Exception as exc:
        logger.error("Summariser failed: %s", exc)
        return False

    # ── Phase 6: Render ───────────────────────────────────────────────────────
    logger.info("Phase 6/8 — Rendering HTML email…")
    try:
        html = renderer.render_email(edition)
    except Exception as exc:
        logger.error("Renderer failed: %s", exc)
        return False

    if dry_run:
        logger.info("Dry-run mode: skipping email send.")
        # Optionally write HTML to a file for inspection
        out_path = f"data/preview_{now_ist.strftime('%Y-%m-%d')}.html"
        try:
            with open(out_path, "w", encoding="utf-8") as fh:
                fh.write(html)
            logger.info("Dry-run HTML saved to: %s", out_path)
        except OSError as exc:
            logger.warning("Could not save dry-run HTML: %s", exc)
        return True

    # ── Phase 7: Send ─────────────────────────────────────────────────────────
    logger.info("Phase 7/8 — Sending email…")
    success = mailer.send_email(html_body=html, edition_date=edition_date)

    if not success:
        logger.error("Email delivery failed — history NOT updated to allow retry.")
        return False

    # ── Phase 8: Save history ─────────────────────────────────────────────────
    logger.info("Phase 8/8 — Saving history…")
    try:
        updated_records = history.add_sent_stories(history_records, edition.stories, edition_date)
        history.save_history(updated_records)
    except Exception as exc:
        logger.error("History save failed (non-fatal): %s", exc)

    logger.info("=" * 60)
    logger.info("Pipeline complete — edition '%s' delivered.", edition_date)
    logger.info("=" * 60)
    return True
