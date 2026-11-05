"""Teaser report pipeline — free, runs immediately on every Zoho submission.

Generates a quick-scan scorecard PDF (no LLM calls) for each submitted
business profile.

Run standalone (manual test):
    python polisense_core/teaser_pipeline.py
"""
from pathlib import Path
from typing import Dict

from polisense_core.utils.postgres_utils import get_connection
from polisense_core.RetrievalPipeline.pg_retriever import retrieve_policies
from polisense_core.PDF_utils.teaser_generator import generate_teaser_pdf
from polisense_core.retrieval_pipeline import _FILTER_KEYS, RETRIEVALS_DIR, _build_filename


def process_batch(
    zoho_data: Dict[str, Dict],
    top_k: int = 5,
    output_dir: Path | str = RETRIEVALS_DIR,
) -> None:
    """
    Process a batch of query-profile pairs and generate teaser PDFs.

    Opens one DB connection for the entire batch and writes one teaser PDF
    per query-profile pair into output_dir.

    Args:
        zoho_data:  {query_name → {"query": str, "profile": dict}}
                    query_name  — human-readable label; becomes the filename
                    query       — free-text search string
                    profile     — business profile dict; accepted filter keys:
                                  industry, geography, business_size, category
        top_k:      number of results per query (default 5)
        output_dir: folder to write PDFs (default: project_root/Retrievals/)
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

                # Retrieve without category filter so the scorecard covers all categories
                teaser_filters = {k: v for k, v in filters.items() if k != "category"}
                teaser_results = retrieve_policies(
                    query=query, conn=conn, top_k=20, **teaser_filters
                )
                teaser_path = output_dir / (_build_filename(entry) + "_teaser.pdf")
                generate_teaser_pdf(
                    query_name=query_name,
                    entry={
                        "query":           query,
                        "profile":         profile,
                        "filters":         teaser_filters,
                        "results":         teaser_results,
                        "submission_time": entry.get("submission_time"),
                        "report_id":       None,
                        "payment_link":    None,
                    },
                    output_path=str(teaser_path),
                )
                print(f"  OK  {query_name}  ->  {teaser_path.name}  ({len(teaser_results)} result(s))")
            except Exception as e:
                print(f"  FAIL  {query_name}: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
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

    process_batch(zoho_data, top_k=5)
