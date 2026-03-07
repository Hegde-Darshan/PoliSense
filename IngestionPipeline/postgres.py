import psycopg2
from psycopg2.extras import Json
from pathlib import Path
from dotenv import load_dotenv
import os
import json

from .utils import build_embedding_document, get_embedding
from pathlib import Path
from langchain_huggingface import HuggingFaceEmbeddings


load_dotenv()
ROOT_PATH = Path(__file__).parent.parent
load_dotenv(ROOT_PATH / ".env")
load_dotenv(ROOT_PATH / ".env.secrets")


def get_connection():
    """Create and return a psycopg2 connection using env variables."""
    conn = psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", 5432),
        dbname=os.getenv("POSTGRES_DB", "PoliSense_dev"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
    )
    return conn


def ingest_into_review_queue(summary_dict: dict,
        conn: psycopg2.extensions.connection):
    """Ingests the structured policy summary into a review queue table in Postgres for HITL verification."""
    pi_name = summary_dict.get("ParentPolicyName") or None
    if pi_name is not None:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO review_queue (
                    parent_policy_name, policy_summary, policy_goals
                ) VALUES (
                    %(parent_policy_name)s, %(policy_summary)s, %(policy_goals)s
                )
                RETURNING review_id
            """, {
                "parent_policy_name":   pi_name,
                "policy_summary":       summary_dict.get("PolicyInformation", {}).get("PolicySummary"),
                "policy_goals":         summary_dict.get("PolicyGoals") or [],
                })

            review_id = cur.fetchone()[0] # type: ignore
        conn.commit()
        return review_id


def ingest_policy(summary_dict: dict, 
        conn: psycopg2.extensions.connection, 
        embedding_model: HuggingFaceEmbeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-small-en-v1.5")):
    """
    Ingests the structured policy summary into the Postgres database. 
    Handles multiple subpolicies and incentives by inserting a row for each incentive under a policy.
    If no incentives are present, inserts a single row with empty incentive fields.
    """
    with conn.cursor() as cur:
        pi = summary_dict.get("PolicyInformation") or []
        
        for p in pi:
            policy_details = {
            "policy_goals":         summary_dict.get("PolicyGoals") or [],
            "special_attributes":   p.get("SpecialAttributes") or [],
            "keywords":             p.get("Keywords") or [],
            "policy_summary":       p.get("PolicySummary"),
            "eligibility_criteria": p.get("EligibilityCriteria"),
            }
            incentives = p.get("IncentivesAndBenefits") or []
            # If no incentives extracted, insert one row with empty incentive fields
            if not incentives:
                incentives = [{}]
            inserted_ids = []
            parts = [
            f"Summary: {p.get('PolicySummary', '')}",
            f"Eligibility: {p.get('EligibilityCriteria', '')}",
            f"Keywords: {', '.join(p.get('Keywords') or [])}",
            f"SpecialAttributes: {', '.join(p.get('SpecialAttributes') or [])}",
            f"Goals: {', '.join(summary_dict.get('PolicyGoals') or [])}",
            ]
            for inc in incentives:
                incentive_details = {
                "description": inc.get("Description"),
                "benefits":    inc.get("Benefits") or {},
                }
                parts.append(
                    f"Incentive: {inc.get('IncentiveName', '')} - {inc.get('Description', '')}"
                )
            
                # Build shared values across all rows for this policy
                embedding_document  = "\n".join(p for p in parts if p.split(": ", 1)[-1].strip())
                embedding_vector = get_embedding(embedding_document, embedding_model)
                cur.execute("""
                    INSERT INTO policies (
                        parent_policy_name, policy_name, incentive_name,
                        category, industry, sub_industry,
                        business_size, geography, years,
                        policy_details, incentive_details,
                        embedding
                    ) VALUES (
                        %(parent_policy_name)s, %(policy_name)s, %(incentive_name)s,
                        %(category)s, %(industry)s, %(sub_industry)s,
                        %(business_size)s, %(geography)s, %(years)s,
                        %(policy_details)s, %(incentive_details)s,
                        %(embedding)s
                    )
                    RETURNING policy_id
                """, {
                    "parent_policy_name":   summary_dict.get("ParentPolicyName"),
                    "policy_name":          p.get("PolicyName"),
                    "incentive_name":       inc.get("IncentiveName"),
                    "category":             p.get("Category"),
                    "industry":             p.get("Industry"),
                    "sub_industry":         p.get("SubIndustry"),
                    "business_size":        p.get("BusinessSize"),
                    "geography":            p.get("Geography"),
                    "years":                p.get("Year") or [],
                    "policy_details":       json.dumps(policy_details),
                    "incentive_details":    json.dumps(incentive_details),
                    "embedding":            embedding_vector,
                })

                inserted_ids.append(cur.fetchone()[0]) # type: ignore

    conn.commit()
    return inserted_ids


if __name__ == "__main__":
    summary_dict = {}
    with open(ROOT_PATH / "IngestionPipeline/example_data.json") as f:
        summary_dict = json.load(f)
    # print(summary_dict)
    print("Acuired data")
    try:
        conn = get_connection()
        print("success")
    except Exception as e:
        print("Error: ",e)
    embedding_model = HuggingFaceEmbeddings(model_name="BAAI/bge-small-en-v1.5")
    ids = ingest_policy(summary_dict, conn, embedding_model) # type: ignore
    print(ids)

