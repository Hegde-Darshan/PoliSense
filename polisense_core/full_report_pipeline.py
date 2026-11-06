"""Full report pipeline — paid, triggered by the payment poller after a client pays.

Generates a comprehensive eligibility & benefit quantum PDF for each client
using Gemini-powered analysis. Called by the payment poller (to be built).
"""
from pathlib import Path
from typing import Dict, List

from polisense_core.utils.postgres_utils import get_connection
from polisense_core.RetrievalPipeline.pg_retriever import retrieve_policies
from polisense_core.PDF_utils.full_report_generator import generate_full_report_pdf
from polisense_core.RetrievalPipeline.eligibility_checker import check_eligibility
from polisense_core.RetrievalPipeline.benefit_calculator import calculate_benefits
from polisense_core.retrieval_pipeline import _FILTER_KEYS, RETRIEVALS_DIR, _build_filename


def _enrich_results(results: list, profile: dict) -> list:
    """Attach eligibility_check and benefit_calculations to each retrieved policy."""
    enriched = []
    for r in results:
        r["eligibility_check"] = check_eligibility(r, profile)
        r["benefit_calculations"] = calculate_benefits(
            r.get("incentive_details") or {}, profile
        )
        enriched.append(r)
    return enriched


def generate_full_report(
    zoho_data: Dict[str, Dict],
    top_k: int = 10,
    output_dir: Path | str = RETRIEVALS_DIR,
) -> None:
    """
    Generate full eligibility & benefit quantum reports for a batch of queries.

    Retrieves policies, runs eligibility checking and benefit calculation for each
    result, then writes a comprehensive PDF per query.

    Args:
        zoho_data:  {query_name → {"query": str, "profile": dict}}
                    profile should include Q9–Q13 fields for best results:
                    enterprise_type, investment_amount_lakhs, employee_count,
                    annual_turnover_lakhs, loan_amount_lakhs, special_attributes,
                    registration_details, business_description
        top_k:      Number of policies per query (default 10)
        output_dir: Output folder (default: project_root/Retrievals/)
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    conn = get_connection()
    try:
        for query_name, entry in zoho_data.items():
            try:
                query   = entry["query"]
                profile = entry.get("profile", {})
                filters = {k: v for k, v in profile.items() if k in _FILTER_KEYS and v}
                if "enquiry_purpose" in profile and profile["enquiry_purpose"] and "category" not in filters:
                    filters["category"] = profile["enquiry_purpose"]

                results = retrieve_policies(
                    query=query, conn=conn, top_k=top_k, **filters
                )
                enriched = _enrich_results(results, profile)

                report_path = output_dir / (_build_filename(entry) + "_full_report.pdf")
                generate_full_report_pdf(
                    query_name=query_name,
                    entry={
                        "query":           query,
                        "profile":         profile,
                        "filters":         filters,
                        "results":         enriched,
                        "submission_time": entry.get("submission_time"),
                    },
                    output_path=str(report_path),
                )
                print(f"  OK  {query_name}  ->  {report_path.name}  ({len(enriched)} result(s))")
            except Exception as e:
                print(f"  FAIL  {query_name}: {e}")
    finally:
        conn.close()


