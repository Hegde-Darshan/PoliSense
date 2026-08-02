"""
retrieval.py
============
PoliSense — No-LLM Retrieval: Rule-Based Filters + Profile Embedding + MMR

This is a production-ready, standalone adaptation of the reference
`polisense_retrieval.py` (no-LLM branch) provided by the team. It has no
dependency on any external project module — everything it needs lives in
this file (plus `config.py` / `logging_config.py`).

Schema (polisense_db_dev.policies):
    policy_id           UUID PK
    incentive_id        UUID
    parent_policy_name  TEXT
    policy_name         TEXT
    incentive_name      TEXT
    category            TEXT                  ← indexed
    industry            TEXT                  ← indexed
    sub_industry        TEXT                  ← indexed
    business_size        TEXT
    geography            TEXT                  ← indexed
    years                TEXT[]                ← GIN indexed
    policy_details        JSONB                 ← GIN indexed
                          .keywords []
                          .policy_goals []
                          .policy_summary
                          .eligibility_criteria
                          .special_attributes []
    incentive_details   JSONB
                          .description
                          .benefits {}
    embedding            VECTOR(N)             ← ivfflat cosine indexed
    created_at / updated_at

Pipeline:
  profile dict  →  rule-based field extraction  →  SQL WHERE filters
                →  flatten profile to text  →  embed  →  vector search
                →  fetch candidate embeddings  →  MMR rerank  →  results

Why no LLM here:
  • Zero API cost for the retrieval step itself
  • Fully deterministic, fast, easy to unit test
  • Profile → filter mapping uses a prioritised alias list per field, so it
    tolerates renamed questionnaire fields without needing an LLM to
    interpret them
"""

from __future__ import annotations

import json
import math
import threading
from typing import Any

import psycopg2
import psycopg2.extras
import psycopg2.pool

from config import (
    DB_CONFIG,
    DB_POOL_MAX_CONN,
    DB_POOL_MIN_CONN,
    DB_SSLMODE,
    EMBEDDING_MODEL_NAME,
    FINAL_N,
    MMR_LAMBDA,
    TOP_K,
)
from logging_config import get_logger

logger = get_logger(__name__)


class RetrievalError(Exception):
    """Raised for any recoverable failure in the retrieval pipeline."""


# ── Step 1: Rule-based filter extraction ──────────────────────────────────────
#
# This replaces an LLM translation step. We look for values in the profile
# dict using a prioritised list of candidate keys for each filter dimension.
# Because the questionnaire may rename fields across versions, each dimension
# has multiple aliases. The first non-empty match wins.
#
# HOW TO EXTEND: add new aliases to any FIELD_ALIASES entry, or add a new
# dimension entry. No other code needs to change.

