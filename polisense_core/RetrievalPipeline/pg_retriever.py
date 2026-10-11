import os
import json
import psycopg2
from pathlib import Path
from dotenv import load_dotenv

from polisense_core.utils.postgres_utils import get_connection, embed_documents

ROOT_PATH = Path(__file__).parent.parent.parent  # project root: PoliSense/
load_dotenv(ROOT_PATH / ".env")
load_dotenv(ROOT_PATH / ".env.secrets")

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


def write_single_result(
    query_name: str,
    entry: dict,
    output_path: str,
) -> None:
    """
    Write retrieval results for a single query-profile pair to a text file.

    Args:
        query_name: human-readable label used in the file header.
        entry:      {"query": str, "profile": dict, "filters": dict, "results": list[dict]}
        output_path: full path to write the file.
    """
    import datetime

    profile = entry.get("profile", {})
    query   = entry.get("query", "")
    filters = entry.get("filters", {})
    results = entry.get("results", [])

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("=" * 65 + "\n")
        f.write(f"  PoliSense — {query_name}\n")
        f.write(f"  Generated : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 65 + "\n\n")

        f.write("▓" * 65 + "\n")
        f.write(f"  Business : {profile.get('business_name', 'N/A')}\n")
        f.write(f"  Query    : {query}\n")
        f.write(f"  Filters  : {filters}\n")
        f.write("▓" * 65 + "\n")

        if not results:
            f.write("\n  No results found.\n\n")
            return

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
    if business_size:
        filters.append("business_size ILIKE %s")
        params.append(f"%{business_size}%")
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

    def _query_from_profile(profile: dict) -> str:
        parts = []
        if profile.get("industry"):
            parts.append(profile["industry"])
        if profile.get("sub_industry"):
            parts.append(profile["sub_industry"])
        if profile.get("business_size"):
            parts.append(f"{profile['business_size']} businesses")
        if profile.get("geography"):
            parts.append(f"in {profile['geography']}")
        if profile.get("special_attributes"):
            parts.append(f"({', '.join(profile['special_attributes'])})")
        base = "government grants and incentives for "
        return base + " ".join(parts) if parts else base.strip()

    def _filters_from_profile(profile: dict) -> dict:
        allowed = ("industry", "sub_industry", "geography", "business_size", "category")
        return {k: v for k, v in profile.items() if k in allowed and v is not None}

    all_results = []
    for profile in SAMPLE_PROFILES:
        query   = _query_from_profile(profile)
        filters = _filters_from_profile(profile)

        print(f"\n{profile['business_name']}")
        print(f"  query  : {query}")
        print(f"  filters: {filters}")

        results = retrieve_policies(query=query, conn=conn, top_k=10, **filters)
        pretty_print_results(results)

        all_results.append({
            "profile": profile,
            "query":   query,
            "filters": filters,
            "signals": profile.get("special_attributes", []),
            "results": results,
        })

    save_results_to_file(all_results, output_path="retrieval_results.txt")
    conn.close()