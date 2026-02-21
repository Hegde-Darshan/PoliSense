import json
from utils import build_embedding_document, get_embedding
from pathlib import Path
from db import get_connection
from langchain_huggingface import HuggingFaceEmbeddings

ROOT_PATH = Path(__file__).parent.parent

def ingest_policy(summary_dict: dict, conn, embedding_model):
    pi = summary_dict.get("PolicyInformation") or {}
    incentives = pi.get("IncentivesAndBenefits") or []

    # Build shared values across all rows for this policy
    embedding_doc = build_embedding_document(summary_dict)
    embedding_vector = get_embedding(embedding_doc, embedding_model)

    policy_details = {
        "policy_goals":         summary_dict.get("PolicyGoals") or [],
        "special_attributes":   pi.get("SpecialAttributes") or [],
        "keywords":             pi.get("Keywords") or [],
        "policy_summary":       pi.get("PolicySummary"),
        "eligibility_criteria": pi.get("EligibilityCriteria"),
    }

    # If no incentives extracted, insert one row with empty incentive fields
    if not incentives:
        incentives = [{}]

    inserted_ids = []

    with conn.cursor() as cur:
        for inc in incentives:
            incentive_details = {
                "description": inc.get("Description"),
                "benefits":    inc.get("Benefits") or {},
            }

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
                "policy_name":          pi.get("PolicyName"),
                "incentive_name":       inc.get("IncentiveName"),
                "category":             pi.get("Category"),
                "industry":             pi.get("Industry"),
                "sub_industry":         pi.get("SubIndustry"),
                "business_size":        pi.get("BusinessSize"),
                "geography":            pi.get("Geography"),
                "years":                pi.get("Year") or [],
                "policy_details":       json.dumps(policy_details),
                "incentive_details":    json.dumps(incentive_details),
                "embedding":            embedding_vector,
            })

            inserted_ids.append(cur.fetchone()[0])

    conn.commit()
    return inserted_ids


def main():
    
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
    ids = ingest_policy(summary_dict, conn, embedding_model)
    print(ids)


if __name__ == "__main__":
    main()