from pydantic import BaseModel, Field
from typing import Optional, List, Literal


# ── Controlled vocabularies ────────────────────────────────────────────────────

IndustryTag = Literal[
    "Manufacturing",
    "Information Technology",
    "Electronics and Hardware",
    "Agriculture and Agro-Processing",
    "Textile and Apparel",
    "Food Processing",
    "Pharmaceuticals and Biotech",
    "Automotive and EV",
    "Renewable Energy and Clean Tech",
    "Tourism and Hospitality",
    "Healthcare and Medical Devices",
    "Education and Skill Development",
    "Logistics and Warehousing",
    "Financial Services and Fintech",
    "Defense and Aerospace",
    "Construction and Real Estate",
    "Retail and E-commerce",
    "Chemical and Petrochemical",
    "Mining and Minerals",
    "Media and Entertainment",
    "All Sectors",
    "Other",
]

BusinessSizeTag = Literal[
    "Micro",    # turnover < ₹1 cr
    "Small",    # ₹1–10 cr
    "Medium",   # ₹10–50 cr
    "MSME",     # covers Micro + Small + Medium together
    "Large",    # ₹50–250 cr
    "Mega",     # > ₹250 cr or investment > ₹500 cr
    "Startup",  # DPIIT-recognized, age < 10 years
    "All",
]

CategoryTag = Literal[
    "Capital Subsidy",
    "Interest Subvention",
    "Tax Incentive",
    "Infrastructure Support",
    "R&D and Innovation Grant",
    "Skill Development",
    "Export Promotion",
    "Market Access and Marketing Support",
    "Land and Building Concession",
    "Power and Utility Concession",
    "Employment Generation",
    "Working Capital Assistance",
    "Credit Guarantee",
    "Other",
]

IncentiveTypeTag = Literal[
    "Capital Subsidy",
    "Interest Subvention",
    "Income Tax Exemption",
    "GST Reimbursement",
    "Stamp Duty Exemption",
    "Land Cost Reimbursement",
    "Power Tariff Concession",
    "Grant",
    "Soft Loan",
    "Credit Guarantee",
    "Employment Subsidy",
    "R&D Reimbursement",
    "Patent Support",
    "Export Incentive",
    "Technology Upgrade Support",
    "Fee Waiver",
    "Other",
]

DocumentTypeTag = Literal[
    "Policy Document",
    "Operational Guidelines",
    "Government Order",
    "Scheme Notification",
    "Budget Announcement",
    "Amendment",
    "Other",
]


# ── Supporting value models ────────────────────────────────────────────────────

class MonetaryValue(BaseModel):
    value: float = Field(description="Numeric amount")
    unit: Literal["lakhs", "crores", "absolute_INR"] = Field(
        description="Unit: 'lakhs' for amounts in lakhs, 'crores' for crores, 'absolute_INR' for rupee amounts under 1 lakh"
    )


class MonetaryThreshold(BaseModel):
    amount: MonetaryValue
    comparator: Literal["min", "max", "exact"] = Field(
        description="Whether this is a minimum, maximum, or exact requirement"
    )


class NumericThreshold(BaseModel):
    value: float
    unit: str = Field(description="Unit of the threshold, e.g. 'employees', 'sq ft', 'MW', 'acres'")
    comparator: Literal["min", "max", "exact"]


class ValidityPeriod(BaseModel):
    start_year: Optional[int] = Field(default=None, description="Year the policy becomes effective, e.g. 2020")
    end_year: Optional[int] = Field(default=None, description="Year the policy expires. None if open-ended or ongoing.")
    raw_text: Optional[str] = Field(
        default=None,
        description="Verbatim validity text from the document, e.g. '2020-2025', 'April 2023 onwards', 'Until further notice'"
    )


# ── Eligibility model ──────────────────────────────────────────────────────────

