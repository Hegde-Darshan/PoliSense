"""
Backfill / repair script for the ingestion data-quality fixes.

Repairs the rows already in the `policies` table — no LLM calls; everything is
reconstructed from stored columns + JSONB and the document text in
`policy_documents`. Idempotent: safe to run repeatedly.

Three passes (run in order):
  1. vocab cleanup  — strip 'All' / 'All Sectors' when specific tags present (#6)
  2. re-embed       — rebuild embedding + search_vector incentive-first (#8)
  3. faithfulness   — audit source_text / eligibility raw_text + missing fields,
                      writing flags to review_queue (#9/#1)

Run:  python polisense_core/backfill_quality.py

Prereq: apply db/migrate_v7.sql (review_queue flag columns) first.
"""
import logging

from psycopg2.extras import RealDictCursor

from polisense_core.utils import postgres_utils as db_utils

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_quality")

# review_type values written by this script's audit pass (and the live pipeline gate).
_AUTO_REVIEW_TYPES = ("faithfulness", "missing_field", "unverifiable")


def clean_vocab(conn) -> None:
    """#6 — drop 'All' / 'All Sectors' from rows that also list specific tags."""
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE policies
            SET applicable_business_sizes = array_remove(applicable_business_sizes, 'All')
            WHERE 'All' = ANY(applicable_business_sizes)
              AND array_length(applicable_business_sizes, 1) > 1
        """)
        sizes_fixed = cur.rowcount
        cur.execute("""
            UPDATE policies
            SET applicable_industries = array_remove(applicable_industries, 'All Sectors')
            WHERE 'All Sectors' = ANY(applicable_industries)
              AND array_length(applicable_industries, 1) > 1
        """)
        ind_fixed = cur.rowcount
    conn.commit()
    logger.info(f"vocab cleanup: {sizes_fixed} size row(s), {ind_fixed} industry row(s) fixed")


def _row_to_dicts(row: dict):
    """Reconstruct the (policy, incentive, summary_dict) shapes build_embedding_text expects."""
    pd = row.get("policy_details") or {}
    idc = row.get("incentive_details") or {}
    policy = {
        "policy_name":               row.get("policy_name"),
        "category":                  row.get("category"),
        "applicable_industries":     row.get("applicable_industries") or [],
        "applicable_business_sizes": row.get("applicable_business_sizes") or [],
        "applicable_geographies":    row.get("applicable_geographies") or [],
        "benefit_headline":          pd.get("benefit_headline"),
        "keywords":                  pd.get("keywords") or [],
        "policy_summary":            pd.get("policy_summary"),
        "eligibility_criteria":      pd.get("eligibility_criteria") or {},
    }
    incentive = {
        "incentive_name":      row.get("incentive_name"),
        "benefit_headline":    idc.get("benefit_headline"),
        "description":         idc.get("description"),
        "quantified_benefits": idc.get("quantified_benefits") or [],
    }
    summary_dict = {"policy_goals": pd.get("policy_goals") or []}
    return policy, incentive, summary_dict


def reembed(conn) -> None:
    """#8 — rebuild embedding + search_vector for every row, incentive-first."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT policy_id, policy_name, incentive_name, category,
                   applicable_industries, applicable_business_sizes, applicable_geographies,
                   policy_details, incentive_details
            FROM policies
        """)
        rows = cur.fetchall()

    updated = 0
    with conn.cursor() as cur:
        for row in rows:
            policy, incentive, summary_dict = _row_to_dicts(row)
            text = db_utils.build_embedding_text(policy, incentive, summary_dict)
            vector = db_utils.embed_documents(text)
            cur.execute("""
                UPDATE policies
                SET embedding = %(embedding)s,
                    search_vector = to_tsvector('english', %(text)s)
                WHERE policy_id = %(pid)s
            """, {"embedding": vector, "text": text, "pid": row["policy_id"]})
            updated += 1
            if updated % 50 == 0:
                logger.info(f"re-embedded {updated}/{len(rows)} rows")
    conn.commit()
    logger.info(f"re-embed: {updated} row(s) updated")


def audit_faithfulness(conn) -> None:
    """#9/#1 — audit existing rows and (re)populate review_queue flags."""
    # Idempotent: clear flags this script previously wrote before re-auditing.
    with conn.cursor() as cur:
        cur.execute("DELETE FROM review_queue WHERE review_type = ANY(%s)", (list(_AUTO_REVIEW_TYPES),))
    conn.commit()

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT policy_id, parent_policy_name, policy_name, incentive_name,
                   start_year, policy_details, incentive_details
            FROM policies
            ORDER BY parent_policy_name, policy_name
        """)
        rows = cur.fetchall()

    # Group rows into per-parent summary_dict shapes that validate_extraction expects.
    parents: dict[str, dict] = {}
    for row in rows:
        parent = row.get("parent_policy_name")
        pd = row.get("policy_details") or {}
        idc = row.get("incentive_details") or {}
        bucket = parents.setdefault(parent, {})
        policy = bucket.setdefault(row.get("policy_name"), {
            "policy_name": row.get("policy_name"),
            "validity": {"start_year": row.get("start_year")},
            "eligibility_criteria": pd.get("eligibility_criteria") or {},
            "incentives": [],
        })
        policy["incentives"].append({
            "incentive_name": row.get("incentive_name"),
            "quantified_benefits": idc.get("quantified_benefits") or [],
        })

    total_flags = 0
    for parent, policies in parents.items():
        with conn.cursor() as cur:
            cur.execute("SELECT raw_text FROM policy_documents WHERE parent_policy_name = %s", (parent,))
            doc = cur.fetchone()
        raw_text = doc[0] if doc else None

        summary_dict = {"parent_policy_name": parent, "policies": list(policies.values())}
        flags = db_utils.validate_extraction(summary_dict, raw_text)
        for f in flags:
            db_utils.flag_for_review(
                conn, parent, f["policy_name"], f["incentive_name"],
                f["review_type"], f["reason"],
            )
        conn.commit()
        total_flags += len(flags)
    logger.info(f"faithfulness audit: {total_flags} flag(s) written to review_queue")


def main() -> None:
    conn = db_utils.get_connection()
    try:
        clean_vocab(conn)       # #6 — must run before re-embed (embedding text includes tags)
        reembed(conn)           # #8
        audit_faithfulness(conn)  # #9/#1
    finally:
        conn.close()
    logger.info("backfill complete")


if __name__ == "__main__":
    main()
