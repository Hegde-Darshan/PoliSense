"""Zoho form field → internal batch dict transformation.

Shared by discovery_runner (poller) and the API layer. Keeps all Zoho
column-name knowledge and mapping tables in one place.
"""
import json
import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Exact column headers as they appear in the Zoho sheet / webhook payload ──
# NOTE: Keys must exactly match Zoho form field labels.
# Verify any new field against an actual Zoho row before adding.
_COL = {
    "timestamp":        "Submitted",
    "person_name":      "Person Name",
    "business_name":    "Legal Name of the Enterprise",
    "industry":         "Primary Business Sector",
    "description":      "Tell us about your business and what you are hoping to achieve",
    "geography":        "Location of the Proposed Project / Unit",
    "turnover":         "What is your approximate annual turnover?",
    "startup":          "Your Entity Registered in Startup (DPIIT Recognition)",
    "enquiry_purpose":  "What is the primary purpose of seeking a subsidy/incentive?",
    "majority_stake":   "Does the enterprise have a majority stake (more than 51%) held by any of the following special categories?",
    # Tier-2 extended fields
    "business_stage":     "Business Stage",
    "investment_pm":      "Investment in Plant & Machinery",
    "total_project_cost": "Estimated Total Project Cost",
    "cost_breakup":       "Break-up of Project Cost (Approximate)",
    "entity_type":        "Type of Entity",
    "udyam_number":       "Udyam Registration Number",
    "prior_subsidy":      "Have you availed any Central or State Government subsidy in the past?",
}

# Public alias so callers (e.g. discovery_runner) can resolve the timestamp column name.
TIMESTAMP_COL: str = _COL["timestamp"]

# ── Form option → internal tag mappings ──────────────────────────────────────
# Keys are lower-cased form labels; None means "no filter for this dimension".

_INDUSTRY_TAG: dict[str, str | None] = {
    "manufacturing":                          "Manufacturing",
    "information technology (it / software)": "Information Technology",
    "it & ites (information technology)":     "Information Technology",
    "electronics and hardware":               "Electronics and Hardware",
    "agriculture / agro-processing":          "Agriculture and Agro-Processing",
    "agri-business & food processing":        "Agriculture and Agro-Processing",
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
    "services":                               None,
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
    "developing a new technology/product (r&d)":            "R&D and Innovation Grant",
    "expanding into export markets":                        "Export Promotion",
    "constructing a factory building or shed":              "Capital Subsidy",
    "purchasing plant & machinery or equipment":            "Capital Subsidy",
    "hiring new employees":                                 "Employment Generation",
    "training or upskilling employees":                     "Skill Development",
    "reducing electricity or utility costs":                "Power and Utility Concession",
    "interest subsidy on business loan":                    "Interest Subvention",
    "working capital support":                              "Working Capital Assistance",
    "tax exemptions or rebates":                            "Tax Incentive",
    "market access or marketing support":                   "Market Access and Marketing Support",
    "land or infrastructure support":                       "Land and Building Concession",
    "credit guarantee or collateral-free loan":             "Credit Guarantee",
    "purchasing new plant & machinery":                    "Capital Subsidy",
    "setting up a new manufacturing facility":             "Capital Subsidy",
    "implementing green technology (e.g., solar, etp)":   "Capital Subsidy",
    "working capital requirement":                         "Working Capital Assistance",
    "i'm not sure — just show me what's available":        None,
}

_ENTERPRISE_TYPE_TAG: dict[str, str | None] = {
    "new enterprise":                                       "New",
    "new enterprise (pre-incorporation or just incorporated)": "New",
    "new":                                "New",
    "new unit":                           "New",
    "setting up a new unit":              "New",
    "greenfield":                         "New",
    "existing enterprise":                "Existing",
    "existing":                           "Existing",
    "existing unit":                      "Existing",
    "established enterprise":             "Existing",
    "existing enterprise - modernization (upgrading technology/machinery)": "Existing",
    "expansion":                          "Expansion",
    "expansion of existing unit":         "Expansion",
    "expansion project":                  "Expansion",
    "diversification":                    "Expansion",
    "existing enterprise - expansion (adding new capacity/products)": "Expansion",
    "startup (innovative, tech-enabled, scalable business model)": "New",
}

_SPECIAL_ATTRIBUTES_TAG: dict[str, str | None] = {
    "women":                              "Women-led",
    "women-led":                          "Women-led",
    "women entrepreneur":                 "Women-led",
    "woman entrepreneur":                 "Women-led",
    "sc":                                 "SC/ST-led",
    "st":                                 "SC/ST-led",
    "sc/st":                              "SC/ST-led",
    "scheduled caste":                    "SC/ST-led",
    "scheduled tribe":                    "SC/ST-led",
    "differently abled":                  "Differently-abled",
    "persons with disabilities":          "Differently-abled",
    "person with disability (pwd)":       "Differently-abled",
    "pwd":                                "Differently-abled",
    "ex-servicemen":                      "Ex-Servicemen",
    "ex servicemen":                      "Ex-Servicemen",
    "defence personnel":                  "Ex-Servicemen",
    "minority community entrepreneur":    None,
    "none":                               None,
    "none of the above":                  None,
    "not applicable":                     None,
}

