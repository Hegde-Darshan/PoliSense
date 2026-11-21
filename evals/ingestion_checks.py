"""Deterministic, read-only data-quality audit of what is already ingested in Postgres.

See EVALUATION.md section 4.1. No LLM calls, no embedding models, no writes to the DB.

Run from repo root:
    venv/Scripts/python.exe -m evals.ingestion_checks
"""

import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

from polisense_core.utils.postgres_utils import get_connection

RESULTS_DIR = Path(__file__).parent / "results"
CURRENT_YEAR = 2026
EXPECTED_EMBED_DIM = 384
FUZZY_THRESHOLD = 0.90
MAX_EXAMPLES_IN_REPORT = 8

# ── Controlled vocabularies (copied from polisense_core/IngestionPipeline/llm_extractor.py) ──

INDUSTRIES = {
    "Manufacturing", "Information Technology", "Electronics and Hardware",
    "Agriculture and Agro-Processing", "Textile and Apparel", "Food Processing",
    "Pharmaceuticals and Biotech", "Automotive and EV", "Renewable Energy and Clean Tech",
    "Tourism and Hospitality", "Healthcare and Medical Devices", "Education and Skill Development",
    "Logistics and Warehousing", "Financial Services and Fintech", "Defense and Aerospace",
    "Construction and Real Estate", "Retail and E-commerce", "Chemical and Petrochemical",
    "Mining and Minerals", "Media and Entertainment",
    # Expanded govt-sourced sub-sectors / cross-section gaps (keep in sync with llm_extractor.IndustryTag)
    "Leather and Footwear", "Rubber and Plastics", "Metals and Metal Products",
    "Capital Goods and Machinery", "Furniture and Wood Products", "Paper and Packaging",
    "Cement, Ceramics and Non-metallic Minerals", "Gems and Jewellery", "Space",
    "Animation, VFX, Gaming and Comics (AVGC)", "Waste Management, Recycling and Environmental Services",
    "Dairy and Animal Husbandry", "Fisheries and Aquaculture",
    "All Sectors", "Other",
}
SIZES = {"Micro", "Small", "Medium", "MSME", "Large", "Mega", "Startup", "All"}
CATEGORIES = {
    "Capital Subsidy", "Interest Subvention", "Tax Incentive", "Infrastructure Support",
    "R&D and Innovation Grant", "Skill Development", "Export Promotion",
    "Market Access and Marketing Support", "Land and Building Concession",
    "Power and Utility Concession", "Employment Generation", "Working Capital Assistance",
    "Credit Guarantee", "Other",
}
INCENTIVE_TYPES = {
    "Capital Subsidy", "Interest Subvention", "Income Tax Exemption", "GST Reimbursement",
    "Stamp Duty Exemption", "Land Cost Reimbursement", "Power Tariff Concession", "Grant",
    "Soft Loan", "Credit Guarantee", "Employment Subsidy", "R&D Reimbursement", "Patent Support",
    "Export Incentive", "Technology Upgrade Support", "Fee Waiver", "Other",
}
DOCUMENT_TYPES = {
    "Policy Document", "Operational Guidelines", "Government Order", "Scheme Notification",
    "Budget Announcement", "Amendment", "Other",
}
BENEFIT_TYPES = {
    "percentage_subsidy", "fixed_grant", "tax_exemption", "loan", "interest_reduction",
    "fee_waiver", "employment_incentive", "reimbursement", "other",
}
ENTERPRISE_TYPES = {"New", "Existing", "Expansion", "Any"}
MONEY_UNITS = {"lakhs", "crores", "absolute_INR"}

STATES_AND_UTS = {
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat",
    "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh",
    "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab",
    "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand",
    "West Bengal",
    "Andaman and Nicobar Islands", "Chandigarh", "Dadra and Nagar Haveli and Daman and Diu",
    "Delhi", "Jammu and Kashmir", "Ladakh", "Lakshadweep", "Puducherry",
}
VALID_GEOGRAPHIES = STATES_AND_UTS | {"National"}
REGIONAL_LABELS = {"North India", "South India", "East India", "West India", "North East India",
                   "North-East India", "Northeast India", "Central India"}

GARBAGE_STRINGS = {"nan", "none", "null", "n/a", "na", "undefined", "nil", "-", "--", "?"}

TOP_LEVEL_COLUMNS = [
    "policy_id", "parent_policy_name", "policy_name", "incentive_name", "category",
    "applicable_industries", "applicable_geographies", "applicable_business_sizes",
    "start_year", "end_year", "policy_details", "incentive_details", "search_vector",
    "embedding", "source_folder", "ingested_at", "approved",
]

SEVERITY = {
    "1_missing_fields": "high",
    "2_garbage_numbers_and_strings": "high",
    "3_digits_where_text_expected": "medium",
    "4_text_where_number_expected": "high",
    "5_year_sanity": "high",
    "6_vocabulary_conformity": "medium",
    "7_duplicates": "medium",
    "8_embedding_and_search_vector": "high",
    "9_source_text_faithfulness": "high",
    "10_value_source_consistency": "medium",
    "11_policy_documents": "medium",
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def is_empty(value):
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, (list, dict)) and len(value) == 0:
        return True
    return False


