import os
import json
import psycopg2
from pathlib import Path
from dotenv import load_dotenv

from polisense_core.utils.postgres_utils import get_connection, embed_documents, rerank_with_cross_encoder

_SELECT_COLUMNS = """
    policy_id,
    parent_policy_name,
    policy_name,
    incentive_name,
    category,
    applicable_industries,
    applicable_geographies,
    applicable_business_sizes,
    start_year,
    end_year,
    policy_details,
    incentive_details
"""


_ZOHO_SUFFIX = " government grants subsidies and incentives"  # appended to every Zoho query


def _build_incentive_text(row: dict) -> str:
    """Assemble a descriptive string for an incentive row from its JSONB fields.

    Intentionally incentive-level only (no parent policy name / category). Prepending the
    generic policy name and category was measured to dilute the cross-encoder's
    discrimination between sibling incentives and regressed policy-level nDCG/MRR on the
    golden eval, so it is deliberately excluded.
    """
    inc = row["incentive_details"]
    parts = [row["incentive_name"]]
    for field in ("benefit_headline", "description", "incentive_specific_eligibility"):
        if inc.get(field):
            parts.append(inc[field])
    for benefit in (inc.get("quantified_benefits") or [])[:3]:
        if benefit.get("source_text"):
            parts.append(benefit["source_text"])
    return " ".join(parts)


def _rrf_merge(
    bm25_rows: list[dict],
    vec_rows: list[dict],
    top_k: int,
    k: int = 60,
) -> list[dict]:
    """
    Merge two ranked result lists with Reciprocal Rank Fusion.

    Each result scores 1/(k+rank) per list it appears in. Results absent from
    one list simply receive no score from that list (the standard RRF formula).
    Returns the top_k rows, preferring the vector row's data (which carries cosine
    similarity_score) for items that appear in both lists.
    """
    bm25_map = {r["policy_id"]: r for r in bm25_rows}
    vec_map  = {r["policy_id"]: r for r in vec_rows}
    rrf_scores: dict[int, float] = {}

    for rank, row in enumerate(bm25_rows, 1):
        pid = row["policy_id"]
        rrf_scores[pid] = rrf_scores.get(pid, 0.0) + 1.0 / (k + rank)

    for rank, row in enumerate(vec_rows, 1):
        pid = row["policy_id"]
        rrf_scores[pid] = rrf_scores.get(pid, 0.0) + 1.0 / (k + rank)

    ranked_ids = sorted(rrf_scores, key=lambda pid: -rrf_scores[pid])[:top_k]
    results = []
    for pid in ranked_ids:
        # Prefer vector row (has cosine similarity_score); fall back to BM25-only row
        row = vec_map.get(pid) or bm25_map[pid]
        if pid not in vec_map:
            row["similarity_score"] = 0.0
        results.append(row)
    return results

ROOT_PATH = Path(__file__).parent.parent.parent
load_dotenv(ROOT_PATH / ".env")
load_dotenv(ROOT_PATH / ".env.secrets")


def save_results_to_file(
    all_results: list[dict],
    output_path: str = "retrieval_results.txt",
):
    """Save pretty-printed retrieval results for all profiles to a text file."""
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
                _write_result_block(f, rank, r)
                rank += 1

            f.write("\n")

    print(f"Results saved to {output_path}")


def write_single_result(
    query_name: str,
    entry: dict,
    output_path: str,
) -> None:
    """Write retrieval results for a single query-profile pair to a text file."""
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
            _write_result_block(f, rank, r)
            rank += 1

        f.write("\n")


