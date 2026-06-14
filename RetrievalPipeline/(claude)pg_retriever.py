"""
PoliSense — Flexible Policy Retrieval from pgvector
====================================================
Schema (polisense_db_dev.policies):
    policy_id           UUID PK
    incentive_id        UUID
    parent_policy_name  TEXT
    policy_name         TEXT
    incentive_name      TEXT
    category            TEXT                  ← indexed
    industry            TEXT                  ← indexed
    sub_industry        TEXT                  ← indexed
    business_size       TEXT
    geography           TEXT                  ← indexed
    years               TEXT[]                ← GIN indexed
    policy_details      JSONB                 ← GIN indexed
                          .keywords []
                          .policy_goals []
                          .policy_summary
                          .eligibility_criteria
                          .special_attributes []
    incentive_details   JSONB
                          .description
                          .benefits {}
    embedding           VECTOR(N)             ← ivfflat cosine indexed
    created_at / updated_at

Pipeline:
  profile dict  →  LLM translation  →  embed  →  hybrid SQL+vector search
                →  LLM rerank + explain  →  ranked results
"""

import json
import os
import re
from typing import Any

import anthropic
import psycopg2
import psycopg2.extras
from openai import OpenAI
from IngestionPipeline.postgres_utils import get_connection

# ── Configuration ──────────────────────────────────────────────────────────────
conn = get_connection()

# Embedding dimension must match the VECTOR(N) in your schema.
# Change this to match whatever model you used when inserting rows.
EMBEDDING_DIM   = 384           # e.g. 384 for all-MiniLM-L6-v2, 1536 for text-embedding-3-small
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"  # OpenAI model name (swap freely) 

TOP_K   = 15   # vector candidates fetched before reranking
FINAL_N = 5    # results returned to caller after reranking

anthropic_client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
openai_client    = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


# ── Step 1: LLM translates arbitrary profile → search intent ──────────────────

TRANSLATION_SYSTEM_PROMPT = """
You are a policy-matching assistant for a government incentive discovery platform (PoliSense).

You receive a business profile as a JSON object. Field names may vary across
questionnaire versions — your job is to understand the meaning, not match keys.

Output a single JSON object with exactly two keys:

1. "semantic_query"
   A rich paragraph (150–250 words) describing the ideal government policy for
   this business. Write it as dense, keyword-rich prose that will be embedded
   and compared against policy descriptions. Cover:
   • Industry and sub-industry
   • Business size / MSME tier
   • State and geography context
   • Specific policy needs (subsidies, IP protection, export, etc.)
   • Ownership type and special attributes
   • Stage of growth

2. "filters"
   A JSON object for SQL WHERE filtering. Map profile values to these exact keys.
   Only include a key when you are confident of the value; omit or set null otherwise.

   Allowed keys and their semantics (matching the DB schema):
   {
     "industry":          string | null,   // e.g. "Manufacturing", "IT", "Food Processing"
     "sub_industry":      string | null,   // e.g. "Leather goods", "Automotive components"
     "category":          string | null,   // e.g. "Intellectual Property Rights", "Credit"
     "geography":         string | null,   // State name OR "National". Prefer specific state.
     "business_size":     string | null,   // "Micro" | "Small" | "Medium" — from MSME registration
     "years":             [string] | null, // e.g. ["2022", "2023"] if a recency filter makes sense
     "special_attributes": [string]        // always a list, empty [] if none apply
                                           // values must come from policy_details.special_attributes
   }

Output ONLY the raw JSON object — no markdown fences, no explanation.
"""


def build_search_intent(profile: dict[str, Any]) -> dict[str, Any]:
    """
    Step 1: Use Claude to convert an arbitrary business profile dict into:
      - a semantic query string (for embedding)
      - a structured filters dict (for SQL WHERE)
    """
    response = anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=TRANSLATION_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"Business profile:\n{json.dumps(profile, indent=2)}",
        }],
    )
    raw = response.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


# ── Step 2: Embed the semantic query ──────────────────────────────────────────

def embed_text(text: str) -> list[float]:
    """
    Embed a string. Swap this function body to change embedding provider.

    Alternatives:
      Cohere  → co.embed(texts=[text], model="embed-english-v3.0").embeddings[0]
      Local   → SentenceTransformer("all-MiniLM-L6-v2").encode(text).tolist()
    """
    response = openai_client.embeddings.create(model=EMBEDDING_MODEL, input=text)
    return response.data[0].embedding


# ── Step 3: Hybrid search (SQL filters + vector similarity) ───────────────────