_INDIA_STATES: frozenset[str] = frozenset({
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh",
    "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand",
    "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur",
    "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab",
    "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura",
    "Uttar Pradesh", "Uttarakhand", "West Bengal",
    "Andaman and Nicobar Islands", "Chandigarh",
    "Dadra and Nagar Haveli and Daman and Diu",
    "Delhi", "Jammu and Kashmir", "Ladakh", "Lakshadweep", "Puducherry",
})

_CITY_TO_STATE: dict[str, str] = {
    "bangalore": "Karnataka",   "bengaluru": "Karnataka",
    "mysore": "Karnataka",      "hubli": "Karnataka",
    "mumbai": "Maharashtra",    "pune": "Maharashtra",
    "nagpur": "Maharashtra",    "nashik": "Maharashtra",
    "delhi": "Delhi",           "new delhi": "Delhi",
    "hyderabad": "Telangana",   "warangal": "Telangana",
    "chennai": "Tamil Nadu",    "coimbatore": "Tamil Nadu",   "madurai": "Tamil Nadu",
    "kolkata": "West Bengal",   "howrah": "West Bengal",
    "ahmedabad": "Gujarat",     "surat": "Gujarat",           "vadodara": "Gujarat",
    "jaipur": "Rajasthan",      "jodhpur": "Rajasthan",
    "lucknow": "Uttar Pradesh", "kanpur": "Uttar Pradesh",    "agra": "Uttar Pradesh",
    "bhopal": "Madhya Pradesh", "indore": "Madhya Pradesh",
    "patna": "Bihar",
    "bhubaneswar": "Odisha",    "cuttack": "Odisha",
    "thiruvananthapuram": "Kerala", "kochi": "Kerala",        "kozhikode": "Kerala",
    "guwahati": "Assam",
    "raipur": "Chhattisgarh",
    "dehradun": "Uttarakhand",
    "ranchi": "Jharkhand",
    "shimla": "Himachal Pradesh",
    "chandigarh": "Chandigarh",
    "panaji": "Goa",
    "visakhapatnam": "Andhra Pradesh", "vizag": "Andhra Pradesh", "vijayawada": "Andhra Pradesh",
    "amaravati": "Andhra Pradesh",
    "dispur": "Assam",
    "imphal": "Manipur",        "shillong": "Meghalaya",
    "aizawl": "Mizoram",        "kohima": "Nagaland",
    "agartala": "Tripura",      "gangtok": "Sikkim",
    "itanagar": "Arunachal Pradesh",
}


# ── Value helpers ─────────────────────────────────────────────────────────────

def _parse_json_array(raw) -> List[str]:
    """Parse a JSON-array string like '["A","B"]' into a list of strings."""
    if not raw and raw != 0:
        return []
    if not isinstance(raw, str):
        return [str(raw)]
    try:
        val = json.loads(raw)
        return val if isinstance(val, list) else [str(val)]
    except (json.JSONDecodeError, TypeError):
        return [raw]


def _get_str(raw) -> str:
    """Extract the first plain string from a Zoho column (handles JSON-array wrapping)."""
    vals = _parse_json_array(raw)
    return str(vals[0]).strip() if vals else ""


def _lookup_all(mapping: dict, raw: str, field: str) -> list[str] | None:
    """Return all matched internal tags for a (possibly multi-select) form field.

    Logs a warning for unrecognised values. Values that map to None in the mapping
    table (e.g. 'My industry is not listed here') are skipped so other selections
    still contribute to the filter. Returns None when nothing maps (no filter applied).
    """
    tags = []
    for raw_val in _parse_json_array(raw):
        key = raw_val.strip().lower()
        if not key:
            continue
        if key not in mapping:
            logger.warning("Unrecognised %s value: %r — skipping", field, raw_val)
            continue
        if mapping[key] is not None:
            tags.append(mapping[key])
    return tags if tags else None


def _parse_inr_field(raw: str) -> float | None:
    """Parse a raw INR numeric string from a Zoho form field to lakhs.

    Handles plain integers ('2000000'), formatted strings ('20,00,000'),
    and values already expressed in lakhs ('20').  Treats values > 100 000
    as absolute INR and converts to lakhs; smaller values assumed to be
    already in lakhs (consistent with how the form labels say "INR").
    """
    if not raw:
        return None
    cleaned = _get_str(raw).replace(",", "").replace("₹", "").strip()
    try:
        value = float(cleaned)
    except ValueError:
        return None
    if value <= 0:
        return None
    if value > 1_00_000:
        return value / 1_00_000
    return value


def _extract_state_from_address(raw: str) -> str | None:
    """Return the Indian state/UT name found in a full address string, or None.

    First tries direct state-name matching; falls back to major-city lookup
    for addresses that mention a city but omit the state name.
    """
    if not raw:
        return None
    raw_lower = raw.lower()
    for state in _INDIA_STATES:
        if re.search(r'\b' + re.escape(state.lower()) + r'\b', raw_lower):
            return state
    for city, state in _CITY_TO_STATE.items():
        if re.search(r'\b' + re.escape(city) + r'\b', raw_lower):
            return state
    return None


