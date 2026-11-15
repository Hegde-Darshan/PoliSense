# PoliSense LLM Extraction Schema

This document is the canonical field reference for the structured extraction performed during the PoliSense ingestion stage.

**Pipeline**: PDF bytes (base64) → Gemini 2.5 Pro (`with_structured_output`) → `PDFExtraction` Pydantic object  
**Source files**: `llm_extractor.py` (schema), `prompts.py` (extraction instructions)

---

## Field Usage Tiers

| Tier | Purpose | Examples |
|---|---|---|
| **Tier 1** | Displayed directly at retrieval time; shown to end users | `benefit_headline`, `policy_summary`, `applicable_*` arrays |
| **Tier 2** | Used by the eligibility checker and benefit calculator for exact numeric reasoning | `value_numeric`, `cap_numeric`, `raw_text`, `source_text` |

The two required verbatim-copy fields are the backbone of Tier 2:
- `EligibilityCriteria.raw_text` — full eligibility section, copied exactly from the PDF
- `QuantifiedBenefit.source_text` — sentence(s) that state a benefit's value, copied exactly from the PDF

---

## Controlled Vocabularies

All enum fields must use exactly one of the values below. Use `"Other"` only when nothing else fits.

### IndustryTag (21 values)

| Value | Notes |
|---|---|
| `Manufacturing` | |
| `Information Technology` | |
| `Electronics and Hardware` | |
| `Agriculture and Agro-Processing` | |
| `Textile and Apparel` | |
| `Food Processing` | |
| `Pharmaceuticals and Biotech` | |
| `Automotive and EV` | |
| `Renewable Energy and Clean Tech` | |
| `Tourism and Hospitality` | |
| `Healthcare and Medical Devices` | |
| `Education and Skill Development` | |
| `Logistics and Warehousing` | |
| `Financial Services and Fintech` | |
| `Defense and Aerospace` | |
| `Construction and Real Estate` | |
| `Retail and E-commerce` | |
| `Chemical and Petrochemical` | |
| `Mining and Minerals` | |
| `Media and Entertainment` | |
| `All Sectors` | Use when the policy explicitly has no industry restriction |
| `Other` | |

### BusinessSizeTag (8 values)

| Value | Reference threshold |
|---|---|
| `Micro` | Turnover < ₹1 cr |
| `Small` | Turnover ₹1–10 cr |
| `Medium` | Turnover ₹10–50 cr |
| `MSME` | Covers Micro + Small + Medium together |
| `Large` | Turnover ₹50–250 cr |
| `Mega` | Turnover > ₹250 cr or investment > ₹500 cr |
| `Startup` | DPIIT-recognised, age < 10 years |
| `All` | Use when no size restriction is stated |

> Classify based on what the document states — do not reclassify by recalculating from raw numbers.

### CategoryTag (14 values)

Assigned at the `PolicyExtraction` level to represent the policy's **primary** benefit mechanism.

| Value |
|---|
| `Capital Subsidy` |
| `Interest Subvention` |
| `Tax Incentive` |
| `Infrastructure Support` |
| `R&D and Innovation Grant` |
| `Skill Development` |
| `Export Promotion` |
| `Market Access and Marketing Support` |
| `Land and Building Concession` |
| `Power and Utility Concession` |
| `Employment Generation` |
| `Working Capital Assistance` |
| `Credit Guarantee` |
| `Other` |

### IncentiveTypeTag (17 values)

Assigned at the `IncentiveExtraction` level to represent the **mechanism** of a specific incentive.

| Value |
|---|
| `Capital Subsidy` |
| `Interest Subvention` |
| `Income Tax Exemption` |
| `GST Reimbursement` |
| `Stamp Duty Exemption` |
| `Land Cost Reimbursement` |
| `Power Tariff Concession` |
| `Grant` |
| `Soft Loan` |
| `Credit Guarantee` |
| `Employment Subsidy` |
| `R&D Reimbursement` |
| `Patent Support` |
| `Export Incentive` |
| `Technology Upgrade Support` |
| `Fee Waiver` |
| `Other` |

### DocumentTypeTag (7 values)

