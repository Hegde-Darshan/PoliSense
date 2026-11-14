"""
Policy-level eligibility checker for Tier-2.

Evaluates one policy's eligibility_criteria against the company profile.
Two-phase: rule-based for numeric/enum fields, then one Gemini Flash call
for all free-text criteria bundled together.

Public API:
    check_policy_eligibility(policy_details, profile) -> PolicyEligibilityResult
"""

import logging
from typing import Optional

from pydantic import BaseModel, Field

from polisense_core.RetrievalPipeline.models import (
    CriterionCheck,
    PolicyEligibilityResult,
)
from polisense_core.RetrievalPipeline.prompts import build_eligibility_prompt, make_gemini_flash

logger = logging.getLogger(__name__)

# Turnover upper bounds per business_size band (in lakhs INR)
_BAND_UPPER_LAKHS: dict[str, float] = {
    "Micro":   100.0,     # < ₹1 crore
    "Small":   1_000.0,   # < ₹10 crore
    "Medium":  5_000.0,   # < ₹50 crore
    "Large":   25_000.0,  # < ₹250 crore
    "Mega":    float("inf"),
    "Startup": 10_000.0,  # DPIIT: < ₹100 crore (use as conservative upper bound)
    "MSME":    5_000.0,   # treat as Medium upper
}

# Hard-blocker fields — NOT_MET here → NOT_ELIGIBLE (not just PARTIALLY_ELIGIBLE)
_HARD_BLOCKERS = frozenset({
    "enterprise_type",
    "minimum_investment",
    "maximum_investment",
    "maximum_turnover",
})

_FREE_TEXT_FIELDS = (
    "location_requirements",
    "registration_requirements",
    "special_category_benefits",
    "exclusions",
    "other_requirements",
)


# ── LLM output schema ──────────────────────────────────────────────────────────

class _LLMCheck(BaseModel):
    field: str
    criteria_description: str
    company_value: Optional[str] = None
    status: str  # MET | NOT_MET | UNCERTAIN
    gap: Optional[str] = None
    recommendation: Optional[str] = None


class _LLMEligibilityResponse(BaseModel):
    checks: list[_LLMCheck] = Field(default_factory=list)
    missing_profile_fields: list[str] = Field(default_factory=list)


# ── Unit helpers ───────────────────────────────────────────────────────────────

def _to_lakhs(monetary_value: dict) -> Optional[float]:
    """Convert MonetaryValue dict {value, unit} to lakhs INR."""
    if not monetary_value:
        return None
    val = monetary_value.get("value")
    unit = monetary_value.get("unit", "lakhs")
    if val is None:
        return None
    if unit == "crores":
        return float(val) * 100
    if unit == "absolute_INR":
        return float(val) / 100_000
    return float(val)


def _fmt(lakhs: float) -> str:
    if lakhs >= 100:
        return f"₹{lakhs / 100:.2f} crores"
    return f"₹{lakhs:.2f} lakhs"


def _investment_lakhs(profile: dict) -> Optional[float]:
    """Return best available investment figure in lakhs: P&M first, then total project cost."""
    pm = profile.get("investment_pm_lakhs")
    if pm is not None:
        return float(pm)
    tcp = profile.get("total_project_cost_lakhs")
    if tcp is not None:
        return float(tcp)
    return None


# ── Rule-based checks ──────────────────────────────────────────────────────────