def parse_zoho_ts(raw: str) -> datetime:
    """Parse Zoho timestamp strings to a tz-aware UTC datetime.

    Handles formats seen in the Zoho sheet API response:
      - "13/10/2026 11:54:59 AM"  (DD/MM/YYYY 12-hour)
      - "2026-10-13T11:54:59"     (ISO)
      - "2026-10-13 11:54:59"     (ISO without T)
    """
    for fmt in (
        "%d/%m/%Y %I:%M:%S %p",
        "%m/%d/%Y %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(raw.strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Unrecognised Zoho timestamp: {raw!r}")


# ── Row → batch dict transformation ──────────────────────────────────────────

def transform_rows_to_batch(rows: List[dict]) -> Dict[str, Dict]:
    """Convert Zoho worksheet rows to the dict shape expected by process_batch().

    Deduplication rule: if the same business submits multiple times on the same
    calendar date, only the latest submission is kept. Submissions on different
    dates each get their own teaser report.
    """
    parsed = []
    for row in rows:
        name = _get_str(row.get(_COL["business_name"], "")) or \
               f"Row_{row.get('row_index', 'unknown')}"
        raw_ts = row.get(_COL["timestamp"], "")
        try:
            submission_time = parse_zoho_ts(raw_ts) if raw_ts else None
        except ValueError:
            submission_time = None
        parsed.append((name, submission_time, row))

    latest_ts: dict[tuple, datetime] = {}
    for name, submission_time, _ in parsed:
        if submission_time is None:
            continue
        key = (name, submission_time.date())
        if key not in latest_ts or submission_time > latest_ts[key]:
            latest_ts[key] = submission_time

    batch: Dict[str, Dict] = {}
    for name, submission_time, row in parsed:
        if submission_time is not None:
            key = (name, submission_time.date())
            if latest_ts.get(key) != submission_time:
                logger.info(
                    "Skipping earlier same-day submission for %s at %s (keeping %s)",
                    name, submission_time, latest_ts[key],
                )
                continue

        industry = _lookup_all(_INDUSTRY_TAG, row.get(_COL["industry"], ""), "industry")
        geography = _extract_state_from_address(row.get(_COL["geography"], ""))

        business_size_list = _lookup_all(_BUSINESS_SIZE_TAG, row.get(_COL["turnover"], ""), "business_size")
        business_size = business_size_list[0] if business_size_list else None
        startup_vals = _parse_json_array(row.get(_COL["startup"], ""))
        if any("yes" in v.lower() for v in startup_vals):
            business_size = "Startup"

        category = _lookup_all(_CATEGORY_TAG, row.get(_COL["enquiry_purpose"], ""), "enquiry_purpose")

        description = _get_str(row.get(_COL["description"], "")).strip()
        if not description:
            parts = []
            if industry:
                parts.append(", ".join(industry) if isinstance(industry, list) else industry)
            if geography:
                parts.append(f"in {geography}")
            if business_size:
                parts.append(f"{business_size} business")
            description = " ".join(parts)
        query = f"{description} government grants subsidies and incentives"

        enterprise_type_list = _lookup_all(
            _ENTERPRISE_TYPE_TAG, row.get(_COL["business_stage"], ""), "business_stage"
        )
        enterprise_type = enterprise_type_list[0] if enterprise_type_list else None

        investment_pm_lakhs = _parse_inr_field(row.get(_COL["investment_pm"], ""))
        total_project_cost_lakhs = _parse_inr_field(row.get(_COL["total_project_cost"], ""))

        special_attributes = _lookup_all(
            _SPECIAL_ATTRIBUTES_TAG, row.get(_COL["majority_stake"], ""), "majority_stake"
        )

        cost_breakup = _get_str(row.get(_COL["cost_breakup"], "")).strip() or None
        person_name  = _get_str(row.get(_COL["person_name"], "")).strip() or None
        entity_type  = _get_str(row.get(_COL["entity_type"], "")).strip() or None
        udyam_number = _get_str(row.get(_COL["udyam_number"], "")).strip() or None

        ts_key = submission_time.strftime("%d%m%Y_%H%M%S") if submission_time else f"row_{row.get('row_index', 'unknown')}"
        query_name = f"{name}_{ts_key}"

        batch[query_name] = {
            "query":           query,
            "submission_time": submission_time,
            "profile": {
                "person_name":      person_name,
                "business_name":    name,
                "industry":         industry,
                "geography":        geography,
                "business_size":    business_size,
                "enquiry_purpose":  category,
                "enterprise_type":           enterprise_type,
                "investment_pm_lakhs":        investment_pm_lakhs,
                "total_project_cost_lakhs":   total_project_cost_lakhs,
                "special_attributes":         special_attributes,
                "entity_type":               entity_type,
                "udyam_number":              udyam_number,
                "project_cost_breakup":      cost_breakup,
            },
        }
    return batch