| Value | When to use |
|---|---|
| `Policy Document` | Detailed scheme terms and conditions |
| `Operational Guidelines` | Procedural or implementation instructions |
| `Government Order` | Binding regulatory orders |
| `Scheme Notification` | Official scheme launch notifications |
| `Budget Announcement` | Budget speech or budget-related documents |
| `Amendment` | Modifications to an existing policy |
| `Other` | Does not fit any above category |

---

## Supporting Value Models

### MonetaryValue

Represents a monetary amount with its scale unit.

| Field | Type | Required | Description |
|---|---|---|---|
| `value` | `float` | Yes | Numeric amount |
| `unit` | `Literal["lakhs", "crores", "absolute_INR"]` | Yes | `"lakhs"` for lakh-scale, `"crores"` for crore-scale, `"absolute_INR"` for amounts under ₹1 lakh |

> For amounts expressed as "lakh crore" (e.g. ₹5 lakh crore), convert to crores (1 lakh crore = 100,000 crores).

### MonetaryThreshold

Wraps `MonetaryValue` with a comparator for eligibility bounds.

| Field | Type | Required | Description |
|---|---|---|---|
| `amount` | `MonetaryValue` | Yes | The monetary amount |
| `comparator` | `Literal["min", "max", "exact"]` | Yes | `"min"` for a lower bound, `"max"` for an upper bound, `"exact"` for a fixed threshold |

### NumericThreshold

For non-monetary numeric criteria (employees, square footage, MW capacity, etc.).

| Field | Type | Required | Description |
|---|---|---|---|
| `value` | `float` | Yes | The base (lowest) threshold number |
| `unit` | `str` | Yes | Free-text unit, e.g. `"employees"`, `"sq ft"`, `"MW"`, `"acres"` |
| `comparator` | `Literal["min", "max", "exact"]` | Yes | Direction of the threshold |
| `raw_text` | `str` | No (Tier 2) | Verbatim text for slab-based or compound thresholds where a single number cannot capture the full criteria. **Required when the threshold varies by investment size, project type, or any other dimension.** |

### ValidityPeriod

| Field | Type | Required | Description |
|---|---|---|---|
| `start_year` | `int` | No | Year the policy becomes effective, e.g. `2020`. Use retrospective start dates over GO issuance dates. |
| `end_year` | `int` | No | Year the policy expires. `null` for open-ended or "until further notice". |
| `raw_text` | `str` | No | Verbatim dates clause from the document, e.g. `"2020-2025"`, `"April 2023 onwards"`, `"Until further notice"` |

---

## EligibilityCriteria

Structured eligibility for programmatic Tier 2 matching. All structured fields are best-effort; `raw_text` is the only required field and is the source of truth for Tier 2 LLM reasoning.

| Field | Type | Required | Description |
|---|---|---|---|
| `raw_text` | `str` | **Yes** | Full verbatim eligibility section copied exactly from the document. If eligibility is scattered, concatenate relevant paragraphs in document order. If no eligibility section exists, use `""`. |
| `enterprise_type` | `List[Literal["New", "Existing", "Expansion", "Any"]]` | No | Whether the policy applies to new enterprises, existing ones, expansion projects, or all. |
| `minimum_investment` | `MonetaryThreshold` | No | Minimum investment required to qualify. |
| `maximum_investment` | `MonetaryThreshold` | No | Maximum investment cap for eligibility, if any. |
| `minimum_employees` | `NumericThreshold` | No | Minimum employee count the enterprise must have or commit to create. If slab-based, set `value` to the base number and populate `raw_text`. |
| `maximum_turnover` | `MonetaryThreshold` | No | Maximum annual turnover for eligibility — common for MSME-targeted policies. |
| `location_requirements` | `str` | No | Specific location or zone requirements, e.g. `"must be in Tier-2/Tier-3 city"`, `"backward district"`, `"special economic zone"`. |
| `registration_requirements` | `str` | No | Required registrations, e.g. `"DPIIT Startup recognition"`, `"Udyam registration"`, `"ISO certification"`. |
| `special_category_benefits` | `List[str]` | No | Groups that receive **enhanced** benefits, e.g. `"Women-led enterprises"`, `"SC/ST entrepreneurs"`. Distinct from `exclusions`. |
| `exclusions` | `str` | No | Entities or activities explicitly barred from the scheme (hard disqualifiers). Do not conflate with eligibility thresholds. |
| `other_requirements` | `str` | No | Any eligibility conditions not captured in the structured fields above. |

