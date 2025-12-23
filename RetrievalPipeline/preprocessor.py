from typing import Dict


def preprocess_query(query: str) -> str:
    """
    Normalize query text for retrieval.
    """
    query = query.lower().strip()
    query = " ".join(query.split())
    return query


def build_metadata_filter(client_profile: Dict | None = None) -> Dict:
    """
    Optional metadata filter for Chroma queries.
    Example:
    {
        "industry": "logistics",
        "country": "india",
        "scale": "small"
    }
    """
    if not client_profile:
        return {}

    filters = {}

    if "industry" in client_profile:
        filters["industry"] = client_profile["industry"]

    if "country" in client_profile:
        filters["country"] = client_profile["country"]

    return filters