def build_filter_clauses(filters: dict[str, Any]) -> tuple[str, list]:
    """
    Convert the LLM-generated filters dict into a parameterised SQL WHERE
    fragment. Each branch maps to an indexed column in the schema.

    Returns (where_sql, params_list).
    """
    clauses: list[str] = []
    params:  list[Any] = []

    # ── Indexed TEXT columns ─────────────────────────────────────────────────

    industry = filters.get("industry")
    if industry:
        # idx_policies_industry — use ILIKE for fuzzy match; still hits index via pg_trgm
        # For exact match use: clauses.append("industry = %s")
        clauses.append("industry ILIKE %s")
        params.append(f"%{industry}%")

    sub_industry = filters.get("sub_industry")
    if sub_industry:
        # idx_policies_sub_industry
        clauses.append("sub_industry ILIKE %s")
        params.append(f"%{sub_industry}%")

    category = filters.get("category")
    if category:
        # idx_policies_category
        clauses.append("category ILIKE %s")
        params.append(f"%{category}%")

    geography = filters.get("geography")
    if geography and geography.lower() != "national":
        # idx_policies_geography — always also include National policies
        clauses.append("(geography ILIKE %s OR geography ILIKE %s)")
        params.extend([f"%{geography}%", "%National%"])

    business_size = filters.get("business_size")
    if business_size:
        # business_size is freeform TEXT from LLM ingestion; partial match is safer
        clauses.append("business_size ILIKE %s")
        params.append(f"%{business_size}%")

    # ── GIN-indexed ARRAY column ─────────────────────────────────────────────

    years = filters.get("years") or []
    if years:
        # idx_policies_years — matches rows whose years[] overlaps the filter list
        clauses.append("years && %s::text[]")
        params.append(years)

    # ── GIN-indexed JSONB column: policy_details ─────────────────────────────

    special_attrs = filters.get("special_attributes") or []
    for attr in special_attrs:
        # idx_policies_details — containment check on the special_attributes array
        # e.g. policy_details->'special_attributes' @> '["IPR Awareness"]'
        clauses.append("policy_details->'special_attributes' @> %s::jsonb")
        params.append(json.dumps([attr]))

    where_sql = " AND ".join(clauses) if clauses else "TRUE"
    return where_sql, params


def retrieve_candidates(
    query_vector: list[float],
    filters: dict[str, Any],
    top_k: int = TOP_K,
) -> list[dict]:
    """
    Step 3: Run hybrid search against polisense_db_dev.policies.
      - Metadata pre-filter via indexed SQL WHERE clauses
      - Vector similarity ranking via pgvector <=> (cosine distance)
      - Returns top_k rows as dicts
    """
    where_sql, filter_params = build_filter_clauses(filters)

    # Build the vector literal once (psycopg2 doesn't auto-adapt list→vector)
    vector_str = f"[{','.join(str(v) for v in query_vector)}]"

    sql = f"""
        SELECT
            policy_id::text,
            incentive_id::text,
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
            1 - (embedding <=> %s::vector) AS similarity
        FROM policies
        WHERE {where_sql}
        ORDER BY embedding <=> %s::vector
        LIMIT %s;
    """
    # Parameter order: first %s = vector for similarity, then filter params,
    # second %s = vector for ORDER BY, then LIMIT
    params = [vector_str] + filter_params + [vector_str, top_k]

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    finally:
        conn.close()

    return [dict(r) for r in rows]


# ── Step 4: LLM reranks candidates and explains each match ────────────────────

RERANK_SYSTEM_PROMPT = """
You are a senior government policy advisor helping Indian businesses find
the most relevant incentive schemes on PoliSense.

You receive:
- A business profile (JSON)
- Candidate policies retrieved by vector similarity (JSON array)

Tasks:
1. Rerank the policies from most to least relevant for this specific business.
   Consider: industry fit, geography, MSME tier, special attributes, stated policy intent.
2. For each policy in your reranked list, produce a structured explanation.
3. Only return the top N policies (specified in "return_top_n").

Output a JSON array (length = return_top_n), each element:
{
  "rank":              integer,          // 1 = best match
  "policy_id":         string,           // from input
  "incentive_id":      string,           // from input
  "policy_name":       string,
  "incentive_name":    string,
  "parent_policy_name": string,
  "relevance_score":   float,            // 0.0 – 1.0
  "match_reason":      string,           // 2-3 sentences: WHY it fits this business
  "eligibility_gaps":  [string],         // what the business needs to verify/fix; [] if none
  "benefits_summary":  string            // one sentence: key financial/non-financial benefit
}

Output ONLY the raw JSON array — no markdown, no explanation.
"""


def rerank_and_explain(
    profile: dict[str, Any],
    candidates: list[dict],
    final_n: int = FINAL_N,
) -> list[dict]:
    """
    Step 4: Use Claude to rerank candidates and generate explanations.
    Passes a slimmed candidate payload to stay within token budget.
    """
    slim_candidates = []
    for c in candidates:
        pd = c.get("policy_details") or {}
        id_ = c.get("incentive_details") or {}
        slim_candidates.append({
            "policy_id":           c["policy_id"],
            "incentive_id":        c["incentive_id"],
            "parent_policy_name":  c["parent_policy_name"],
            "policy_name":         c["policy_name"],
            "incentive_name":      c["incentive_name"],
            "category":            c["category"],
            "industry":            c["industry"],
            "sub_industry":        c["sub_industry"],
            "business_size":       c["business_size"],
            "geography":           c["geography"],
            "similarity":          round(float(c["similarity"]), 4),
            # JSONB fields — pass key parts only
            "policy_summary":      pd.get("policy_summary", ""),
            "policy_goals":        pd.get("policy_goals", [])[:4],
            "eligibility_criteria": pd.get("eligibility_criteria", ""),
            "special_attributes":  pd.get("special_attributes", []),
            "keywords":            pd.get("keywords", []),
            # Incentive details
            "incentive_description": id_.get("description", ""),
            "benefits":            id_.get("benefits", {}),
        })

    payload = {
        "business_profile":   profile,
        "candidate_policies": slim_candidates,
        "return_top_n":       final_n,
    }

    response = anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=RERANK_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": json.dumps(payload, indent=2)}],
    )

    raw = response.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


