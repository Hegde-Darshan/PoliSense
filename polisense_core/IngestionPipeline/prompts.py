from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import SystemMessage, HumanMessage, FileContentBlock, TextContentBlock
from pathlib import Path
import base64

import logging
root_logger = logging.getLogger("ingestion_pipeline")
logger = root_logger.getChild("prompts")

from dotenv import load_dotenv

class PoliSensePrompts:
    """Class to encapsulate prompt templates for the PoliSense project."""
    def __init__(self, pdf_paths: list = [], policy_name:str="") -> None:
        self.pdf_paths = pdf_paths
        self.policy_name = policy_name
        self.prompt = self._get_pdf_extract_prompt()
    
    def get_prompt(self):
        """Returns the appropriate prompt template based on the input parameters."""
        return self.prompt.format_messages()
    
    @staticmethod
    def _get_pdf_bytes(pdf_paths: list[str]) -> list[FileContentBlock]:
        """Utility function to read a list of PDF files and return their content as bytes."""
        pdf_blocks = [FileContentBlock(type = "file", 
                                mime_type="application/pdf", 
                                base64 = base64.b64encode(open(pdf_path, "rb").read()).decode('utf-8'))  
                        for pdf_path in pdf_paths]
        return pdf_blocks

    
    def _get_pdf_extract_prompt(self) -> ChatPromptTemplate:
        """Returns a ChatPromptTemplate for PDF document extraction."""
        system_message = SystemMessage(
            "You are a specialized AI for extracting structured data from Indian government policy, grant, and "
            "incentive documents. You have deep familiarity with Indian government scheme terminology, policy "
            "document conventions, and the MSME sector. Your output must conform exactly to the provided JSON "
            "schema — populate every field the document supports, and use only the allowed controlled-vocabulary "
            "values for enum fields."
        )

        pdf_blocks = [FileContentBlock(type="file",
                                mime_type="application/pdf",
                                base64=base64.b64encode(open(pdf_path, "rb").read()).decode("utf-8"))
                      for pdf_path in self.pdf_paths]
        if not pdf_blocks:
            logger.warning("No PDF files were read. Check the paths and files provided.")

        text_block = TextContentBlock(type="text", text="""This is a comprehensive extraction task — partial extraction is a failure mode. Extract all structured information from the given policy document according to the output schema.

## Document-level instructions

1. Document type: Classify using exactly one of the allowed values: "Policy Document", "Operational Guidelines", "Government Order", "Scheme Notification", "Budget Announcement", "Amendment", or "Other". The type is usually stated on the title page. If not labeled explicitly, use the document's regulatory function: binding orders → "Government Order"; detailed scheme terms → "Policy Document"; operational procedures → "Operational Guidelines."

2. Parent policy vs sub-policies: parent_policy_name is the umbrella act or programme (e.g. "Karnataka Industrial Policy 2020-25"). policy_name within each PolicyExtraction is the sub-scheme's official name (e.g. "Capital Investment Subsidy Scheme"). Each distinct scheme or benefit programme is a separate item in the policies list. If the document covers only one scheme, the list has one item.

3. Issuing authority: Check the document header, letterhead, title page footer, and any official stamp or seal — the issuing ministry or department may appear only there, not in the body text.

## Policy-level extraction

4. Controlled vocabularies: Use only the allowed values for category, applicable_industries, applicable_business_sizes, and incentive_type. Do not invent new values — map to the closest allowed option; use "Other" only when nothing fits. Use ["All Sectors"] for applicable_industries when the policy explicitly covers all sectors. In free-text fields (description, policy_summary, raw_text), preserve the document's original terminology — do not replace it with controlled vocabulary terms.

5. Geographies: Use full Indian state names (e.g. "Karnataka", "Maharashtra"), full Union Territory names (e.g. "Delhi", "Chandigarh", "Puducherry"), "National" for pan-India policies, or recognised regional labels like "North East India". Never abbreviate. If no geography restriction is stated, use ["National"].

6. Business sizes: Indian MSME size categories are provided as reference for interpreting policy text — Micro (turnover < ₹1 cr), Small (₹1–10 cr), Medium (₹10–50 cr), MSME (Micro + Small + Medium together), Large (₹50–250 cr), Mega (> ₹250 cr or investment > ₹500 cr), Startup (DPIIT-recognised, age < 10 years). Use ["All"] if no size restriction is stated. Classify based on what the document states — do not reclassify by recalculating from raw numbers.

7. Multi-policy scope: Each PolicyExtraction in the policies list may have its own distinct applicable_industries, applicable_geographies, and applicable_business_sizes. Extract these independently per sub-scheme — do not copy the parent policy's scope into every child item.

8. Policy-level benefit_headline: Write one accurate sentence with the key numbers that summarises the most broadly applicable benefit across all incentives. Lead with the benefit that covers the widest audience — if the largest benefit applies only to Mega enterprises, note that in parentheses.

9. Policy goals: Look for a section titled "Objectives", "Vision", "Targets", or "Policy Goals" and capture the stated goals in policy_goals as a list.

10. Special focus areas: Scan the document for clauses that grant enhanced benefits or special treatment to specific beneficiary groups or cross-cutting themes — e.g. Women-led enterprises, SC/ST entrepreneurs, Persons with Disabilities, Green manufacturing, Export-oriented units, Border area development. Capture these in special_focus_areas. If the document contains no such clauses beyond its core eligible sector, leave special_focus_areas null — do not populate it with the policy's target industry segments.

## Eligibility extraction

11. raw_text (required): Copy the verbatim eligibility section from the document — do not paraphrase. If eligibility is scattered across multiple sections, concatenate the relevant paragraphs in document order. When the same eligibility condition appears in multiple sections, prefer the most detailed occurrence — typically the main scheme body, not a summary table or application checklist. If no eligibility section exists, use an empty string — do not write placeholder phrases like "Not specified" or "Not found."

12. Structured eligibility fields (best-effort): Populate all structured fields (enterprise_type, minimum_investment, maximum_investment, minimum_employees, maximum_turnover, location_requirements, registration_requirements, special_category_benefits, exclusions, other_requirements) only where the document states them explicitly. Leave fields null if absent — do not infer or estimate. exclusions captures hard disqualifiers (entities barred from the scheme); these are distinct from eligibility thresholds.

13. Monetary and numeric threshold fields: For minimum_investment, maximum_investment, and maximum_turnover, the MonetaryValue.unit must be one of "lakhs" (for amounts in lakhs), "crores" (for amounts in crores), or "absolute_INR" (for rupee amounts under ₹1 lakh). The comparator field must be "min" for lower bounds, "max" for upper bounds, or "exact" for fixed thresholds. For minimum_employees, NumericThreshold.unit is free text (e.g. "employees", "permanent employees"); set value to the base (lowest) threshold number. If the employment criteria is slab-based (different job counts for different investment brackets), copy the full verbatim criteria table or paragraph into NumericThreshold.raw_text — do not encode the slab schedule into the unit string.

## Incentive and benefit extraction

14. Scan first: Before extracting incentive details, scan the entire document including annexures, schedules, and footnotes to identify all incentives. Extract only incentives that have a stated quantum, rate, or mechanism — do not extract aspirational objectives as incentives. If the document appears to be truncated or later sections seem cut off, note this in policy_goals or policy_summary.

15. One incentive per mechanism: Each distinct benefit mechanism (capital subsidy, power tariff concession, GST reimbursement, etc.) is a separate IncentiveExtraction. Variations in rate by business size, district category, geography, enterprise type, sector, commencement year, or benefit phase within the same mechanism are captured as multiple QuantifiedBenefit slabs within that one IncentiveExtraction — not as separate incentives.

16. Slab-based benefits: When a benefit rate varies by any dimension (business size, district category, geography, enterprise type, sector, project phase, or commencement year), create one QuantifiedBenefit per slab — do not average or merge them. Set applicable_to on each slab row describing which sub-group or condition it applies to.

17. conditions vs applicable_to: applicable_to describes the sub-group or slab this benefit row covers (e.g. "Micro enterprises", "Units in backward districts"). conditions describes triggering events that must occur before the benefit can be claimed (e.g. "only after commencement of commercial production", "within 3 years of incorporation"). These are distinct fields — populate both when both are present.

18. Incentive-level benefit_headline: The benefit_headline on IncentiveExtraction should cover only this specific mechanism — keep it scoped to this incentive, not the full policy.

19. Incentive-specific eligibility: If an incentive has eligibility conditions that apply to it alone (not the whole policy), capture them in incentive_specific_eligibility on IncentiveExtraction — do not merge these into the policy-level EligibilityCriteria.

20. Application procedures: Scan for sections titled "How to Apply", "Application Procedure", "Implementing Agency", or "Nodal Agency". Populate application_authority with the department or body the applicant must approach, application_process with the key steps or portal name, and application_deadline with any stated deadline or window.

21. source_text (required on every QuantifiedBenefit): Copy the exact sentence(s) from the document that state this benefit's value and cap — do not paraphrase. When the same text appears in multiple sections, copy from the most detailed occurrence. For values presented in a table cell rather than a sentence, quote the full cell content in the form "Column Header: Cell Value" for each relevant column — do not use ellipsis or abbreviate.

22. value_raw and cap_raw: Reproduce values exactly as written in the document (e.g. "25%", "₹50 lakhs", "100% for first 5 years"). Parse value_numeric / cap_numeric from these (numbers only, no units). If a cap or value is implied but not explicitly stated in the document, leave the field null — do not infer or estimate. For amounts expressed as "lakh crore" (e.g. ₹5 lakh crore), express in crores (1 lakh crore = 100,000 crores).

23. Validity: Copy the verbatim dates clause into ValidityPeriod.raw_text. When the document has been extended or amended, use the most recent effective dates for start_year / end_year. Retrospective start dates take precedence over GO issuance dates. Use null for end_year when the document says "until further notice", "ongoing", or states no end date.

## Table and cross-reference handling

24. Tables: Extract every row — do not skip rows with smaller percentages or narrower scope. Interpret each table into plain text, preserving the semantics between row headers and column headers, before mapping to the schema.

25. Cross-references: Resolve internal cross-references inline (e.g. if a section says "as per Schedule 2", include the Schedule 2 content in the relevant field). For references to external acts or other documents (e.g. "as per the MSMED Act 2006"), note the reference as-is — do not attempt to include external content.

## Keywords

26. Write 10–15 keywords in the keywords field for semantic search by business owners. Include: (a) benefit types using common terminology ("subsidy", "tax exemption", "stamp duty waiver"), (b) target industries using common names, (c) the state name and any state-specific agency abbreviations (e.g. "KIADB", "GIDC"), (d) applicant type terms ("MSME", "startup", "women entrepreneur"). Avoid repeating the policy name, and avoid generic terms like "government scheme" or "India" that apply to all documents.""")

        human_message = HumanMessage(content_blocks=[*pdf_blocks, text_block])
        logger.info(f"Text block of the prompt is as follows:\n {text_block}")

        return ChatPromptTemplate.from_messages([system_message, human_message])

    def get_form_extract_prompt(self):
        pass

    



if __name__ == "__main__":

    env_vars = Path(r"C:\Users\lenovo\OneDrive\Desktop\Projects\PoliSense")
    try:
        load_dotenv(env_vars / ".env")
        load_dotenv(env_vars / ".env.secrets")
    except Exception as e:
        print(f"Error loading .env file: {e}")
    # Example usage
    pdfs = [r"C:\Users\lenovo\OneDrive\Desktop\Projects\PoliSense\Data\LLM Notes.pdf"]
    prompt_manager = PoliSensePrompts(pdf_paths=pdfs)
    if prompt_manager.prompt:
        print(prompt_manager.prompt.messages)
        print(type(prompt_manager.prompt))

