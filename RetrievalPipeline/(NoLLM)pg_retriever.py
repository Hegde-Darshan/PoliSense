"""
PoliSense — No-LLM Retrieval: Rule-Based Filters + Profile Embedding + MMR
===========================================================================
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
  profile dict  →  rule-based field extraction  →  SQL WHERE filters
                →  flatten profile to text  →  embed  →  vector search
                →  fetch candidate embeddings  →  MMR rerank  →  results

Differences from the LLM version (polisense_retrieval.py):
  • No LLM calls anywhere — zero API cost for the retrieval step itself
  • Profile→filter mapping is deterministic rule-based extraction
  • Query vector = embedding of the raw flattened profile text
  • Reranking uses Maximal Marginal Relevance (MMR) instead of LLM judgment
    to balance relevance vs. result diversity

Trade-offs vs. LLM version:
  ✓ Faster, cheaper, fully deterministic
  ✗ Filter extraction is only as good as questionnaire field name conventions
  ✗ No natural-language explanation or eligibility gap analysis in results
  ✗ MMR optimises diversity, not semantic quality — may surface noisier matches
"""

import json
import math
import os
from typing import Any
import sys
from pathlib import Path

ROOT_PATH = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_PATH))

import psycopg2
import psycopg2.extras
from openai import OpenAI
from IngestionPipeline.postgres_utils import get_connection
from sentence_transformers import SentenceTransformer



EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
TOP_K   = 30   # wider candidate pool before MMR (no LLM to rerank, so fetch more)
FINAL_N = 5    # results returned after MMR
MMR_LAMBDA = 0.6  # λ: 1.0 = pure relevance, 0.0 = pure diversity. 0.6 is a good default.

# openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


# ── Step 1: Rule-based filter extraction ──────────────────────────────────────
#
# This replaces the LLM translation step. We look for values in the profile
# dict using a prioritised list of candidate keys for each filter dimension.
# Because the questionnaire may rename fields across versions, each dimension
# has multiple aliases. The first non-empty match wins.
#
# HOW TO EXTEND: add new aliases to any FIELD_ALIASES entry, or add a new
# dimension entry. No other code needs to change.

FIELD_ALIASES: dict[str, list[str]] = {
    # Maps filter dimension → candidate profile keys, in priority order
    "industry": [
        "industry", "industry_sector", "primary_industry", "sector",
        "business_sector", "main_industry",
    ],
    "sub_industry": [
        "sub_industry", "sub_sector", "specific_industry", "product_focus",
        "industry_focus", "niche",
    ],
    "category": [
        "policy_category", "category", "incentive_category", "scheme_category",
    ],
    "geography": [
        "state", "geography", "location_state", "operating_state",
        "registered_state", "region",
    ],
    "business_size": [
        # Prefer explicit MSME tier labels; fall back to registration strings
        "msme_tier", "business_size", "enterprise_size", "msme_category",
        "msme_registration", "registration_msme", "udyam_category",
    ],
    "special_attributes": [
        "special_attributes", "special_categories", "business_attributes",
        "attributes", "categories", "qualifications",
    ],
    "years": [
        "policy_years", "scheme_years", "years", "year_filter",
    ],
    "policy_intent": [
        # Used to enrich the text query; not a direct SQL filter
        "policy_intent", "policy_goals", "incentive_goals", "support_needed",
        "seeking", "requirements",
    ],
}

MSME_TIER_TO_DB_TOKEN: dict[str, list[str]] = {
    # A Micro business matches rows that mention Micro OR MSME
    "Micro":  ["Micro", "MSME"],
    # A Small business matches rows that mention Small OR MSME
    # (rows like "Micro and Small Enterprises" also contain "Small")
    "Small":  ["Small", "MSME"],
    # A Medium business matches rows that mention Medium OR MSME
    "Medium": ["Medium", "MSME"],
}