def _write_result_block(f, rank: int, r: dict) -> None:
    """Write a single result entry to an open file handle."""
    industries = ", ".join(r.get("applicable_industries") or []) or "N/A"
    geographies = ", ".join(r.get("applicable_geographies") or []) or "N/A"
    sizes = ", ".join(r.get("applicable_business_sizes") or []) or "N/A"

    pd = r.get("policy_details") or {}
    id_ = r.get("incentive_details") or {}

    policy_headline    = (pd.get("benefit_headline") or "")[:200]
    incentive_headline = (id_.get("benefit_headline") or "")[:200]
    eligibility_raw    = ""
    elig = pd.get("eligibility_criteria")
    if isinstance(elig, dict):
        eligibility_raw = (elig.get("raw_text") or "")[:200]
    elif isinstance(elig, str):
        eligibility_raw = elig[:200]

    retrieval_score  = r["similarity_score"]
    incentive_score  = r.get("incentive_score")
    score_line = f"Retrieval: {retrieval_score:.4f}"
    if incentive_score is not None:
        score_line += f"  |  Incentive: {incentive_score:.4f}"

    f.write(f"\n{'═' * 60}\n")
    f.write(f"  #{rank}  {score_line}\n")
    f.write(f"{'═' * 60}\n")
    f.write(f"  {'Parent Policy':>13} : {r['parent_policy_name']}\n")
    f.write(f"  {'Scheme':>13} : {r['policy_name']}\n")
    f.write(f"  {'Incentive':>13} : {r['incentive_name']}\n")
    f.write(f"  {'Category':>13} : {r['category']}  |  Industries: {industries}\n")
    f.write(f"  {'Geography':>13} : {geographies}  |  Size: {sizes}\n")
    if policy_headline:
        f.write(f"  {'Headline':>13} : {policy_headline}\n")
    if incentive_headline:
        f.write(f"  {'Benefit':>13} : {incentive_headline}\n")
    if eligibility_raw:
        f.write(f"  {'Eligibility':>13} : {eligibility_raw}\n")


def _build_filter_clause(geography: "str | None") -> tuple[str, list]:
    """Return (WHERE clause string, params list) for the geography hard filter."""
    if not geography:
        return "", []
    clause = (
        "(EXISTS (SELECT 1 FROM unnest(applicable_geographies) g WHERE g ILIKE %s)"
        " OR 'National' = ANY(applicable_geographies))"
    )
    return f"WHERE {clause}", [f"%{geography}%"]


def geography_coverage_count(conn, geography: "str | None") -> int:
    """Number of policies specifically tagged for this state (excludes National-only rows).

    Used to decide whether a business's geography is covered at all. Uses a direct COUNT
    rather than the vector query, which under a restrictive geography filter returns 0 due
    to HNSW post-filtering (the ANN candidate set may contain no eligible rows). The 2
    generic 'National' cluster rows are not meaningful coverage, so they are not counted.
    """
    if not geography:
        return 1  # no geography ⇒ treat as covered (national / all)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM policies "
            "WHERE EXISTS (SELECT 1 FROM unnest(applicable_geographies) g WHERE g ILIKE %s)",
            [f"%{geography}%"],
        )
        return cur.fetchone()[0]


# Boost magnitudes are deliberately small relative to the cross-encoder's raw-logit
# range (~-11..+10). They nudge/tie-break the semantic ranking — they must NOT
# override it. A specific tag match (the policy names this exact industry) is stronger
# evidence of fit than a catch-all "All Sectors" / "All" entry, which applies to every
# business and so is weak evidence of *specific* relevance.
_INDUSTRY_BOOST     = 1.5   # policy lists this exact industry
_INDUSTRY_ALL_BOOST = 0.5   # policy is "All Sectors" — applies broadly, weak signal
_SIZE_BOOST         = 0.5   # business-size match (specific or "All")
_CATEGORY_BOOST     = 1.5   # enquiry_purpose ↔ category — strong intent signal
# When the business industry is known and a policy names specific industries (not a
# catch-all "All Sectors" entry) none of which match, that is positive evidence of *mis*fit
# — not merely absence of evidence. A small penalty sinks clearly off-industry policies
# below correct-industry ones without ever excluding them. Kept small vs the logit range so
# a strongly semantic match can still win.
_INDUSTRY_MISMATCH_PENALTY = -0.75

# Generic "bucket" tags: broad enough that sector-specialized policies (Space, Aerospace,
# EV) attach them, so matching one is weak evidence of real sector fit. A match ONLY via a
# bucket tag on a vertical policy is treated as a misfit, not a match — otherwise a chemical
# manufacturer surfaces the Space Technology Policy because both carry "Manufacturing". The
# explicit horizontal policies instead tag "All Sectors" (handled as its own branch).
_BROAD_INDUSTRY_TAGS = {"Manufacturing", "Other"}