---

## QuantifiedBenefit

One `QuantifiedBenefit` represents a single slab or condition of a benefit. For slab-based benefits (e.g. Micro: 30%, Small: 25%, Medium: 20%), create one item per slab — do not merge.

| Field | Type | Required | Description |
|---|---|---|---|
| `benefit_type` | `Literal[...]` | **Yes** | Mechanism of this benefit. See values below. |
| `description` | `str` | **Yes** | Plain-text description of exactly what this benefit provides. |
| `value_raw` | `str` | **Yes** | Value exactly as written in the document, e.g. `"25%"`, `"₹50 lakhs"`, `"5 years"`, `"100% exemption"`. |
| `source_text` | `str` | **Yes** | Verbatim sentence(s) from the document that state this benefit's value and cap. Do not paraphrase. For table cells, quote as `"Column Header: Cell Value"`. |
| `value_numeric` | `float` | No (Tier 2) | Numeric value parsed from `value_raw`, e.g. `25.0` for `"25%"`. |
| `value_unit` | `str` | No (Tier 2) | Unit of `value_numeric`, e.g. `"%"`, `"lakhs INR"`, `"years"`, `"absolute INR"`. |
| `cap_raw` | `str` | No | Maximum cap exactly as written, e.g. `"subject to a maximum of ₹50 lakhs"`. Leave `null` if not explicitly stated. |
| `cap_numeric` | `float` | No (Tier 2) | Numeric cap value for Tier 2 computation. |
| `cap_unit` | `str` | No (Tier 2) | Unit of `cap_numeric`, e.g. `"lakhs INR"`, `"crores INR"`. |
| `applicable_to` | `str` | No | The sub-group or slab this row covers, e.g. `"Micro enterprises"`, `"Units in backward districts"`, `"New enterprises only"`. |
| `conditions` | `str` | No | Triggering events that must occur **before** the benefit can be claimed, e.g. `"only after commencement of commercial production"`, `"within 3 years of incorporation"`. Distinct from `applicable_to`. |

**`benefit_type` allowed values:**

| Value | Meaning |
|---|---|
| `percentage_subsidy` | Benefit expressed as a percentage of cost |
| `fixed_grant` | Lump-sum grant amount |
| `tax_exemption` | Exemption from a tax |
| `loan` | Subsidised or soft loan |
| `interest_reduction` | Reduction in interest rate |
| `fee_waiver` | Waiver of a fee or charge |
| `employment_incentive` | Incentive tied to job creation |
| `reimbursement` | Reimbursement of an expense already incurred |
| `other` | Does not fit the above |

---

## IncentiveExtraction

Each distinct benefit mechanism is one `IncentiveExtraction`. Rate variations by size, geography, or project phase are captured as `QuantifiedBenefit` slabs within that one item — not as separate incentives.