def ref(row):
    """Identifying fields for an offending row."""
    return {
        "policy_id": row["policy_id"],
        "parent_policy_name": row["parent_policy_name"],
        "policy_name": row["policy_name"],
        "incentive_name": row["incentive_name"],
    }


def failure(row, field, value, reason):
    out = ref(row) if row is not None else {}
    if isinstance(value, str) and len(value) > 300:
        value = value[:300] + "..."
    out.update({"field": field, "value": value, "reason": reason})
    return out


def walk(obj, path=""):
    """Yield (path, leaf_value) for every leaf in a nested JSON structure."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk(v, f"{path}[{i}]")
    else:
        yield path, obj


def normalise(text):
    """Lowercase, keep only letters/digits, collapse whitespace."""
    return " ".join(re.sub(r"[^0-9a-z]+", " ", (text or "").lower()).split())


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def quantified_benefits(row):
    qbs = (row["incentive_details"] or {}).get("quantified_benefits") or []
    return qbs if isinstance(qbs, list) else []


def result(check, description, denominator, failures, stats=None):
    return {
        "check": check,
        "description": description,
        "severity": SEVERITY[check],
        "denominator": denominator,
        "failure_count": len(failures),
        "failure_rate": round(len(failures) / denominator, 4) if denominator else None,
        "stats": stats or {},
        "failures": failures,
    }


# ── Data loading ───────────────────────────────────────────────────────────────

def load_data(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT policy_id::text, parent_policy_name, policy_name, incentive_name, category,
               applicable_industries, applicable_geographies, applicable_business_sizes,
               start_year, end_year, policy_details, incentive_details,
               search_vector IS NOT NULL AS has_search_vector,
               COALESCE(length(search_vector), 0) AS search_vector_len,
               embedding IS NOT NULL AS has_embedding,
               embedding::text AS embedding_text,
               source_folder, ingested_at, approved
        FROM policies
        ORDER BY parent_policy_name, policy_name, incentive_name
    """)
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    for r in rows:
        r["policy_details"] = r["policy_details"] or {}
        r["incentive_details"] = r["incentive_details"] or {}

    cur.execute("""
        SELECT doc_id::text, parent_policy_name, raw_text, extraction_method, page_count,
               extraction_quality, source_file_paths, created_at
        FROM policy_documents
    """)
    cols = [d[0] for d in cur.description]
    docs = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()
    return rows, docs


# ── Check 1: missing / empty ───────────────────────────────────────────────────

JSON_FIELDS = {
    "policy_details.policy_summary": lambda r: r["policy_details"].get("policy_summary"),
    "policy_details.benefit_headline": lambda r: r["policy_details"].get("benefit_headline"),
    "policy_details.eligibility_criteria.raw_text":
        lambda r: (r["policy_details"].get("eligibility_criteria") or {}).get("raw_text"),
    "policy_details.issuing_authority": lambda r: r["policy_details"].get("issuing_authority"),
    "policy_details.document_type": lambda r: r["policy_details"].get("document_type"),
    "policy_details.keywords": lambda r: r["policy_details"].get("keywords"),
    "policy_details.policy_goals": lambda r: r["policy_details"].get("policy_goals"),
    "incentive_details.description": lambda r: r["incentive_details"].get("description"),
    "incentive_details.benefit_headline": lambda r: r["incentive_details"].get("benefit_headline"),
    "incentive_details.incentive_type": lambda r: r["incentive_details"].get("incentive_type"),
    "incentive_details.quantified_benefits": lambda r: r["incentive_details"].get("quantified_benefits"),
}
# end_year NULL means "open-ended" by schema design, so it is reported but not counted as a failure.
INFORMATIONAL_NULLS = {"end_year"}


def check_missing(rows):
    failures = []
    per_field = {}
    for col in TOP_LEVEL_COLUMNS:
        if col == "search_vector":
            missing = [r for r in rows if not r["has_search_vector"]]
        elif col == "embedding":
            missing = [r for r in rows if not r["has_embedding"]]
        else:
            missing = [r for r in rows if is_empty(r[col])]
        per_field[col] = {"missing": len(missing), "rate": round(len(missing) / len(rows), 4),
                          "informational": col in INFORMATIONAL_NULLS}
        if col not in INFORMATIONAL_NULLS:
            failures += [failure(r, col, None, "NULL/empty") for r in missing]
    for name, getter in JSON_FIELDS.items():
        missing = [r for r in rows if is_empty(getter(r))]
        per_field[name] = {"missing": len(missing), "rate": round(len(missing) / len(rows), 4),
                           "informational": False}
        failures += [failure(r, name, getter(r), "NULL/empty") for r in missing]
    # Inside each quantified benefit: source_text and value_raw are required by the schema.
    qb_total, qb_missing = 0, Counter()
    for r in rows:
        for i, qb in enumerate(quantified_benefits(r)):
            qb_total += 1
            for key in ("source_text", "value_raw", "description"):
                if is_empty(qb.get(key)):
                    qb_missing[key] += 1
                    failures.append(failure(r, f"quantified_benefits[{i}].{key}", qb.get(key), "NULL/empty"))
            if qb.get("value_numeric") is None:
                qb_missing["value_numeric (informational)"] += 1
    stats = {"per_field": per_field, "quantified_benefits_total": qb_total,
             "quantified_benefit_missing": dict(qb_missing),
             "rows_with_any_missing": len({f["policy_id"] for f in failures})}
    return result("1_missing_fields", "NULL/empty top-level columns and key JSON fields (failure = one missing field)",
                  len(rows), failures, stats)


