"""Long-running Zoho Sheets poller.

Fetches new form submissions every 2 hours and runs the retrieval pipeline
against each new row. Run this as the 24/7 entry point:

    python polisense_core/zoho_poller.py
"""
import json
import logging
import logging.config
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import requests
import schedule
from dotenv import load_dotenv

from polisense_core.retrieval_pipeline import process_batch
from polisense_core.settings import BASE_DIR
from polisense_core.utils.logger import LOGGING_CONFIG

load_dotenv()

logging.config.dictConfig(LOGGING_CONFIG)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# ── Zoho OAuth / sheet config (from .env) ───────────────────────────────────
_ZOHO_DC       = os.getenv("ZOHO_DC", "com")          # data-centre: com / in / eu / au
_CLIENT_ID     = os.getenv("ZOHO_CLIENT_ID")
_CLIENT_SECRET = os.getenv("ZOHO_CLIENT_SECRET")
_REFRESH_TOKEN = os.getenv("ZOHO_REFRESH_TOKEN")
_WORKBOOK_ID   = os.getenv("ZOHO_WORKBOOK_ID")
_SHEET_NAME    = os.getenv("ZOHO_SHEET_NAME", "Sheet1")

# ── Column name mapping — update when form schema is confirmed ───────────────
# Keys are internal names; values are the exact column headers in the Zoho sheet.
_COL = {
    "timestamp":     "form_submission_timestamp",
    "business_name": "Name",
    "industry":      "Industry",
    "sub_industry":  "Sub Industry",
    "geography":     "Geography",
    "business_size": "Business Size",
    "category":      "Category",
}

# ── Persistent state ─────────────────────────────────────────────────────────
_STATE_FILE = BASE_DIR / "documents" / "zoho_poll_state.json"


def _load_last_polled() -> Optional[datetime]:
    if _STATE_FILE.exists():
        ts = json.loads(_STATE_FILE.read_text()).get("last_polled_at")
        if ts:
            return datetime.fromisoformat(ts)
    return None


def _save_last_polled(ts: datetime) -> None:
    _STATE_FILE.write_text(json.dumps({"last_polled_at": ts.isoformat()}))


# ── Zoho API helpers ─────────────────────────────────────────────────────────

def get_access_token() -> str:
    resp = requests.post(
        f"https://accounts.zoho.{_ZOHO_DC}/oauth/v2/token",
        params={
            "grant_type":    "refresh_token",
            "client_id":     _CLIENT_ID,
            "client_secret": _CLIENT_SECRET,
            "refresh_token": _REFRESH_TOKEN,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def fetch_all_rows(access_token: str) -> list[dict]:
    resp = requests.get(
        f"https://sheet.zoho.com/api/v2/{_WORKBOOK_ID}",
        params={
            "method":         "worksheet.records.fetch",
            "worksheet_name": _SHEET_NAME,
        },
        headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "success":
        raise RuntimeError(f"Zoho API returned error: {data}")
    return data.get("records", [])


def _parse_zoho_ts(raw: str) -> datetime:
    """Parse Zoho timestamp strings to a tz-aware UTC datetime."""
    for fmt in ("%m/%d/%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Unrecognised Zoho timestamp: {raw!r}")


# ── Row → batch dict transformation ─────────────────────────────────────────

def transform_rows_to_batch(rows: list[dict]) -> Dict[str, Dict]:
    """Convert Zoho rows to the dict shape expected by process_batch()."""
    batch: Dict[str, Dict] = {}
    for row in rows:
        name         = row.get(_COL["business_name"], f"Row_{row.get('ROWNO', 'unknown')}")
        industry     = row.get(_COL["industry"], "")
        sub_industry = row.get(_COL["sub_industry"], "")
        geography    = row.get(_COL["geography"], "")
        business_size = row.get(_COL["business_size"], "")
        category     = row.get(_COL["category"], "")

        query_parts = [p for p in [
            business_size,
            industry,
            sub_industry,
            f"company in {geography}" if geography else "",
            "grants subsidies and incentives",
        ] if p]

        batch[name] = {
            "query": " ".join(query_parts),
            "profile": {
                "business_name": name,
                "industry":      industry,
                "sub_industry":  sub_industry,
                "geography":     geography,
                "business_size": business_size,
                "category":      category,
            },
        }
    return batch


# ── Main poll cycle ──────────────────────────────────────────────────────────

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
            raw_ts = row.get(_COL["timestamp"])
            if not raw_ts:
                continue
            try:
                if _parse_zoho_ts(raw_ts) > last_polled:
                    new_rows.append(row)
            except ValueError:
                logger.warning("Could not parse timestamp for row %s — skipping", row.get("ROWNO"))
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
    schedule.every(2).hours.do(poll_and_process)
    logger.info("Zoho poller running — polls every 2 hours. Press Ctrl+C to stop.")
    while True:
        schedule.run_pending()
        time.sleep(60)
