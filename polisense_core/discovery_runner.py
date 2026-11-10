"""Long-running Zoho Sheets poller.

Fetches new form submissions every 2 hours and runs the retrieval pipeline
against each new row. Run this as the 24/7 entry point:

    python polisense_core/discovery_runner.py
"""
import json
import logging
import logging.config
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import requests
from dotenv import load_dotenv

from polisense_core.discovery_pipeline import process_batch
from polisense_core.settings import BASE_DIR
from polisense_core.utils.logger import LOGGING_CONFIG
from polisense_core.utils.zoho_transforms import (
    TIMESTAMP_COL,
    parse_zoho_ts,
    transform_rows_to_batch,
)

load_dotenv()

logging.config.dictConfig(LOGGING_CONFIG)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# ── Zoho OAuth / sheet config (from .env) ────────────────────────────────────
_ZOHO_DC       = os.getenv("ZOHO_DC", "in")          # data-centre: in | com | eu | au
_CLIENT_ID     = os.getenv("ZOHO_CLIENT_ID")
_CLIENT_SECRET = os.getenv("ZOHO_CLIENT_SECRET")
_REFRESH_TOKEN = os.getenv("ZOHO_REFRESH_TOKEN")
_WORKBOOK_ID   = os.getenv("ZOHO_WORKBOOK_ID")
_SHEET_NAME    = os.getenv("ZOHO_SHEET_NAME", "Entries")

# ── Persistent state ──────────────────────────────────────────────────────────
_STATE_FILE = BASE_DIR / "documents" / "zoho_poll_state.json"


def _load_last_polled() -> Optional[datetime]:
    if _STATE_FILE.exists():
        ts = json.loads(_STATE_FILE.read_text()).get("last_polled_at")
        if ts:
            return datetime.fromisoformat(ts)
    return None


def _save_last_polled(ts: datetime) -> None:
    _STATE_FILE.write_text(json.dumps({"last_polled_at": ts.isoformat()}))


# ── Zoho API helpers ──────────────────────────────────────────────────────────

def get_access_token() -> str:
    """Exchange the refresh token for a new short-lived access token."""
    resp = requests.post(
        f"https://accounts.zoho.{_ZOHO_DC}/oauth/v2/token",
        data={
            "grant_type":    "refresh_token",
            "client_id":     _CLIENT_ID,
            "client_secret": _CLIENT_SECRET,
            "refresh_token": _REFRESH_TOKEN,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def fetch_all_rows(access_token: str) -> List[dict]:
    """POST to the Zoho Sheet API and return all records from the worksheet."""
    resp = requests.post(
        f"https://sheet.zoho.{_ZOHO_DC}/api/v2/{_WORKBOOK_ID}",
        headers={
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Content-Type":  "application/x-www-form-urlencoded",
        },
        data={
            "method":         "worksheet.records.fetch",
            "worksheet_name": _SHEET_NAME,
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "success":
        raise RuntimeError(f"Zoho API returned error: {data}")
    # Strip whitespace from column keys — Zoho occasionally includes trailing spaces
    return [{k.strip(): v for k, v in row.items()} for row in data.get("records", [])]


# ── Main poll cycle ───────────────────────────────────────────────────────────

def poll_and_process() -> None:
    logger.info("Polling Zoho Sheets for new submissions...")
    last_polled = _load_last_polled()
    poll_start  = datetime.now(timezone.utc)

    try:
        token = get_access_token()
        rows  = fetch_all_rows(token)
    except Exception:
        logger.exception("Failed to fetch rows from Zoho Sheets — will retry next cycle")
        return

    if last_polled:
        new_rows = []
        for row in rows:
            raw_ts = row.get(TIMESTAMP_COL)
            if not raw_ts:
                continue
            try:
                if parse_zoho_ts(raw_ts) > last_polled:
                    new_rows.append(row)
            except ValueError:
                logger.warning(
                    "Could not parse timestamp for row %s — skipping",
                    row.get("row_index"),
                )
        rows = new_rows

    if not rows:
        logger.info("No new submissions since %s", last_polled)
        _save_last_polled(poll_start)
        return

    logger.info("%d new submission(s) — running retrieval pipeline", len(rows))
    batch = transform_rows_to_batch(rows)
    process_batch(batch)
    _save_last_polled(poll_start)
    logger.info("Poll complete.")


if __name__ == "__main__":
    poll_and_process()
