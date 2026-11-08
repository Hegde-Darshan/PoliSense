"""
Eligibility checker for policy retrieval results.

Performs a hybrid check:
  - Structured numeric / enum fields (investment, employees, turnover, enterprise_type)
    are evaluated with rule-based logic.
  - Free-text fields (location_requirements, registration_requirements, exclusions, etc.)
    are assessed by a single Gemini call per policy using eligibility_criteria.raw_text
    as the authoritative source.

Public API:
    check_eligibility(policy_result, company_profile) -> dict
"""

import json
import logging
from typing import Optional, List, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ── Output schema ──────────────────────────────────────────────────────────────

class CriteriaCheck(BaseModel):
    field: str = Field(description="Name of the eligibility criterion")
    criteria_description: str = Field(description="What the policy requires")
    company_value: Optional[str] = Field(default=None, description="What the company has")
    status: Literal["MET", "NOT_MET", "UNCERTAIN"]
    gap: Optional[str] = Field(default=None, description="For NOT_MET: description of the shortfall")
    recommendation: Optional[str] = Field(default=None, description="How to close the gap or what additional info is needed")


class EligibilityCheckResult(BaseModel):
    criteria_checks: List[CriteriaCheck] = Field(default_factory=list)
    overall_eligibility: Literal["ELIGIBLE", "PARTIALLY_ELIGIBLE", "NOT_ELIGIBLE"]
    missing_profile_fields: List[str] = Field(
        default_factory=list,
        description="Profile fields that, if provided, would improve this assessment",
    )


# ── Unit helpers ───────────────────────────────────────────────────────────────

def _to_lakhs(monetary_value: dict) -> Optional[float]:
    """Convert a MonetaryValue dict {value, unit} to lakhs INR."""
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
    return float(val)  # already lakhs


def _fmt_lakhs(lakhs: float) -> str:
    if lakhs >= 100:
        return f"₹{lakhs / 100:.2f} crores"
    return f"₹{lakhs:.2f} lakhs"


# ── Rule-based structured checks ───────────────────────────────────────────────