# ── Check 2: NaN / garbage numbers and placeholder strings ─────────────────────

def check_garbage(rows):
    failures = []
    reasons = Counter()

    def flag(row, field, value, reason):
        reasons[reason] += 1
        failures.append(failure(row, field, value, reason))

    text_cols = ["parent_policy_name", "policy_name", "incentive_name", "category", "source_folder"]
    array_cols = ["applicable_industries", "applicable_geographies", "applicable_business_sizes"]
    for r in rows:
        leaves = [(c, r[c]) for c in text_cols]
        for c in array_cols:
            leaves += [(f"{c}[{i}]", v) for i, v in enumerate(r[c] or [])]
        leaves += [("policy_details." + p, v) for p, v in walk(r["policy_details"])]
        leaves += [("incentive_details." + p, v) for p, v in walk(r["incentive_details"])]

        for path, v in leaves:
            if isinstance(v, str):
                if v.strip().lower() in GARBAGE_STRINGS:
                    flag(r, path, v, "placeholder string (NaN/None/null/N/A)")
                elif re.fullmatch(r"\s*-?\d{16,}(\.\d+)?\s*", v):
                    flag(r, path, v, "runaway number in string (>15 digits)")
            elif is_number(v):
                if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                    flag(r, path, v, "NaN/Infinity")
                elif abs(v) >= 1e15:
                    flag(r, path, v, "runaway number (>15 digits)")
                elif v < 0:
                    flag(r, path, v, "negative number")

        for i, qb in enumerate(quantified_benefits(r)):
            for num_key, unit_key in (("value_numeric", "value_unit"), ("cap_numeric", "cap_unit")):
                v, unit = qb.get(num_key), str(qb.get(unit_key) or "").lower()
                if is_number(v) and ("%" in unit or "percent" in unit) and not (0 <= v <= 100):
                    flag(r, f"quantified_benefits[{i}].{num_key}", v, f"percentage outside 0-100 (unit={unit})")
                # absolute rupee amounts above 1 lakh crore are implausible for a single benefit
                if is_number(v) and ("absolute" in unit or unit in {"inr", "rs", "rupees", "₹"}) and v > 1e12:
                    flag(r, f"quantified_benefits[{i}].{num_key}", v, "implausible absolute INR amount (> 1e12)")
                if is_number(v) and ("crore" in unit) and v > 1e5:
                    flag(r, f"quantified_benefits[{i}].{num_key}", v, "implausible crore amount (> 1 lakh crore)")
                if is_number(v) and ("lakh" in unit) and v > 1e7:
                    flag(r, f"quantified_benefits[{i}].{num_key}", v, "implausible lakh amount (> 1 lakh crore)")
    return result("2_garbage_numbers_and_strings",
                  "Placeholder strings, NaN/Inf, runaway (>15 digit) numbers, negatives, bad percentages/amounts",
                  len(rows), failures, {"by_reason": dict(reasons)})


# ── Check 3: digits where text is expected ─────────────────────────────────────

def looks_non_textual(s):
    s = s.strip()
    if len(s) < 3:
        return "too short (< 3 chars)"
    letters = sum(ch.isalpha() for ch in s)
    if letters == 0:
        return "no letters (purely numeric/punctuation)"
    # codes like 'AS9100' or 'MDR 2017' are fine; flag only strings with almost no letters
    if letters < 2 and letters / len(s) < 0.4:
        return f"mostly digits/punctuation ({letters}/{len(s)} letters)"
    return None


def check_digits_in_text(rows):
    failures = []
    reasons = Counter()
    for r in rows:
        fields = [(c, r[c]) for c in ("parent_policy_name", "policy_name", "incentive_name", "category")]
        for c in ("applicable_industries", "applicable_geographies", "applicable_business_sizes"):
            fields += [(f"{c}[{i}]", v) for i, v in enumerate(r[c] or [])]
        pd, idt = r["policy_details"], r["incentive_details"]
        fields += [
            ("policy_details.policy_summary", pd.get("policy_summary")),
            ("policy_details.benefit_headline", pd.get("benefit_headline")),
            ("policy_details.issuing_authority", pd.get("issuing_authority")),
            ("incentive_details.benefit_headline", idt.get("benefit_headline")),
            ("incentive_details.description", idt.get("description")),
            ("policy_details.eligibility_criteria.raw_text",
             (pd.get("eligibility_criteria") or {}).get("raw_text")),
        ]
        fields += [(f"policy_details.keywords[{i}]", k) for i, k in enumerate(pd.get("keywords") or [])]
        for path, v in fields:
            if not isinstance(v, str) or not v.strip():
                continue  # missing is check 1
            reason = looks_non_textual(v)
            # Short-but-valid tags such as size 'All' or keyword 'IT' are not text failures.
            if reason and reason.startswith("too short") and (v in SIZES or v.isupper()):
                continue
            if reason:
                reasons[reason.split(" (")[0]] += 1
                failures.append(failure(r, path, v, reason))
    return result("3_digits_where_text_expected",
                  "Text fields that are numeric, mostly digits/punctuation, or < 3 chars",
                  len(rows), failures, {"by_reason": dict(reasons)})


