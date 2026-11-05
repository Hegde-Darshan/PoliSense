"""Full report pipeline — paid, triggered manually after payment confirmation.

Generates a comprehensive eligibility & benefit quantum PDF for each client
using Gemini-powered analysis. Run only after the client has paid.

Run for specific clients (operator-triggered after payment):
    python polisense_core/full_report_pipeline.py "Company Name A" "Company Name B"

Run with hardcoded test profile (no Zoho connection required):
    python polisense_core/full_report_pipeline.py
"""
import sys
from pathlib import Path
from typing import Dict, List

from polisense_core.utils.postgres_utils import get_connection
from polisense_core.RetrievalPipeline.pg_retriever import retrieve_policies
from polisense_core.PDF_utils.full_report_generator import generate_full_report_pdf
from polisense_core.RetrievalPipeline.eligibility_checker import check_eligibility
from polisense_core.RetrievalPipeline.benefit_calculator import calculate_benefits
from polisense_core.retrieval_pipeline import _FILTER_KEYS, RETRIEVALS_DIR, _build_filename
from polisense_core.zoho_poller import get_access_token, fetch_all_rows, transform_rows_to_batch


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


def run_for_clients(client_names: List[str]) -> None:
    """Fetch Zoho rows, filter to the given client names, and generate full reports.

    Args:
        client_names: Business names exactly as they appear in the Zoho sheet.
    """
    token = get_access_token()
    rows  = fetch_all_rows(token)
    batch = transform_rows_to_batch(rows)

    target = {name: entry for name, entry in batch.items() if name in client_names}
    if not target:
        print(f"No matching clients found in Zoho. Available: {list(batch.keys())}")
        return

    generate_full_report(target)


if __name__ == "__main__":
    if sys.argv[1:]:
        # Operator-triggered: python full_report_pipeline.py "Company A" "Company B"
        run_for_clients(sys.argv[1:])
    else:
        # Fallback test profile — no Zoho connection required
        zoho_data: Dict[str, Dict] = {
            "SuperServices_IT_Karnataka": {
                "query": "skill development programmes and incentives for IT small enterprises in Karnataka",
                "profile": {
                    "business_name":           "Super Services Pvt Ltd",
                    "industry":                "Information Technology",
                    "geography":               "Karnataka",
                    "business_size":           "Small",
                    "enterprise_type":         "Existing",
                    "investment_amount_lakhs": 25,
                    "employee_count":          45,
                    "annual_turnover_lakhs":   256,
                    "loan_amount_lakhs":       95,
                    "special_attributes":      [],
                    "registration_details":    "",
                },
            },
        }
        generate_full_report(zoho_data, top_k=10)