def _rule_based_checks(ec: dict, profile: dict) -> tuple[list, list]:
    """
    Evaluate structured numeric/enum fields against company profile.
    Returns (checks: List[CriteriaCheck], missing_fields: List[str]).
    """
    checks: list[CriteriaCheck] = []
    missing: list[str] = []

    # ── enterprise_type ────────────────────────────────────────────────────────
    criteria_et = ec.get("enterprise_type")
    if criteria_et:
        company_et = profile.get("enterprise_type")
        desc = f"Business unit type: {', '.join(criteria_et)}"
        if not company_et:
            missing.append("enterprise_type")
            checks.append(CriteriaCheck(
                field="enterprise_type",
                criteria_description=desc,
                status="UNCERTAIN",
                recommendation="Provide enterprise type (New / Existing / Expansion) to verify",
            ))
        elif "Any" in criteria_et or company_et in criteria_et:
            checks.append(CriteriaCheck(
                field="enterprise_type",
                criteria_description=desc,
                company_value=company_et,
                status="MET",
            ))
        else:
            checks.append(CriteriaCheck(
                field="enterprise_type",
                criteria_description=desc,
                company_value=company_et,
                status="NOT_MET",
                gap=f"Policy requires {' or '.join(criteria_et)}; company is {company_et}",
                recommendation=f"This scheme is available only to {' or '.join(criteria_et)} enterprises",
            ))

    # ── minimum_investment ─────────────────────────────────────────────────────
    min_inv = ec.get("minimum_investment")
    if min_inv and isinstance(min_inv, dict):
        amount_dict = min_inv.get("amount") or {}
        min_lakhs = _to_lakhs(amount_dict)
        company_inv = profile.get("investment_amount_lakhs")
        desc = f"Minimum investment: ₹{amount_dict.get('value')} {amount_dict.get('unit', 'lakhs')}"
        if min_lakhs is not None:
            if company_inv is None:
                missing.append("investment_amount_lakhs")
                checks.append(CriteriaCheck(
                    field="minimum_investment",
                    criteria_description=desc,
                    status="UNCERTAIN",
                    recommendation="Provide investment amount to verify this threshold",
                ))
            elif float(company_inv) >= min_lakhs:
                checks.append(CriteriaCheck(
                    field="minimum_investment",
                    criteria_description=desc,
                    company_value=_fmt_lakhs(float(company_inv)),
                    status="MET",
                ))
            else:
                shortfall = min_lakhs - float(company_inv)
                checks.append(CriteriaCheck(
                    field="minimum_investment",
                    criteria_description=desc,
                    company_value=_fmt_lakhs(float(company_inv)),
                    status="NOT_MET",
                    gap=(
                        f"Investment is {_fmt_lakhs(float(company_inv))}; "
                        f"minimum required is {_fmt_lakhs(min_lakhs)} "
                        f"(shortfall: {_fmt_lakhs(shortfall)})"
                    ),
                    recommendation=f"Increase investment to at least {_fmt_lakhs(min_lakhs)} to qualify",
                ))

    # ── maximum_investment ─────────────────────────────────────────────────────
    max_inv = ec.get("maximum_investment")
    if max_inv and isinstance(max_inv, dict):
        amount_dict = max_inv.get("amount") or {}
        max_lakhs = _to_lakhs(amount_dict)
        company_inv = profile.get("investment_amount_lakhs")
        desc = f"Maximum investment cap: ₹{amount_dict.get('value')} {amount_dict.get('unit', 'lakhs')}"
        if max_lakhs is not None:
            if company_inv is None:
                missing.append("investment_amount_lakhs")
                checks.append(CriteriaCheck(
                    field="maximum_investment",
                    criteria_description=desc,
                    status="UNCERTAIN",
                    recommendation="Provide investment amount to verify this cap",
                ))
            elif float(company_inv) <= max_lakhs:
                checks.append(CriteriaCheck(
                    field="maximum_investment",
                    criteria_description=desc,
                    company_value=_fmt_lakhs(float(company_inv)),
                    status="MET",
                ))
            else:
                excess = float(company_inv) - max_lakhs
                checks.append(CriteriaCheck(
                    field="maximum_investment",
                    criteria_description=desc,
                    company_value=_fmt_lakhs(float(company_inv)),
                    status="NOT_MET",
                    gap=(
                        f"Investment of {_fmt_lakhs(float(company_inv))} exceeds cap "
                        f"of {_fmt_lakhs(max_lakhs)} by {_fmt_lakhs(excess)}"
                    ),
                    recommendation="This scheme targets smaller investments; your investment may exceed the eligible cap",
                ))

    # ── minimum_employees ─────────────────────────────────────────────────────
    min_emp = ec.get("minimum_employees")
    if min_emp and isinstance(min_emp, dict):
        min_count = min_emp.get("value")
        unit = min_emp.get("unit", "employees")
        company_emp = profile.get("employee_count")
        desc = f"Minimum {unit}: {int(min_count) if min_count else '?'}"
        if min_count is not None:
            if company_emp is None:
                missing.append("employee_count")
                checks.append(CriteriaCheck(
                    field="minimum_employees",
                    criteria_description=desc,
                    status="UNCERTAIN",
                    recommendation="Provide employee count to verify this threshold",
                ))
            elif int(company_emp) >= int(min_count):
                checks.append(CriteriaCheck(
                    field="minimum_employees",
                    criteria_description=desc,
                    company_value=f"{company_emp} {unit}",
                    status="MET",
                ))
            else:
                checks.append(CriteriaCheck(
                    field="minimum_employees",
                    criteria_description=desc,
                    company_value=f"{company_emp} {unit}",
                    status="NOT_MET",
                    gap=f"Company has {company_emp} {unit}; minimum required is {int(min_count)}",
                    recommendation=f"Increase employment to at least {int(min_count)} {unit} to qualify",
                ))

    # ── maximum_turnover ───────────────────────────────────────────────────────
    max_turn = ec.get("maximum_turnover")
    if max_turn and isinstance(max_turn, dict):
        amount_dict = max_turn.get("amount") or {}
        max_lakhs = _to_lakhs(amount_dict)
        company_turn = profile.get("annual_turnover_lakhs")
        desc = f"Maximum annual turnover: ₹{amount_dict.get('value')} {amount_dict.get('unit', 'lakhs')}"
        if max_lakhs is not None:
            if company_turn is None:
                missing.append("annual_turnover_lakhs")
                checks.append(CriteriaCheck(
                    field="maximum_turnover",
                    criteria_description=desc,
                    status="UNCERTAIN",
                    recommendation="Provide annual turnover to verify MSME size eligibility",
                ))
            elif float(company_turn) <= max_lakhs:
                checks.append(CriteriaCheck(
                    field="maximum_turnover",
                    criteria_description=desc,
                    company_value=_fmt_lakhs(float(company_turn)),
                    status="MET",
                ))
            else:
                checks.append(CriteriaCheck(
                    field="maximum_turnover",
                    criteria_description=desc,
                    company_value=_fmt_lakhs(float(company_turn)),
                    status="NOT_MET",
                    gap=(
                        f"Turnover of {_fmt_lakhs(float(company_turn))} exceeds "
                        f"the cap of {_fmt_lakhs(max_lakhs)}"
                    ),
                    recommendation="This scheme is targeted at smaller businesses; your turnover may exceed the eligibility threshold",
                ))

    return checks, list(set(missing))


# ── LLM schema for free-text checks ───────────────────────────────────────────

class _LLMCriteriaCheck(BaseModel):
    field: str
    criteria_description: str
    company_value: Optional[str] = None
    status: Literal["MET", "NOT_MET", "UNCERTAIN"]
    gap: Optional[str] = None
    recommendation: Optional[str] = None


class _LLMCheckResponse(BaseModel):
    checks: List[_LLMCriteriaCheck] = Field(default_factory=list)
    missing_profile_fields: List[str] = Field(default_factory=list)


_FREE_TEXT_FIELDS = (
    "location_requirements",
    "registration_requirements",
    "special_category_benefits",
    "exclusions",
    "other_requirements",
)