# ── Check 4: text where numbers are expected ───────────────────────────────────

def check_text_in_numbers(rows):
    failures = []
    checked = 0
    for r in rows:
        for i, qb in enumerate(quantified_benefits(r)):
            for key in ("value_numeric", "cap_numeric"):
                v = qb.get(key)
                if v is None:
                    continue
                checked += 1
                if not is_number(v):
                    failures.append(failure(r, f"quantified_benefits[{i}].{key}", v,
                                            f"non-numeric ({type(v).__name__})"))
        elig = r["policy_details"].get("eligibility_criteria") or {}
        for key in ("minimum_investment", "maximum_investment", "maximum_turnover"):
            amount = ((elig.get(key) or {}).get("amount") or {}).get("value")
            if amount is not None:
                checked += 1
                if not is_number(amount):
                    failures.append(failure(r, f"eligibility_criteria.{key}.amount.value", amount, "non-numeric"))
        emp = (elig.get("minimum_employees") or {}).get("value")
        if emp is not None:
            checked += 1
            if not is_number(emp):
                failures.append(failure(r, "eligibility_criteria.minimum_employees.value", emp, "non-numeric"))
    return result("4_text_where_number_expected",
                  "value_numeric / cap_numeric / eligibility threshold values that are not numbers",
                  checked, failures)


# ── Check 5: year sanity ───────────────────────────────────────────────────────

def year_hint(value):
    """Explain the common corruption patterns seen in bad year values."""
    s = str(value)
    if len(s) == 8 and 1950 <= int(s[:4]) <= 2100 and 1950 <= int(s[4:]) <= 2100:
        return " [looks like start+end concatenated, e.g. '2019-2024' -> 20192024]"
    if len(s) > 4 and 1950 <= int(s[:4]) <= 2100:
        return f" [valid year {s[:4]} followed by extra digits '{s[4:]}']"
    return ""


def check_years(rows):
    failures = []
    null_start = null_end = expired = 0
    for r in rows:
        s, e = r["start_year"], r["end_year"]
        if s is None:
            null_start += 1
        elif not 1950 <= s <= 2100:
            failures.append(failure(r, "start_year", s, "start_year outside 1950-2100" + year_hint(s)))
        if e is None:
            null_end += 1
        else:
            if not 1950 <= e <= 2100:
                failures.append(failure(r, "end_year", e, "end_year outside 1950-2100"))
            if e < CURRENT_YEAR:
                expired += 1
        if s is not None and e is not None and s > e:
            failures.append(failure(r, "start_year/end_year", f"{s}-{e}", "start_year > end_year"))
    stats = {"null_start_year": null_start, "null_end_year (open-ended)": null_end,
             f"expired (end_year < {CURRENT_YEAR})": expired,
             "start_year_distribution": dict(sorted(Counter(r["start_year"] for r in rows
                                                            if r["start_year"] is not None).items()))}
    return result("5_year_sanity", "1950 <= start_year <= end_year <= 2100", len(rows), failures, stats)


# ── Check 6: vocabulary conformity ─────────────────────────────────────────────

