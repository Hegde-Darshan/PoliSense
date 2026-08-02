"""
questionnaire.py
================
Declarative definition of the PoliSense Business Profile Questionnaire,
mirroring `PoliSense_Business_Questionnaire.docx` section for section.

`app.py` renders this structure as a Streamlit form. Keeping it declarative
(rather than inlined in the UI code) makes it easy to add/remove/reorder
questions without touching the form-rendering logic, and keeps the profile
dict keys ("Profile field" in the docx) in one obvious place.

Each field dict has:
    key       - key written into the business_profile dict (matches the
                "Profile field" annotation in the questionnaire)
    label     - question text shown to the user
    widget    - "text" | "textarea" | "number" | "select" | "multiselect"
    options   - choices, for select/multiselect widgets
    default   - optional default value
    help      - optional helper text (from the section's ℹ note)
"""

from __future__ import annotations

from typing import Any, TypedDict


class Field(TypedDict, total=False):
    key: str
    label: str
    widget: str
    options: list[str]
    default: Any
    help: str


class Section(TypedDict):
    title: str
    info: str
    fields: list[Field]


QUESTIONNAIRE: list[Section] = [
    {
        "title": "Section 1 — Business Identity",
        "info": "Used to identify your business and understand its basic legal structure.",
        "fields": [
            {
                "key": "business_name",
                "label": "Q1. What is the registered name of your business?",
                "widget": "text",
            },
            {
                "key": "legal_entity_type",
                "label": "Q2. What is your legal entity type?",
                "widget": "select",
                "options": [
                    "Sole Proprietorship", "Partnership", "LLP", "Private Limited",
                    "Public Limited", "OPC (One Person Company)", "Trust / Society",
                    "Cooperative", "Other",
                ],
            },
            {
                "key": "year_of_establishment",
                "label": "Q3. What year was your business established?",
                "widget": "number",
                "default": 2020,
            },
            {
                "key": "ownership_type",
                "label": "Q4. Who owns this business?",
                "widget": "select",
                "options": [
                    "Private (General)", "Women-Owned (>51% women ownership)",
                    "SC/ST-Owned", "Government / PSU", "Foreign-owned", "Joint Venture",
                ],
            },
        ],
    },
    {
        "title": "Section 2 — Industry & Operations",
        "info": "Critical for matching your business to relevant industry-specific policies. Be as specific as possible in sub-industry.",
        "fields": [
            {
                "key": "industry",
                "label": "Q5. What is your primary industry sector?",
                "widget": "select",
                "options": [
                    "Automotive / EV / Energy Storage", "Clean Mobility / Green Transport",
                    "Electronics System Design & Manufacturing (ESDM)",
                    "Information Technology / Software", "Manufacturing (General)",
                    "Food Processing / Agri", "Textiles / Handloom", "Healthcare / Pharma",
                    "Other (please specify)",
                ],
            },
            {
                "key": "sub_industry",
                "label": "Q6. What is your specific sub-industry or product focus?",
                "widget": "text",
            },
            {
                "key": "primary_activity",
                "label": "Q7. What is the primary activity of your business?",
                "widget": "select",
                "options": [
                    "Manufacturing / Production", "Design & Engineering (R&D)",
                    "Assembly / Fabrication", "Services / Consulting",
                    "Trading / Distribution", "Mixed (Manufacturing + Services)",
                ],
            },
            {
                "key": "products_services",
                "label": "Q8. What are your key products or services? (briefly describe)",
                "widget": "textarea",
            },
        ],
    },
    {
        "title": "Section 3 — Business Size & Financials",
        "info": "Used to determine MSME tier (Micro / Small / Medium) and eligibility for size-specific incentives.",
        "fields": [
            {
                "key": "employee_count",
                "label": "Q9. How many full-time employees does your business currently have?",
                "widget": "number",
                "default": 10,
            },
            {
                "key": "turnover_range",
                "label": "Q10. What is your approximate annual turnover (last financial year)?",
                "widget": "select",
                "options": [
                    "Less than INR 50 Lakh", "INR 50 Lakh – 1 Crore", "INR 1 – 5 Crore",
                    "INR 5 – 10 Crore", "INR 10 – 25 Crore", "INR 25 – 50 Crore",
                    "INR 50 – 100 Crore", "INR 100 – 250 Crore", "INR 250 – 500 Crore",
                    "INR 500 – 1000 Crore", "More than INR 1000 Crore",
                ],
            },
            {
                "key": "fixed_asset_investment",
                "label": "Q11. What is the total investment in plant & machinery / fixed assets?",
                "widget": "select",
                "options": [
                    "Less than INR 1 Crore", "INR 1 – 10 Crore", "INR 10 – 50 Crore",
                    "INR 50 – 250 Crore", "INR 250 – 500 Crore", "INR 500 – 1000 Crore",
                    "More than INR 1000 Crore",
                ],
            },
            {
                "key": "growth_stage",
                "label": "Q12. What is your current growth stage?",
                "widget": "select",
                "options": [
                    "Idea / Pre-revenue", "Startup (< 2 years, < INR 25 Cr turnover)",
                    "Early Stage", "Early Growth", "Growth / Scaling", "Expansion",
                    "Mature / Stable",
                ],
            },
        ],
    },
    {
        "title": "Section 4 — Location & Geography",
        "info": "Many policies are state-specific. Provide the state where your business operations are primarily based.",
        "fields": [
            {
                "key": "country",
                "label": "Q13. In which country is your business registered / operating?",
                "widget": "text",
                "default": "India",
            },
            {
                "key": "state",
                "label": "Q14. In which state / UT is your primary place of business?",
                "widget": "text",
            },
            {
                "key": "district",
                "label": "Q15. In which district / city is your primary place of business?",
                "widget": "text",
            },
            {
                "key": "location_type",
                "label": "Q16. Is your business located in a rural area, industrial zone, or SEZ?",
                "widget": "select",
                "options": [
                    "Urban / Metro", "Tier-2 / Tier-3 City", "Rural / Semi-urban",
                    "Industrial Park / Cluster", "SEZ (Special Economic Zone)",
                    "Technology Park / ITIR",
                ],
            },
        ],
    },
    {
        "title": "Section 5 — Registrations & Certifications",
        "info": "Determines eligibility for schemes that require specific registrations.",
        "fields": [
            {
                "key": "msme_registration",
                "label": "Q17. Is your business registered as an MSME under the Udyam portal?",
                "widget": "select",
                "options": [
                    "Yes — Micro Enterprise", "Yes — Small Enterprise",
                    "Yes — Medium Enterprise", "No, but eligible", "No",
                ],
            },
            {
                "key": "udyam_number",
                "label": "Q18. If yes, what is your Udyam Registration Number?",
                "widget": "text",
            },
            {
                "key": "dpiit_startup",
                "label": "Q19. Is your business registered as a Startup under DPIIT?",
                "widget": "select",
                "options": [
                    "Yes — DPIIT recognised", "Applied, awaiting recognition", "No",
                ],
            },
            {
                "key": "other_registrations",
                "label": "Q20. Do you hold any of the following registrations?",
                "widget": "multiselect",
                "options": [
                    "GST Registration", "IEM (Industrial Entrepreneur Memorandum)",
                    "ISO Certification", "BIS / Quality Certification",
                    "Export Import Code (IEC)", "None of the above",
                ],
            },
        ],
    },
    {
        "title": "Section 6 — Special Attributes",
        "info": "Helps surface additional incentives for women-led, SC/ST, rural, and other priority categories.",
        "fields": [
            {
                "key": "special_attributes",
                "label": "Q21. Does your business qualify for any of the following categories?",
                "widget": "multiselect",
                "options": [
                    "Women-led / Women-owned (> 51%)", "SC / ST owned",
                    "Differently-abled founder / owner", "Youth-led (founder < 35 years)",
                    "Rural / village enterprise", "SHG-based (Self Help Group)",
                    "Export-oriented unit", "Import substitution focus",
                    "R&D / IP-driven", "Deep Tech / Emerging Technology",
                    "None of the above",
                ],
            },
            {
                "key": "multi_state_interest",
                "label": "Q22. Are you open to applying for policies outside your home state?",
                "widget": "select",
                "options": [
                    "Yes — open to any state", "Yes — specific states only",
                    "No — home state only",
                ],
            },
            {
                "key": "policy_intent",
                "label": "Q23. What is the primary goal for seeking policy support?",
                "widget": "multiselect",
                "options": [
                    "Capital investment subsidy", "Tax / duty exemptions", "R&D funding",
                    "Export promotion", "Employment generation support",
                    "Skill development", "Land / infrastructure access",
                    "Working capital / interest subsidy", "Market access / branding support",
                ],
            },
        ],
    },
]
