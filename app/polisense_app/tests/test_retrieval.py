"""
Unit tests for the parts of retrieval.py that don't need a live database or
the embedding model: filter extraction, profile-to-text flattening, SQL
clause building, and MMR reranking.

Run with:
    python -m pytest tests/ -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from retrieval import (  # noqa: E402
    _normalise_business_size,
    build_filter_clauses,
    extract_filters,
    mmr_rerank,
    profile_to_text,
)

SAMPLE_PROFILE = {
    "business_name": "Innovate Crafts Pvt Ltd",
    "industry": "Manufacturing",
    "sub_industry": "Handmade leather goods and accessories",
    "state": "Rajasthan",
    "msme_registration": "Yes — Small Enterprise",
    "special_attributes": ["Women-led / Women-owned (> 51%)", "Export-oriented unit"],
    "policy_intent": ["Capital investment subsidy", "Export promotion"],
    "products_services": "Leather bags, wallets, and belts",
}


def test_normalise_business_size():
    assert _normalise_business_size("Yes — Small Enterprise") == "Small"
    assert _normalise_business_size("Micro") == "Micro"
    assert _normalise_business_size(None) is None
    assert _normalise_business_size("") is None


def test_extract_filters_basic():
    filters = extract_filters(SAMPLE_PROFILE)
    assert filters["industry"] == "Manufacturing"
    assert filters["geography"] == "Rajasthan"
    assert filters["business_size"] == "Small"


def test_extract_filters_missing_fields_are_none():
    filters = extract_filters({"business_name": "Empty Co"})
    assert filters["industry"] is None
    assert filters["geography"] is None
    assert filters["business_size"] is None


def test_profile_to_text_contains_key_facts():
    text = profile_to_text(SAMPLE_PROFILE)
    assert "Manufacturing" in text
    assert "Rajasthan" in text
    assert "Small Enterprise" in text
    assert "Export promotion" in text


def test_build_filter_clauses_industry_and_geography():
    filters = {"industry": "Manufacturing (General)", "geography": "Karnataka", "business_size": "Small"}
    where_sql, params = build_filter_clauses(filters)
    assert "industry ILIKE" in where_sql
    assert "geography ILIKE" in where_sql
    assert "business_size ILIKE" in where_sql
    # industry_token strips the parenthetical qualifier
    assert "%Manufacturing%" in params


def test_build_filter_clauses_empty_returns_true():
    where_sql, params = build_filter_clauses({})
    assert where_sql == "TRUE"
    assert params == []


def test_mmr_rerank_selects_top_n_and_ranks():
    candidates = [
        {"policy_id": "1", "similarity": 0.9, "embedding": [1.0, 0.0]},
        {"policy_id": "2", "similarity": 0.8, "embedding": [0.99, 0.1]},  # near-duplicate of #1
        {"policy_id": "3", "similarity": 0.7, "embedding": [0.0, 1.0]},  # diverse
    ]
    query_vector = [1.0, 0.0]
    results = mmr_rerank(query_vector, candidates, final_n=2, lmbda=0.5)

    assert len(results) == 2
    assert results[0]["mmr_rank"] == 1
    assert results[1]["mmr_rank"] == 2
    # The most relevant item should be picked first
    assert results[0]["policy_id"] == "1"


def test_mmr_rerank_empty_candidates():
    assert mmr_rerank([1.0, 0.0], [], final_n=5) == []
