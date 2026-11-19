import psycopg2
from psycopg2.extras import Json
from pathlib import Path
from dotenv import load_dotenv
import os
import json
import re
import difflib

from sentence_transformers import SentenceTransformer, CrossEncoder


load_dotenv()
ROOT_PATH = Path(__file__).parent.parent.parent  # polisense_core/utils/ -> polisense_core/ -> project root
load_dotenv(ROOT_PATH / ".env")
load_dotenv(ROOT_PATH / ".env.secrets")

# Module-level singletons — loaded once per process, not once per call
_embedding_model: SentenceTransformer | None = None
_reranker_model: CrossEncoder | None = None


def _get_embedding_model() -> SentenceTransformer:
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = SentenceTransformer("BAAI/bge-small-en-v1.5")
    return _embedding_model


def _get_reranker_model() -> CrossEncoder:
    global _reranker_model
    if _reranker_model is None:
        _reranker_model = CrossEncoder("BAAI/bge-reranker-base")
    return _reranker_model


def embed_documents(text: str) -> list[float]:
    model = _get_embedding_model()
    return model.encode(text, normalize_embeddings=True).tolist()


# ── Embedding text construction ────────────────────────────────────────────────

# BGE bge-small-en-v1.5 silently truncates at 512 tokens. We put incentive-specific
# signal FIRST so sibling incentives get distinct vectors, and keep the large shared
# policy blobs (summary, eligibility) LAST so they absorb any truncation. These are
# also capped so policy-identity tokens always survive.
_SHARED_BLOB_CHAR_CAP = 1000


def build_embedding_text(policy: dict, incentive: dict, summary_dict: dict) -> str:
    """Build the text embedded (and BM25-indexed) for one incentive row.

    Shared by ingestion and the backfill script so both produce identical text.
    `policy` is the PolicyExtraction dict, `incentive` the IncentiveExtraction dict,
    `summary_dict` the root PDFExtraction dict (for policy_goals).
    """
    eligibility = policy.get("eligibility_criteria") or {}
    summary = (policy.get("policy_summary") or "")[:_SHARED_BLOB_CHAR_CAP]
    elig_raw = (eligibility.get("raw_text") or "")[:_SHARED_BLOB_CHAR_CAP]

    parts: list[str] = []
    # Incentive-specific signal first — this is what must survive truncation.
    if incentive.get("incentive_name"):
        parts.append(f"Incentive: {incentive['incentive_name']}")
    if incentive.get("benefit_headline"):
        parts.append(f"Benefit: {incentive['benefit_headline']}")
    if incentive.get("description"):
        parts.append(f"Description: {incentive['description']}")
    for qb in (incentive.get("quantified_benefits") or []):
        if qb.get("description"):
            parts.append(f"Benefit detail: {qb['description']}")

    # Policy identity and metadata.
    parts.extend([
        f"Policy: {policy.get('policy_name', '')}",
        f"Category: {policy.get('category', '')}",
        f"Industry: {', '.join(policy.get('applicable_industries') or [])}",
        f"Size: {', '.join(policy.get('applicable_business_sizes') or [])}",
        f"Geography: {', '.join(policy.get('applicable_geographies') or [])}",
        f"Headline: {policy.get('benefit_headline', '')}",
        f"Keywords: {', '.join(policy.get('keywords') or [])}",
        f"Goals: {', '.join(summary_dict.get('policy_goals') or [])}",
    ])

    # Large shared blobs last — these are the ones that get truncated, not the incentive.
    parts.append(f"Summary: {summary}")
    parts.append(f"Eligibility: {elig_raw}")

    return "\n".join(p for p in parts if p.split(": ", 1)[-1].strip())


# ── Extraction faithfulness / completeness validation ──────────────────────────

def _normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def check_text_faithfulness(candidate: str, raw_text: str, threshold: float = 0.90) -> bool:
    """True if `candidate` appears (near-)verbatim in `raw_text`.

    Accepts: (a) exact normalized substring, (b) best-window difflib ratio >= threshold,
    or (c) >= 90% of the candidate's sentences individually present (the "stitched from
    verbatim sentences" case). Uses stdlib difflib — no extra dependency.
    """
    cand = _normalize_ws(candidate)
    doc = _normalize_ws(raw_text)
    if not cand or not doc:
        return False
    if cand in doc:
        return True

    # (b) best fuzzy window around the candidate's length.
    matcher = difflib.SequenceMatcher(None, cand, doc)
    if matcher.quick_ratio() >= threshold:
        blocks = matcher.get_matching_blocks()
        matched = sum(b.size for b in blocks)
        if cand and matched / len(cand) >= threshold:
            return True

    # (c) sentence-level stitch.
    sentences = [s for s in re.split(r"(?<=[.;:])\s+", cand) if len(s) > 10]
    if sentences:
        found = sum(1 for s in sentences if s in doc)
        if found / len(sentences) >= threshold:
            return True
    return False


