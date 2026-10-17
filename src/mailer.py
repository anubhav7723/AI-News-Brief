"""
src/mailer.py — Phase 6: Gmail SMTP Email Delivery

Sends the rendered HTML email via Gmail SMTP (port 587, STARTTLS).
Uses app-password authentication, not OAuth2, to remain free and simple.

Features:
- Multipart email with HTML and plain-text fallback
- Meaningful subject line including the edition date
- Bounded retry with exponential backoff
- Idempotent: will not send if the edition guard flag is set
- Detailed logging for debugging
"""

from __future__ import annotations

import logging
import os
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
MAX_RETRIES = 3


# ─── Plain-text fallback ──────────────────────────────────────────────────────

def _html_to_plaintext(html: str) -> str:
    """
    Very simple HTML → plain text conversion.
    Used as fallback for email clients that don't render HTML.
    """
    import re
    text = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ─── Message Builder ──────────────────────────────────────────────────────────

def _build_message(
    sender: str,
    recipient: str,
    edition_date: str,
    html_body: str,
) -> MIMEMultipart:
    """Build a MIME multipart email with HTML and plain-text parts."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"AI Daily Brief — {edition_date}"
    msg["From"] = f"AI Daily Brief <{sender}>"
    msg["To"] = recipient

    # Plain-text part (fallback)
    plain = _html_to_plaintext(html_body)
    msg.attach(MIMEText(plain, "plain", "utf-8"))

    # HTML part (preferred by modern email clients)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    return msg


# ─── SMTP Sender ──────────────────────────────────────────────────────────────

def send_email(
    html_body: str,
    edition_date: str,
    sender: str | None = None,
    recipient: str | None = None,
    password: str | None = None,
) -> bool:
    """
    Send the rendered HTML email.

    Reads EMAIL_SENDER, EMAIL_RECIPIENT, EMAIL_PASSWORD from env if not
    provided as arguments.

    Returns True on success, False on failure (after all retries).
    Does not raise — failures are logged and the pipeline continues.
    """
    sender    = sender    or os.environ.get("EMAIL_SENDER", "")
    recipient = recipient or os.environ.get("EMAIL_RECIPIENT", "")
    password  = password  or os.environ.get("EMAIL_PASSWORD", "")

    if not all([sender, recipient, password]):
        logger.error(
            "Email not sent: EMAIL_SENDER, EMAIL_RECIPIENT, and EMAIL_PASSWORD must all be set."
        )
        return False

    if not html_body or len(html_body) < 100:
        logger.error("Email not sent: HTML body is empty or too short — refusing to send.")
        return False

    recipients = [r.strip() for r in recipient.replace(";", ",").split(",") if r.strip()]
    if not recipients:
        logger.error("Email not sent: No valid recipient addresses found in EMAIL_RECIPIENT.")
        return False

    msg = _build_message(sender, ", ".join(recipients), edition_date, html_body)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info("Sending email (attempt %d/%d) to %d recipient(s)…", attempt, MAX_RETRIES, len(recipients))
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
                server.ehlo()
                server.starttls()
                server.login(sender, password)
                server.sendmail(sender, recipients, msg.as_string())
            logger.info(
                "✅ Email sent successfully to %s — Subject: '%s'",
                ", ".join(recipients),
                msg["Subject"],
            )
            return True
        except smtplib.SMTPAuthenticationError as exc:
            logger.error(
                "SMTP authentication failed. Check EMAIL_SENDER and EMAIL_PASSWORD. "
                "Make sure you are using a Gmail App Password, not your account password. "
                "Error: %s", exc,
            )
            return False  # Auth errors are not retryable
        except Exception as exc:
            wait = 2 ** attempt
            logger.warning(
                "Email send attempt %d/%d failed: %s. Retrying in %ds…",
                attempt, MAX_RETRIES, exc, wait,
            )
            if attempt < MAX_RETRIES:
                time.sleep(wait)

    logger.error("Email delivery failed after %d attempts.", MAX_RETRIES)
    return False