# Normalise free-text MSME registration answers → canonical size tokens
# Extend this map as new questionnaire phrasings appear
MSME_SIZE_NORMALISATION: dict[str, str] = {
    "micro":   "Micro",
    "small":   "Small",
    "medium":  "Medium",
    "msme": "MSME",
    "startup": "Startup"
}


def _first_value(profile: dict[str, Any], keys: list[str]) -> Any:
    """Return the first non-None, non-empty value found for any key in keys."""
    for k in keys:
        v = profile.get(k)
        if v is not None and v != "" and v != []:
            return v
    return None


def _normalise_business_size(raw: Any) -> str | None:
    """
    Extract a canonical MSME size string from whatever the profile field holds.
    Handles:
      "Yes — Small Enterprise"  →  "Small"
      "Small"                   →  "Small"
      "msme_small"              →  "Small"
    """
    if not raw:
        return None
    text = str(raw).lower()
    for token, canonical in MSME_SIZE_NORMALISATION.items():
        if token in text:
            return canonical
    return None


def extract_filters(profile: dict[str, Any]) -> dict[str, Any]:
    """
    Step 1: Deterministically extract SQL-ready filter values from the profile.

    Returns a filters dict with the same keys expected by build_filter_clauses().
    Values are None / [] when no confident match is found — those dimensions
    are simply skipped (no filter applied), keeping recall high.
    """
    filters: dict[str, Any] = {}

    industry = _first_value(profile, FIELD_ALIASES["industry"])
    filters["industry"] = str(industry).strip() if industry else None

    # sub_industry = _first_value(profile, FIELD_ALIASES["sub_industry"])
    # filters["sub_industry"] = str(sub_industry).strip() if sub_industry else None

    category = _first_value(profile, FIELD_ALIASES["category"])
    filters["category"] = str(category).strip() if category else None

    geography = _first_value(profile, FIELD_ALIASES["geography"])
    filters["geography"] = str(geography).strip() if geography else None

    raw_size = _first_value(profile, FIELD_ALIASES["business_size"])
    filters["business_size"] = _normalise_business_size(raw_size)

    # raw_attrs = _first_value(profile, FIELD_ALIASES["special_attributes"])
    # if isinstance(raw_attrs, list):
    #     filters["special_attributes"] = [str(a).strip() for a in raw_attrs if a]
    # elif isinstance(raw_attrs, str) and raw_attrs:
    #     filters["special_attributes"] = [raw_attrs.strip()]
    # else:
    #     filters["special_attributes"] = []

    # raw_years = _first_value(profile, FIELD_ALIASES["years"])
    # if isinstance(raw_years, list):
    #     filters["years"] = [str(y) for y in raw_years]
    # elif isinstance(raw_years, str) and raw_years:
    #     filters["years"] = [raw_years]
    # else:
    #     filters["years"] = []

    return filters


# ── Step 2: Flatten profile to embeddable text ────────────────────────────────