def check_vocabulary(rows):
    failures = []
    reasons = Counter()
    other = Counter()
    city_tags = Counter()

    def flag(row, field, value, reason):
        reasons[reason] += 1
        failures.append(failure(row, field, value, reason))

    for r in rows:
        if r["category"] not in CATEGORIES:
            flag(r, "category", r["category"], "category not in CategoryTag")
        if r["category"] == "Other":
            other["category"] += 1

        inds = r["applicable_industries"] or []
        for v in inds:
            if v not in INDUSTRIES:
                flag(r, "applicable_industries", v, "industry not in IndustryTag")
        if "Other" in inds:
            other["industry"] += 1
        if "All Sectors" in inds and len(inds) > 1:
            flag(r, "applicable_industries", inds, "'All Sectors' mixed with specific industries")

        sizes = r["applicable_business_sizes"] or []
        for v in sizes:
            if v not in SIZES:
                flag(r, "applicable_business_sizes", v, "size not in BusinessSizeTag")
        if "All" in sizes and len(sizes) > 1:
            flag(r, "applicable_business_sizes", sizes, "'All' mixed with specific sizes")

        for v in r["applicable_geographies"] or []:
            if v in VALID_GEOGRAPHIES:
                continue
            if v in REGIONAL_LABELS:
                flag(r, "applicable_geographies", v, "regional label (not a state/UT)")
            else:
                city_tags[v] += 1
                flag(r, "applicable_geographies", v,
                     "not a state/UT/National (likely city/district tag; breaks state ILIKE filter)")

        it = r["incentive_details"].get("incentive_type")
        if it not in INCENTIVE_TYPES:
            flag(r, "incentive_details.incentive_type", it, "incentive_type not in IncentiveTypeTag")
        if it == "Other":
            other["incentive_type"] += 1

        dt = r["policy_details"].get("document_type")
        if dt not in DOCUMENT_TYPES:
            flag(r, "policy_details.document_type", dt, "document_type not in DocumentTypeTag")

        for i, qb in enumerate(quantified_benefits(r)):
            bt = qb.get("benefit_type")
            if bt not in BENEFIT_TYPES:
                flag(r, f"quantified_benefits[{i}].benefit_type", bt, "benefit_type not in allowed set")
            if bt == "other":
                other["benefit_type"] += 1

        elig = r["policy_details"].get("eligibility_criteria") or {}
        for v in elig.get("enterprise_type") or []:
            if v not in ENTERPRISE_TYPES:
                flag(r, "eligibility_criteria.enterprise_type", v, "enterprise_type not in allowed set")
        for key in ("minimum_investment", "maximum_investment", "maximum_turnover"):
            unit = ((elig.get(key) or {}).get("amount") or {}).get("unit")
            if elig.get(key) and unit not in MONEY_UNITS:
                flag(r, f"eligibility_criteria.{key}.amount.unit", unit, "money unit not in allowed set")

    n = len(rows)
    stats = {
        "by_reason": dict(reasons),
        "other_rate": {k: round(v / n, 4) for k, v in other.items()},
        "other_counts": dict(other),
        "non_state_geography_tags": dict(city_tags.most_common()),
        "category_distribution": dict(Counter(r["category"] for r in rows).most_common()),
        "incentive_type_distribution": dict(Counter(r["incentive_details"].get("incentive_type")
                                                    for r in rows).most_common()),
    }
    return result("6_vocabulary_conformity",
                  "Enum values outside the Literal sets, non-state geographies, contradictory 'All' tags",
                  n, failures, stats)


# ── Check 7: duplicates ────────────────────────────────────────────────────────