class EligibilityCriteria(BaseModel):
    """
    Structured eligibility for programmatic Tier-2 matching.
    Always populate raw_text — the structured fields are best-effort.
    """
    enterprise_type: Optional[List[Literal["New", "Existing", "Expansion", "Any"]]] = Field(
        default=None,
        description="Whether the policy applies to new enterprises, existing ones, expansion projects, or all"
    )
    minimum_investment: Optional[MonetaryThreshold] = Field(
        default=None,
        description="Minimum investment required to qualify"
    )
    maximum_investment: Optional[MonetaryThreshold] = Field(
        default=None,
        description="Maximum investment cap for eligibility, if any"
    )
    minimum_employees: Optional[NumericThreshold] = Field(
        default=None,
        description="Minimum employee count the enterprise must have or commit to create"
    )
    maximum_turnover: Optional[MonetaryThreshold] = Field(
        default=None,
        description="Maximum annual turnover allowed for eligibility (common for MSME-targeted policies)"
    )
    location_requirements: Optional[str] = Field(
        default=None,
        description="Specific location or zone requirements, e.g. 'must be in Tier-2/Tier-3 city', 'backward district', 'special economic zone'"
    )
    registration_requirements: Optional[str] = Field(
        default=None,
        description="Required registrations, e.g. 'DPIIT Startup recognition', 'Udyam registration', 'ISO certification'"
    )
    special_category_benefits: Optional[List[str]] = Field(
        default=None,
        description="Groups that receive enhanced benefits, e.g. 'Women-led enterprises', 'SC/ST entrepreneurs', 'Persons with Disabilities'"
    )
    exclusions: Optional[str] = Field(
        default=None,
        description="Entities or activities explicitly excluded. This is distinct from eligibility — these are hard disqualifiers."
    )
    other_requirements: Optional[str] = Field(
        default=None,
        description="Any other eligibility conditions not captured in the structured fields above"
    )
    raw_text: str = Field(
        description="Full verbatim eligibility section from the document. Required. This is the source of truth for Tier-2 LLM reasoning — copy it exactly."
    )


# ── Incentive models ───────────────────────────────────────────────────────────

class QuantifiedBenefit(BaseModel):
    """
    A single quantified benefit component. Use multiple items for slab-based structures
    (e.g. Micro: 30%, Small: 25%, Medium: 20%) — one QuantifiedBenefit per slab.
    """
    benefit_type: Literal[
        "percentage_subsidy",
        "fixed_grant",
        "tax_exemption",
        "loan",
        "interest_reduction",
        "fee_waiver",
        "employment_incentive",
        "reimbursement",
        "other",
    ] = Field(description="Mechanism of the benefit")
    description: str = Field(
        description="Plain-text description of exactly what this benefit provides"
    )
    value_raw: str = Field(
        description="Value exactly as written in the document, e.g. '25%', '₹50 lakhs', '5 years', '100% exemption'"
    )
    value_numeric: Optional[float] = Field(
        default=None,
        description="Numeric value parsed from value_raw for computation, e.g. 25.0 for '25%'"
    )
    value_unit: Optional[str] = Field(
        default=None,
        description="Unit of value_numeric, e.g. '%', 'lakhs INR', 'years', 'absolute INR'"
    )
    cap_raw: Optional[str] = Field(
        default=None,
        description="Maximum cap as written, e.g. 'subject to a maximum of ₹50 lakhs', 'up to ₹2 crore'"
    )
    cap_numeric: Optional[float] = Field(
        default=None,
        description="Numeric cap value for Tier-2 computation"
    )
    cap_unit: Optional[str] = Field(
        default=None,
        description="Unit of cap_numeric, e.g. 'lakhs INR', 'crores INR'"
    )
    applicable_to: Optional[str] = Field(
        default=None,
        description="Which sub-group or slab this benefit row applies to, e.g. 'Micro enterprises', 'Units in backward districts', 'New enterprises only'"
    )
    conditions: Optional[str] = Field(
        default=None,
        description="Any triggering conditions for this benefit, e.g. 'only after commencement of commercial production', 'within 3 years of incorporation'"
    )
    source_text: str = Field(
        description="Verbatim sentence(s) from the document this was extracted from. Required — do not paraphrase. Used by Tier-2 for verification and exact computation."
    )


class IncentiveExtraction(BaseModel):
    incentive_name: str = Field(description="Official name of this incentive or benefit")
    incentive_type: IncentiveTypeTag = Field(description="Mechanism category of the incentive")
    description: str = Field(
        description="Complete description of the incentive covering what it is, who can use it, and how it works"
    )
    benefit_headline: str = Field(
        description="One compelling sentence with the key numbers for Tier-1 display to a potential applicant. "
                    "Lead with the biggest number. E.g. '25% capital subsidy up to ₹50 lakhs for new manufacturing units in backward districts'"
    )
    quantified_benefits: List[QuantifiedBenefit] = Field(
        description="Each distinct quantified component. Create one item per slab, condition, or benefit type — do not merge them."
    )
    application_authority: Optional[str] = Field(
        default=None,
        description="Department, board, or body the applicant must approach, e.g. 'District Industries Centre', 'Karnataka Udyog Mitra'"
    )
    application_process: Optional[str] = Field(
        default=None,
        description="Brief description of the application procedure including key steps or portal names"
    )
    application_deadline: Optional[str] = Field(
        default=None,
        description="Deadline or application window if specified, e.g. 'within 6 months of commencement', 'before 31 March 2025'"
    )
    incentive_specific_eligibility: Optional[str] = Field(
        default=None,
        description="Any eligibility conditions specific to this incentive only, beyond the policy-level criteria"
    )


