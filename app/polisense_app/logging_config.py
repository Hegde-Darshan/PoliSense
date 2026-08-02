"""
logging_config.py
==================
Single place that configures logging for the whole app.

Every module calls `get_logger(__name__)` to get a properly configured
logger. Handlers are attached only once per logger name, so this is safe to
call repeatedly across Streamlit reruns (Streamlit re-executes the script on
every interaction, which would otherwise duplicate log lines).

Log destinations:
  - <LOG_FILE> (default: logs.log)  — rotating file handler, kept on disk
  - stdout                          — so logs also show up in `streamlit run`
                                       output / container logs (e.g. Docker,
                                       Streamlit Cloud, Railway, etc.)
"""

import logging
import sys
from logging.handlers import RotatingFileHandler

from config import (
    LOG_BACKUP_COUNT,
    LOG_FILE,
    LOG_LEVEL,
    LOG_MAX_BYTES,
    LOG_TO_CONSOLE,
)

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_CONFIGURED_LOGGERS: set[str] = set()


def get_logger(name: str = "polisense") -> logging.Logger:
    """
    Return a logger configured to write to LOG_FILE (rotating) and stdout.

    Safe to call multiple times with the same name (e.g. on every Streamlit
    rerun) — handlers are attached only the first time.
    """
    logger = logging.getLogger(name)

    if name in _CONFIGURED_LOGGERS:
        return logger

    logger.setLevel(LOG_LEVEL)
    formatter = logging.Formatter(_LOG_FORMAT, _DATE_FORMAT)

    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(LOG_LEVEL)
    logger.addHandler(file_handler)

    if LOG_TO_CONSOLE:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        console_handler.setLevel(LOG_LEVEL)
        logger.addHandler(console_handler)

    # Don't bubble up to the root logger (avoids duplicate lines when other
    # libraries — e.g. sentence-transformers — configure the root logger).
    logger.propagate = False

    _CONFIGURED_LOGGERS.add(name)
    return logger