def profile_to_text(profile: dict[str, Any]) -> str:
    """
    Step 2: Convert the business profile dict into a single text string
    suitable for embedding.

    Strategy: produce a structured prose paragraph that mirrors what a policy
    document might say about an ideal beneficiary. This increases cosine
    similarity with relevant policy embeddings vs. dumping raw JSON.

    No LLM is used — we template the known fields directly.
    """
    parts: list[str] = []

    # Helper: pull value using aliases, return empty string if missing
    def get(dim: str) -> str:
        v = _first_value(profile, FIELD_ALIASES[dim])
        return str(v).strip() if v else ""

    industry     = get("industry")
    sub_industry = get("sub_industry")
    geography    = get("geography")
    biz_size     = _normalise_business_size(
        _first_value(profile, FIELD_ALIASES["business_size"])
    ) or ""
    attrs        = _first_value(profile, FIELD_ALIASES["special_attributes"]) or []
    intent       = _first_value(profile, FIELD_ALIASES["policy_intent"]) or []

    # Pull a few extra fields directly (common across questionnaire versions)
    products     = profile.get("products_services") or profile.get("products") or ""
    growth_stage = profile.get("growth_stage") or profile.get("stage") or ""
    location_type= profile.get("location_type") or ""
    registrations= profile.get("other_registrations") or profile.get("registrations") or []

    # Build readable prose
    if industry:
        line = f"Industry: {industry}"
        if sub_industry:
            line += f" — specifically {sub_industry}"
        parts.append(line)

    if products:
        parts.append(f"Products / services: {products}")

    if biz_size:
        parts.append(f"MSME tier: {biz_size} Enterprise")

    if geography:
        parts.append(f"Location: {geography}, India")
    if location_type:
        parts.append(f"Location type: {location_type}")

    if growth_stage:
        parts.append(f"Growth stage: {growth_stage}")

    if isinstance(attrs, list) and attrs:
        parts.append(f"Special attributes: {', '.join(attrs)}")

    if isinstance(intent, list) and intent:
        parts.append(f"Policy needs: {', '.join(intent)}")
    elif isinstance(intent, str) and intent:
        parts.append(f"Policy needs: {intent}")

    if isinstance(registrations, list) and registrations:
        parts.append(f"Registrations held: {', '.join(registrations)}")

    # Append any remaining string values the template didn't cover, so nothing
    # from the profile is silently dropped when a new field is added
    covered_keys = {
        k for dim in FIELD_ALIASES.values() for k in dim
    } | {
        "products_services", "products", "growth_stage", "stage",
        "location_type", "other_registrations", "registrations",
    }
    extras = [
        f"{k}: {v}"
        for k, v in profile.items()
        if k not in covered_keys and isinstance(v, (str, int, float)) and v
    ]
    if extras:
        parts.append("Additional context: " + "; ".join(extras))

    return "\n".join(parts)


# ── Step 3: Embed the profile text ────────────────────────────────────────────

def embed_text(text: str) -> list[float]:
    """
      Local   → SentenceTransformer("all-MiniLM-L6-v2").encode(text).tolist()
    """
    model = SentenceTransformer("BAAI/bge-small-en-v1.5")  # fresh every time, no cache
    result = model.encode(text, normalize_embeddings=True).tolist()
    print(f"Input len: {len(text)}, vec[:3]: {result[:3]}")
    return result


# ── Step 4: Hybrid search ─────────────────────────────────────────────────────