# ── Public API ─────────────────────────────────────────────────────────────────

def find_matching_policies(
    business_profile: dict[str, Any],
    top_k:   int = TOP_K,
    final_n: int = FINAL_N,
    verbose: bool = True,
) -> list[dict]:
    """
    Full pipeline: business_profile → ranked policy matches.

    Parameters
    ----------
    business_profile : dict
        Raw answers from any version of the PoliSense questionnaire.
        The LLM handles mapping, so key names don't matter.
    top_k : int
        Vector-search candidates to fetch before LLM reranking.
    final_n : int
        Final matches to return after reranking.
    verbose : bool
        Print progress to stdout.

    Returns
    -------
    list[dict]  — length <= final_n, sorted by rank ascending.
        Each dict has: rank, policy_id, incentive_id, policy_name,
        incentive_name, parent_policy_name, relevance_score,
        match_reason, eligibility_gaps, benefits_summary.
    """
    def log(msg):
        if verbose:
            print(msg)

    log("→ [1/4] Translating business profile to search intent (LLM)...")
    intent = build_search_intent(business_profile)
    log(f"        Query preview : {intent['semantic_query'][:100]}...")
    log(f"        Filters       : {intent['filters']}")

    log("\n→ [2/4] Embedding semantic query...")
    query_vector = embed_text(intent["semantic_query"])
    log(f"        Vector dim    : {len(query_vector)}")

    log(f"\n→ [3/4] Hybrid search — top {top_k} candidates...")
    candidates = retrieve_candidates(query_vector, intent["filters"], top_k)
    log(f"        Candidates    : {len(candidates)}")

    if not candidates:
        log("        ⚠ No candidates found. Retrying without metadata filters...")
        candidates = retrieve_candidates(query_vector, {}, top_k)
        log(f"        Candidates (unfiltered): {len(candidates)}")
        if not candidates:
            return []

    log(f"\n→ [4/4] Reranking and explaining top {final_n} matches (LLM)...")
    results = rerank_and_explain(business_profile, candidates, final_n)
    log(f"        Done. Returning {len(results)} matches.\n")

    return results


# ── CLI demo ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    example_profile = {
        # Section 1 — Business Identity
        "business_name":        "Innovate Crafts Pvt Ltd",
        "legal_entity_type":    "Private Limited",
        "year_of_establishment": 2019,
        "ownership_type":       "Women-Owned (>51% women ownership)",

        # Section 2 — Industry & Operations
        "industry":             "Manufacturing (General)",
        "sub_industry":         "Handmade leather goods and accessories",
        "primary_activity":     "Manufacturing / Production",
        "products_services":    "Leather bags, wallets, and belts — domestic + export",

        # Section 3 — Business Size & Financials
        "employee_count":       38,
        "turnover_range":       "INR 1 – 5 Crore",
        "fixed_asset_investment": "Less than INR 1 Crore",
        "growth_stage":         "Early Growth",

        # Section 4 — Location
        "country":              "India",
        "state":                "Rajasthan",
        "district":             "Jodhpur",
        "location_type":        "Industrial Park / Cluster",

        # Section 5 — Registrations
        "msme_registration":    "Yes — Small Enterprise",
        "udyam_number":         "UDYAM-RJ-12-0045678",
        "dpiit_startup":        "No",
        "other_registrations":  ["GST Registration", "Export Import Code (IEC)"],

        # Section 6 — Special Attributes
        "special_attributes":   [
            "Women-led / Women-owned (> 51%)",
            "Export-oriented unit",
            "R&D / IP-driven",
        ],
        "multi_state_interest": "Yes — open to any state",
        "policy_intent":        [
            "Capital investment subsidy",
            "Export promotion",
            "Working capital / interest subsidy",
        ],
    }

    matches = find_matching_policies(example_profile, top_k=15, final_n=5)

    print("=" * 65)
    print(" POLISENSE — TOP POLICY MATCHES")
    print("=" * 65)
    for m in matches:
        print(f"\n  #{m['rank']}  {m['policy_name']}")
        if m.get("parent_policy_name"):
            print(f"       Parent   : {m['parent_policy_name']}")
        print(f"       Incentive: {m.get('incentive_name', '—')}")
        print(f"       Score    : {m['relevance_score']:.2f}  (similarity-based + LLM rerank)")
        print(f"       Benefits : {m['benefits_summary']}")
        print(f"       Why fit  : {m['match_reason']}")
        if m.get("eligibility_gaps"):
            print(f"       ⚠ Gaps  : {'; '.join(m['eligibility_gaps'])}")
    print()