_INDUSTRY_SPECIFICITY_PIVOT = 2   # policies listing <= this many specific sectors earn full boost


def _dedupe_incentives(results: list[dict]) -> list[dict]:
    """Collapse duplicate ``(parent_policy_name, incentive_name)`` rows, keeping the first
    (highest-scored, since ``results`` is pre-sorted).

    The corpus stores some incentives multiple times — e.g. the EV policy repeats
    "Investment Promotion Subsidy" and "Subsidy for Setting up ETPs" once per sub-sector.
    Returning every copy wastes top-k slots on the same incentive and crowds out other
    relevant incentives; the relevance labels collapse these to unique keys anyway. Rows
    with no incentive_name (policy-only rows) are never deduped.
    """
    seen: set = set()
    out: list[dict] = []
    for r in results:
        name = r.get("incentive_name")
        if name:
            key = (r.get("parent_policy_name"), name)
            if key in seen:
                continue
            seen.add(key)
        out.append(r)
    return out


def _industry_specificity_factor(specific_tags: list[str]) -> float:
    """
    Scale the industry boost by how focused the policy is. A policy that lists many
    specific sectors is weak evidence of fit (e.g. a Biotech policy that also tags
    Healthcare/Food Processing), so its boost decays with the number of sectors claimed.
    Expects the policy's *specific* sector tags (generic buckets and 'All Sectors' already
    removed by the caller).
    """
    n = len(specific_tags)
    if n <= _INDUSTRY_SPECIFICITY_PIVOT:
        return 1.0
    return max(0.33, _INDUSTRY_SPECIFICITY_PIVOT / n)


def _compute_metadata_boost(
    row: dict,
    industry: "str | list[str] | None" = None,
    business_size: "str | None" = None,
    enquiry_purpose: "list[str] | None" = None,
) -> float:
    """
    Soft boost added to the ranking score for metadata matches.
    Never excludes a policy — only shifts its rank relative to mismatches.
    Applied twice: once before the cross-encoder to curate the candidate pool,
    and once after to produce the final ordering.

    A match on a *specific* sector earns the full boost scaled by the policy's specificity
    (fewer claimed sectors ⇒ stronger signal). An explicit "All Sectors" (horizontal) policy
    earns a reduced flat boost. A match only via a generic bucket tag ("Manufacturing"/
    "Other") on a sector-specialized policy — or no tag match at all when the policy names
    specific sectors — is treated as a misfit and penalized.
    """
    boost = 0.0
    if industry:
        industries = row.get("applicable_industries") or []
        targets = industry if isinstance(industry, list) else [industry]
        # The policy's specific (named-sector) tags, excluding generic buckets and the
        # explicit "All Sectors" catch-all.
        specific_policy_tags = [
            i for i in industries if i not in _BROAD_INDUSTRY_TAGS and i != "All Sectors"
        ]
        # A "specific" match is on a named sector (not a generic bucket).
        specific_match = any(
            t in industries for t in targets if t not in _BROAD_INDUSTRY_TAGS
        )
        if specific_match:
            boost += _INDUSTRY_BOOST * _industry_specificity_factor(specific_policy_tags)
        elif "All Sectors" in industries:
            boost += _INDUSTRY_ALL_BOOST
        elif any(t in industries for t in targets) or specific_policy_tags:
            # Matched at most a generic bucket on a sector-specialized policy, or matched no
            # tag while the policy names specific sectors — a sector misfit either way.
            boost += _INDUSTRY_MISMATCH_PENALTY
    if business_size:
        sizes = row.get("applicable_business_sizes") or []
        if business_size in sizes or "All" in sizes:
            boost += _SIZE_BOOST
    if enquiry_purpose:
        if row.get("category") in enquiry_purpose:
            boost += _CATEGORY_BOOST
    return boost