FIELD_ALIASES: dict[str, list[str]] = {
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

# A Micro business matches rows that mention Micro OR MSME, etc.
MSME_TIER_TO_DB_TOKEN: dict[str, list[str]] = {
    "Micro": ["Micro", "MSME"],
    "Small": ["Small", "MSME"],
    "Medium": ["Medium", "MSME"],
}

# Normalise free-text MSME registration answers → canonical size tokens.
# Extend this map as new questionnaire phrasings appear.
MSME_SIZE_NORMALISATION: dict[str, str] = {
    "micro": "Micro",
    "small": "Small",
    "medium": "Medium",
    "msme": "MSME",
    "startup": "Startup",
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
    Values are None when no confident match is found — those dimensions are
    simply skipped (no filter applied), keeping recall high.
    """
    filters: dict[str, Any] = {}

    industry = _first_value(profile, FIELD_ALIASES["industry"])
    filters["industry"] = str(industry).strip() if industry else None

    category = _first_value(profile, FIELD_ALIASES["category"])
    filters["category"] = str(category).strip() if category else None

    geography = _first_value(profile, FIELD_ALIASES["geography"])
    filters["geography"] = str(geography).strip() if geography else None

    raw_size = _first_value(profile, FIELD_ALIASES["business_size"])
    filters["business_size"] = _normalise_business_size(raw_size)

    logger.debug("Extracted filters: %s", filters)
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

    def get(dim: str) -> str:
        v = _first_value(profile, FIELD_ALIASES[dim])
        return str(v).strip() if v else ""

    industry = get("industry")
    sub_industry = get("sub_industry")
    geography = get("geography")
    biz_size = _normalise_business_size(
        _first_value(profile, FIELD_ALIASES["business_size"])
    ) or ""
    attrs = _first_value(profile, FIELD_ALIASES["special_attributes"]) or []
    intent = _first_value(profile, FIELD_ALIASES["policy_intent"]) or []

    products = profile.get("products_services") or profile.get("products") or ""
    growth_stage = profile.get("growth_stage") or profile.get("stage") or ""
    location_type = profile.get("location_type") or ""
    registrations = profile.get("other_registrations") or profile.get("registrations") or []

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

    # Append any remaining string/number values the template didn't cover, so
    # nothing from the profile is silently dropped when a new field is added.
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

    text = "\n".join(parts)
    logger.debug("Flattened profile text (%d chars)", len(text))
    return text


# ── Step 3: Embed the profile text ────────────────────────────────────────────
#
# The embedding model is loaded lazily and cached as a module-level
# singleton so it survives across Streamlit reruns / repeated calls within
# the same process, instead of being reloaded from disk on every request.

_embedding_model = None
_embedding_model_lock = threading.Lock()


def get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        with _embedding_model_lock:
            if _embedding_model is None:  # re-check inside the lock
                logger.info("Loading embedding model '%s' (first use, may take a moment)...", EMBEDDING_MODEL_NAME)
                # Imported lazily so the (heavy) sentence-transformers / torch
                # import cost is only paid the first time an embedding is
                # actually needed.
                from sentence_transformers import SentenceTransformer

                _embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
                logger.info("Embedding model loaded.")
    return _embedding_model


def embed_text(text: str) -> list[float]:
    """Embed a string with the local sentence-transformers model."""
    model = get_embedding_model()
    vector = model.encode(text, normalize_embeddings=True).tolist()
    logger.debug("Embedded text (%d chars) -> vector dim=%d", len(text), len(vector))
    return vector


# ── Step 4: Hybrid search ──────────────────────────────────────────────────────

def build_filter_clauses(filters: dict[str, Any]) -> tuple[str, list]:
    """
    Convert filters dict → parameterised SQL WHERE fragment.

    industry
        Strips any parenthetical qualifier from the profile value before
        matching, e.g. "Manufacturing (General)" → search for "Manufacturing".
        Always also includes catch-all rows ("Multiple Industries",
        "Multi-sectoral", "MSME") since those are relevant to everyone.

    geography
        Always includes "National" policies as an OR branch alongside the
        business's own state, so state-agnostic policies are never excluded.

    business_size
        Stored as verbose multi-tier strings, never a single tier, so we
        search for each DB token that corresponds to the profile's MSME tier
        using OR (e.g. "Small" matches "Micro and Small Enterprises" and
        plain "MSME" rows).
    """
    clauses: list[str] = []
    params: list[Any] = []

    # ── industry ─────────────────────────────────────────────────────────────
    industry = filters.get("industry")
    if industry:
        industry_token = industry.split("(")[0].strip()
        clauses.append(
            "(industry ILIKE %s"
            " OR industry ILIKE '%%Multiple Industries%%'"
            " OR industry ILIKE '%%Multi-sectoral%%'"
            " OR industry ILIKE '%%MSME%%')"
        )
        params.append(f"%{industry_token}%")

    # ── category ─────────────────────────────────────────────────────────────
    category = filters.get("category")
    if category:
        clauses.append("category ILIKE %s")
        params.append(f"%{category}%")

    # ── geography ────────────────────────────────────────────────────────────
    # Always OR in National policies. We do NOT restrict this to a hardcoded
    # allow-list of states (unlike an early draft of this pipeline) — if the
    # business's state genuinely has no matching rows, the ILIKE simply
    # contributes no extra matches and National rows still come through.
    geography = filters.get("geography")
    if geography and geography.lower() != "national":
        clauses.append("(geography ILIKE %s OR geography ILIKE '%%National%%')")
        params.append(f"%{geography}%")

    # ── business_size ───────────────────────────────────────────────────────
    business_size = filters.get("business_size")  # canonical: "Micro"|"Small"|"Medium"
    if business_size:
        db_tokens = MSME_TIER_TO_DB_TOKEN.get(business_size, [business_size])
        or_parts = " OR ".join("business_size ILIKE %s" for _ in db_tokens)
        clauses.append(f"({or_parts})")
        params.extend(f"%{token}%" for token in db_tokens)

    where_sql = " AND ".join(clauses) if clauses else "TRUE"
    return where_sql, params


# ── Connection pooling ─────────────────────────────────────────────────────────
#
# A small connection pool avoids opening a fresh TCP + auth handshake to
# Postgres on every single search, which matters once the app has concurrent
# users.

_connection_pool: psycopg2.pool.SimpleConnectionPool | None = None
_pool_lock = threading.Lock()


def _get_pool() -> psycopg2.pool.SimpleConnectionPool:
    global _connection_pool
    if _connection_pool is None:
        with _pool_lock:
            if _connection_pool is None:
                logger.info(
                    "Initialising DB connection pool (%s..%s conns) to %s:%s/%s as user=%s (password_set=%s)",
                    DB_POOL_MIN_CONN, DB_POOL_MAX_CONN,
                    DB_CONFIG["host"], DB_CONFIG["port"], DB_CONFIG["dbname"],
                    DB_CONFIG["user"], bool(DB_CONFIG["password"]),
                )
                if not DB_CONFIG["password"]:
                    # Fail fast with a message that names the exact env vars
                    # to check, instead of letting psycopg2 raise the much
                    # more cryptic "fe_sendauth: no password supplied".
                    logger.error(
                        "No DB password resolved from the environment "
                        "(checked PG_PASSWORD and POSTGRES_PASSWORD)."
                    )
                    raise RetrievalError(
                        "No database password is configured. Set PG_PASSWORD "
                        "(or POSTGRES_PASSWORD) in a .env file that config.py "
                        "can find — see config.py's _CANDIDATE_ENV_FILES for "
                        "the exact locations it checks — or as a real "
                        "environment variable."
                    )
                try:
                    _connection_pool = psycopg2.pool.SimpleConnectionPool(
                        DB_POOL_MIN_CONN,
                        DB_POOL_MAX_CONN,
                        sslmode=DB_SSLMODE,
                        **DB_CONFIG,
                    )
                except psycopg2.OperationalError as exc:
                    logger.exception("Failed to connect to the database.")
                    raise RetrievalError(
                        f"Could not connect to the database at "
                        f"{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['dbname']}. "
                        f"Check your PG_* environment variables."
                    ) from exc
    return _connection_pool


def test_connection() -> bool:
    """Quick health check used by the app's sidebar / startup checks."""
    conn = None
    try:
        conn = _get_pool().getconn()
        with conn.cursor() as cur:
            cur.execute("SELECT 1;")
            cur.fetchone()
        logger.info("Database connection test succeeded.")
        return True
    except Exception:
        logger.exception("Database connection test failed.")
        return False
    finally:
        if conn is not None:
            _get_pool().putconn(conn)


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

    pool = _get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            logger.debug("Executing search SQL with WHERE: %s | top_k=%s", where_sql, top_k)
            cur.execute(sql, params)
            rows = cur.fetchall()
    except psycopg2.Error:
        conn.rollback()
        logger.exception("Database query failed during candidate retrieval.")
        raise RetrievalError("The policy search query failed. Please try again.")
    finally:
        pool.putconn(conn)

    results = []
    for row in rows:
        r = dict(row)
        raw_emb = r.pop("embedding_text", None)
        if raw_emb:
            r["embedding"] = [float(x) for x in raw_emb.strip("[]").split(",")]
        else:
            r["embedding"] = []
        results.append(r)

    logger.info("Retrieved %d candidate(s) from the database.", len(results))
    return results


# ── Step 5: MMR reranking ─────────────────────────────────────────────────────
#
# Maximal Marginal Relevance (Carbonell & Goldstein, 1998):
#
#   MMR(d_i) = λ · sim(d_i, query) − (1 − λ) · max_{d_j ∈ S} sim(d_i, d_j)
#
# At each iteration we pick the candidate that maximises this score, where S
# is the set of already-selected results. A higher λ (→1) favours relevance;
# lower (→0) favours diversity. This avoids raw cosine results clustering
# around a single parent policy's sub-schemes.

def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def mmr_rerank(
    query_vector: list[float],
    candidates: list[dict],
    final_n: int = FINAL_N,
    lmbda: float = MMR_LAMBDA,
) -> list[dict]:
    """Rerank candidates using Maximal Marginal Relevance. Returns final_n results."""
    if not candidates:
        return []

    remaining = list(candidates)
    selected: list[dict] = []

    while remaining and len(selected) < final_n:
        best_score = -float("inf")
        best_item = None

        for candidate in remaining:
            emb = candidate.get("embedding") or []
            if not emb:
                relevance = float(candidate.get("similarity", 0))
            else:
                relevance = _cosine(query_vector, emb)

            if selected:
                max_redundancy = max(
                    (_cosine(emb, s.get("embedding") or []) for s in selected if emb and s.get("embedding")),
                    default=0.0,
                )
            else:
                max_redundancy = 0.0

            mmr_score = lmbda * relevance - (1 - lmbda) * max_redundancy

            if mmr_score > best_score:
                best_score = mmr_score
                best_item = candidate

        if best_item is None:
            break

        best_item["mmr_rank"] = len(selected) + 1
        best_item["mmr_score"] = round(best_score, 4)
        selected.append(best_item)
        remaining.remove(best_item)

    logger.info("MMR reranking selected %d result(s) (lambda=%s).", len(selected), lmbda)
    return selected


# ── Public API ─────────────────────────────────────────────────────────────────

def find_matching_policies(
    business_profile: dict[str, Any],
    top_k: int = TOP_K,
    final_n: int = FINAL_N,
    lmbda: float = MMR_LAMBDA,
) -> list[dict]:
    """
    Full no-LLM pipeline: business_profile → MMR-ranked policy matches.

    Raises RetrievalError on unrecoverable failures (DB down, bad query, ...)
    so the Streamlit layer can show a friendly message instead of a raw
    traceback.
    """
    logger.info("Starting retrieval for business_name=%r", business_profile.get("business_name"))

    try:
        logger.debug("[1/4] Extracting filters (rule-based)...")
        filters = extract_filters(business_profile)
        logger.info("Filters extracted: %s", filters)

        logger.debug("[2/4] Building profile text and embedding...")
        profile_text = profile_to_text(business_profile)
        query_vector = embed_text(profile_text)
        logger.info("Query embedded (dim=%d).", len(query_vector))

        logger.debug("[3/4] Hybrid search — top %d candidates...", top_k)
        candidates = retrieve_candidates(query_vector, filters, top_k)

        if not candidates:
            logger.warning("No candidates found with filters applied. Retrying without filters.")
            candidates = retrieve_candidates(query_vector, {}, top_k)
            logger.info("Candidates (unfiltered retry): %d", len(candidates))
            if not candidates:
                logger.warning("No candidates found even without filters. Returning empty result set.")
                return []

        logger.debug("[4/4] MMR reranking (lambda=%s) -> top %d...", lmbda, final_n)
        results = mmr_rerank(query_vector, candidates, final_n, lmbda)
        logger.info("Retrieval complete. Returning %d result(s).", len(results))
        return results

    except RetrievalError:
        raise
    except Exception as exc:  # noqa: BLE001 - convert any unexpected failure
        logger.exception("Unexpected error during retrieval.")
        raise RetrievalError(f"An unexpected error occurred during policy matching: {exc}") from exc