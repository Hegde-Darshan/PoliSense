"""
Benefit quantum calculator for retrieved policy incentives.

For each QuantifiedBenefit in incentive_details.quantified_benefits:
  - Simple benefit types (percentage_subsidy, employment_incentive, fixed_grant,
    fee_waiver, interest_reduction with numeric values) are calculated with
    rule-based arithmetic.
  - Complex slabs, missing value_numeric, or multi-condition structures are
    resolved via a single Gemini Flash call per incentive.

Public API:
    calculate_benefits(incentive_details, company_profile) -> List[dict]
"""

import json
import logging
from typing import Optional, List, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ── Output schema ──────────────────────────────────────────────────────────────

class BenefitCalculation(BaseModel):
    benefit_description: str
    value_raw: str = Field(description="Verbatim value from policy document")
    applicable_to: Optional[str] = None
    calculated_amount: Optional[str] = None
    calculation_steps: Optional[str] = None
    cap_applied: bool = False
    effective_benefit: Optional[str] = None
    conditions: Optional[str] = None
    source_text: str
    confidence: Literal["HIGH", "MEDIUM", "LOW"] = "LOW"
    not_applicable_reason: Optional[str] = None


# ── Unit helpers ───────────────────────────────────────────────────────────────

def _to_lakhs_from_unit(value: float, unit: str) -> float:
    unit_lc = (unit or "").lower()
    if "crore" in unit_lc:
        return value * 100
    if "absolute" in unit_lc or "inr" == unit_lc:
        return value / 100_000
    return value  # already lakhs


def _fmt_lakhs(lakhs: float) -> str:
    if lakhs >= 100:
        return f"₹{lakhs / 100:.2f} crores"
    return f"₹{lakhs:.2f} lakhs"


def _cap_to_lakhs(cap_numeric: Optional[float], cap_unit: Optional[str]) -> Optional[float]:
    if cap_numeric is None:
        return None
    return _to_lakhs_from_unit(cap_numeric, cap_unit or "lakhs INR")


# ── Rule-based calculation ─────────────────────────────────────────────────────

_RULE_ELIGIBLE_TYPES = {
    "percentage_subsidy",
    "employment_incentive",
    "fixed_grant",
    "fee_waiver",
    "interest_reduction",
    "reimbursement",
    "loan",
}