def retrieve_policies(
    query: str,
    conn,
    top_k: int = 5,
    industry: str | list[str] = None,
    geography: str = None,
    business_size: str = None,
    enquiry_purpose: list[str] | None = None,
    rerank: bool = True,
    trace: dict | None = None,
) -> list[dict]:
    """
    Retrieve the most relevant policies using hybrid BM25+vector search with RRF merging.

    Runs both a pgvector cosine query and a PostgreSQL full-text (BM25) query against the
    same metadata filters, then merges the two ranked lists with Reciprocal Rank Fusion.

    Hard filter: geography — only policies matching the state or tagged 'National' are
    returned.

    Two-stage metadata boosting: after RRF produces a 2×top_k candidate pool, metadata
    boosts (industry, business_size, enquiry_purpose/category) are applied and the pool
    is pre-sorted to select the top_k candidates fed to the cross-encoder. This ensures
    metadata-relevant policies are always in the cross-encoder input rather than being
    ranked after the fact. The same boosts are applied again post-reranking for the final
    ordering. No policy is ever hard-excluded on these dimensions.

    trace: optional dict for evaluation/debugging. When given, it is filled with
    trace["stages"] (ordered stage names), one ranked row list per stage, and
    trace["config"]. Return value and behaviour are unchanged. When adding or
    renaming a stage, record it with _trace() so evals keep seeing every stage.
    """
    def _trace(stage: str, rows: list[dict]) -> None:
        if trace is not None:
            trace.setdefault("stages", []).append(stage)
            trace[stage] = [dict(r) for r in rows]  # copies: later stages mutate rows

    prefixed_query = f"Represent this sentence for searching relevant passages: {query}"
    query_vector = embed_documents(prefixed_query)

    where_clause, filter_params = _build_filter_clause(geography)

    fetch_n = top_k * 4  # larger pool so RRF has ample candidates before metadata pre-sort

    # ── Vector query ──────────────────────────────────────────────────────────
    vec_sql = f"""
        SELECT
            {_SELECT_COLUMNS},
            1 - (embedding <=> %s::vector) AS similarity_score
        FROM policies
        {where_clause}
        ORDER BY embedding <=> %s::vector
        LIMIT %s;
    """
    vec_params = [query_vector] + filter_params + [query_vector, fetch_n]

    with conn.cursor() as cur:
        # Raise HNSW search breadth so restrictive geography filters still surface their
        # eligible rows. With the default ef_search (40) and a filter matching only a few
        # rows, the ANN candidate set may contain none of them and the query returns 0
        # even though matching rows exist (pgvector post-filters after the index scan).
        cur.execute("SET hnsw.ef_search = 200")
        cur.execute(vec_sql, vec_params)
        vec_rows_raw = cur.fetchall()
        columns = [desc[0] for desc in cur.description]

    vec_rows = []
    for row in vec_rows_raw:
        record = dict(zip(columns, row))
        record["policy_details"]    = record["policy_details"]    or {}
        record["incentive_details"] = record["incentive_details"] or {}
        vec_rows.append(record)

    # ── BM25 query (only when search_vector column is populated) ──────────────
    bm25_rows: list[dict] = []
    # plainto_tsquery ANDs every word, so a long business description matches no row (0 BM25 hits).
    # Swap & for | : any shared term matches, ts_rank_cd ranks rows by how many/close. The Zoho
    # suffix is stripped, otherwise "government/grant/subsidy" match every row and drown real terms.
    bm25_tsq = "replace(plainto_tsquery('english', %s)::text, ' & ', ' | ')::tsquery"
    bm25_query = query.replace(_ZOHO_SUFFIX, "").strip()
    bm25_where_parts = [f"search_vector @@ {bm25_tsq}"]
    bm25_filter_params = [bm25_query] + filter_params[:]  # BM25 uses raw query, not prefixed

    if where_clause:
        extra = where_clause.replace("WHERE ", "", 1)
        bm25_where_parts.append(extra)

    bm25_sql = f"""
        SELECT
            {_SELECT_COLUMNS},
            ts_rank_cd(search_vector, {bm25_tsq}) AS similarity_score
        FROM policies
        WHERE {' AND '.join(bm25_where_parts)}
        ORDER BY similarity_score DESC
        LIMIT %s;
    """
    # ts_rank_cd needs the query twice: once in WHERE, once in SELECT
    bm25_params = [bm25_query] + bm25_filter_params + [fetch_n]

    try:
        with conn.cursor() as cur:
            cur.execute(bm25_sql, bm25_params)
            bm25_rows_raw = cur.fetchall()
            bm25_columns  = [desc[0] for desc in cur.description]

        for row in bm25_rows_raw:
            record = dict(zip(bm25_columns, row))
            record["policy_details"]    = record["policy_details"]    or {}
            record["incentive_details"] = record["incentive_details"] or {}
            bm25_rows.append(record)
    except Exception:
        # search_vector column missing (pre-migration) — degrade gracefully to vector-only
        conn.rollback()

    _trace("vector", vec_rows)
    _trace("bm25", bm25_rows)

    # ── RRF merge → generous candidate pool ──────────────────────────────────
    if bm25_rows:
        candidates = _rrf_merge(bm25_rows, vec_rows, top_k * 3)
    else:
        candidates = vec_rows[:top_k * 3]
    _trace("rrf", candidates)

    # ── Metadata pre-sort: curate the cross-encoder input pool ───────────────
    # Compute boost for every candidate and pre-sort so that industry/category/
    # size-matching policies are pulled into the pool the cross-encoder scores.
    # This guards against metadata matches being ranked out of the pool by a
    # generic query. The pool is kept larger than top_k (rerank_n) so that
    # semantically strong policies that lack a tag match (e.g. a broad industrial
    # policy for a generic manufacturer) are still scored by the cross-encoder
    # and can win on semantic relevance. No policy is excluded on metadata.
    for r in candidates:
        r["metadata_boost"] = _compute_metadata_boost(r, industry, business_size, enquiry_purpose)
    candidates.sort(
        key=lambda r: r["similarity_score"] + r["metadata_boost"],
        reverse=True,
    )
    rerank_n = top_k * 2
    _trace("presort", candidates)
    results = candidates[:rerank_n]
    _trace("rerank_input", results)

    # ── Cross-encoder rerank ───────────────────────────────────────────────────
    if rerank and results:
        # Strip Zoho boilerplate before cross-encoder: for short business descriptions
        # the appended suffix is a large fraction of the query and pulls scores toward
        # generic MSME-scheme space instead of the actual business activity.
        clean_query = bm25_query
        texts = [_build_incentive_text(r) for r in results]
        scores = rerank_with_cross_encoder(clean_query, texts)
        for r, score in zip(results, scores):
            r["incentive_score"] = float(score)

    # ── Final sort: cross-encoder score (dominant) + small metadata nudge ────
    results.sort(
        key=lambda r: r.get("incentive_score", r["similarity_score"]) + r.get("metadata_boost", 0.0),
        reverse=True,
    )

    # ── Collapse exact-duplicate incentives so copies don't waste top-k slots ──
    results = _dedupe_incentives(results)

    _trace("final", results[:top_k])
    if trace is not None:
        trace["config"] = {"top_k": top_k, "fetch_n": fetch_n, "candidates_n": top_k * 3,
                           "rerank_n": rerank_n, "rerank": rerank}
    return results[:top_k]