def validate_extraction(summary_dict: dict, raw_text: str | None) -> list[dict]:
    """Return a list of review flags for faithfulness + required-field problems.

    Each flag: {policy_name, incentive_name, review_type, reason}. Non-blocking —
    the caller ingests regardless and writes these to review_queue.
    """
    flags: list[dict] = []
    for p in (summary_dict.get("policies") or []):
        policy_name = p.get("policy_name")
        eligibility = p.get("eligibility_criteria") or {}
        elig_raw = eligibility.get("raw_text")

        # Required-field checks (#1).
        if (p.get("validity") or {}).get("start_year") is None:
            flags.append({"policy_name": policy_name, "incentive_name": None,
                          "review_type": "missing_field", "reason": "start_year is NULL"})
        if not (elig_raw or "").strip():
            flags.append({"policy_name": policy_name, "incentive_name": None,
                          "review_type": "missing_field",
                          "reason": "eligibility_criteria.raw_text is empty"})

        # Faithfulness checks (#9).
        if (elig_raw or "").strip():
            if raw_text is None:
                flags.append({"policy_name": policy_name, "incentive_name": None,
                              "review_type": "unverifiable",
                              "reason": "eligibility raw_text unverifiable — no document text"})
            elif not check_text_faithfulness(elig_raw, raw_text):
                flags.append({"policy_name": policy_name, "incentive_name": None,
                              "review_type": "faithfulness",
                              "reason": "eligibility raw_text not found in document"})

        for inc in (p.get("incentives") or []):
            incentive_name = inc.get("incentive_name")
            for i, qb in enumerate(inc.get("quantified_benefits") or []):
                src = (qb.get("source_text") or "").strip()
                if not src:
                    flags.append({"policy_name": policy_name, "incentive_name": incentive_name,
                                  "review_type": "missing_field",
                                  "reason": f"quantified_benefits[{i}].source_text is empty"})
                elif raw_text is None:
                    flags.append({"policy_name": policy_name, "incentive_name": incentive_name,
                                  "review_type": "unverifiable",
                                  "reason": f"source_text[{i}] unverifiable — no document text"})
                elif not check_text_faithfulness(src, raw_text):
                    flags.append({"policy_name": policy_name, "incentive_name": incentive_name,
                                  "review_type": "faithfulness",
                                  "reason": f"quantified_benefits[{i}].source_text not found in document"})
    return flags


def rerank_with_cross_encoder(query: str, texts: list[str]) -> list[float]:
    """Score (query, text) pairs; returns raw logits (higher = more relevant).

    Raw logits are used instead of sigmoid so that domain-specific text (where most
    pairs are mildly relevant) retains dynamic range.  Sigmoid would compress all
    low-relevance scores near zero, making tiny floating-point differences the sort key.
    """
    import torch
    pairs = [(query, t) for t in texts]
    return _get_reranker_model().predict(pairs, activation_fn=torch.nn.Identity()).tolist()


def get_connection():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", 5432),
        dbname=os.getenv("POSTGRES_DB", "PoliSense_dev"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
    )


def ingest_into_review_queue(summary_dict: dict,
        conn: psycopg2.extensions.connection):
    """Ingests the structured policy summary into a review queue table for HITL verification."""
    parent_name = summary_dict.get("parent_policy_name") or None
    if parent_name is None:
        return None

    policies = summary_dict.get("policies") or []
    policy_summary = policies[0].get("policy_summary") if policies else None

    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO review_queue (
                parent_policy_name, policy_summary, policy_goals
            ) VALUES (
                %(parent_policy_name)s, %(policy_summary)s, %(policy_goals)s
            )
            RETURNING review_id
        """, {
            "parent_policy_name": parent_name,
            "policy_summary":     policy_summary,
            "policy_goals":       summary_dict.get("policy_goals") or [],
        })
        review_id = cur.fetchone()[0]  # type: ignore
    conn.commit()
    return review_id


def flag_for_review(conn: psycopg2.extensions.connection,
        parent_policy_name: str | None,
        policy_name: str | None,
        incentive_name: str | None,
        review_type: str,
        reason: str,
        details: dict | None = None) -> int | None:
    """Insert one data-quality flag into review_queue. Does NOT commit — the caller
    owns the transaction. Returns the new review_id."""
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO review_queue (
                parent_policy_name, policy_name, incentive_name,
                review_type, review_reason, details
            ) VALUES (
                %(parent)s, %(policy)s, %(incentive)s,
                %(rtype)s, %(reason)s, %(details)s
            )
            RETURNING review_id
        """, {
            "parent":    parent_policy_name,
            "policy":    policy_name,
            "incentive": incentive_name,
            "rtype":     review_type,
            "reason":    reason,
            "details":   Json(details) if details is not None else None,
        })
        review_id = cur.fetchone()[0]  # type: ignore
    return review_id