# ── Policy-level model ─────────────────────────────────────────────────────────

class PolicyExtraction(BaseModel):
    """Structured extraction for one scheme or sub-policy within a document."""
    policy_name: str = Field(description="Official name of this scheme or sub-policy")
    category: CategoryTag = Field(description="Primary category that best describes this policy's mechanism")
    applicable_industries: List[IndustryTag] = Field(
        description="Industries this policy applies to. Use ['All Sectors'] if there is no industry restriction."
    )
    applicable_geographies: List[str] = Field(
        description="Regions covered. Use full names: Indian state names (e.g. 'Karnataka', 'Maharashtra'), 'National' for pan-India, "
                    "or regional labels like 'North India'. Do not abbreviate."
    )
    applicable_business_sizes: List[BusinessSizeTag] = Field(
        description="Business sizes eligible. Use ['All'] if no size restriction is stated."
    )
    validity: ValidityPeriod = Field(description="Validity period of this scheme")
    policy_summary: str = Field(
        description="Comprehensive summary covering the policy's objectives, scope, and main provisions. "
                    "Should be self-contained — a reader with no prior context should understand the policy from this alone."
    )
    benefit_headline: str = Field(
        description="One sentence summarizing the most compelling benefits with numbers for Tier-1 display. "
                    "Lead with the biggest or most broadly applicable benefit. "
                    "E.g. 'Up to 30% capital subsidy and 5-year tax holiday for new manufacturing investments in Karnataka'"
    )
    eligibility_criteria: EligibilityCriteria = Field(description="Structured eligibility criteria for this policy")
    incentives: List[IncentiveExtraction] = Field(
        description="All incentives and benefits provided under this policy. Extract every distinct benefit as a separate item."
    )
    keywords: List[str] = Field(
        description="10 to 15 keywords covering industry terms, benefit types, target groups, and policy mechanisms. "
                    "These are used for semantic search — include synonyms and common search terms."
    )
    special_focus_areas: Optional[List[str]] = Field(
        default=None,
        description="Any special focus groups or themes, e.g. 'Women-led enterprises', 'SC/ST entrepreneurs', "
                    "'Green manufacturing', 'Export-oriented units', 'Border area development'"
    )


# ── Root extraction model ──────────────────────────────────────────────────────

class PDFExtraction(BaseModel):
    """Root extraction schema for a government policy or grant document."""
    parent_policy_name: str = Field(
        description="Official name of the parent policy, act, or programme this document belongs to"
    )
    issuing_authority: str = Field(
        description="Ministry, department, or government body that issued this policy, "
                    "e.g. 'Ministry of Heavy Industries', 'Department of Industries and Commerce, Government of Karnataka'"
    )
    document_type: DocumentTypeTag = Field(
        description="Type of government document. Check the title page and first two pages — "
                    "the type is usually stated explicitly."
    )
    policy_goals: List[str] = Field(
        description="Main objectives of the parent policy as stated in the document, "
                    "e.g. 'Attract ₹5 lakh crore investment by 2025', 'Generate 20 lakh new jobs'"
    )
    policies: List[PolicyExtraction] = Field(
        description="All schemes and sub-policies contained in this document. "
                    "If the document describes one scheme in detail, this list will have one item. "
                    "If it contains multiple schemes, extract each as a separate PolicyExtraction."
    )


# ── LLM initialisation ─────────────────────────────────────────────────────────

def initialize_llm_with_config(
        model_name: str = "gemini-4-argon",
        temperature: float = 0,
        max_tokens: int | None = None,
        timeout: float | None = None,
        max_retries: int = 2,
        is_structured_model: bool = True,
):
    import os
    from langchain_google_genai import ChatGoogleGenerativeAI

    model = ChatGoogleGenerativeAI(
        model=model_name,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        max_retries=max_retries,
        vertexai=True,
        project=os.environ["GOOGLE_CLOUD_PROJECT"],
        location="global",
        api_version="v1",
    )

    if is_structured_model:
        return model.with_structured_output(
            schema=PDFExtraction.model_json_schema(),
            method="json_schema",
        )
    return model