def build_filter_clauses(filters: dict[str, Any]) -> tuple[str, list]:
    """
    Convert filters dict → parameterised SQL WHERE fragment.
 
    Each clause is written to match the actual stored values in the DB:
 
    industry
        Stored as short labels: "Manufacturing", "MSME", "General", etc.
        Strip any parenthetical qualifier from the profile value before
        matching, e.g. "Manufacturing (General)" → search for "Manufacturing".
        Also always include rows where industry = "Multiple Industries" or
        "Multi-sectoral" since those are catch-all rows relevant to everyone.
 
    geography
        Only two state values exist: "Karnataka" and "National".
        If the profile state isn't in the DB we still want National policies,
        so we always include geography = 'National' as an OR branch.
        The state-specific OR branch is added only when the state is present
        in the DB — avoids a clause that matches nothing and makes the AND
        combination too restrictive.
 
    business_size
        Stored as verbose multi-tier strings, never a single tier.
        We search for each DB token that corresponds to the profile's MSME
        tier using OR, so "Small" matches both "Micro and Small Enterprises"
        and "Micro, Small and Medium Enterprises (MSMEs)" and plain "MSME".
 
    sub_industry / category / years / special_attributes
        Unchanged — these work as before.
    """
    clauses: list[str] = []
    params:  list[Any] = []
 
    # ── industry ─────────────────────────────────────────────────────────────
    industry = filters.get("industry")
    if industry:
        # Strip parenthetical qualifiers: "Manufacturing (General)" → "Manufacturing"
        industry_token = industry.split("(")[0].strip()
        # Match the specific industry OR catch-all multi-sector rows.
        # Hardcoded literals use %% so psycopg2 does not treat them as
        # parameter placeholders — they render as literal % in the query.
        clauses.append(
            "(industry ILIKE %s"
            " OR industry ILIKE '%%Multiple Industries%%'"
            " OR industry ILIKE '%%Multi-sectoral%%'"
            " OR industry ILIKE '%%MSME%%')"
        )
        params.append(f"%{industry_token}%")
 
    # ── sub_industry ─────────────────────────────────────────────────────────
    # sub_industry = filters.get("sub_industry")
    # if sub_industry:
    #     clauses.append("sub_industry ILIKE %s")
    #     params.append(f"%{sub_industry}%")
 
    # ── category ─────────────────────────────────────────────────────────────
    category = filters.get("category")
    if category:
        clauses.append("category ILIKE %s")
        params.append(f"%{category}%")
 
    # ── geography ─────────────────────────────────────────────────────────────
    # Always include National policies. Add a state-specific OR only when
    # the profile state actually exists as a geography value in the DB.
    # Known state values in DB: "Karnataka", "State-specific (Karnataka)"
    # If you add more states to the DB, extend KNOWN_DB_STATES below.
    KNOWN_DB_STATES: set[str] = {
        "karnataka",
    }
    geography = filters.get("geography")
    if geography and geography.lower() != "national":
        if geography.lower() in KNOWN_DB_STATES:
            # State exists in DB — include both state and National rows
            clauses.append(
                "(geography ILIKE %s OR geography ILIKE '%%National%%')"
            )
            params.append(f"%{geography}%")
        else:
            # State not in DB — only return National policies rather than
            # applying a filter that would match nothing
            clauses.append("geography ILIKE '%%National%%'")
            # params.append(f"%National%")
    # If geography is "National" or missing, no clause added → all rows included
 
    # ── business_size ─────────────────────────────────────────────────────────
    business_size = filters.get("business_size")  # canonical: "Micro"|"Small"|"Medium"
    if business_size:
        db_tokens = MSME_TIER_TO_DB_TOKEN.get(business_size, [business_size])
        # print(db_tokens)
        # Build: (business_size ILIKE '%Small%' OR business_size ILIKE '%MSME%')
        or_parts = " OR ".join("business_size ILIKE %s" for _ in db_tokens)
        # print(or_parts)
        clauses.append(f"({or_parts})")
        params.extend(f"%{token}%" for token in db_tokens)
        # print(params)
 
    # ── years ─────────────────────────────────────────────────────────────────
    # years = filters.get("years") or []
    # if years:
    #     clauses.append("years && %s::text[]")
    #     params.append(years)
 
    # # ── special_attributes (JSONB containment) ────────────────────────────────
    # for attr in filters.get("special_attributes") or []:
    #     clauses.append("policy_details->'special_attributes' @> %s::jsonb")
    #     params.append(json.dumps([attr]))
 
    return (" AND ".join(clauses) if clauses else "TRUE"), params
 