def _rule_calc(qb: dict, profile: dict) -> Optional[BenefitCalculation]:
    """
    Attempt rule-based calculation for a single QuantifiedBenefit.
    Returns None if the benefit type / data cannot be handled by rules.
    """
    benefit_type = qb.get("benefit_type")
    value_numeric = qb.get("value_numeric")
    value_unit = qb.get("value_unit") or ""
    cap_numeric = qb.get("cap_numeric")
    cap_unit = qb.get("cap_unit") or "lakhs INR"
    value_raw = qb.get("value_raw") or ""
    description = qb.get("description") or ""
    applicable_to = qb.get("applicable_to")
    conditions = qb.get("conditions")
    source_text = qb.get("source_text") or ""

    base = dict(
        benefit_description=description,
        value_raw=value_raw,
        applicable_to=applicable_to,
        conditions=conditions,
        source_text=source_text,
    )

    # ── fixed_grant / fee_waiver / loan: return face value as-is ──────────────
    if benefit_type in ("fixed_grant", "fee_waiver", "loan"):
        return BenefitCalculation(
            **base,
            calculated_amount=value_raw,
            calculation_steps="Fixed amount — no calculation required",
            cap_applied=False,
            effective_benefit=value_raw,
            confidence="HIGH",
        )

    if value_numeric is None:
        return None  # cannot proceed without numeric value

    # ── percentage_subsidy ────────────────────────────────────────────────────
    if benefit_type == "percentage_subsidy" and "%" in value_unit:
        company_inv = profile.get("investment_amount_lakhs")
        if company_inv is None:
            return BenefitCalculation(
                **base,
                calculation_steps=f"{value_numeric}% of investment amount — investment not provided in profile",
                confidence="LOW",
            )
        raw_amount = float(company_inv) * value_numeric / 100
        cap_lakhs = _cap_to_lakhs(cap_numeric, cap_unit)
        if cap_lakhs is not None and raw_amount > cap_lakhs:
            return BenefitCalculation(
                **base,
                calculated_amount=_fmt_lakhs(raw_amount),
                calculation_steps=(
                    f"{value_numeric}% × {_fmt_lakhs(float(company_inv))} = {_fmt_lakhs(raw_amount)}, "
                    f"capped at {_fmt_lakhs(cap_lakhs)}"
                ),
                cap_applied=True,
                effective_benefit=_fmt_lakhs(cap_lakhs),
                confidence="HIGH",
            )
        return BenefitCalculation(
            **base,
            calculated_amount=_fmt_lakhs(raw_amount),
            calculation_steps=f"{value_numeric}% × {_fmt_lakhs(float(company_inv))} = {_fmt_lakhs(raw_amount)}",
            cap_applied=False,
            effective_benefit=_fmt_lakhs(raw_amount),
            confidence="HIGH",
        )

    # ── percentage reimbursement (same arithmetic as percentage_subsidy) ───────
    if benefit_type == "reimbursement" and "%" in value_unit:
        company_inv = profile.get("investment_amount_lakhs")
        if company_inv is None:
            return BenefitCalculation(
                **base,
                calculation_steps=f"{value_numeric}% reimbursement — investment not provided",
                confidence="LOW",
            )
        raw_amount = float(company_inv) * value_numeric / 100
        cap_lakhs = _cap_to_lakhs(cap_numeric, cap_unit)
        effective = min(raw_amount, cap_lakhs) if cap_lakhs is not None else raw_amount
        return BenefitCalculation(
            **base,
            calculated_amount=_fmt_lakhs(raw_amount),
            calculation_steps=f"{value_numeric}% reimbursement × {_fmt_lakhs(float(company_inv))} = {_fmt_lakhs(raw_amount)}",
            cap_applied=(cap_lakhs is not None and raw_amount > cap_lakhs),
            effective_benefit=_fmt_lakhs(effective),
            confidence="HIGH",
        )

    # ── employment_incentive ──────────────────────────────────────────────────
    if benefit_type == "employment_incentive":
        company_emp = profile.get("employee_count")
        if company_emp is None:
            return BenefitCalculation(
                **base,
                calculation_steps=f"{value_raw} per employee — employee count not provided",
                confidence="LOW",
            )
        # value_unit may be "absolute INR" or "lakhs INR"
        per_emp_lakhs = _to_lakhs_from_unit(value_numeric, value_unit)
        total = per_emp_lakhs * int(company_emp)
        steps = f"{_fmt_lakhs(per_emp_lakhs)} per employee × {company_emp} employees = {_fmt_lakhs(total)}"
        cap_lakhs = _cap_to_lakhs(cap_numeric, cap_unit)
        effective = min(total, cap_lakhs) if cap_lakhs is not None else total
        return BenefitCalculation(
            **base,
            calculated_amount=_fmt_lakhs(total),
            calculation_steps=steps,
            cap_applied=(cap_lakhs is not None and total > cap_lakhs),
            effective_benefit=_fmt_lakhs(effective),
            confidence="HIGH",
        )

    # ── interest_reduction (annual basis) ─────────────────────────────────────
    if benefit_type == "interest_reduction" and "%" in value_unit:
        loan_amt = profile.get("loan_amount_lakhs")
        if loan_amt is None:
            return BenefitCalculation(
                **base,
                calculation_steps=f"{value_numeric}% p.a. interest subvention — loan amount not provided",
                confidence="LOW",
            )
        annual_saving = float(loan_amt) * value_numeric / 100
        return BenefitCalculation(
            **base,
            calculated_amount=f"{_fmt_lakhs(annual_saving)} per year",
            calculation_steps=(
                f"{value_numeric}% × {_fmt_lakhs(float(loan_amt))} loan = "
                f"{_fmt_lakhs(annual_saving)}/year"
            ),
            cap_applied=False,
            effective_benefit=f"{_fmt_lakhs(annual_saving)} per year",
            confidence="MEDIUM",
        )

    return None  # type not handled by rules


# ── LLM fallback schema ────────────────────────────────────────────────────────

class _LLMBenefitCalc(BaseModel):
    benefit_description: str
    value_raw: str
    applicable_to: Optional[str] = None
    calculated_amount: Optional[str] = None
    calculation_steps: Optional[str] = None
    cap_applied: bool = False
    effective_benefit: Optional[str] = None
    conditions: Optional[str] = None
    not_applicable_reason: Optional[str] = None
    confidence: Literal["HIGH", "MEDIUM", "LOW"] = "MEDIUM"


class _LLMBenefitResponse(BaseModel):
    calculations: List[_LLMBenefitCalc] = Field(default_factory=list)