def ingest_policy(summary_dict: dict,
        conn: psycopg2.extensions.connection,
        source_folder: str | None = None):
    """
    Ingests a PDFExtraction dict into the policies table.
    Inserts one row per incentive per policy. Policies with no incentives
    get a single row with empty incentive fields.
    """
    inserted_ids = []

    with conn.cursor() as cur:
        for p in (summary_dict.get("policies") or []):
            validity    = p.get("validity") or {}
            eligibility = p.get("eligibility_criteria") or {}

            policy_details = {
                "policy_goals":         summary_dict.get("policy_goals") or [],
                "special_focus_areas":  p.get("special_focus_areas") or [],
                "keywords":             p.get("keywords") or [],
                "policy_summary":       p.get("policy_summary"),
                "eligibility_criteria": eligibility,
                "benefit_headline":     p.get("benefit_headline"),
                "issuing_authority":    summary_dict.get("issuing_authority"),
                "document_type":        summary_dict.get("document_type"),
            }

            incentives = p.get("incentives") or []
            if not incentives:
                incentives = [{}]

            for inc in incentives:
                incentive_details = {
                    "description":                    inc.get("description"),
                    "incentive_type":                 inc.get("incentive_type"),
                    "benefit_headline":               inc.get("benefit_headline"),
                    "quantified_benefits":            inc.get("quantified_benefits") or [],
                    "application_authority":          inc.get("application_authority"),
                    "application_process":            inc.get("application_process"),
                    "application_deadline":           inc.get("application_deadline"),
                    "incentive_specific_eligibility": inc.get("incentive_specific_eligibility"),
                }

                embedding_document = build_embedding_text(p, inc, summary_dict)
                embedding_vector = embed_documents(embedding_document)

                cur.execute("""
                    INSERT INTO policies (
                        parent_policy_name, policy_name, incentive_name,
                        category,
                        applicable_industries, applicable_geographies, applicable_business_sizes,
                        start_year, end_year,
                        policy_details, incentive_details,
                        search_vector, embedding,
                        source_folder, ingested_at
                    ) VALUES (
                        %(parent_policy_name)s, %(policy_name)s, %(incentive_name)s,
                        %(category)s,
                        %(applicable_industries)s, %(applicable_geographies)s, %(applicable_business_sizes)s,
                        %(start_year)s, %(end_year)s,
                        %(policy_details)s, %(incentive_details)s,
                        to_tsvector('english', %(search_text)s), %(embedding)s,
                        %(source_folder)s, NOW()
                    )
                    RETURNING policy_id
                """, {
                    "parent_policy_name":        summary_dict.get("parent_policy_name"),
                    "policy_name":               p.get("policy_name"),
                    "incentive_name":            inc.get("incentive_name"),
                    "category":                  p.get("category"),
                    "applicable_industries":     p.get("applicable_industries") or [],
                    "applicable_geographies":    p.get("applicable_geographies") or [],
                    "applicable_business_sizes": p.get("applicable_business_sizes") or [],
                    "start_year":                validity.get("start_year"),
                    "end_year":                  validity.get("end_year"),
                    "policy_details":            json.dumps(policy_details),
                    "incentive_details":         json.dumps(incentive_details),
                    "search_text":               embedding_document,
                    "embedding":                 embedding_vector,
                    "source_folder":             source_folder,
                })

                inserted_ids.append(cur.fetchone()[0])  # type: ignore

    conn.commit()
    return inserted_ids


def ingest_policy_document(
        parent_policy_name: str,
        pdf_paths: list[str],
        conn: psycopg2.extensions.connection,
) -> int | None:
    """
    Extract raw text from PDFs using pypdf and upsert into policy_documents.
    One row per parent_policy_name — ON CONFLICT DO NOTHING makes re-ingestion safe.
    Does NOT commit; the caller (db_ingestion) owns the transaction so a rollback
    on ingestion failure also rolls back this insert.
    Returns doc_id if a new row was inserted, None if it already existed.
    """
    from pypdf import PdfReader

    all_pages: list[str] = []
    for path in pdf_paths:
        for page in PdfReader(path).pages:
            all_pages.append(page.extract_text() or "")

    raw_text   = "\n\n".join(all_pages).strip().replace('\x00', '') or None
    page_count = len(all_pages)

    if raw_text is None:
        quality = "empty"
    elif any(t == "" for t in all_pages):
        quality = "partial"
    else:
        quality = "full"

    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO policy_documents
                (parent_policy_name, raw_text, extraction_method,
                 page_count, extraction_quality, source_file_paths)
            VALUES
                (%(name)s, %(text)s, 'pypdf',
                 %(pages)s, %(quality)s, %(paths)s)
            ON CONFLICT (parent_policy_name) DO NOTHING
            RETURNING doc_id
        """, {
            "name":    parent_policy_name,
            "text":    raw_text,
            "pages":   page_count,
            "quality": quality,
            "paths":   [str(p) for p in pdf_paths],
        })
        row = cur.fetchone()

    return row[0] if row else None  # type: ignore


def clear_policies_table(conn):
    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE policies RESTART IDENTITY CASCADE;")
    conn.commit()
    print("policies table cleared.")