def _rule_based_checks(
    ec: dict, profile: dict
) -> tuple[list[CriterionCheck], list[str]]:
    checks: list[CriterionCheck] = []
    missing: list[str] = []

    # ── enterprise_type ────────────────────────────────────────────────────────
    criteria_et = ec.get("enterprise_type")
    if criteria_et:
        company_et = profile.get("enterprise_type")
        desc = f"Enterprise type: {', '.join(criteria_et)}"
        if not company_et:
            missing.append("enterprise_type")
            checks.append(CriterionCheck(
                field="enterprise_type",
                criteria_description=desc,
                status="UNCERTAIN",
                recommendation="Provide enterprise type (New / Existing / Expansion)",
            ))
        elif "Any" in criteria_et or company_et in criteria_et:
            checks.append(CriterionCheck(
                field="enterprise_type",
                criteria_description=desc,
                company_value=company_et,
                status="MET",
            ))
        else:
            checks.append(CriterionCheck(
                field="enterprise_type",
                criteria_description=desc,
                company_value=company_et,
                status="NOT_MET",
                gap=f"Policy requires {' or '.join(criteria_et)}; company is {company_et}",
                recommendation=f"This scheme is only for {' / '.join(criteria_et)} enterprises",
            ))

    # ── minimum_investment ─────────────────────────────────────────────────────
    min_inv = ec.get("minimum_investment")
    if min_inv and isinstance(min_inv, dict):
        amount_dict = min_inv.get("amount") or {}
        min_lakhs = _to_lakhs(amount_dict)
        company_inv = _investment_lakhs(profile)
        inv_source = "P&M investment" if profile.get("investment_pm_lakhs") is not None else "total project cost"
        desc = f"Minimum investment: {_fmt(min_lakhs) if min_lakhs else '?'}"
        if min_lakhs is not None:
            if company_inv is None:
                missing.append("investment_pm_lakhs")
                checks.append(CriterionCheck(
                    field="minimum_investment",
                    criteria_description=desc,
                    status="UNCERTAIN",
                    recommendation="Provide investment in Plant & Machinery (or total project cost)",
                ))
            elif company_inv >= min_lakhs:
                checks.append(CriterionCheck(
                    field="minimum_investment",
                    criteria_description=desc,
                    company_value=f"{_fmt(company_inv)} ({inv_source})",
                    status="MET",
                ))
            else:
                shortfall = min_lakhs - company_inv
                checks.append(CriterionCheck(
                    field="minimum_investment",
                    criteria_description=desc,
                    company_value=f"{_fmt(company_inv)} ({inv_source})",
                    status="NOT_MET",
                    gap=f"{_fmt(company_inv)} is below the minimum of {_fmt(min_lakhs)} (shortfall: {_fmt(shortfall)})",
                    recommendation=f"Investment must reach at least {_fmt(min_lakhs)} to qualify",
                ))

    # ── maximum_investment ─────────────────────────────────────────────────────
    max_inv = ec.get("maximum_investment")
    if max_inv and isinstance(max_inv, dict):
        amount_dict = max_inv.get("amount") or {}
        max_lakhs = _to_lakhs(amount_dict)
        company_inv = _investment_lakhs(profile)
        inv_source = "P&M investment" if profile.get("investment_pm_lakhs") is not None else "total project cost"
        desc = f"Maximum investment cap: {_fmt(max_lakhs) if max_lakhs else '?'}"
        if max_lakhs is not None:
            if company_inv is None:
                missing.append("investment_pm_lakhs")
                checks.append(CriterionCheck(
                    field="maximum_investment",
                    criteria_description=desc,
                    status="UNCERTAIN",
                    recommendation="Provide investment amount to verify this cap",
                ))
            elif company_inv <= max_lakhs:
                checks.append(CriterionCheck(
                    field="maximum_investment",
                    criteria_description=desc,
                    company_value=f"{_fmt(company_inv)} ({inv_source})",
                    status="MET",
                ))
            else:
                excess = company_inv - max_lakhs
                checks.append(CriterionCheck(
                    field="maximum_investment",
                    criteria_description=desc,
                    company_value=f"{_fmt(company_inv)} ({inv_source})",
                    status="NOT_MET",
                    gap=f"Investment of {_fmt(company_inv)} exceeds cap of {_fmt(max_lakhs)} by {_fmt(excess)}",
                    recommendation="This scheme targets smaller investments",
                ))

    # ── minimum_employees ─────────────────────────────────────────────────────
    min_emp = ec.get("minimum_employees")
    if min_emp and isinstance(min_emp, dict):
        min_count = min_emp.get("value")
        unit = min_emp.get("unit", "employees")
        raw = min_emp.get("raw_text")
        # employee_count is never in the form — always UNCERTAIN
        desc = raw if raw else f"Minimum {int(min_count) if min_count else '?'} {unit}"
        if min_count is not None:
            missing.append("employee_count")
            checks.append(CriterionCheck(
                field="minimum_employees",
                criteria_description=desc,
                status="UNCERTAIN",
                recommendation=f"Employee count not collected in form; policy requires at least {int(min_count)} {unit}",
            ))

    # ── maximum_turnover ───────────────────────────────────────────────────────
    max_turn = ec.get("maximum_turnover")
    if max_turn and isinstance(max_turn, dict):
        amount_dict = max_turn.get("amount") or {}
        max_lakhs = _to_lakhs(amount_dict)
        business_size = profile.get("business_size")
        desc = f"Maximum turnover: {_fmt(max_lakhs) if max_lakhs else '?'}"
        if max_lakhs is not None:
            if not business_size or business_size not in _BAND_UPPER_LAKHS:
                missing.append("business_size")
                checks.append(CriterionCheck(
                    field="maximum_turnover",
                    criteria_description=desc,
                    status="UNCERTAIN",
                    recommendation="Provide annual turnover to verify MSME size eligibility",
                ))
            else:
                band_upper = _BAND_UPPER_LAKHS[business_size]
                # Conservative check: if the band's upper bound exceeds the threshold, flag UNCERTAIN
                # (we know company is at most band_upper, so if band_upper <= max: MET for certain)
                if band_upper <= max_lakhs:
                    checks.append(CriterionCheck(
                        field="maximum_turnover",
                        criteria_description=desc,
                        company_value=f"{business_size} (turnover < {_fmt(band_upper)})",
                        status="MET",
                    ))
                else:
                    # Band straddles or exceeds threshold — could be MET or NOT_MET
                    checks.append(CriterionCheck(
                        field="maximum_turnover",
                        criteria_description=desc,
                        company_value=f"{business_size} (turnover up to {_fmt(band_upper)})",
                        status="UNCERTAIN",
                        recommendation=(
                            f"Scheme requires turnover below {_fmt(max_lakhs)}; "
                            f"{business_size} band can include turnovers above this threshold"
                        ),
                    ))

    return checks, list(set(missing))