def pretty_print_results(results: list[dict]):
    """Human-readable console display of retrieval results."""
    if not results:
        print("No results found.")
        return
    for i, r in enumerate(results, 1):
        pd  = r.get("policy_details") or {}
        id_ = r.get("incentive_details") or {}

        industries  = ", ".join(r.get("applicable_industries") or []) or "N/A"
        geographies = ", ".join(r.get("applicable_geographies") or []) or "N/A"
        sizes       = ", ".join(r.get("applicable_business_sizes") or []) or "N/A"

        elig = pd.get("eligibility_criteria")
        elig_text = ""
        if isinstance(elig, dict):
            elig_text = (elig.get("raw_text") or "")[:200]
        elif isinstance(elig, str):
            elig_text = elig[:200]

        score_line = f"Retrieval: {r['similarity_score']:.4f}"
        if r.get("incentive_score") is not None:
            score_line += f"  |  Incentive: {r['incentive_score']:.4f}"

        print(f"\n{'=' * 60}")
        print(f"  #{i}  {score_line}")
        print(f"{'=' * 60}")
        print(f"  {'Parent Policy':>13} : {r['parent_policy_name']}")
        print(f"  {'Scheme':>13} : {r['policy_name']}")
        print(f"  {'Incentive':>13} : {r['incentive_name']}")
        print(f"  {'Category':>13} : {r['category']}  |  Industries: {industries}")
        print(f"  {'Geography':>13} : {geographies}  |  Size: {sizes}")
        if pd.get("benefit_headline"):
            print(f"  {'Headline':>13} : {pd['benefit_headline'][:200]}")
        if id_.get("benefit_headline"):
            print(f"  {'Benefit':>13} : {id_['benefit_headline'][:200]}")
        if elig_text:
            print(f"  {'Eligibility':>13} : {elig_text}")


