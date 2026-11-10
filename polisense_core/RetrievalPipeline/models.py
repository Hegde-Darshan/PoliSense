"""
Pydantic result models for the Tier-2 pipeline.

These models represent the structured output of eligibility checking and
benefit quantification. They are distinct from the ingestion-time extraction
models in IngestionPipeline/llm_extractor.py.
"""

from __future__ import annotations

import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ── Eligibility models ─────────────────────────────────────────────────────────

class CriterionCheck(BaseModel):
    field: str = Field(description="Name of the eligibility criterion")
    criteria_description: str = Field(description="What the policy requires")
    company_value: Optional[str] = Field(default=None, description="What the company has")
    status: Literal["MET", "NOT_MET", "UNCERTAIN"]
    gap: Optional[str] = Field(
        default=None,
        description="For NOT_MET: exact reason the company is disqualified",
    )
    recommendation: Optional[str] = Field(
        default=None,
        description="Actionable advice to resolve NOT_MET or UNCERTAIN; names missing field for UNCERTAIN",
    )


class PolicyEligibilityResult(BaseModel):
    overall_eligibility: Literal["ELIGIBLE", "PARTIALLY_ELIGIBLE", "NOT_ELIGIBLE"]
    criteria_checks: list[CriterionCheck] = Field(default_factory=list)
    missing_profile_fields: list[str] = Field(
        default_factory=list,
        description="Profile fields that would convert UNCERTAIN criteria to definitive results",
    )


# ── Benefit models ─────────────────────────────────────────────────────────────

class BenefitSlabResult(BaseModel):
    slab_description: str
    value_raw: str = Field(description="Verbatim value from policy document")
    source_text: str = Field(description="Verbatim sentence(s) from document")
    is_applicable: Optional[bool] = Field(
        default=None,
        description="True=applicable, False=not applicable, None=uncertain",
    )
    not_applicable_reason: Optional[str] = None
    calculated_amount_lakhs: Optional[float] = None
    effective_amount_lakhs: Optional[float] = Field(
        default=None, description="After cap applied"
    )
    cap_applied: bool = False
    calculation_steps: str = ""
    confidence: Literal["HIGH", "MEDIUM", "LOW"] = "LOW"
    missing_field: Optional[str] = Field(
        default=None,
        description="Profile field needed to resolve UNCERTAIN applicability",
    )


class IncentiveResult(BaseModel):
    incentive_name: str
    incentive_type: str
    benefit_headline: str
    applicability: Literal["APPLICABLE", "NOT_APPLICABLE", "UNCERTAIN"]
    applicability_reason: Optional[str] = None
    benefit_slabs: list[BenefitSlabResult] = Field(default_factory=list)
    total_potential_benefit_lakhs: Optional[float] = Field(
        default=None,
        description="Sum of effective_amount_lakhs across applicable slabs",
    )
    application_authority: Optional[str] = None
    application_process: Optional[str] = None
    application_deadline: Optional[str] = None


# ── Policy-level result ────────────────────────────────────────────────────────

class FullPolicyResult(BaseModel):
    policy_name: str
    parent_policy_name: str
    similarity_score: float
    eligibility: PolicyEligibilityResult
    applicable_incentives: list[IncentiveResult] = Field(
        default_factory=list,
        description="APPLICABLE and UNCERTAIN incentives with benefit calculations",
    )
    not_applicable_incentives: list[IncentiveResult] = Field(
        default_factory=list,
        description="NOT_APPLICABLE incentives — brief, no benefit detail",
    )
    total_potential_benefit_lakhs: Optional[float] = Field(
        default=None,
        description="Sum across all applicable incentives",
    )
    missing_profile_fields: list[str] = Field(
        default_factory=list,
        description="Union of missing fields from eligibility check and all incentive checks",
    )


# ── Top-level report ───────────────────────────────────────────────────────────

class Tier2Report(BaseModel):
    business_name: str
    query: str
    generated_at: datetime.datetime = Field(
        default_factory=datetime.datetime.now
    )
    profile: dict
    eligible_policies: list[FullPolicyResult] = Field(default_factory=list)
    partially_eligible_policies: list[FullPolicyResult] = Field(default_factory=list)
    not_eligible_policies: list[FullPolicyResult] = Field(default_factory=list)
    total_eligible_count: int = 0
    total_potential_benefit_lakhs: Optional[float] = None
    global_missing_fields: list[str] = Field(
        default_factory=list,
        description="Union of missing_profile_fields across all policies",
    )
