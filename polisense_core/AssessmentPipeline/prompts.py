"""
LLM prompt templates and model initialisation for Tier-2 analysis.

Both eligibility checking and benefit calculation use Gemini 2.5 Flash
with structured output (JSON schema mode) at temperature=0.
"""

import json
import logging
from typing import Any

from langchain_google_genai import ChatGoogleGenerativeAI

logger = logging.getLogger(__name__)

_FLASH_MODEL = "gemini-2.5-flash"


def make_gemini_flash(schema: dict) -> Any:
    """Return a Gemini Flash LLM bound to a JSON schema for structured output."""
    return ChatGoogleGenerativeAI(
        model=_FLASH_MODEL,
        temperature=0,
        max_retries=2,
    ).with_structured_output(schema=schema, method="json_schema")


# ── Eligibility prompt ─────────────────────────────────────────────────────────

def build_eligibility_prompt(
    free_text_criteria: dict,
    raw_text: str,
    profile: dict,
) -> str:
    """
    Build the system+human prompt for the per-policy eligibility LLM call.
    free_text_criteria: {field_name: value} for non-empty free-text fields only.
    """
    criteria_block = "\n".join(
        f"  - {k}: {v}" for k, v in free_text_criteria.items()
    )
    profile_block = json.dumps(
        {k: v for k, v in profile.items() if v is not None},
        indent=2,
        ensure_ascii=False,
    )
    return (
        "You are a government scheme eligibility analyst for Indian businesses.\n"
        "Evaluate each criterion strictly using the verbatim policy text as the authoritative source.\n"
        "Never infer beyond what is stated. "
        "If the company profile lacks information needed for a criterion, "
        "mark it UNCERTAIN and name the specific missing field.\n\n"
        f"Criteria to evaluate:\n{criteria_block}\n\n"
        f"Verbatim eligibility text from policy document (authoritative):\n{raw_text}\n\n"
        f"Company profile:\n{profile_block}\n\n"
        "For each criterion above, return one check with:\n"
        "  field (the key name), criteria_description (plain English requirement),\n"
        "  company_value (what the company has, or null), "
        "status (MET | NOT_MET | UNCERTAIN),\n"
        "  gap (for NOT_MET: exact reason), "
        "recommendation (actionable advice or missing field name).\n"
        "Only evaluate criteria listed above — do not add others.\n"
        "Also list any profile fields that are absent but would change UNCERTAIN to definitive."
    )


# ── Incentive check + benefit prompt ──────────────────────────────────────────

def build_incentive_prompt(
    incentive_name: str,
    incentive_type: str,
    incentive_specific_eligibility: str | None,
    quantified_benefits: list,
    profile: dict,
) -> str:
    """
    Build the prompt for the per-incentive combined applicability + benefit LLM call.
    """
    profile_block = json.dumps(
        {k: v for k, v in profile.items() if v is not None},
        indent=2,
        ensure_ascii=False,
    )
    benefits_block = json.dumps(quantified_benefits, indent=2, ensure_ascii=False)
    elig_note = (
        f"Incentive-specific eligibility condition: {incentive_specific_eligibility}"
        if incentive_specific_eligibility
        else "Incentive-specific eligibility condition: none stated"
    )
    return (
        "You are a financial analyst specialising in Indian government incentive calculations.\n"
        "Use ONLY the source_text from each benefit slab as the authoritative figure — "
        "do not invent amounts not stated there.\n"
        "Show step-by-step arithmetic. Express all amounts in INR lakhs.\n\n"
        f"Incentive: {incentive_name} ({incentive_type})\n"
        f"{elig_note}\n\n"
        f"Company profile:\n{profile_block}\n\n"
        f"Benefit slabs (each has verbatim source_text from the policy document):\n"
        f"{benefits_block}\n\n"
        "For each slab, return one result with:\n"
        "  slab_description (brief label), value_raw (verbatim from policy), "
        "source_text (copy verbatim),\n"
        "  is_applicable (true/false/null for uncertain),\n"
        "  not_applicable_reason (if false), missing_field (if null),\n"
        "  calculated_amount_lakhs (float, if applicable),\n"
        "  effective_amount_lakhs (after cap, if applicable),\n"
        "  cap_applied (bool), calculation_steps (show the arithmetic),\n"
        "  confidence (HIGH=all inputs known, MEDIUM=estimates used, LOW=key data missing).\n"
        "Return slabs in the same order as the input list."
    )
