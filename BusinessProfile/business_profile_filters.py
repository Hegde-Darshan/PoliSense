# profile_schema.py
# ─────────────────────────────────────────────────────────────────────────────
# Step 1: Extract canonical values from DB
# Step 2: Validate / create profiles using only those values
# Step 3: Use profile fields directly as retrieval filters
# ─────────────────────────────────────────────────────────────────────────────

import sys
import json
from pathlib import Path

ROOT_PATH = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_PATH))

from IngestionPipeline.postgres import get_connection


# ── STEP 1: Extract canonical values from DB ──────────────────────────────────

def get_canonical_values(conn) -> dict:
    """Pull all distinct filterable values directly from the policies table."""
    with conn.cursor() as cur:

        cur.execute("SELECT DISTINCT industry FROM policies WHERE industry IS NOT NULL")
        industries = sorted(set(r[0] for r in cur.fetchall()))

        cur.execute("SELECT DISTINCT sub_industry FROM policies WHERE sub_industry IS NOT NULL")
        raw = [r[0] for r in cur.fetchall()]
        sub_industries = sorted(set(
            part.strip() for s in raw for part in s.split(",") if part.strip()
        ))

        cur.execute("SELECT DISTINCT geography FROM policies WHERE geography IS NOT NULL")
        geographies = sorted(set(r[0] for r in cur.fetchall()))

        cur.execute("SELECT DISTINCT business_size FROM policies WHERE business_size IS NOT NULL")
        raw = [r[0] for r in cur.fetchall()]
        business_sizes = sorted(set(
            part.strip() for s in raw for part in s.split(",") if part.strip()
        ))

        cur.execute("SELECT DISTINCT category FROM policies WHERE category IS NOT NULL")
        categories = sorted(set(r[0] for r in cur.fetchall()))

    return {
        "industry":      industries,
        "sub_industry":  sub_industries,
        "geography":     geographies,
        "business_size": business_sizes,
        "category":      categories,
    }


# ── STEP 2: Profile validator ─────────────────────────────────────────────────

class ProfileValidator:
    """
    Validates a business profile against canonical DB values.
    Raises ValueError with clear messages if any field has an invalid value.
    """

    def __init__(self, canonical: dict):
        self.canonical = canonical

    def validate(self, profile: dict) -> dict:
        """
        Validate profile fields against DB values.
        Returns cleaned profile with only valid filter fields retained.
        Raises ValueError listing all invalid fields at once.
        """
        errors = []

        for field in ["industry", "sub_industry", "geography", "business_size"]:
            value = profile.get(field)
            if value is None:
                continue  # optional — skip
            valid_values = self.canonical[field]
            if value not in valid_values:
                # Find close matches to help user fix the value
                close = [v for v in valid_values if value.lower() in v.lower() or v.lower() in value.lower()]
                suggestion = f" Did you mean: {close}?" if close else f" Valid values: {valid_values}"
                errors.append(f"  '{field}': '{value}' is not a valid DB value.{suggestion}")

        if errors:
            raise ValueError(
                f"Profile '{profile.get('business_name', 'unknown')}' has invalid fields:\n"
                + "\n".join(errors)
            )

        return profile

    def print_valid_values(self):
        """Print all valid values for each filterable field."""
        print("\n📋 Valid DB values for business profile fields:")
        for field, values in self.canonical.items():
            print(f"\n  {field}:")
            for v in values:
                print(f"    - {v}")


# ── STEP 3: Extract filters directly from validated profile ───────────────────

def extract_filters(profile: dict) -> dict:
    """
    Directly use profile fields as retrieval filters.
    No mapping, no transformation — field values ARE the DB values.
    Only includes fields that are non-None.
    """
    filters = {}

    # Direct DB filter fields
    for field in ["industry", "sub_industry", "geography", "business_size"]:
        value = profile.get(field)
        if value is not None:
            filters[field] = value

    # Special signals for re-ranking (not DB filters)
    signals = []
    ownership = (profile.get("ownership_type") or "").lower()
    special   = [s.lower() for s in (profile.get("special_attributes") or [])]

    if "women" in ownership or "women-led" in special: signals.append("women_owned")
    if any(x in special for x in ["sc", "st", "sc/st"]): signals.append("sc_st")
    if "rural" in special:                               signals.append("rural")
    if any(x in special for x in ["shg", "shg-based"]): signals.append("shg")
    if any(x in special for x in ["youth", "youth-led"]): signals.append("youth_led")
    if any(x in special for x in ["export", "export-oriented"]): signals.append("export_oriented")

    if signals:
        filters["_special_signals"] = signals

    return filters