# ── Run directly to test ───────────────────────────────────────────────────────
if __name__ == "__main__":
    conn = get_connection()

    SAMPLE_PROFILES = [
        {
            "business_name":   "VoltEdge Battery Pvt Ltd",
            "industry":        "Automotive and EV",
            "geography":       "Karnataka",
            "business_size":   "Startup",
            "ownership_type":  "Private",
            "special_attributes": ["Startup", "Deep Tech"],
        },
        {
            "business_name":   "ChargeFast Solutions Pvt Ltd",
            "industry":        "Automotive and EV",
            "geography":       "Karnataka",
            "business_size":   "Small",
        },
        {
            "business_name":   "GreenFleet Mobility Pvt Ltd",
            "industry":        "Renewable Energy and Clean Tech",
            "geography":       "Karnataka",
            "business_size":   "Startup",
            "ownership_type":  "Women-Owned",
            "special_attributes": ["Startup", "Women-led"],
        },
        {
            "business_name":   "NeuralChip Technologies Pvt Ltd",
            "industry":        "Electronics and Hardware",
            "geography":       "Karnataka",
            "business_size":   "Startup",
            "special_attributes": ["Deep Tech"],
        },
        {
            "business_name":   "MedSense Electronics Pvt Ltd",
            "industry":        "Electronics and Hardware",
            "geography":       "Karnataka",
            "business_size":   "Micro",
            "ownership_type":  "Women-Owned",
            "special_attributes": ["Women-led", "Export-oriented"],
        },
        {
            "business_name":   "IdeaSpark Innovations Pvt Ltd",
            "industry":        None,
            "geography":       None,
            "business_size":   "Small",
        },
    ]

    test_cases = [
        {
            "label":   "EV battery manufacturing subsidies for MSMEs",
            "query":   "What subsidies are available for small businesses manufacturing EV batteries in Karnataka?",
            "filters": {"industry": "Automotive and EV", "geography": "Karnataka"},
        },
        {
            "label":   "Charging infrastructure incentives",
            "query":   "capital subsidy for setting up EV fast charging and battery swapping stations",
            "filters": {"geography": "Karnataka"},
        },
        {
            "label":   "Electronics startup R&D grants",
            "query":   "R&D grants and prototyping cost reimbursement for electronics startups",
            "filters": {"industry": "Electronics and Hardware", "geography": "Karnataka"},
        },
        {
            "label":   "Cross-policy: MSME fiscal incentives",
            "query":   "fiscal incentives like stamp duty exemption and land conversion fee reimbursement for MSMEs in Karnataka",
            "filters": {},
        },
    ]

    def _query_from_profile(profile: dict) -> str:
        parts = []
        if profile.get("industry"):
            parts.append(profile["industry"])
        if profile.get("business_size"):
            parts.append(f"{profile['business_size']} businesses")
        if profile.get("geography"):
            parts.append(f"in {profile['geography']}")
        if profile.get("special_attributes"):
            parts.append(f"({', '.join(profile['special_attributes'])})")
        base = "government grants and incentives for "
        return base + " ".join(parts) if parts else base.strip()

    def _filters_from_profile(profile: dict) -> dict:
        allowed = ("industry", "geography", "business_size")
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