def retrieve_candidates(
    query_vector: list[float],
    filters: dict[str, Any],
    top_k: int = TOP_K,
) -> list[dict]:
    """
    Step 4: Hybrid search — SQL filters + cosine vector ranking.

    Also fetches the embedding column so MMR can compute inter-result
    similarity without a second round-trip to the DB.
    """
    where_sql, filter_params = build_filter_clauses(filters)
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
            embedding::text                                    AS embedding_text,
            1 - (embedding <=> %s::vector)                    AS similarity
        FROM policies
        WHERE {where_sql}
        ORDER BY embedding <=> %s::vector
        LIMIT %s;
    """
    params = [vector_str] + filter_params + [vector_str, top_k]
    # print(filter_params)
    # print(len(params))
    conn = get_connection()

    # conn = psycopg2.connect(**DB_CONFIG)
    try:
        # print(sql)
        # print(params)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    finally:
        conn.close()

    # Parse the embedding text back to list[float] for MMR
    results = []
    for row in rows:
        r = dict(row)
        raw_emb = r.pop("embedding_text", None)
        if raw_emb:
            # pgvector returns embeddings as "[0.1,0.2,...]"
            r["embedding"] = [float(x) for x in raw_emb.strip("[]").split(",")]
        else:
            r["embedding"] = []
        results.append(r)
    return results


# ── Step 5: MMR reranking ─────────────────────────────────────────────────────
#
# Maximal Marginal Relevance (Carbonell & Goldstein, 1998):
#
#   MMR(d_i) = λ · sim(d_i, query) − (1 − λ) · max_{d_j ∈ S} sim(d_i, d_j)
#
# At each iteration we pick the candidate that maximises this score, where S
# is the set of already-selected results. λ controls the relevance/diversity
# trade-off. A higher λ (→1) favours relevance; lower (→0) favours diversity.
#
# Why MMR here?
#   Without an LLM to judge quality, raw cosine results often cluster around
#   the same parent policy (all its sub-schemes score similarly). MMR pushes
#   diverse policies to the top so the user sees a broader set of options.


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def mmr_rerank(
    query_vector: list[float],
    candidates:   list[dict],
    final_n:      int   = FINAL_N,
    lmbda:        float = MMR_LAMBDA,
) -> list[dict]:
    """
    Step 5: Rerank candidates using Maximal Marginal Relevance.

    Parameters
    ----------
    query_vector : list[float]
        The embedded business profile query.
    candidates : list[dict]
        Rows from retrieve_candidates(), each with an "embedding" field.
    final_n : int
        How many results to return.
    lmbda : float
        λ in the MMR formula. 0.6 balances relevance and diversity well.

    Returns
    -------
    list[dict]
        final_n results with an added "mmr_rank" and "mmr_score" field.
    """
    if not candidates:
        return []

    remaining = list(candidates)  # candidates not yet selected
    selected:  list[dict] = []

    while remaining and len(selected) < final_n:
        best_score = -float("inf")
        best_item  = None

        for candidate in remaining:
            emb = candidate.get("embedding") or []
            if not emb:
                # No embedding stored — fall back to similarity score only
                relevance = float(candidate.get("similarity", 0))
            else:
                relevance = _cosine(query_vector, emb)

            # Penalise by maximum similarity to any already-selected result
            if selected:
                max_redundancy = max(
                    _cosine(emb, s.get("embedding") or [])
                    for s in selected
                    if emb and s.get("embedding")
                )
            else:
                max_redundancy = 0.0

            mmr_score = lmbda * relevance - (1 - lmbda) * max_redundancy

            if mmr_score > best_score:
                best_score = mmr_score
                best_item  = candidate

        if best_item is None:
            break

        best_item["mmr_rank"]  = len(selected) + 1
        best_item["mmr_score"] = round(best_score, 4)
        selected.append(best_item)
        remaining.remove(best_item)

    return selected


# ── Public API ─────────────────────────────────────────────────────────────────

def find_matching_policies(
    business_profile: dict[str, Any],
    top_k:   int   = TOP_K,
    final_n: int   = FINAL_N,
    lmbda:   float = MMR_LAMBDA,
    verbose: bool  = True,
) -> list[dict]:
    """
    Full no-LLM pipeline: business_profile → MMR-ranked policy matches.

    Parameters
    ----------
    business_profile : dict
        Raw questionnaire answers. Any key names are fine — aliases handle
        the mapping.
    top_k : int
        Vector-search candidates to fetch before MMR. Use a larger value
        than the LLM pipeline (default 30) since MMR is cheap.
    final_n : int
        Results to return after MMR reranking.
    lmbda : float
        MMR diversity weight. 0.6 is a good starting point.
        Increase toward 1.0 for more relevance, decrease for more diversity.
    verbose : bool
        Print progress to stdout.

    Returns
    -------
    list[dict]
        Policies sorted by mmr_rank (1 = best). Each dict includes all DB
        columns plus mmr_rank and mmr_score.
    """
    def log(msg):
        if verbose:
            print(msg)

    log("→ [1/4] Extracting filters from business profile (rule-based)...")
    filters = extract_filters(business_profile)
    log(f"        Filters: {filters}")

    log("\n→ [2/4] Building profile text and embedding...")
    profile_text = profile_to_text(business_profile)
    log(f"        Profile text preview: {profile_text[:120]}...")
    query_vector = embed_text(profile_text)
    log(f"        Vector dim: {len(query_vector)}")

    log(f"\n→ [3/4] Hybrid search — top {top_k} candidates...")
    candidates = retrieve_candidates(query_vector, filters, top_k)
    log(f"        Candidates: {len(candidates)}")

    if not candidates:
        log("        ⚠ No candidates found. Retrying without metadata filters...")
        candidates = retrieve_candidates(query_vector, {}, top_k)
        log(f"        Candidates (unfiltered): {len(candidates)}")
        if not candidates:
            return []

    log(f"\n→ [4/4] MMR reranking (λ={lmbda}) → top {final_n}...")
    results = mmr_rerank(query_vector, candidates, final_n, lmbda)
    log(f"        Done. Returning {len(results)} results.\n")

    return results


# ── CLI demo ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    example_profile = {
        "business_name":          "Innovate Crafts Pvt Ltd",
        "legal_entity_type":      "Private Limited",
        "year_of_establishment":  2019,
        "ownership_type":         "Women-Owned (>51% women ownership)",
        "industry":               "Manufacturing",
        "sub_industry":           "Handmade leather goods and accessories",
        "primary_activity":       "Manufacturing / Production",
        "products_services":      "Leather bags, wallets, and belts — domestic + export",
        "employee_count":         38,
        "turnover_range":         "INR 1 – 5 Crore",
        "fixed_asset_investment": "Less than INR 1 Crore",
        "growth_stage":           "Early Growth",
        "country":                "India",
        "state":                  "Rajasthan",
        "district":               "Jodhpur",
        "location_type":          "Industrial Park / Cluster",
        "msme_registration":      "Yes — Small Enterprise",
        "udyam_number":           "UDYAM-RJ-12-0045678",
        "dpiit_startup":          "No",
        "other_registrations":    ["GST Registration", "Export Import Code (IEC)"],
        "special_attributes":     [
            "Women-led / Women-owned (> 51%)",
            "Export-oriented unit",
            "R&D / IP-driven",
        ],
        "multi_state_interest":   "Yes — open to any state",
        "policy_intent":          [
            "Capital investment subsidy",
            "Export promotion",
            "Working capital / interest subsidy",
        ],
    }

    matches = find_matching_policies(
        example_profile,
        top_k=30,
        final_n=5,
        lmbda=0.6,
    )

    print("=" * 65)
    print(" POLISENSE — TOP POLICY MATCHES  (no-LLM / MMR)")
    print("=" * 65)
    for m in matches:
        pd = m.get("policy_details") or {}
        id_ = m.get("incentive_details") or {}
        print(f"\n  #{m['mmr_rank']}  {m['policy_name']}")
        if m.get("parent_policy_name"):
            print(f"       Parent    : {m['parent_policy_name']}")
        print(f"       Incentive : {m.get('incentive_name', '—')}")
        print(f"       Geography : {m.get('geography', '—')}")
        print(f"       Size      : {m.get('business_size', '—')}")
        print(f"       Similarity: {m.get('similarity', 0):.4f}  "
              f"MMR score: {m['mmr_score']:.4f}")
        summary = pd.get("policy_summary", "")
        if summary:
            print(f"       Summary   : {summary[:160]}...")
        benefits = id_.get("benefits") or {}
        if benefits:
            benefit_str = "; ".join(f"{k}: {v}" for k, v in benefits.items())
            print(f"       Benefits  : {benefit_str[:160]}")
    print()