# ── LLM free-text check ────────────────────────────────────────────────────────

def _llm_checks(
    ec: dict, profile: dict
) -> tuple[list[CriterionCheck], list[str]]:
    free_text = {k: v for k, v in ec.items() if k in _FREE_TEXT_FIELDS and v}
    if not free_text:
        return [], []

    prompt = build_eligibility_prompt(
        free_text_criteria=free_text,
        raw_text=ec.get("raw_text") or "Not available",
        profile=profile,
    )
    llm = make_gemini_flash(_LLMEligibilityResponse.model_json_schema())

    try:
        resp = llm.invoke(prompt)
        result = _LLMEligibilityResponse(**resp) if isinstance(resp, dict) else resp
        checks = [
            CriterionCheck(
                field=c.field,
                criteria_description=c.criteria_description,
                company_value=c.company_value,
                status=c.status if c.status in ("MET", "NOT_MET", "UNCERTAIN") else "UNCERTAIN",
                gap=c.gap,
                recommendation=c.recommendation,
            )
            for c in result.checks
        ]
        return checks, result.missing_profile_fields
    except Exception as exc:
        logger.warning("LLM eligibility check failed: %s", exc)
        return [
            CriterionCheck(
                field=field,
                criteria_description=str(value)[:300],
                status="UNCERTAIN",
                recommendation="Automated check unavailable — manual review required",
            )
            for field, value in free_text.items()
        ], []


# ── Overall eligibility determination ─────────────────────────────────────────

def _determine_overall(checks: list[CriterionCheck]) -> str:
    if not checks:
        return "PARTIALLY_ELIGIBLE"
    statuses = {c.status for c in checks}
    if "NOT_MET" in statuses:
        not_met_fields = {c.field for c in checks if c.status == "NOT_MET"}
        if not_met_fields & _HARD_BLOCKERS:
            return "NOT_ELIGIBLE"
        return "PARTIALLY_ELIGIBLE"
    if statuses == {"MET"}:
        return "ELIGIBLE"
    return "PARTIALLY_ELIGIBLE"  # mix of MET and UNCERTAIN


# ── Public API ─────────────────────────────────────────────────────────────────

def check_policy_eligibility(
    policy_details: dict,
    profile: dict,
) -> PolicyEligibilityResult:
    """
    Check company eligibility for one policy.

    Args:
        policy_details: The policy_details JSONB dict from a policies row.
        profile:        Extended company profile including tier-2 fields.

    Returns:
        PolicyEligibilityResult with overall status and per-criterion breakdown.
    """
    ec = (policy_details or {}).get("eligibility_criteria") or {}

    if not ec:
        return PolicyEligibilityResult(
            overall_eligibility="PARTIALLY_ELIGIBLE",
            criteria_checks=[],
            missing_profile_fields=[],
        )

    rule_checks, rule_missing = _rule_based_checks(ec, profile)
    llm_checks, llm_missing = _llm_checks(ec, profile)

    all_checks = rule_checks + llm_checks
    all_missing = list(set(rule_missing + llm_missing))
    overall = _determine_overall(all_checks)

    return PolicyEligibilityResult(
        overall_eligibility=overall,
        criteria_checks=all_checks,
        missing_profile_fields=all_missing,
    )
