"""
Retrieval evaluation runner.

Reads a sample profiles JSON, runs the retrieval pipeline for each company,
and writes a results JSON keyed by company name.

Usage:
    python eval/eval_retrieval.py
    python eval/eval_retrieval.py --top-k 5 --output eval/my_results.json
"""
import argparse
import json
from pathlib import Path

from polisense_core.utils.postgres_utils import get_connection
from polisense_core.RetrievalPipeline.pg_retriever import retrieve_policies

_DEFAULT_INPUT = Path(__file__).parent / "sample_profiles.json"
_DEFAULT_OUTPUT = Path(__file__).parent / "retrieval_results.json"


def run_eval(input_path: Path, output_path: Path, top_k: int) -> None:
    with open(input_path) as f:
        companies = json.load(f)

    output = {}
    conn = get_connection()
    try:
        for company_name, entry in companies.items():
            query = entry["query"].strip()
            profile = entry.get("profile", {})

            try:
                results = retrieve_policies(
                    query=query,
                    conn=conn,
                    top_k=top_k,
                    industry=profile.get("industry"),
                    geography=profile.get("geography"),
                    business_size=profile.get("business_size"),
                )
                output[company_name] = {
                    "query": query,
                    "industry": profile.get("industry"),
                    "geography": profile.get("geography"),
                    "business_size": profile.get("business_size"),
                    "results": [
                        {
                            "incentive_name": r["incentive_name"],
                            "policy_name": r["policy_name"],
                            "parent_policy_name": r["parent_policy_name"],
                            "similarity_score": r.get("similarity_score"),
                            "metadata_boost": r.get("metadata_boost"),
                        }
                        for r in results
                    ],
                }
                print(f"[OK] {company_name}: {len(results)} results")
            except Exception as exc:
                print(f"[FAIL] {company_name}: {exc}")
    finally:
        conn.close()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\nSaved {len(output)} companies -> {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run retrieval eval over sample profiles.")
    parser.add_argument("--input", type=Path, default=_DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT)
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()
    run_eval(args.input, args.output, args.top_k)


if __name__ == "__main__":
    main()
