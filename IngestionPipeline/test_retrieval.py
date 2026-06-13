# retrieval.py
import os
import json
import psycopg2
from pathlib import Path
from dotenv import load_dotenv
from langchain_huggingface import HuggingFaceEmbeddings
import utils
from IngestionPipeline.postgres_utils import get_connection

ROOT_PATH = Path(__file__).parent.parent
load_dotenv(ROOT_PATH / ".env")
load_dotenv(ROOT_PATH / ".env.secrets")

# ── Reuse the same embedding model from ingestion ──────────────────────────────
# embedding_model = HuggingFaceEmbeddings(model_name="BAAI/bge-small-en-v1.5")


def retrieve_policies(
    query: str,
    conn,
    top_k: int = 5,
    # Optional metadata filters — pass None to skip
    industry: str|None = None,
    category: str|None = None,
    geography: str|None = None,
    business_size: str|None = None,
) -> list[dict]:
    """
    Retrieve the most relevant policies for a given query using vector similarity.
    Optionally filter by metadata fields before ranking.
    """
    # BGE models perform better with this instruction prefix for queries
    prefixed_query = f"Represent this sentence for searching relevant passages: {query}"
    query_vector = utils.embed_documents(prefixed_query)

    # Build dynamic WHERE clause for optional metadata filters
    filters = []
    params = []

    if industry:
        filters.append("industry ILIKE %s")
        params.append(f"%{industry}%")
    if category:
        filters.append("category ILIKE %s")
        params.append(f"%{category}%")
    if geography:
        filters.append("geography ILIKE %s")
        params.append(f"%{geography}%")
    if business_size:
        filters.append("business_size ILIKE %s")
        params.append(f"%{business_size}%")

    where_clause = ("WHERE " + " AND ".join(filters)) if filters else ""

    sql = f"""
        SELECT
            policy_id,
            parent_policy_name,
            policy_name,
            incentive_name,
            category,
            industry,
            sub_industry,
            business_size,
            geography,
            years,
            policy_details,
            incentive_details,
            1 - (embedding <=> %s::vector) AS similarity_score
        FROM policies
        {where_clause}
        ORDER BY embedding <=> %s::vector
        LIMIT %s;
    """

    # query_vector appears twice (once for SELECT score, once for ORDER BY)
    params = [query_vector] + params + [query_vector, top_k]

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
        columns = [desc[0] for desc in cur.description]

    results = []
    for row in rows:
        record = dict(zip(columns, row))
        # psycopg2 auto-deserializes jsonb columns — no json.loads() needed
        record["policy_details"]    = record["policy_details"]   or {}
        record["incentive_details"] = record["incentive_details"] or {}
        results.append(record)

    return results


def pretty_print_results(results: list[dict]):
    """Human-readable display of retrieval results."""
    if not results:
        print("No results found.")
        return
    for i, r in enumerate(results, 1):
        print(f"\n{'═'*60}")
        print(f"  #{i}  [{r['similarity_score']:.4f}]  {r['parent_policy_name']}")
        print(f"{'═'*60}")
        print(f"  Policy      : {r['policy_name']}")
        print(f"  Incentive   : {r['incentive_name']}")
        print(f"  Category    : {r['category']}  |  Industry: {r['industry']}")
        print(f"  Geography   : {r['geography']}  |  Size: {r['business_size']}")
        print(f"  Summary     : {r['policy_details'].get('policy_summary', 'N/A')[:300]}")
        print(f"  Eligibility : {r['policy_details'].get('eligibility_criteria', 'N/A')[:200]}")
        inc = r["incentive_details"]
        if inc.get("description"):
            print(f"  Benefit     : {inc['description'][:200]}")


# ── Run directly to test ───────────────────────────────────────────────────────
if __name__ == "__main__":
    conn = get_connection()

    test_cases = [
        # ── EV Policy (Karnataka EV & Energy Storage Policy 2017) ─────────────
        {
            "label": "EV battery manufacturing subsidies for MSMEs",
            "query": "What subsidies are available for small businesses manufacturing EV batteries in Karnataka?",
            "filters": {"industry": "Automotive", "geography": "Karnataka"},
        },
        {
            "label": "Charging infrastructure incentives",
            "query": "capital subsidy for setting up EV fast charging and battery swapping stations",
            "filters": {"geography": "Karnataka"},
        },
        {
            "label": "Large enterprise EV investment incentives",
            "query": "production linked subsidy and capital subsidy for large enterprises investing in electric vehicle manufacturing",
            "filters": {"geography": "Karnataka"},
        },

        # ── Clean Mobility Policy 2025-30 ─────────────────────────────────────
        {
            "label": "Clean mobility transition support",
            "query": "incentives for transitioning from internal combustion engines to clean mobility vehicles",
            "filters": {"geography": "Karnataka"},
        },
        {
            "label": "EV adoption for transport operators",
            "query": "tax exemptions and benefits for operators adopting electric vehicles for public transport",
            "filters": {"geography": "Karnataka"},
        },

        # ── ESDM Policy 2017-2022 ─────────────────────────────────────────────
        {
            "label": "Electronics startup R&D grants",
            "query": "R&D grants and prototyping cost reimbursement for electronics startups",
            "filters": {"industry": "Electronics", "geography": "Karnataka"},
        },
        {
            "label": "Patent and international marketing support for ESDM",
            "query": "financial support for patent registration and international marketing for electronics manufacturers",
            "filters": {"geography": "Karnataka"},
        },
        {
            "label": "Power and stamp duty concessions for electronics",
            "query": "power tariff concession and stamp duty exemption for electronics system design companies",
            "filters": {"geography": "Karnataka"},
        },

        # ── Cross-policy queries (should surface results from multiple policies) ─
        {
            "label": "Cross-policy: MSME fiscal incentives",
            "query": "fiscal incentives like stamp duty exemption and land conversion fee reimbursement for MSMEs in Karnataka",
            "filters": {},  # no filter — let vector search rank across all policies
        },
        {
            "label": "Cross-policy: Employment and investment targets",
            "query": "policies targeting employment generation and large scale investment attraction in Karnataka",
            "filters": {},
        },
    ]

    for tc in test_cases:
        print(f"\n\n{'▓'*65}")
        print(f"  [{tc['label']}]")
        print(f"  QUERY : {tc['query']}")
        if tc["filters"]:
            print(f"  FILTER: {tc['filters']}")
        print(f"{'▓'*65}")

        results = retrieve_policies(
            query=tc["query"],
            conn=conn,
            top_k=3,
            **tc["filters"],
        )
        with open("retrieval_results.txt", 'w') as r:
            r.write(str(results))
        pretty_print_results(results)

    conn.close()