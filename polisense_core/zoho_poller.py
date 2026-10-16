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
from typing import Dict, List, Optional

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

# ── Zoho OAuth / sheet config (from .env) ────────────────────────────────────
_ZOHO_DC       = os.getenv("ZOHO_DC", "in")          # data-centre: in | com | eu | au
_CLIENT_ID     = os.getenv("ZOHO_CLIENT_ID")
_CLIENT_SECRET = os.getenv("ZOHO_CLIENT_SECRET")
_REFRESH_TOKEN = os.getenv("ZOHO_REFRESH_TOKEN")
_WORKBOOK_ID   = os.getenv("ZOHO_WORKBOOK_ID")
_SHEET_NAME    = os.getenv("ZOHO_SHEET_NAME", "Entries")

# ── Exact column headers as they appear in the Zoho sheet ────────────────────
_COL = {
    "timestamp":     "Submitted",
    "business_name": "Legal Name of the Enterprise",
    "industry":      "Primary Business Sector",
    "sub_industry":  "Detailed Business Activity",
    "geography":     "Location of the Proposed Project / Unit",
    "business_size": "Your Entity Registered in Startup (DPIIT Recognition)",
    "category":      "What is the primary purpose of seeking a subsidy/incentive?",
}

# ── Persistent state ──────────────────────────────────────────────────────────
_STATE_FILE = BASE_DIR / "documents" / "zoho_poll_state.json"

# ── Known Indian state names (lower-case) for geography extraction ────────────
_INDIAN_STATES = {
    "andhra pradesh", "arunachal pradesh", "assam", "bihar", "chhattisgarh",
    "goa", "gujarat", "haryana", "himachal pradesh", "jharkhand", "karnataka",
    "kerala", "madhya pradesh", "maharashtra", "manipur", "meghalaya", "mizoram",
    "nagaland", "odisha", "punjab", "rajasthan", "sikkim", "tamil nadu",
    "tamilnadu", "telangana", "tripura", "uttar pradesh", "uttarakhand",
    "west bengal", "delhi", "jammu and kashmir", "ladakh",
}

# canonical display names for ambiguous / abbreviated state strings
_STATE_CANONICAL = {
    "tamilnadu": "Tamil Nadu",
}


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
    return data.get("records", [])


def _parse_zoho_ts(raw: str) -> datetime:
    """Parse Zoho timestamp strings to a tz-aware UTC datetime.

    Handles formats seen in the Zoho sheet API response:
      - "13/10/2026 11:54:59 AM"  (DD/MM/YYYY 12-hour)
      - "2026-10-13T11:54:59"     (ISO)
      - "2026-10-13 11:54:59"     (ISO without T)
    """
    for fmt in (
        "%d/%m/%Y %I:%M:%S %p",   # Zoho: 13/10/2026 11:54:59 AM
        "%m/%d/%Y %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(raw.strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Unrecognised Zoho timestamp: {raw!r}")


# ── Value helpers ─────────────────────────────────────────────────────────────

def _parse_json_array(raw: str) -> List[str]:
    """Parse a JSON-array string like '["A","B"]' into a list of strings."""
    if not raw:
        return []
    try:
        val = json.loads(raw)
        return val if isinstance(val, list) else [str(val)]
    except (json.JSONDecodeError, TypeError):
        return [raw]


def _join_values(raw: str) -> str:
    """Return a comma-joined string from a JSON-array column value."""
    return ", ".join(p.strip() for p in _parse_json_array(raw) if p.strip())


def _extract_state(location_str: str) -> str:
    """Identify an Indian state name from a concatenated Zoho address string."""
    lower = location_str.lower()
    for state in _INDIAN_STATES:
        if state in lower:
            return _STATE_CANONICAL.get(state, state.title())
    return ""


# ── Row → batch dict transformation ──────────────────────────────────────────

def transform_rows_to_batch(rows: List[dict]) -> Dict[str, Dict]:
    """Convert Zoho worksheet rows to the dict shape expected by process_batch()."""
    batch: Dict[str, Dict] = {}
    for row in rows:
        name = (row.get(_COL["business_name"]) or "").strip() or \
               f"Row_{row.get('row_index', 'unknown')}"

        industry     = _join_values(row.get(_COL["industry"], ""))
        sub_industry = (row.get(_COL["sub_industry"]) or "").strip()
        geography    = _extract_state(row.get(_COL["geography"], ""))
        category     = _join_values(row.get(_COL["category"], ""))

        # Use "Startup" as business_size only if DPIIT-recognised
        dpiit_raw    = _join_values(row.get(_COL["business_size"], ""))
        business_size = "Startup" if "yes" in dpiit_raw.lower() else ""

        query_parts = [p for p in [
            industry,
            sub_industry,
            f"company in {geography}" if geography else "",
            category,
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
            raw_ts = row.get(_COL["timestamp"])
            if not raw_ts:
                continue
            try:
                if _parse_zoho_ts(raw_ts) > last_polled:
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
    schedule.every(2).hours.do(poll_and_process)
    logger.info("Zoho poller running — polls every 2 hours. Press Ctrl+C to stop.")
    while True:
        schedule.run_pending()
        time.sleep(60)