# --- STEP 4: Create query using business profile ---------------------------
def generate_query_from_profile(profile: dict) -> str:
    """
    Auto-generate a retrieval query from a business profile.
    No user input needed — the profile has all the signal required.
    """
    parts = []

    # What kind of business
    if profile.get("sub_industry"):
        parts.append(profile["sub_industry"])
    elif profile.get("industry"):
        parts.append(profile["industry"])

    # What size
    if profile.get("business_size"):
        parts.append(profile["business_size"])

    # What they're looking for — inferred from growth stage
    stage = (profile.get("growth_stage") or "").lower()
    if stage in ["startup", "early stage", "idea"]:
        parts.append("grants subsidies funding support")
    elif stage in ["growth", "scaling", "expansion"]:
        parts.append("capital subsidy investment incentives")
    else:
        parts.append("incentives subsidies benefits")

    # Special attributes add intent signals
    special = [s.lower() for s in (profile.get("special_attributes") or [])]
    if "women-led" in special or "women" in (profile.get("ownership_type") or "").lower():
        parts.append("women owned enterprise")
    if "export-oriented" in special:
        parts.append("export promotion")
    if "deep tech" in special or "r&d" in special:
        parts.append("R&D grant patent reimbursement")
    if "rural" in special:
        parts.append("rural enterprise")

    return " ".join(parts)

# ── Sample profiles using exact DB values ─────────────────────────────────────
# These are what business profiles should look like after the questionnaire
# is filled in — industry/sub_industry/geography/business_size must be
# selected from the canonical DB values (e.g. via a dropdown in your UI).

SAMPLE_PROFILES = [
    {
        "business_name": "VoltEdge Battery Pvt Ltd",
        "industry":      "Automotive, Energy Storage",        # exact DB value
        "sub_industry":  "EV Battery Manufacturing",          # exact DB value
        "geography":     "Karnataka",                         # exact DB value
        "business_size": "Startup",                           # exact DB value
        "ownership_type": "Private",
        "special_attributes": ["Startup", "Deep Tech"],
    },
    {
        "business_name": "ChargeFast Solutions Pvt Ltd",
        "industry":      "Automotive, Energy Storage",
        "sub_industry":  "Charging Infrastructure",
        "geography":     "Karnataka",
        "business_size": "Small Enterprise",
        "ownership_type": "Private",
    },
    {
        "business_name": "GreenFleet Mobility Pvt Ltd",
        "industry":      "Clean Mobility",
        "sub_industry":  None,                                # not set → skipped as filter
        "geography":     "Karnataka",
        "business_size": "Startup",
        "ownership_type": "Women-Owned",
        "special_attributes": ["Startup", "Women-led"],
    },
    {
        "business_name": "NeuralChip Technologies Pvt Ltd",
        "industry":      "Electronics System Design & Manufacturing (ESDM)",
        "sub_industry":  "semiconductors",
        "geography":     "Karnataka",
        "business_size": "Startup",
        "ownership_type": "Private",
        "special_attributes": ["Deep Tech"],
    },
    {
        "business_name": "MedSense Electronics Pvt Ltd",
        "industry":      "Electronics System Design & Manufacturing (ESDM)",
        "sub_industry":  "Medical Electronics",
        "geography":     "Karnataka",
        "business_size": "Micro Enterprise",
        "ownership_type": "Women-Owned",
        "special_attributes": ["Women-led", "Export-oriented"],
    },
    {
        "business_name": "IdeaSpark Innovations Pvt Ltd",
        "industry":      None,   # AI/ML not in DB → no industry filter applied
        "sub_industry":  None,
        "geography":     None,   # Telangana not in DB → no geography filter
        "business_size": "Small Enterprise",
        "ownership_type": "Private",
        "special_attributes": ["Startup", "Youth-led"],
    },
]


# ── Main: validate profiles and show extracted filters ────────────────────────

if __name__ == "__main__":
    conn      = get_connection()
    canonical = get_canonical_values(conn)
    print(canonical)
    validator = ProfileValidator(canonical)

    # Optionally print all valid values
    validator.print_valid_values()

    print(f"\n\n{'─'*65}")
    print("  Profile filter extraction")
    print(f"{'─'*65}")

    for profile in SAMPLE_PROFILES:
        try:
            validator.validate(profile)
            filters = extract_filters(profile)
            signals = filters.pop("_special_signals", [])
            print(f"\n  ✅ {profile['business_name']}")
            print(f"     filters : {filters}")
            if signals:
                print(f"     signals : {signals}")
        except ValueError as e:
            print(f"\n  ❌ {e}")

    conn.close()