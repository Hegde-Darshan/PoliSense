import re
import datetime
from pathlib import Path
from typing import List, Dict, Any

from polisense_core.utils.postgres_utils import get_connection
from polisense_core.RetrievalPipeline.pg_retriever import retrieve_policies

_FILTER_KEYS = ("industry", "geography", "business_size", "category")

# Default output folder — project root / Retrievals/
RETRIEVALS_DIR = Path(__file__).parent.parent / "Retrievals"


def _sanitize_filename(name: str) -> str:
    """Strip filesystem-unsafe characters and collapse whitespace to underscores."""
    safe = re.sub(r'[^\w\s-]', '', name).strip()
    safe = re.sub(r'\s+', '_', safe)
    return safe[:80]


def _build_filename(entry: dict) -> str:
    """Build output filename from business name and Zoho submission time."""
    profile = entry.get("profile", {})
    business_name = profile.get("business_name") or entry.get("query", "Unnamed")[:40]

    sub_time = entry.get("submission_time")
    if sub_time:
        ts_str = sub_time.strftime("%d%m%Y_%H%M")
    else:
        ts_str = datetime.datetime.now().strftime("%d%m%Y_%H%M")

    return _sanitize_filename(business_name) + "_" + ts_str


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


if __name__ == "__main__":
    results = retrieval_pipeline(
        query="skill development programmes for IT enterprises in Karnataka",
        client_profile={
            "industry":      "Information Technology",
            "geography":     "Karnataka",
            "business_size": "Small",
        },
        top_k=5,
    )
    for r in results:
        print(r["incentive_name"], r["similarity_score"])