def _llm_based_checks(ec: dict, profile: dict) -> tuple[list, list]:
    """
    Use Gemini Flash to assess free-text eligibility fields.
    Returns (checks: List[CriteriaCheck], missing_fields: List[str]).
    """
    free_text = {k: v for k, v in ec.items() if k in _FREE_TEXT_FIELDS and v}
    if not free_text:
        return [], []

    relevant_profile = {
        k: v for k, v in profile.items()
        if k in (
            "business_name", "industry", "geography", "business_size",
            "enterprise_type", "investment_amount_lakhs", "employee_count",
            "annual_turnover_lakhs", "loan_amount_lakhs", "special_attributes",
            "registration_details", "business_description",
        )
        and v is not None
    }

    prompt = (
        "You are a government scheme eligibility analyst. "
        "Assess whether the company meets the free-text eligibility criteria listed below.\n\n"
        f"Company Profile:\n{json.dumps(relevant_profile, indent=2)}\n\n"
        f"Eligibility criteria to assess (each key is a criterion field):\n"
        f"{json.dumps(free_text, indent=2)}\n\n"
        "Verbatim eligibility section from the policy document (authoritative source):\n"
        f"{ec.get('raw_text', 'Not available')}\n\n"
        "For each criterion field listed above, return one CriteriaCheck with:\n"
        "  - field: the criterion key name\n"
        "  - criteria_description: what the policy requires in plain English\n"
        "  - company_value: what the company has, or null if not in profile\n"
        "  - status: MET / NOT_MET / UNCERTAIN (use UNCERTAIN only when the profile lacks information)\n"
        "  - gap: for NOT_MET only — exact reason the company is disqualified\n"
        "  - recommendation: actionable advice to resolve a NOT_MET or UNCERTAIN condition\n\n"
        "Also list any profile fields that are missing but would help confirm eligibility.\n"
        "Only assess the criteria listed — do not add criteria not in the list."
    )

    from langchain_google_genai import ChatGoogleGenerativeAI
    llm = ChatGoogleGenerativeAI(
        model="gemini-3.8-flash",
        temperature=0,
        max_retries=2,
    ).with_structured_output(
        schema=_LLMCheckResponse.model_json_schema(),
        method="json_schema",
    )

    try:
        resp = llm.invoke(prompt)
        result = _LLMCheckResponse(**resp) if isinstance(resp, dict) else resp
        checks = [
            CriteriaCheck(
                field=c.field,
                criteria_description=c.criteria_description,
                company_value=c.company_value,
                status=c.status,
                gap=c.gap,
                recommendation=c.recommendation,
            )
            for c in result.checks
        ]
        return checks, result.missing_profile_fields
    except Exception as exc:
        logger.warning("LLM eligibility check failed: %s", exc)
        # Graceful fallback: mark every free-text field as UNCERTAIN
        checks = [
            CriteriaCheck(
                field=field,
                criteria_description=str(value)[:300],
                status="UNCERTAIN",
                recommendation="Manual review required — automated check unavailable",
            )
            for field, value in free_text.items()
        ]
        return checks, []


# ── Overall eligibility determination ─────────────────────────────────────────

_HARD_BLOCKERS = {"enterprise_type", "minimum_investment", "maximum_investment", "maximum_turnover"}


def _determine_overall(
    checks: list,
) -> Literal["ELIGIBLE", "PARTIALLY_ELIGIBLE", "NOT_ELIGIBLE"]:
    if not checks:
        return "PARTIALLY_ELIGIBLE"

    statuses = [c.status for c in checks]

    if "NOT_MET" in statuses:
        not_met_fields = {c.field for c in checks if c.status == "NOT_MET"}
        if not_met_fields & _HARD_BLOCKERS:
            return "NOT_ELIGIBLE"
        return "PARTIALLY_ELIGIBLE"

    if all(s == "MET" for s in statuses):
        return "ELIGIBLE"

    return "PARTIALLY_ELIGIBLE"  # mix of MET and UNCERTAIN


# ── Public API ─────────────────────────────────────────────────────────────────

def check_eligibility(policy_result: dict, company_profile: dict) -> dict:
    """
    Check company eligibility for one retrieved policy.

    Args:
        policy_result:   One result dict from retrieve_policies().
        company_profile: Company profile dict (existing + new Q9–Q13 fields).

    Returns:
        Dict form of EligibilityCheckResult with keys:
          criteria_checks, overall_eligibility, missing_profile_fields.
    """
    pd_ = policy_result.get("policy_details") or {}
    ec = pd_.get("eligibility_criteria") or {}

    if not ec:
        return EligibilityCheckResult(
            criteria_checks=[],
            overall_eligibility="PARTIALLY_ELIGIBLE",
            missing_profile_fields=[],
        ).model_dump()

    rule_checks, rule_missing = _rule_based_checks(ec, company_profile)
    llm_checks, llm_missing = _llm_based_checks(ec, company_profile)

    all_checks = rule_checks + llm_checks
    all_missing = list(set(rule_missing + llm_missing))
    overall = _determine_overall(all_checks)

    return EligibilityCheckResult(
        criteria_checks=all_checks,
        overall_eligibility=overall,
        missing_profile_fields=all_missing,
    ).model_dump()
