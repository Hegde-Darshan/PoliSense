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



def build_chroma_where_filter(filters: dict) -> dict:
    """
    Convert flat metadata filters into a Chroma-compatible where clause.
    """
    clauses = []

    for key, values in filters.items():
        if not values:
            continue

        # Normalize single value → list
        if not isinstance(values, list):
            values = [values]

        clauses.append({
            key: {"$in": values}
        })

    if not clauses:
        return {}

    if len(clauses) == 1:
        return clauses[0]

    return {"$or": clauses}
