# retrieval.py
import os
import json
import psycopg2
import sys
from pathlib import Path

ROOT_PATH = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_PATH))

from dotenv import load_dotenv
# from langchain_huggingface import HuggingFaceEmbeddings

from IngestionPipeline.postgres_utils import get_connection, embed_documents
from BusinessProfile.business_profile_filters import *

load_dotenv(ROOT_PATH / ".env")
load_dotenv(ROOT_PATH / ".env.secrets")

# ── Reuse the same embedding model from ingestion ──────────────────────────────
# embedding_model = HuggingFaceEmbeddings(model_name="BAAI/bge-small-en-v1.5")

def save_results_to_file(
    all_results: list[dict],   # list of {profile, query, filters, results}
    output_path: str = "retrieval_results.txt"
):
    """Save pretty printed retrieval results for all profiles to a text file."""
    
    with open(output_path, "w", encoding="utf-8") as f:

        f.write("=" * 65 + "\n")
        f.write("  PoliSense — Retrieval Results\n")
        f.write(f"  Generated: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"  Total profiles: {len(all_results)}\n")
        f.write("=" * 65 + "\n\n")

        for entry in all_results:
            profile = entry["profile"]
            query   = entry["query"]
            filters = entry["filters"]
            results = entry["results"]

            # Profile header
            f.write("▓" * 65 + "\n")
            f.write(f"  Business : {profile.get('business_name')}\n")
            f.write(f"  Query    : {query}\n")
            f.write(f"  Filters  : {filters}\n")
            if entry.get("signals"):
                f.write(f"  Signals  : {entry['signals']}\n")
            f.write("▓" * 65 + "\n")

            if not results:
                f.write("\n  No results found.\n\n")
                continue

            seen = set()
            rank = 1
            for r in results:
                if r["policy_id"] in seen:
                    continue
                seen.add(r["policy_id"])

                f.write(f"\n{'═' * 60}\n")
                f.write(f"  #{rank}  [{r['similarity_score']:.4f}]  {r['parent_policy_name']}\n")
                f.write(f"{'═' * 60}\n")
                f.write(f"  Policy      : {r['policy_name']}\n")
                f.write(f"  Incentive   : {r['incentive_name']}\n")
                f.write(f"  Category    : {r['category']}  |  Industry: {r['industry']}\n")
                f.write(f"  Geography   : {r['geography']}  |  Size: {r['business_size']}\n")
                summary     = (r['policy_details'].get('policy_summary') or 'N/A')[:300]
                eligibility = (r['policy_details'].get('eligibility_criteria') or 'N/A')[:200]
                description = (r['incentive_details'].get('description') or '')[:200]
                f.write(f"  Summary     : {summary}\n")
                f.write(f"  Eligibility : {eligibility}\n")
                if description:
                    f.write(f"  Benefit     : {description}\n")
                rank += 1

            f.write("\n")

    print(f"✅ Results saved to {output_path}")

def retrieve_policies(
    query: str,
    conn,
    top_k: int = 5,
    # Optional metadata filters — pass None to skip
    industry: str = None,
    category: str = None,
    geography: str = None,
    business_size: str = None,
    sub_industry: str = None,
) -> list[dict]:
    """
    Retrieve the most relevant policies for a given query using vector similarity.
    Optionally filter by metadata fields before ranking.
    """
    # BGE models perform better with this instruction prefix for queries
    prefixed_query = f"Represent this sentence for searching relevant passages: {query}"
    query_vector = embed_documents(prefixed_query)

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
    # if business_size:
    #     filters.append("business_size ILIKE %s")
    #     params.append(f"%{business_size}%")
    if sub_industry:                            # ← add this block
        filters.append("sub_industry ILIKE %s")
        params.append(f"%{sub_industry}%")

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
    # params = params + [top_k]

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

    SAMPLE_PROFILES = [
        {
            "business_name": "VoltEdge Battery Pvt Ltd",
            "industry":      "Automotive, Energy Storage",        # exact DB value
            "sub_industry":  "EV Battery Manufacturing",          # exact DB value
            "geography":     "Karnataka",                         # exact DB value
            "business_size": "Startup",                           # exact DB value
            "ownership_type": "Private",
            "special_attributes": ["Startup", "Deep Tech"],
        },
        {
            "business_name": "ChargeFast Solutions Pvt Ltd",
            "industry":      "Automotive, Energy Storage",
            "sub_industry":  "Charging Infrastructure",
            "geography":     "Karnataka",
            "business_size": "Small Enterprise",
            "ownership_type": "Private",
        },
        {
            "business_name": "GreenFleet Mobility Pvt Ltd",
            "industry":      "Clean Mobility",
            "sub_industry":  None,                                # not set → skipped as filter
            "geography":     "Karnataka",
            "business_size": "Startup",
            "ownership_type": "Women-Owned",
            "special_attributes": ["Startup", "Women-led"],
        },
        {
            "business_name": "NeuralChip Technologies Pvt Ltd",
            "industry":      "Electronics System Design & Manufacturing (ESDM)",
            "sub_industry":  "semiconductors",
            "geography":     "Karnataka",
            "business_size": "Startup",
            "ownership_type": "Private",
            "special_attributes": ["Deep Tech"],
        },
        {
            "business_name": "MedSense Electronics Pvt Ltd",
            "industry":      "Electronics System Design & Manufacturing (ESDM)",
            "sub_industry":  "Medical Electronics",
            "geography":     "Karnataka",
            "business_size": "Micro Enterprise",
            "ownership_type": "Women-Owned",
            "special_attributes": ["Women-led", "Export-oriented"],
        },
        {
            "business_name": "IdeaSpark Innovations Pvt Ltd",
            "industry":      None,   # AI/ML not in DB → no industry filter applied
            "sub_industry":  None,
            "geography":     None,   # Telangana not in DB → no geography filter
            "business_size": "Small Enterprise",
            "ownership_type": "Private",
            "special_attributes": ["Startup", "Youth-led"],
        },
    ]

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

    canonical = get_canonical_values(conn)
    validator = ProfileValidator(canonical)
    all_results = []
    for profile in SAMPLE_PROFILES:
        try:
            clean_profile = validator.validate(profile)
            query   = generate_query_from_profile(clean_profile)
            filters = extract_filters(clean_profile)
            signals = filters.pop("_special_signals", [])
            signal_context = " ".join(signals)

            print(f"\n{profile['business_name']}")
            print(f"  query  : {query}")
            print(f"  filters: {filters}")

            results = retrieve_policies(
                query=query,
                conn=conn,
                top_k=10,
                **filters,
            )
            pretty_print_results(results)
            # Collect for file
            all_results.append({
                "profile": profile,
                "query":   query,
                "filters": filters,
                "signals": signals,
                "results": results,
            })
        except ValueError as e:
            print(f"\n {e}")
            all_results.append({
                "profile": profile,
                "query":   "",
                "filters": {},
                "signals": [],
                "results": [],
            })


    # for tc in test_cases:
    #     print(f"\n\n{'▓'*65}")
    #     print(f"  [{tc['label']}]")
    #     print(f"  QUERY : {tc['query']}")
    #     if tc["filters"]:
    #         print(f"  FILTER: {tc['filters']}")
    #     print(f"{'▓'*65}")

    #     results = retrieve_policies(
    #         query=tc["query"],
    #         conn=conn,
    #         top_k=3,
    #         **tc["filters"],
    #     )
    #     with open("retrieval_results.txt", 'w') as r:
    #         r.write(str(results))
    #     pretty_print_results(results)
    save_results_to_file(all_results, output_path="retrieval_results.txt")
    conn.close()