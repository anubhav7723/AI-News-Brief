"""
main.py — Entry point for AI Daily Brief

Usage:
  python main.py              # Run full pipeline (production)
  python main.py --dry-run    # Run but don't send email (save HTML preview)
  python main.py --debug      # Run with DEBUG logging
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def _load_env() -> None:
    """
    Load .env file if present.  In GitHub Actions, secrets are injected as
    environment variables directly, so no .env file is needed there.
    """
    env_path = Path(".env")
    if env_path.exists():
        load_dotenv(env_path)
        print(f"Loaded environment from {env_path.resolve()}")
    else:
        print("No .env file found — using environment variables.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="AI Daily Brief — automated AI news newspaper pipeline"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Render the email but do not send it. Saves HTML to data/preview_<date>.html",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Bypass 'already sent today' check and force re-generation",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Enable DEBUG-level logging",
    )
    args = parser.parse_args()

    _load_env()

    # Import pipeline here so env is loaded before module-level code runs
    from src.pipeline import run

    log_level = "DEBUG" if args.debug else os.environ.get("LOG_LEVEL", "INFO")
    success = run(dry_run=args.dry_run, force=args.force, log_level=log_level)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
