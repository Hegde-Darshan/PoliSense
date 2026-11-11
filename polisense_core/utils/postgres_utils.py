import psycopg2
from psycopg2.extras import Json
from pathlib import Path
from dotenv import load_dotenv
import os
import json

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

            # Embedding base: all policy-level semantic signals
            base_parts = [
                f"Policy: {p.get('policy_name', '')}",
                f"Industry: {', '.join(p.get('applicable_industries') or [])}",
                f"Category: {p.get('category', '')}",
                f"Size: {', '.join(p.get('applicable_business_sizes') or [])}",
                f"Geography: {', '.join(p.get('applicable_geographies') or [])}",
                f"Headline: {p.get('benefit_headline', '')}",
                f"Summary: {p.get('policy_summary', '')}",
                f"Eligibility: {eligibility.get('raw_text', '')}",
                f"Keywords: {', '.join(p.get('keywords') or [])}",
                f"Goals: {', '.join(summary_dict.get('policy_goals') or [])}",
            ]

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

                inc_parts = base_parts[:]
                if inc.get("incentive_name"):
                    inc_parts.append(f"Incentive: {inc['incentive_name']}")
                if inc.get("benefit_headline"):
                    inc_parts.append(f"Benefit: {inc['benefit_headline']}")
                if inc.get("description"):
                    inc_parts.append(f"Description: {inc['description']}")
                for qb in (inc.get("quantified_benefits") or []):
                    if qb.get("description"):
                        inc_parts.append(f"Benefit detail: {qb['description']}")

                embedding_document = "\n".join(
                    part for part in inc_parts if part.split(": ", 1)[-1].strip()
                )
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
