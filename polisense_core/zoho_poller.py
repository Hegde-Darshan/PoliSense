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
    "business_name": "What is the name of your business?",
    "industry":      "Which of the following best describes your industry?",
    "description":   "Tell us about your business and what you are hoping to achieve",
    "geography":     "In which state are your business operations primarily located?",
    "turnover":      "What is your approximate annual turnover?",
    "startup":       "Is your business registered under the Government of India's Startup India programme?",
    "category":      "What kind of support are you mainly looking for?",
    "context":       "Is there anything else that would help us find the right schemes for you? (Optional)",
}

# ── Persistent state ──────────────────────────────────────────────────────────
_STATE_FILE = BASE_DIR / "documents" / "zoho_poll_state.json"

# ── Form option → internal tag mappings ──────────────────────────────────────
# Keys are lower-cased form labels; None means "no filter for this dimension".

_INDUSTRY_TAG: dict[str, str | None] = {
    "manufacturing":                          "Manufacturing",
    "information technology (it / software)": "Information Technology",
    "electronics and hardware":               "Electronics and Hardware",
    "agriculture / agro-processing":          "Agriculture and Agro-Processing",
    "textiles and apparel":                   "Textile and Apparel",
    "food processing":                        "Food Processing",
    "pharmaceuticals and biotechnology":      "Pharmaceuticals and Biotech",
    "automotive and electric vehicles":       "Automotive and EV",
    "renewable energy and clean technology":  "Renewable Energy and Clean Tech",
    "tourism and hospitality":                "Tourism and Hospitality",
    "healthcare and medical devices":         "Healthcare and Medical Devices",
    "education and skill development":        "Education and Skill Development",
    "logistics and warehousing":              "Logistics and Warehousing",
    "financial services and fintech":         "Financial Services and Fintech",
    "defence and aerospace":                  "Defense and Aerospace",
    "construction and real estate":           "Construction and Real Estate",
    "retail and e-commerce":                  "Retail and E-commerce",
    "chemicals and petrochemicals":           "Chemical and Petrochemical",
    "mining and minerals":                    "Mining and Minerals",
    "media and entertainment":                "Media and Entertainment",
    "my industry is not listed here":         None,
}

_BUSINESS_SIZE_TAG: dict[str, str | None] = {
    "less than ₹1 crore":                 "Micro",
    "₹1 crore to ₹10 crore":             "Small",
    "₹10 crore to ₹50 crore":            "Medium",
    "₹50 crore to ₹250 crore":           "Large",
    "more than ₹250 crore":               "Mega",
    "i'd prefer not to say / not sure":   None,
}

_CATEGORY_TAG: dict[str, str | None] = {
    "funding to buy machinery, equipment, or expand my facility":          "Capital Subsidy",
    "lower interest rates on business loans":                               "Interest Subvention",
    "tax exemptions or tax rebates":                                        "Tax Incentive",
    "support with infrastructure — roads, power connection, water supply":  "Infrastructure Support",
    "funding for research, innovation, or developing new products":         "R&D and Innovation Grant",
    "training and skill development programmes for my employees":           "Skill Development",
    "help with exporting my products to other countries":                   "Export Promotion",
    "access to new markets or marketing support":                           "Market Access and Marketing Support",
    "subsidised land or help with building costs":                          "Land and Building Concession",
    "reduced electricity tariffs or utility cost support":                  "Power and Utility Concession",
    "support for hiring new employees":                                     "Employment Generation",
    "working capital or short-term credit support":                         "Working Capital Assistance",
    "collateral-free loan guarantees":                                      "Credit Guarantee",
    "i'm not sure — just show me what's available":                        None,
}

_GEOGRAPHY_NATIONAL = "we operate across multiple states / all of india"


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


def _get_str(raw: str) -> str:
    """Extract the first plain string from a Zoho column (handles JSON-array wrapping)."""
    vals = _parse_json_array(raw)
    return vals[0].strip() if vals else ""


def _lookup(mapping: dict, raw: str, field: str) -> str | None:
    """Map a form label to an internal tag; log a warning on unknown values."""
    key = _get_str(raw).lower()
    if not key:
        return None
    if key not in mapping:
        logger.warning("Unrecognised %s value: %r — filter will not be applied", field, key)
        return None
    return mapping[key]


# ── Row → batch dict transformation ──────────────────────────────────────────

def transform_rows_to_batch(rows: List[dict]) -> Dict[str, Dict]:
    """Convert Zoho worksheet rows to the dict shape expected by process_batch()."""
    batch: Dict[str, Dict] = {}
    for row in rows:
        name = _get_str(row.get(_COL["business_name"], "")) or \
               f"Row_{row.get('row_index', 'unknown')}"

        industry = _lookup(_INDUSTRY_TAG, row.get(_COL["industry"], ""), "industry")

        geo_raw   = _get_str(row.get(_COL["geography"], ""))
        geography = "National" if geo_raw.lower() == _GEOGRAPHY_NATIONAL else geo_raw or None

        # Q5 sets the base size tier; Q6 "Yes" overrides it to "Startup"
        business_size = _lookup(_BUSINESS_SIZE_TAG, row.get(_COL["turnover"], ""), "business_size")
        if _get_str(row.get(_COL["startup"], "")).strip().lower() == "yes":
            business_size = "Startup"

        category = _lookup(_CATEGORY_TAG, row.get(_COL["category"], ""), "category")

        # Build query from Q3 (description) + optional Q8 (extra context)
        description = _get_str(row.get(_COL["description"], "")).strip()
        extra       = _get_str(row.get(_COL["context"], "")).strip()
        if extra:
            query = f"{description}. Additional context: {extra} government grants subsidies and incentives"
        else:
            query = f"{description} government grants subsidies and incentives"

        batch[name] = {
            "query": query,
            "profile": {
                "business_name": name,
                "industry":      industry,
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
