import os
import re
from pathlib import Path
from typing import List, Dict, Any

from polisense_core.utils.postgres_utils import get_connection
from polisense_core.RetrievalPipeline.pg_retriever import (
    retrieve_policies,
    write_single_result,
    pretty_print_results,
)

_FILTER_KEYS = ("industry", "geography", "business_size", "category")

# Default output folder — project root / Retrievals/
RETRIEVALS_DIR = Path(__file__).parent.parent / "Retrievals"


def _sanitize_filename(name: str) -> str:
    """Strip filesystem-unsafe characters and collapse whitespace to underscores."""
    safe = re.sub(r'[^\w\s-]', '', name).strip()
    safe = re.sub(r'\s+', '_', safe)
    return safe[:100]


def retrieval_pipeline(
    query: str,
    client_profile: Dict | None = None,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """
    Retrieve relevant policies for a single query using PostgreSQL/pgvector.

    Args:
        query: Free-text search query.
        client_profile: Optional dict with any of:
            industry, geography, business_size, category.
            industry and business_size use exact array containment;
            geography uses ILIKE containment; category uses ILIKE.
        top_k: Number of results to return.

    Returns:
        List of policy dicts — each has policy_id, parent_policy_name,
        policy_name, incentive_name, category, applicable_industries,
        applicable_geographies, applicable_business_sizes, start_year,
        end_year, policy_details, incentive_details, similarity_score.
    """
    query = " ".join(query.lower().strip().split())

    filters: Dict[str, str] = {}
    if client_profile:
        for key in _FILTER_KEYS:
            val = client_profile.get(key)
            if val:
                filters[key] = val

    conn = get_connection()
    try:
        return retrieve_policies(query=query, conn=conn, top_k=top_k, **filters)
    finally:
        conn.close()


def process_batch(
    zoho_data: Dict[str, Dict],
    top_k: int = 5,
    output_dir: Path | str = RETRIEVALS_DIR,
) -> None:
    """
    Process a batch of query-profile pairs injected from Zoho Sheets.

    Opens one DB connection for the entire batch and writes one result file
    per query-profile pair into output_dir.

    Args:
        zoho_data:  {query_name → {"query": str, "profile": dict}}
                    query_name  — human-readable label; becomes the filename
                    query       — free-text search string (provided by Zoho row)
                    profile     — business profile dict; accepted filter keys:
                                  industry, geography, business_size, category
        top_k:      number of results per query (default 5)
        output_dir: folder to write .txt files (default: project_root/Retrievals/)
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

                filename    = _sanitize_filename(query_name) + ".txt"
                output_path = output_dir / filename
                write_single_result(
                    query_name=query_name,
                    entry={
                        "query":   query,
                        "profile": profile,
                        "filters": filters,
                        "results": results,
                    },
                    output_path=str(output_path),
                )
                print(f"  OK  {query_name}  ->  {filename}  ({len(results)} result(s))")
            except Exception as e:
                print(f"  FAIL  {query_name}: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    # ── Stub: replaced by Zoho Sheets polling when the poller is built ────────
    # Shape: {query_name: {"query": str, "profile": dict}}
    # query_name becomes the output filename (characters sanitized automatically).
    zoho_data: Dict[str, Dict] = {
        "MedSense_ESDM_Grants": {
            "query": "R&D grants and subsidies for medical electronics micro enterprises in Karnataka",
            "profile": {
                "business_name": "MedSense Electronics Pvt Ltd",
                "industry":      "Electronics and Hardware",
                "geography":     "Karnataka",
                "business_size": "Micro",
            },
        },
        "VoltEdge_EV_Battery": {
            "query": "capital subsidy for EV battery manufacturing startups in Karnataka",
            "profile": {
                "business_name": "VoltEdge Battery Pvt Ltd",
                "industry":      "Automotive and EV",
                "geography":     "Karnataka",
                "business_size": "Startup",
            },
        },
    }

    process_batch(zoho_data, top_k=5)