def _llm_calc(pending: list[dict], incentive_details: dict, profile: dict) -> list[BenefitCalculation]:
    """
    Use Gemini Flash to calculate benefit quantum for pending (complex) slabs.
    pending: list of QuantifiedBenefit dicts that could not be handled by rules.
    """
    if not pending:
        return []

    relevant_profile = {
        k: v for k, v in profile.items()
        if k in (
            "business_name", "industry", "geography", "business_size",
            "enterprise_type", "investment_amount_lakhs", "employee_count",
            "annual_turnover_lakhs", "loan_amount_lakhs", "special_attributes",
            "registration_details",
        )
        and v is not None
    }

    prompt = (
        "You are a financial analyst for government incentive schemes. "
        "Calculate the actual benefit quantum for the company profile below.\n\n"
        f"Company Profile:\n{json.dumps(relevant_profile, indent=2)}\n\n"
        f"Incentive Name: {incentive_details.get('incentive_name', 'Unknown')}\n"
        f"Incentive Type: {incentive_details.get('incentive_type', 'Unknown')}\n\n"
        "Benefit slabs to calculate (verbatim source_text is authoritative):\n"
        f"{json.dumps(pending, indent=2)}\n\n"
        "For each benefit slab:\n"
        "1. Determine if it applies to this company (check applicable_to and conditions).\n"
        "2. If applicable, calculate the actual INR benefit using the company profile.\n"
        "   Show step-by-step calculation (e.g. '25% × ₹80L = ₹20L, capped at ₹50L').\n"
        "3. If not applicable to this company, set not_applicable_reason.\n"
        "4. Rate confidence as HIGH (exact numeric inputs available), MEDIUM (estimates used), "
        "or LOW (insufficient profile data).\n"
        "Return one calculation object per slab in the same order as the input list.\n"
        "Use INR lakhs/crores formatting for all monetary amounts."
    )

    from langchain_google_genai import ChatGoogleGenerativeAI
    llm = ChatGoogleGenerativeAI(
        model="gemini-3.8-flash",
        temperature=0,
        max_retries=2,
    ).with_structured_output(
        schema=_LLMBenefitResponse.model_json_schema(),
        method="json_schema",
    )

    try:
        resp = llm.invoke(prompt)
        result = _LLMBenefitResponse(**resp) if isinstance(resp, dict) else resp
        calcs = []
        for i, c in enumerate(result.calculations):
            src = pending[i].get("source_text") if i < len(pending) else ""
            calcs.append(BenefitCalculation(
                benefit_description=c.benefit_description,
                value_raw=c.value_raw,
                applicable_to=c.applicable_to,
                calculated_amount=c.calculated_amount,
                calculation_steps=c.calculation_steps,
                cap_applied=c.cap_applied,
                effective_benefit=c.effective_benefit,
                conditions=c.conditions,
                source_text=src or "",
                confidence=c.confidence,
                not_applicable_reason=c.not_applicable_reason,
            ))
        return calcs
    except Exception as exc:
        logger.warning("LLM benefit calculation failed: %s", exc)
        return [
            BenefitCalculation(
                benefit_description=qb.get("description") or "",
                value_raw=qb.get("value_raw") or "",
                applicable_to=qb.get("applicable_to"),
                conditions=qb.get("conditions"),
                source_text=qb.get("source_text") or "",
                confidence="LOW",
                calculation_steps="Automated calculation unavailable — manual review required",
            )
            for qb in pending
        ]


# ── Public API ─────────────────────────────────────────────────────────────────

def calculate_benefits(incentive_details: dict, company_profile: dict) -> list[dict]:
    """
    Calculate benefit quantum for all slabs in one incentive's quantified_benefits.

    Args:
        incentive_details:  One incentive_details dict from retrieve_policies().
        company_profile:    Company profile dict (existing + new Q9–Q13 fields).

    Returns:
        List of dicts, one per QuantifiedBenefit, with calculation results.
        Each dict is the model_dump() of a BenefitCalculation.
    """
    qbs: list = (incentive_details or {}).get("quantified_benefits") or []
    if not qbs:
        return []

    results: list[BenefitCalculation] = []
    pending_llm: list[dict] = []
    pending_indices: list[int] = []

    for i, qb in enumerate(qbs):
        rule_result = _rule_calc(qb, company_profile)
        if rule_result is not None:
            results.append((i, rule_result))
        else:
            pending_llm.append(qb)
            pending_indices.append(i)

    if pending_llm:
        llm_results = _llm_calc(pending_llm, incentive_details, company_profile)
        for idx, calc in zip(pending_indices, llm_results):
            results.append((idx, calc))

    # Sort back to original order
    results.sort(key=lambda x: x[0])
    return [r.model_dump() for _, r in results]
