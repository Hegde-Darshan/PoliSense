"""
Central place to resolve where documents/ and config.yml live.
Instead of hardcoding './documents/...' everywhere, code asks this module.
"""
import os
from pathlib import Path

# Consumers (like your serving layer) can override this via env var.
# Falls back to current working directory if not set — preserves old behavior
# for anyone still running this repo standalone.
BASE_DIR = Path(os.getenv("RAG_BASE_DIR", os.getcwd()))

DOCUMENTS_DIR = BASE_DIR / "documents"
CONFIG_PATH = BASE_DIR / "config.yml"

