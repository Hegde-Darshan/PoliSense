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


def _build_incentive_text(row: dict) -> str:
    """Assemble a descriptive string for an incentive row from its JSONB fields."""
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


def _build_filter_clause(
    industry: "str | list[str] | None",
    category: "str | list[str] | None",
    geography: "str | None",
    business_size: "str | None",
) -> tuple[str, list]:
    """Return (WHERE clause string, params list) for the shared metadata filters."""
    filters = []
    params  = []

    if industry:
        if isinstance(industry, list):
            filters.append(
                "(applicable_industries && %s OR 'All Sectors' = ANY(applicable_industries))"
            )
            params.append(industry)
        else:
            filters.append(
                "(%s = ANY(applicable_industries) OR 'All Sectors' = ANY(applicable_industries))"
            )
            params.append(industry)

    if business_size:
        filters.append(
            "(%s = ANY(applicable_business_sizes) OR 'All' = ANY(applicable_business_sizes))"
        )
        params.append(business_size)

    if geography:
        filters.append(
            "(EXISTS (SELECT 1 FROM unnest(applicable_geographies) g WHERE g ILIKE %s)"
            " OR 'National' = ANY(applicable_geographies))"
        )
        params.append(f"%{geography}%")

    if category:
        if isinstance(category, list):
            filters.append("(category ILIKE ANY(%s))")
            params.append([f"%{c}%" for c in category])
        else:
            filters.append("category ILIKE %s")
            params.append(f"%{category}%")

    where_clause = ("WHERE " + " AND ".join(filters)) if filters else ""
    return where_clause, params


def retrieve_policies(
    query: str,
    conn,
    top_k: int = 5,
    industry: str | list[str] = None,
    category: str | list[str] = None,
    geography: str = None,
    business_size: str = None,
    rerank: bool = True,
) -> list[dict]:
    """
    Retrieve the most relevant policies using hybrid BM25+vector search with RRF merging.

    Runs both a pgvector cosine query and a PostgreSQL full-text (BM25) query against the
    same metadata filters, then merges the two ranked lists with Reciprocal Rank Fusion.
    This fixes the blind spot where exact scheme names and legal terms score poorly in
    pure vector search.

    Filters use array containment on applicable_industries, applicable_business_sizes,
    applicable_geographies. Policies tagged 'All Sectors', 'All', or 'National' always
    pass the corresponding filter so universally-applicable policies are never excluded.

    When rerank=True (default), the merged candidates are reranked with a cross-encoder
    (BAAI/bge-reranker-base) that jointly scores query+incentive text for token-level
    relevance matching.
    """
    prefixed_query = f"Represent this sentence for searching relevant passages: {query}"
    query_vector = embed_documents(prefixed_query)

    where_clause, filter_params = _build_filter_clause(industry, category, geography, business_size)

    fetch_n = top_k * 2  # fetch more from each source so RRF has a full candidate pool

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
    bm25_where_parts = ["search_vector @@ plainto_tsquery('english', %s)"]
    bm25_filter_params = [query] + filter_params[:]  # BM25 uses raw query, not prefixed

    if where_clause:
        extra = where_clause.replace("WHERE ", "", 1)
        bm25_where_parts.append(extra)

    bm25_sql = f"""
        SELECT
            {_SELECT_COLUMNS},
            ts_rank_cd(search_vector, plainto_tsquery('english', %s)) AS similarity_score
        FROM policies
        WHERE {' AND '.join(bm25_where_parts)}
        ORDER BY similarity_score DESC
        LIMIT %s;
    """
    # ts_rank_cd needs the query twice: once in WHERE, once in SELECT
    bm25_params = [query] + bm25_filter_params + [fetch_n]

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

    # ── RRF merge ─────────────────────────────────────────────────────────────
    if bm25_rows:
        results = _rrf_merge(bm25_rows, vec_rows, top_k)
    else:
        results = vec_rows[:top_k]

    # ── Cross-encoder rerank ───────────────────────────────────────────────────
    if rerank and results:
        # Strip Zoho boilerplate before cross-encoder: for short business descriptions
        # the appended suffix is a large fraction of the query and pulls scores toward
        # generic MSME-scheme space instead of the actual business activity.
        clean_query = query.replace(" government grants subsidies and incentives", "").strip()
        texts = [_build_incentive_text(r) for r in results]
        scores = rerank_with_cross_encoder(clean_query, texts)
        for r, score in zip(results, scores):
            r["incentive_score"] = float(score)
        # Only reorder when the cross-encoder has genuine signal: logit > -3.0 means
        # sigmoid > 5% for the best candidate. With raw logits the range is always 3-5
        # units regardless of relevance, so range-based thresholds always fire — use
        # max instead.
        if max(scores) > -3.0:
            results.sort(key=lambda r: r["incentive_score"], reverse=True)

    return results


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
        allowed = ("industry", "geography", "business_size", "category")
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
