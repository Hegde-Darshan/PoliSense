"""
Per-incentive applicability check and benefit quantum calculator for Tier-2.

For each incentive row in a PolicyGroup:
  1. Rule-based arithmetic for simple benefit types where numeric inputs exist.
  2. Single Gemini Flash call (combined applicability + calculation) for the
     remaining slabs or when rule-based cannot proceed.

Public API:
    check_and_calculate_incentive(incentive_row, profile) -> IncentiveResult
    extract_cost_breakup(profile) -> dict   (mutates profile in-place, returns it)
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from pydantic import BaseModel, Field

from polisense_core.AssessmentPipeline.models import (
    BenefitSlabResult,
    IncentiveResult,
)
from polisense_core.AssessmentPipeline.prompts import build_incentive_prompt, make_gemini_flash

logger = logging.getLogger(__name__)


# ── LLM output schema ──────────────────────────────────────────────────────────

class _LLMSlabResult(BaseModel):
    slab_description: str = ""
    value_raw: str = ""
    source_text: str = ""
    is_applicable: Optional[bool] = None
    not_applicable_reason: Optional[str] = None
    missing_field: Optional[str] = None
    calculated_amount_lakhs: Optional[float] = None
    effective_amount_lakhs: Optional[float] = None
    cap_applied: bool = False
    calculation_steps: str = ""
    confidence: str = "LOW"


class _LLMIncentiveResponse(BaseModel):
    applicability: str = "UNCERTAIN"  # APPLICABLE | NOT_APPLICABLE | UNCERTAIN
    applicability_reason: Optional[str] = None
    slab_results: list[_LLMSlabResult] = Field(default_factory=list)


# ── Unit helpers ───────────────────────────────────────────────────────────────

def _to_lakhs(value: float, unit: str) -> float:
    u = (unit or "").lower()
    if "crore" in u:
        return value * 100
    if "absolute" in u or u == "inr":
        return value / 100_000
    return value


def _fmt(lakhs: float) -> str:
    if lakhs >= 100:
        return f"₹{lakhs / 100:.2f} crores"
    return f"₹{lakhs:.2f} lakhs"


def _cap_lakhs(cap_numeric: Optional[float], cap_unit: Optional[str]) -> Optional[float]:
    if cap_numeric is None:
        return None
    return _to_lakhs(cap_numeric, cap_unit or "lakhs INR")


def _apply_cap(raw: float, cap: Optional[float]) -> tuple[float, bool]:
    if cap is not None and raw > cap:
        return cap, True
    return raw, False


def _investment_base(profile: dict, prefer_eligible_fci: bool = False) -> Optional[float]:
    """
    Return the investment base in lakhs for subsidy calculations.
    prefer_eligible_fci=True: total_project_cost - land_cost (common policy definition).
    """
    pm = profile.get("investment_pm_lakhs")
    tcp = profile.get("total_project_cost_lakhs")
    land = profile.get("land_cost_lakhs")

    if prefer_eligible_fci and tcp is not None:
        eligible = tcp - (land or 0.0)
        return float(eligible)
    if pm is not None:
        return float(pm)
    if tcp is not None:
        return float(tcp)
    return None


# ── Cost break-up extraction ───────────────────────────────────────────────────

_AMOUNT_PATTERN = re.compile(
    r"""
    (?P<value>[\d,]+(?:\.\d+)?)\s*   # numeric part (may have commas)
    (?P<unit>
        crore[s]?|cr\.?|
        lakh[s]?|l\.?|
        inr|rs\.?|rupee[s]?|
        [₹]?                     # ₹ symbol
    )?
    """,
    re.VERBOSE | re.IGNORECASE,
)

_SECTION_PATTERNS = {
    "land_cost_lakhs": re.compile(
        r"(?:land|site\s*dev(?:elopment)?|land\s*&\s*site)", re.IGNORECASE
    ),
    "civil_cost_lakhs": re.compile(
        r"(?:civil|building|construction|shed|factory\s*building)", re.IGNORECASE
    ),
    "working_capital_lakhs": re.compile(
        r"(?:working\s*capital|wc\b|margin\s*money)", re.IGNORECASE
    ),
}


def _parse_inr_to_lakhs(text: str) -> Optional[float]:
    """Extract the first monetary amount from text and return it in lakhs."""
    m = _AMOUNT_PATTERN.search(text)
    if not m:
        return None
    raw_val = float(m.group("value").replace(",", ""))
    unit = (m.group("unit") or "").lower().strip(".")
    if any(x in unit for x in ("crore", "cr")):
        return raw_val * 100
    if any(x in unit for x in ("lakh", "l")) or not unit:
        return raw_val
    # absolute INR (no unit or "rs/inr")
    return raw_val / 100_000 if raw_val > 100_000 else raw_val


def extract_cost_breakup(profile: dict) -> dict:
    """
    Extract land/civil/WC components from project_cost_breakup free text.
    Tries regex first; falls back to Gemini Flash if any component missing.
    Mutates profile in-place and returns it.
    """
    text = profile.get("project_cost_breakup")
    if not text:
        return profile

    # Split on common separators to get per-category segments
    segments = re.split(r"[,\n;|]+", text)

    extracted: dict[str, Optional[float]] = {
        "land_cost_lakhs": None,
        "civil_cost_lakhs": None,
        "working_capital_lakhs": None,
    }

    for seg in segments:
        for key, pat in _SECTION_PATTERNS.items():
            if pat.search(seg) and extracted[key] is None:
                val = _parse_inr_to_lakhs(seg)
                if val is not None:
                    extracted[key] = val

    all_found = all(v is not None for v in extracted.values())

    if not all_found:
        # LLM fallback
        from polisense_core.AssessmentPipeline.prompts import make_gemini_flash

        class _BreakupSchema(BaseModel):
            land_cost_lakhs: Optional[float] = None
            civil_cost_lakhs: Optional[float] = None
            pm_cost_lakhs: Optional[float] = None
            working_capital_lakhs: Optional[float] = None

        prompt = (
            "Extract the project cost break-up from the following free text into the structured fields below.\n"
            "Express all amounts in INR lakhs. If a component is not mentioned, return null.\n\n"
            f"Break-up text: {text}\n\n"
            f"Cross-reference: Investment in Plant & Machinery = "
            f"{profile.get('investment_pm_lakhs')} lakhs, "
            f"Total Project Cost = {profile.get('total_project_cost_lakhs')} lakhs."
        )
        try:
            llm = make_gemini_flash(_BreakupSchema.model_json_schema())
            resp = llm.invoke(prompt)
            result = _BreakupSchema(**resp) if isinstance(resp, dict) else resp
            if extracted["land_cost_lakhs"] is None and result.land_cost_lakhs is not None:
                extracted["land_cost_lakhs"] = result.land_cost_lakhs
            if extracted["civil_cost_lakhs"] is None and result.civil_cost_lakhs is not None:
                extracted["civil_cost_lakhs"] = result.civil_cost_lakhs
            if extracted["working_capital_lakhs"] is None and result.working_capital_lakhs is not None:
                extracted["working_capital_lakhs"] = result.working_capital_lakhs
        except Exception as exc:
            logger.warning("Break-up LLM extraction failed: %s", exc)

    for key, val in extracted.items():
        if val is not None:
            profile[key] = val

    return profile


# ── Rule-based slab calculation ────────────────────────────────────────────────

def _rule_calc_slab(qb: dict, profile: dict) -> Optional[BenefitSlabResult]:
    """
    Attempt rule-based calculation for one QuantifiedBenefit dict.
    Returns None if the type/data cannot be handled without an LLM.
    """
    btype = qb.get("benefit_type")
    value_numeric = qb.get("value_numeric")
    value_unit = qb.get("value_unit") or ""
    cap_numeric = qb.get("cap_numeric")
    cap_unit = qb.get("cap_unit") or "lakhs INR"
    value_raw = qb.get("value_raw") or ""
    description = qb.get("description") or ""
    source_text = qb.get("source_text") or ""
    cap_lk = _cap_lakhs(cap_numeric, cap_unit)

    base = dict(
        slab_description=description,
        value_raw=value_raw,
        source_text=source_text,
    )

    # ── fixed_grant / fee_waiver / loan ───────────────────────────────────────
    if btype in ("fixed_grant", "fee_waiver", "loan"):
        if value_numeric is not None:
            amount_lk = _to_lakhs(value_numeric, value_unit)
            effective, capped = _apply_cap(amount_lk, cap_lk)
            return BenefitSlabResult(
                **base,
                is_applicable=True,
                calculated_amount_lakhs=amount_lk,
                effective_amount_lakhs=effective,
                cap_applied=capped,
                calculation_steps="Fixed amount",
                confidence="HIGH",
            )
        return None  # no numeric — send to LLM

    if value_numeric is None:
        return None

    # ── percentage_subsidy ────────────────────────────────────────────────────
    if btype == "percentage_subsidy" and "%" in value_unit:
        inv = _investment_base(profile)
        if inv is None:
            return BenefitSlabResult(
                **base,
                is_applicable=None,
                calculation_steps=f"{value_numeric}% of investment — investment amount not provided",
                confidence="LOW",
                missing_field="investment_pm_lakhs",
            )
        raw = inv * value_numeric / 100
        effective, capped = _apply_cap(raw, cap_lk)
        steps = f"{value_numeric}% × {_fmt(inv)} = {_fmt(raw)}"
        if capped:
            steps += f", capped at {_fmt(cap_lk)}"
        return BenefitSlabResult(
            **base,
            is_applicable=True,
            calculated_amount_lakhs=raw,
            effective_amount_lakhs=effective,
            cap_applied=capped,
            calculation_steps=steps,
            confidence="HIGH",
        )

    # ── reimbursement (percentage) ────────────────────────────────────────────
    if btype == "reimbursement" and "%" in value_unit:
        inv = _investment_base(profile)
        if inv is None:
            return BenefitSlabResult(
                **base,
                is_applicable=None,
                calculation_steps=f"{value_numeric}% reimbursement — investment not provided",
                confidence="LOW",
                missing_field="investment_pm_lakhs",
            )
        raw = inv * value_numeric / 100
        effective, capped = _apply_cap(raw, cap_lk)
        steps = f"{value_numeric}% reimbursement × {_fmt(inv)} = {_fmt(raw)}"
        if capped:
            steps += f", capped at {_fmt(cap_lk)}"
        return BenefitSlabResult(
            **base,
            is_applicable=True,
            calculated_amount_lakhs=raw,
            effective_amount_lakhs=effective,
            cap_applied=capped,
            calculation_steps=steps,
            confidence="HIGH",
        )

    # ── stamp_duty / land_cost — use land_cost_lakhs ──────────────────────────
    if btype in ("other",) and "stamp" in description.lower():
        land = profile.get("land_cost_lakhs")
        if land is None:
            return BenefitSlabResult(
                **base,
                is_applicable=None,
                calculation_steps="Stamp duty exemption — land cost not provided",
                confidence="LOW",
                missing_field="land_cost_lakhs",
            )
        # Stamp duty in India is typically 5–8% of property value
        raw = float(land) * value_numeric / 100 if "%" in value_unit else _to_lakhs(value_numeric, value_unit)
        effective, capped = _apply_cap(raw, cap_lk)
        return BenefitSlabResult(
            **base,
            is_applicable=True,
            calculated_amount_lakhs=raw,
            effective_amount_lakhs=effective,
            cap_applied=capped,
            calculation_steps=f"Based on land cost of {_fmt(float(land))}",
            confidence="MEDIUM",
        )

    # ── employment_incentive — always LLM (employee_count not in form) ────────
    if btype == "employment_incentive":
        return BenefitSlabResult(
            **base,
            is_applicable=None,
            calculation_steps=f"{value_raw} per employee — employee count not collected",
            confidence="LOW",
            missing_field="employee_count",
        )

    # ── interest_reduction — always LLM (loan_amount not in form) ─────────────
    if btype == "interest_reduction":
        return BenefitSlabResult(
            **base,
            is_applicable=None,
            calculation_steps=f"{value_raw} interest subvention — loan amount not provided",
            confidence="LOW",
            missing_field="loan_amount_lakhs",
        )

    return None  # unhandled type → LLM


# ── LLM-based calculation ──────────────────────────────────────────────────────

def _llm_calc_incentive(
    incentive_row: dict,
    profile: dict,
    pending_slabs: list[dict],
    pending_indices: list[int],
) -> list[tuple[int, BenefitSlabResult]]:
    """Run the LLM for all pending slabs in one call."""
    if not pending_slabs:
        return []

    inc = incentive_row.get("incentive_details") or {}
    prompt = build_incentive_prompt(
        incentive_name=incentive_row.get("incentive_name") or "",
        incentive_type=inc.get("incentive_type") or "",
        incentive_specific_eligibility=inc.get("incentive_specific_eligibility"),
        quantified_benefits=pending_slabs,
        profile=profile,
    )
    llm = make_gemini_flash(_LLMIncentiveResponse.model_json_schema())

    try:
        resp = llm.invoke(prompt)
        result = _LLMIncentiveResponse(**resp) if isinstance(resp, dict) else resp

        out: list[tuple[int, BenefitSlabResult]] = []
        for i, (orig_idx, slab_input) in enumerate(zip(pending_indices, pending_slabs)):
            if i < len(result.slab_results):
                s = result.slab_results[i]
                confidence = s.confidence if s.confidence in ("HIGH", "MEDIUM", "LOW") else "LOW"
                out.append((orig_idx, BenefitSlabResult(
                    slab_description=s.slab_description or slab_input.get("description") or "",
                    value_raw=s.value_raw or slab_input.get("value_raw") or "",
                    source_text=s.source_text or slab_input.get("source_text") or "",
                    is_applicable=s.is_applicable,
                    not_applicable_reason=s.not_applicable_reason,
                    missing_field=s.missing_field,
                    calculated_amount_lakhs=s.calculated_amount_lakhs,
                    effective_amount_lakhs=s.effective_amount_lakhs,
                    cap_applied=s.cap_applied,
                    calculation_steps=s.calculation_steps or "",
                    confidence=confidence,
                )))
            else:
                out.append((orig_idx, _slab_fallback(slab_input)))
        return out
    except Exception as exc:
        logger.warning("LLM benefit calculation failed: %s", exc)
        return [
            (orig_idx, _slab_fallback(s))
            for orig_idx, s in zip(pending_indices, pending_slabs)
        ]


def _slab_fallback(qb: dict) -> BenefitSlabResult:
    return BenefitSlabResult(
        slab_description=qb.get("description") or "",
        value_raw=qb.get("value_raw") or "",
        source_text=qb.get("source_text") or "",
        is_applicable=None,
        calculation_steps="Automated calculation unavailable — manual review required",
        confidence="LOW",
    )


# ── Incentive-level applicability determination ────────────────────────────────

def _incentive_applicability(
    slabs: list[BenefitSlabResult],
    incentive_specific_elig: Optional[str],
) -> tuple[str, Optional[str]]:
    """
    Derive overall incentive applicability from slab results.
    Returns (applicability, reason).
    """
    if not slabs:
        return "UNCERTAIN", "No benefit slabs found"

    true_count = sum(1 for s in slabs if s.is_applicable is True)
    false_count = sum(1 for s in slabs if s.is_applicable is False)
    uncertain_count = sum(1 for s in slabs if s.is_applicable is None)

    if true_count > 0:
        return "APPLICABLE", None
    if false_count == len(slabs):
        reasons = [s.not_applicable_reason for s in slabs if s.not_applicable_reason]
        return "NOT_APPLICABLE", reasons[0] if reasons else "No applicable slabs"
    return "UNCERTAIN", "Applicability could not be fully determined"


# ── Public API ─────────────────────────────────────────────────────────────────

def check_and_calculate_incentive(
    incentive_row: dict,
    profile: dict,
) -> IncentiveResult:
    """
    Check applicability and calculate benefit quantum for one incentive row.

    Args:
        incentive_row: One row from tier-1 results (has incentive_name, incentive_details, etc.)
        profile:       Extended company profile (including extracted cost components).

    Returns:
        IncentiveResult with applicability status and per-slab benefit calculations.
    """
    inc = incentive_row.get("incentive_details") or {}
    qbs: list[dict] = inc.get("quantified_benefits") or []

    slab_results: list[tuple[int, BenefitSlabResult]] = []
    pending_slabs: list[dict] = []
    pending_indices: list[int] = []

    for i, qb in enumerate(qbs):
        rule_result = _rule_calc_slab(qb, profile)
        if rule_result is not None:
            slab_results.append((i, rule_result))
        else:
            pending_slabs.append(qb)
            pending_indices.append(i)

    if pending_slabs:
        llm_results = _llm_calc_incentive(
            incentive_row, profile, pending_slabs, pending_indices
        )
        slab_results.extend(llm_results)

    slab_results.sort(key=lambda x: x[0])
    final_slabs = [s for _, s in slab_results]

    applicability, reason = _incentive_applicability(
        final_slabs, inc.get("incentive_specific_eligibility")
    )

    # Sum effective_amount_lakhs for applicable slabs
    total: Optional[float] = None
    applicable_amounts = [
        s.effective_amount_lakhs
        for s in final_slabs
        if s.is_applicable is True and s.effective_amount_lakhs is not None
    ]
    if applicable_amounts:
        total = sum(applicable_amounts)

    return IncentiveResult(
        incentive_name=incentive_row.get("incentive_name") or "",
        incentive_type=inc.get("incentive_type") or "",
        benefit_headline=inc.get("benefit_headline") or "",
        applicability=applicability,
        applicability_reason=reason,
        benefit_slabs=final_slabs,
        total_potential_benefit_lakhs=total,
        application_authority=inc.get("application_authority"),
        application_process=inc.get("application_process"),
        application_deadline=inc.get("application_deadline"),
    )
