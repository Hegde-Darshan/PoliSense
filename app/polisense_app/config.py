"""
config.py
=========
Central configuration for the PoliSense Streamlit app.

Everything here is loaded from environment variables (via a local .env file
in development, or real environment variables / secrets manager in
production). Nothing sensitive is hardcoded.

Copy `.env.example` to `.env` and fill in your values before running.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

_THIS_DIR = Path(__file__).resolve().parent

# Load .env files from several candidate locations, in priority order:
#   1. A .env sitting right next to this file (self-contained default)
#   2. .env / .env.secrets one level up (in case this app lives inside a
#      larger project, e.g. alongside an existing IngestionPipeline that
#      already defines DB credentials there)
#   3. .env / .env.secrets two levels up (same reasoning, deeper nesting)
#   4. A plain .env in the current working directory (wherever the app is
#      launched from)
#
# `override=False` means the first value found for a given key wins, so a
# local .env next to this file always takes precedence over a shared one
# further up the tree.
_CANDIDATE_ENV_FILES = [
    _THIS_DIR / ".env",
    _THIS_DIR.parent / ".env",
    _THIS_DIR.parent / ".env.secrets",
    _THIS_DIR.parent.parent / ".env",
    _THIS_DIR.parent.parent / ".env.secrets",
]
for _candidate in _CANDIDATE_ENV_FILES:
    if _candidate.exists():
        load_dotenv(_candidate, override=False)
load_dotenv(override=False)  # fallback: cwd-relative .env, if any


def _get_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _env(*names: str, default: str | None = None) -> str | None:
    """
    Return the first non-empty env var found among `names`. Lets us support
    two naming conventions at once — this app's own PG_* names, and the
    POSTGRES_* names used by an existing ingestion pipeline — without
    requiring duplicate credentials in two different .env files.
    """
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return default


# ── Database ────────────────────────────────────────────────────────────────

DB_CONFIG = {
    "host": _env("PG_HOST", "POSTGRES_HOST", default="localhost"),
    "port": int(_env("PG_PORT", "POSTGRES_PORT", default="5432")),
    "dbname": _env("PG_DBNAME", "POSTGRES_DB", default="polisense_db_dev"),
    "user": _env("PG_USER", "POSTGRES_USER", default="postgres"),
    "password": _env("PG_PASSWORD", "POSTGRES_PASSWORD", default=""),
}

# Require SSL when connecting to a managed/cloud Postgres instance.
# Set PG_SSLMODE=require in production (RDS, Supabase, Neon, etc).
DB_SSLMODE = os.environ.get("PG_SSLMODE", "prefer")

DB_POOL_MIN_CONN = int(os.environ.get("DB_POOL_MIN_CONN", 1))
DB_POOL_MAX_CONN = int(os.environ.get("DB_POOL_MAX_CONN", 10))

# ── Embedding model ─────────────────────────────────────────────────────────

EMBEDDING_MODEL_NAME = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")

# ── Retrieval params ─────────────────────────────────────────────────────────

TOP_K = int(os.environ.get("TOP_K", 30))
FINAL_N = int(os.environ.get("FINAL_N", 5))
MMR_LAMBDA = float(os.environ.get("MMR_LAMBDA", 0.6))

# ── Logging ──────────────────────────────────────────────────────────────────

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
LOG_FILE = os.environ.get("LOG_FILE", "logs.log")
LOG_MAX_BYTES = int(os.environ.get("LOG_MAX_BYTES", 5 * 1024 * 1024))  # 5 MB
LOG_BACKUP_COUNT = int(os.environ.get("LOG_BACKUP_COUNT", 5))
LOG_TO_CONSOLE = _get_bool("LOG_TO_CONSOLE", True)

# ── App ──────────────────────────────────────────────────────────────────────

APP_TITLE = os.environ.get("APP_TITLE", "PoliSense — Policy Discovery")


def _log_startup_diagnostics() -> None:
    """
    Print (once, at import time) which .env files were actually found and
    what DB config was resolved from them — with the password masked. This
    turns "why is my password empty" into a one-line answer in logs.log
    instead of a guessing game.
    """
    from logging_config import get_logger  # local import: avoid a cycle at module load

    logger = get_logger("config")
    found = [str(p) for p in _CANDIDATE_ENV_FILES if p.exists()]
    logger.info("Env files found: %s", found or "none (relying on real environment variables)")
    logger.info(
        "Resolved DB config: host=%s port=%s dbname=%s user=%s password_set=%s sslmode=%s",
        DB_CONFIG["host"], DB_CONFIG["port"], DB_CONFIG["dbname"],
        DB_CONFIG["user"], bool(DB_CONFIG["password"]), DB_SSLMODE,
    )


_log_startup_diagnostics()