| Field | Type | Required | Description |
|---|---|---|---|
| `incentive_name` | `str` | **Yes** | Official name of this incentive or benefit. |
| `incentive_type` | `IncentiveTypeTag` | **Yes** | Mechanism category — see [IncentiveTypeTag](#incentivetypetag-17-values). |
| `description` | `str` | **Yes** | Complete description covering what the incentive is, who can use it, and how it works. |
| `benefit_headline` | `str` | **Yes** | **(Tier 1)** One compelling sentence with the key numbers scoped to this incentive alone. Lead with the biggest number. E.g. `"25% capital subsidy up to ₹50 lakhs for new manufacturing units in backward districts"`. |
| `quantified_benefits` | `List[QuantifiedBenefit]` | **Yes** | All distinct slabs or components. One item per slab, condition, or benefit type — do not merge. |
| `application_authority` | `str` | No | Department or body the applicant must approach, e.g. `"District Industries Centre"`, `"Karnataka Udyog Mitra"`. |
| `application_process` | `str` | No | Key application steps or portal name. |
| `application_deadline` | `str` | No | Deadline or application window if stated, e.g. `"within 6 months of commencement"`, `"before 31 March 2025"`. |
| `incentive_specific_eligibility` | `str` | No | Eligibility conditions that apply only to this incentive, beyond the policy-level criteria. |

---

## PolicyExtraction

One `PolicyExtraction` per scheme or sub-policy within a document. If a document contains multiple schemes, each is a separate item in `PDFExtraction.policies`.

| Field | Type | Required | Description |
|---|---|---|---|
| `policy_name` | `str` | **Yes** | Official name of this scheme or sub-policy. |
| `category` | `CategoryTag` | **Yes** | Primary category that best describes this policy's benefit mechanism — see [CategoryTag](#categorytag-14-values). |
| `applicable_industries` | `List[IndustryTag]` | **Yes** | Industries this policy applies to. Use `["All Sectors"]` if no industry restriction is stated. |
| `applicable_geographies` | `List[str]` | **Yes** | Use full Indian state/UT names (e.g. `"Karnataka"`, `"Delhi"`), `"National"` for pan-India, or recognised regional labels (e.g. `"North East India"`). Never abbreviate. Use `["National"]` if no geography restriction. |
| `applicable_business_sizes` | `List[BusinessSizeTag]` | **Yes** | Business sizes eligible. Use `["All"]` if no size restriction is stated. |
| `validity` | `ValidityPeriod` | **Yes** | Validity period of this scheme. |
| `policy_summary` | `str` | **Yes** | Comprehensive, self-contained summary covering objectives, scope, and main provisions. A reader with no prior context should understand the policy from this alone. |
| `benefit_headline` | `str` | **Yes** | **(Tier 1)** One sentence summarising the most broadly applicable benefit with key numbers. Lead with the benefit covering the widest audience. E.g. `"Up to 30% capital subsidy and 5-year tax holiday for new manufacturing investments in Karnataka"`. |
| `eligibility_criteria` | `EligibilityCriteria` | **Yes** | Structured eligibility criteria — see [EligibilityCriteria](#eligibilitycriteria). |
| `incentives` | `List[IncentiveExtraction]` | **Yes** | All incentives under this policy. Extract every distinct benefit as a separate item. Scan annexures and schedules before concluding extraction. |
| `keywords` | `List[str]` | **Yes** | 10–15 terms for semantic search. Include: benefit types (`"subsidy"`, `"tax exemption"`), target industries, the state name, state-specific agency abbreviations (e.g. `"KIADB"`, `"GIDC"`), and applicant types (`"MSME"`, `"startup"`, `"women entrepreneur"`). Avoid the policy name and generic terms like `"government scheme"`. |
| `special_focus_areas` | `List[str]` | No | Groups or themes that receive enhanced treatment, e.g. `"Women-led enterprises"`, `"SC/ST entrepreneurs"`, `"Green manufacturing"`, `"Export-oriented units"`. Leave `null` if no such clauses exist — do not populate with the policy's target industry. |

---

## PDFExtraction (Root)

The root object returned by the LLM for each document.

| Field | Type | Required | Description |
|---|---|---|---|
| `parent_policy_name` | `str` | **Yes** | Official name of the parent policy, act, or programme (e.g. `"Karnataka Industrial Policy 2020-25"`). |
| `issuing_authority` | `str` | **Yes** | Ministry, department, or body that issued the document. Check the title page, letterhead, header, and any official stamp — the authority may appear only there. E.g. `"Ministry of Heavy Industries"`, `"Department of Industries and Commerce, Government of Karnataka"`. |
| `document_type` | `DocumentTypeTag` | **Yes** | Type of government document — see [DocumentTypeTag](#documenttypetag-7-values). If not labeled explicitly, infer from regulatory function. |
| `policy_goals` | `List[str]` | **Yes** | Main objectives as stated in the document's "Objectives", "Vision", "Targets", or "Policy Goals" section. Each goal is a separate list item. |
| `policies` | `List[PolicyExtraction]` | **Yes** | All schemes and sub-policies in the document. One item per distinct scheme. If the document covers only one scheme, this list has one item. |

---

## Schema Hierarchy

```
PDFExtraction
├── parent_policy_name
├── issuing_authority
├── document_type
├── policy_goals
└── policies: List[PolicyExtraction]
    ├── policy_name
    ├── category
    ├── applicable_industries
    ├── applicable_geographies
    ├── applicable_business_sizes
    ├── validity: ValidityPeriod
    │   ├── start_year
    │   ├── end_year
    │   └── raw_text
    ├── policy_summary
    ├── benefit_headline                    ← Tier 1
    ├── eligibility_criteria: EligibilityCriteria
    │   ├── raw_text                        ← REQUIRED, Tier 2
    │   ├── enterprise_type
    │   ├── minimum_investment: MonetaryThreshold
    │   ├── maximum_investment: MonetaryThreshold
    │   ├── minimum_employees: NumericThreshold
    │   ├── maximum_turnover: MonetaryThreshold
    │   ├── location_requirements
    │   ├── registration_requirements
    │   ├── special_category_benefits
    │   ├── exclusions
    │   └── other_requirements
    ├── incentives: List[IncentiveExtraction]
    │   ├── incentive_name
    │   ├── incentive_type
    │   ├── description
    │   ├── benefit_headline                ← Tier 1
    │   ├── application_authority
    │   ├── application_process
    │   ├── application_deadline
    │   ├── incentive_specific_eligibility
    │   └── quantified_benefits: List[QuantifiedBenefit]
    │       ├── benefit_type
    │       ├── description
    │       ├── value_raw
    │       ├── value_numeric               ← Tier 2
    │       ├── value_unit                  ← Tier 2
    │       ├── cap_raw
    │       ├── cap_numeric                 ← Tier 2
    │       ├── cap_unit                    ← Tier 2
    │       ├── applicable_to
    │       ├── conditions
    │       └── source_text                 ← REQUIRED, Tier 2
    ├── keywords
    └── special_focus_areas
```

---

## Extraction Rules Summary

Key rules from the 26-point extraction prompt (`prompts.py`):

**Verbatim copy discipline**
- `raw_text` and `source_text` must be copied exactly — never paraphrased.
- For table cells, use `"Column Header: Cell Value"` format; do not abbreviate.

**Slab splitting**
- One `QuantifiedBenefit` per distinct slab (by business size, district category, geography, enterprise type, sector, project phase, or commencement year).
- Use `applicable_to` to identify which sub-group/slab the row covers.
- Use `conditions` for triggering events (e.g. "after commencement of commercial production"). These are distinct fields.

**Sub-policy detection**
- Each distinct scheme in the document is a separate `PolicyExtraction`.
- Each sub-scheme has its own `applicable_industries`, `applicable_geographies`, and `applicable_business_sizes` — do not copy the parent scope into every child.

**Incentive scoping**
- One `IncentiveExtraction` per benefit mechanism (capital subsidy, power tariff, GST reimbursement, etc.).
- Rate variations within the same mechanism → multiple `QuantifiedBenefit` slabs, not separate incentives.
- Incentive-level eligibility conditions go in `incentive_specific_eligibility`, not in the policy-level `EligibilityCriteria`.

**Tables**
- Extract every row — do not skip rows with smaller percentages or narrower scope.
- Resolve internal cross-references inline (e.g. "as per Schedule 2" → include Schedule 2 content in the field).
- For external act references (e.g. "as per the MSMED Act 2006"), note the reference as-is.

**Validity**
- Use retrospective start dates over GO issuance dates.
- When a policy has been extended or amended, use the most recent effective dates.
- Set `end_year` to `null` for "until further notice" or open-ended policies.

**Cap and value inference**
- Leave `cap_raw`, `cap_numeric`, `value_numeric` as `null` if not explicitly stated. Do not infer or estimate.

**Scan completeness**
- Scan the entire document including annexures, schedules, and footnotes before concluding extraction.
- Extract only incentives with a stated quantum, rate, or mechanism — not aspirational objectives.