def check_duplicates(rows):
    failures = []
    groups = defaultdict(list)
    for r in rows:
        key = tuple((r[c] or "").strip().lower() for c in ("parent_policy_name", "policy_name", "incentive_name"))
        groups[key].append(r)
    for key, members in groups.items():
        if len(members) > 1:
            for r in members[1:]:
                failures.append(failure(r, "(parent, policy, incentive)", " | ".join(key),
                                        f"duplicate of policy_id {members[0]['policy_id']} ({len(members)} copies)"))
    per_parent = Counter(r["parent_policy_name"] for r in rows)
    sizes = sorted(per_parent.values())
    stats = {
        "duplicate_groups": sum(1 for m in groups.values() if len(m) > 1),
        "parents": len(per_parent),
        "parents_with_single_row": sorted(p for p, c in per_parent.items() if c == 1),
        "incentives_per_parent": {"min": sizes[0], "median": sizes[len(sizes) // 2], "max": sizes[-1],
                                  "mean": round(sum(sizes) / len(sizes), 1)},
        "largest_parents": dict(per_parent.most_common(5)),
    }
    return result("7_duplicates", "Identical (parent_policy_name, policy_name, incentive_name) rows",
                  len(rows), failures, stats)


# ── Check 8: embedding and search_vector ───────────────────────────────────────

def check_vectors(rows):
    failures = []
    dims = Counter()
    for r in rows:
        if not r["has_embedding"]:
            failures.append(failure(r, "embedding", None, "NULL embedding"))
        else:
            vec = [float(x) for x in r["embedding_text"].strip("[]").split(",")]
            dims[len(vec)] += 1
            norm = math.sqrt(sum(x * x for x in vec))
            if len(vec) != EXPECTED_EMBED_DIM:
                failures.append(failure(r, "embedding", len(vec), f"wrong dimension (expected {EXPECTED_EMBED_DIM})"))
            if norm == 0:
                failures.append(failure(r, "embedding", 0.0, "zero vector"))
            elif abs(norm - 1) > 0.01:
                failures.append(failure(r, "embedding", round(norm, 4), "not unit-normalised (bge is normalised)"))
            if any(math.isnan(x) for x in vec):
                failures.append(failure(r, "embedding", "NaN", "NaN in embedding"))
        if not r["has_search_vector"]:
            failures.append(failure(r, "search_vector", None, "NULL search_vector"))
        elif r["search_vector_len"] == 0:
            failures.append(failure(r, "search_vector", 0, "empty search_vector (0 lexemes)"))
    # identical embeddings usually mean the same text was embedded twice
    seen = defaultdict(list)
    for r in rows:
        if r["has_embedding"]:
            seen[r["embedding_text"]].append(r)
    identical = [m for m in seen.values() if len(m) > 1]
    for members in identical:
        for r in members[1:]:
            failures.append(failure(r, "embedding", None,
                                    f"identical embedding to sibling {members[0]['incentive_name']!r} "
                                    f"({members[0]['policy_id']}); incentive-specific text likely truncated "
                                    f"away by the 512-token model limit"))
    lex = sorted(r["search_vector_len"] for r in rows)
    stats = {"dimension_distribution": dict(dims), "identical_embedding_groups": len(identical),
             "search_vector_lexemes": {"min": lex[0], "median": lex[len(lex) // 2], "max": lex[-1]}}
    return result("8_embedding_and_search_vector", "NULL/wrong-dim/zero/non-normalised embeddings, empty search_vector",
                  len(rows), failures, stats)


# ── Check 9: source-text faithfulness ──────────────────────────────────────────

def fuzzy_partial_ratio(needle, haystack, shingle=5, max_candidates=30):
    """Approximate partial ratio: align `needle` against `haystack` at positions where a
    word 5-gram of the needle occurs, then score with difflib. Both inputs pre-normalised."""
    words = needle.split()
    if len(words) < shingle:
        shingle = max(1, len(words))
    starts = set()
    for i in range(0, len(words) - shingle + 1):
        gram = " ".join(words[i:i + shingle])
        offset = len(" ".join(words[:i])) + (1 if i else 0)
        pos = haystack.find(gram)
        while pos != -1 and len(starts) < max_candidates:
            starts.add(max(0, pos - offset))
            pos = haystack.find(gram, pos + 1)
        if len(starts) >= max_candidates:
            break
    best = 0.0
    for s in starts:
        window = haystack[s:s + len(needle)]
        sm = SequenceMatcher(None, needle, window, autojunk=False)
        if sm.real_quick_ratio() <= best or sm.quick_ratio() <= best:
            continue  # cheap upper bounds: this window cannot beat the current best
        best = max(best, sm.ratio())
        if best >= 0.999:
            break
    return best


def sentence_coverage(text, haystack):
    """Share of the text's sentences (>= 4 words) that appear verbatim in the document.
    High coverage + low overall ratio means the model stitched real sentences together;
    low coverage means paraphrase or invention."""
    sentences = [normalise(s) for s in re.split(r"[.;\n]|\s[a-z0-9ivx]{1,3}\)\s", text)]
    sentences = [s for s in sentences if len(s.split()) >= 4]
    if not sentences:
        return 0.0
    return sum(1 for s in sentences if s in haystack) / len(sentences)


def check_faithfulness(rows, docs):
    doc_text = defaultdict(str)
    doc_quality = {}
    for d in docs:
        doc_text[d["parent_policy_name"]] += " " + normalise(d["raw_text"])
        doc_quality[d["parent_policy_name"]] = d["extraction_quality"]

    failures = []
    counts = Counter()
    cache = {}
    for r in rows:
        targets = []
        elig = (r["policy_details"].get("eligibility_criteria") or {}).get("raw_text")
        if elig:
            targets.append(("eligibility_criteria.raw_text", elig))
        for i, qb in enumerate(quantified_benefits(r)):
            if qb.get("source_text"):
                targets.append((f"quantified_benefits[{i}].source_text", qb["source_text"]))

        haystack = doc_text.get(r["parent_policy_name"], "").strip()
        for field, text in targets:
            kind = "eligibility" if field.startswith("elig") else "source_text"
            counts[f"{kind}_checked"] += 1
            if not haystack:
                counts[f"{kind}_unverifiable_no_doc_text"] += 1
                continue
            needle = normalise(text)
            key = (r["parent_policy_name"], needle)
            if key not in cache:
                if needle in haystack:
                    cache[key] = 1.0
                else:
                    cache[key] = fuzzy_partial_ratio(needle, haystack)
            score = cache[key]
            if score == 1.0:
                counts[f"{kind}_exact"] += 1
            elif score >= FUZZY_THRESHOLD:
                counts[f"{kind}_fuzzy"] += 1
            else:
                counts[f"{kind}_not_found"] += 1
                coverage = sentence_coverage(text, haystack)
                if coverage >= 0.8:
                    counts[f"{kind}_not_found_but_stitched_from_verbatim_sentences"] += 1
                f = failure(r, field, text, f"not found in policy_documents.raw_text (best ratio {score:.2f}, "
                                            f"{coverage:.0%} of sentences verbatim)")
                f["best_ratio"] = round(score, 3)
                f["sentence_coverage"] = round(coverage, 3)
                f["doc_extraction_quality"] = doc_quality.get(r["parent_policy_name"])
                failures.append(f)
    verifiable = sum(counts[f"{k}_checked"] - counts[f"{k}_unverifiable_no_doc_text"]
                     for k in ("eligibility", "source_text"))
    stats = dict(counts)
    for k in ("eligibility", "source_text"):
        v = counts[f"{k}_checked"] - counts[f"{k}_unverifiable_no_doc_text"]
        stats[f"{k}_not_found_rate"] = round(counts[f"{k}_not_found"] / v, 4) if v else None
    # Eligibility raw_text is expected to repeat across incentives of one policy, so also
    # report the number of distinct texts not found.
    stats["distinct_texts_not_found"] = len({(f["parent_policy_name"], f["value"]) for f in failures})
    return result("9_source_text_faithfulness",
                  f"source_text / eligibility raw_text present in the source document (exact or fuzzy >= {FUZZY_THRESHOLD:.0%})",
                  verifiable, failures, stats)


# ── Check 10: value <-> source consistency ─────────────────────────────────────

def numbers_in(text):
    text = re.sub(r"(?<=\d),(?=\d)", "", text or "")  # 1,00,000 -> 100000
    return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", text)]


def value_matches(value, numbers):
    for n in numbers:
        for factor in (1, 1e3, 1e5, 1e7, 1e-5, 1e-7, 1e2):  # same, thousand, lakh, crore (and reverse)
            if math.isclose(value, n * factor, rel_tol=1e-6, abs_tol=1e-9):
                return True
    return False


def check_value_consistency(rows):
    failures = []
    checked = 0
    for r in rows:
        for i, qb in enumerate(quantified_benefits(r)):
            for num_key, raw_keys in (("value_numeric", ("value_raw", "source_text")),
                                      ("cap_numeric", ("cap_raw", "source_text", "value_raw"))):
                v = qb.get(num_key)
                if not is_number(v):
                    continue
                checked += 1
                text = " ".join(str(qb.get(k) or "") for k in raw_keys)
                if not value_matches(float(v), numbers_in(text)):
                    failures.append(failure(r, f"quantified_benefits[{i}].{num_key}", v,
                                            f"number not found in {'/'.join(raw_keys)}: {text[:200]!r}"))
    return result("10_value_source_consistency",
                  "value_numeric/cap_numeric appear in value_raw/cap_raw/source_text (allowing lakh/crore/thousand scaling)",
                  checked, failures)


# ── Check 11: policy_documents ─────────────────────────────────────────────────

def check_documents(rows, docs):
    failures = []
    doc_parents = {d["parent_policy_name"] for d in docs}
    row_parents = {r["parent_policy_name"] for r in rows}
    for d in docs:
        base = {"doc_id": d["doc_id"], "parent_policy_name": d["parent_policy_name"]}
        text = d["raw_text"] or ""
        if not text.strip():
            failures.append({**base, "field": "raw_text", "value": len(text), "reason": "empty raw_text"})
        elif d["page_count"] and len(text) / d["page_count"] < 200:
            failures.append({**base, "field": "raw_text", "value": round(len(text) / d["page_count"]),
                             "reason": "< 200 chars per page (likely scanned/partial)"})
        if d["extraction_quality"] != "full":
            failures.append({**base, "field": "extraction_quality", "value": d["extraction_quality"],
                             "reason": "extraction_quality is not full"})
        if not d["page_count"]:
            failures.append({**base, "field": "page_count", "value": d["page_count"], "reason": "NULL/0 page_count"})
        if d["parent_policy_name"] not in row_parents:
            failures.append({**base, "field": "parent_policy_name", "value": d["parent_policy_name"],
                             "reason": "document has no rows in policies"})
    for p in sorted(row_parents - doc_parents):
        n = sum(1 for r in rows if r["parent_policy_name"] == p)
        failures.append({"doc_id": None, "parent_policy_name": p, "field": "parent_policy_name",
                         "value": p, "reason": f"policies parent ({n} rows) has no policy_documents row"})
    lengths = sorted(len(d["raw_text"] or "") for d in docs)
    stats = {
        "documents": len(docs),
        "extraction_quality_distribution": dict(Counter(d["extraction_quality"] for d in docs)),
        "extraction_method_distribution": dict(Counter(d["extraction_method"] for d in docs)),
        "raw_text_chars": {"min": lengths[0], "median": lengths[len(lengths) // 2], "max": lengths[-1]},
        "policy_rows_backed_by_non_full_docs": sum(
            1 for r in rows
            if {d["parent_policy_name"]: d["extraction_quality"] for d in docs}.get(r["parent_policy_name"]) != "full"),
    }
    return result("11_policy_documents", "Document text quality and parent linkage between tables",
                  len(docs), failures, stats)


# ── Reporting ──────────────────────────────────────────────────────────────────

FIX_HINTS = {
    "1_missing_fields": "Reject/retry extractions with empty required fields before insert (raw_text, source_text, headline).",
    "2_garbage_numbers_and_strings": "Add a post-parse validator: abs(value) < 1e12, percentages 0-100, no 'NaN'/'None' strings; coerce placeholders to NULL.",
    "3_digits_where_text_expected": "Validate names/tags have letters and >= 3 chars; drop numeric-only keywords/tags.",
    "4_text_where_number_expected": "Coerce value_numeric/cap_numeric with a strict float parser; set NULL on failure instead of storing text.",
    "5_year_sanity": "Clamp/validate years in the Pydantic model (1950-2100, start <= end); typos like 20044 should fail validation and trigger a retry.",
    "6_vocabulary_conformity": "Map city/district tags to their state (Bengaluru -> Karnataka) or store them in a separate field; reduce 'Other'; drop 'All' when specific tags present.",
    "7_duplicates": "Dedupe on (parent, policy, incentive) before insert; use an ON CONFLICT upsert key.",
    "8_embedding_and_search_vector": "Fail the insert if embedding is NULL/wrong-dim/zero; rebuild search_vector for empty rows.",
    "9_source_text_faithfulness": "Post-check source_text/raw_text against the PDF text; retry or flag for review when not found (likely paraphrase or hallucination).",
    "10_value_source_consistency": "Verify value_numeric is parseable from value_raw; when not, set NULL or route to the review queue.",
    "11_policy_documents": "Add OCR fallback for 'partial'/'empty' PDFs; keep policies and policy_documents parents in sync.",
}


def write_report(results, json_path, md_path, row_count):
    lines = [
        "# Ingestion data-quality report",
        "",
        f"Generated {datetime.now():%Y-%m-%d %H:%M} by `evals/ingestion_checks.py` (read-only, no LLM calls). "
        f"Full findings: `{json_path.name}`.",
        "",
        f"`policies` rows audited: {row_count}.",
        "",
        "## Headline",
        "",
        "| Check | Failures | Denominator | Rate | Severity |",
        "|---|---:|---:|---:|---|",
    ]
    for res in results:
        rate = f"{res['failure_rate']:.1%}" if res["failure_rate"] is not None else "n/a"
        sev = res["severity"] if res["failure_count"] else "ok"
        lines.append(f"| {res['check']} | {res['failure_count']} | {res['denominator']} | {rate} | {sev} |")
    lines.append("")

    lines += ["## Details and top offenders", ""]
    for res in results:
        lines += [f"### {res['check']}", "", res["description"], ""]
        stats = {k: v for k, v in res["stats"].items() if k != "per_field"}
        if stats:
            lines += ["```json", json.dumps(stats, indent=1, ensure_ascii=False, default=str)[:2500], "```", ""]
        if "per_field" in res["stats"]:
            lines += ["| Field | Missing | Rate |", "|---|---:|---:|"]
            for f, s in res["stats"]["per_field"].items():
                if s["missing"]:
                    note = " (informational: NULL = open-ended)" if s["informational"] else ""
                    lines.append(f"| {f}{note} | {s['missing']} | {s['rate']:.1%} |")
            lines.append("")
        if res["failures"]:
            # group reasons by their generic prefix (drop per-row details in brackets/quotes)
            by_reason = Counter(re.split(r" \(| \[|: | '| policy_id", f["reason"])[0] for f in res["failures"])
            lines.append("Failure reasons: " + "; ".join(f"{r} = {c}" for r, c in by_reason.most_common(8)))
            lines.append("")
            lines += ["| Parent | Incentive | Field | Value | Reason |", "|---|---|---|---|---|"]
            for f in res["failures"][:MAX_EXAMPLES_IN_REPORT]:
                val = str(f.get("value"))[:120].replace("|", "/").replace("\n", " ")
                reason = str(f["reason"])[:140].replace("|", "/").replace("\n", " ")
                lines.append(f"| {f.get('parent_policy_name')} | {f.get('incentive_name', '')} | "
                             f"{f.get('field')} | {val} | {reason} |")
            lines.append("")

    lines += ["## What to fix in ingestion", ""]
    ranked = sorted((r for r in results if r["failure_count"]),
                    key=lambda r: ({"high": 0, "medium": 1, "low": 2}[r["severity"]], -(r["failure_rate"] or 0)))
    for res in ranked:
        lines.append(f"- **{res['check']}** ({res['failure_count']} failures): {FIX_HINTS[res['check']]}")
    lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")


def main():
    conn = get_connection()
    conn.set_session(readonly=True)
    try:
        rows, docs = load_data(conn)
    finally:
        conn.close()

    results = [
        check_missing(rows),
        check_garbage(rows),
        check_digits_in_text(rows),
        check_text_in_numbers(rows),
        check_years(rows),
        check_vocabulary(rows),
        check_duplicates(rows),
        check_vectors(rows),
        check_faithfulness(rows, docs),
        check_value_consistency(rows),
        check_documents(rows, docs),
    ]

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = RESULTS_DIR / f"ingestion_checks_{stamp}.json"
    md_path = RESULTS_DIR / "ingestion_report.md"
    payload = {"generated_at": datetime.now().isoformat(), "policies_rows": len(rows),
               "policy_documents_rows": len(docs), "checks": results}
    json_path.write_text(json.dumps(payload, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    write_report(results, json_path, md_path, len(rows))

    for res in results:
        rate = f"{res['failure_rate']:.1%}" if res["failure_rate"] is not None else "n/a"
        print(f"{res['check']:<34} {res['failure_count']:>5} / {res['denominator']:<5} ({rate})")
    print(f"\nWrote {json_path}\nWrote {md_path}")


if __name__ == "__main__":
    main()
