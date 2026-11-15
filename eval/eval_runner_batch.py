#!/usr/bin/env python3
"""
PoliSense Eval Runner — Batch Retrieval Evaluation

Runs the retrieval pipeline over all query-profile pairs in sample_profiles.json
and writes results to eval_<timestamp>.json with full result details.

Usage:
    python eval_runner_batch.py [--top-k 10]
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any

# Add parent to path so imports work
sys.path.insert(0, str(Path(__file__).parent.parent))

from polisense_core.utils.postgres_utils import get_connection
from polisense_core.RetrievalPipeline.pg_retriever import retrieve_policies


def normalize_profile(profile: Dict) -> Dict:
    """
    Normalize profile dict: ensure industry is a list, handle None values properly.
    """
    normalized = {}

    # Industry
    industry = profile.get("industry")
    if industry is not None:
        if isinstance(industry, list):
            normalized["industry"] = industry
        else:
            normalized["industry"] = [industry] if industry else None
    else:
        normalized["industry"] = None

    # Geography
    geography = profile.get("geography")
    normalized["geography"] = geography if geography else None

    # Business size
    business_size = profile.get("business_size")
    normalized["business_size"] = business_size if business_size else None

    return normalized


def run_evaluation(eval_input_path: Path, top_k: int = 10) -> Dict[str, Any]:
    """
    Run retrieval pipeline over all query-profile pairs.

    Returns a dict with:
    - run_metadata: timestamp, top_k, counts
    - results: {query_name: {query, profile, retrieved_policies, error}}
    """

    # Load eval set
    with open(eval_input_path, "r", encoding="utf-8") as f:
        eval_set = json.load(f)

    # Prepare output structure
    timestamp_utc = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    run_metadata = {
        "timestamp": timestamp_utc,
        "top_k": top_k,
        "total_queries": len(eval_set),
        "successful_queries": 0,
        "failed_queries": 0,
        "eval_source": str(eval_input_path),
    }

    results = {}

    # Open single DB connection for the batch
    print(f"Opening database connection...")
    try:
        conn = get_connection()
    except Exception as e:
        print(f"ERROR: Failed to connect to database: {e}")
        print("Make sure Docker is running (docker compose up -d) and .env credentials are correct.")
        sys.exit(1)

    try:
        # Run retrieval for each query
        query_names = sorted(eval_set.keys())
        for idx, query_name in enumerate(query_names, 1):
            print(f"[{idx}/{len(query_names)}] Running: {query_name}")

            entry = eval_set[query_name]
            query_text = entry.get("query", "")
            profile = entry.get("profile", {})

            # Normalize profile
            norm_profile = normalize_profile(profile)

            # Prepare result entry
            result_entry = {
                "query": query_text,
                "profile": norm_profile,
                "retrieved_policies": [],
                "error": None,
            }

            try:
                # Call retrieval pipeline
                policies = retrieve_policies(
                    query=query_text,
                    conn=conn,
                    top_k=top_k,
                    industry=norm_profile.get("industry"),
                    geography=norm_profile.get("geography"),
                    business_size=norm_profile.get("business_size"),
                    rerank=True,
                )

                # Transform results to output format
                ranked_policies = []
                for rank, policy in enumerate(policies, 1):
                    ranked_policies.append({
                        "rank": rank,
                        "policy_id": policy.get("policy_id"),
                        "parent_policy_name": policy.get("parent_policy_name"),
                        "policy_name": policy.get("policy_name"),
                        "incentive_name": policy.get("incentive_name"),
                        "final_score": float(policy.get("incentive_score", policy.get("similarity_score", 0.0))),
                        "metadata_boost": float(policy.get("metadata_boost", 0.0)),
                        "category": policy.get("category"),
                        "applicable_industries": policy.get("applicable_industries", []),
                        "applicable_geographies": policy.get("applicable_geographies", []),
                        "applicable_business_sizes": policy.get("applicable_business_sizes", []),
                    })

                result_entry["retrieved_policies"] = ranked_policies
                run_metadata["successful_queries"] += 1

                print(f"  [OK] Retrieved {len(ranked_policies)} policies")

            except Exception as e:
                result_entry["error"] = str(e)
                run_metadata["failed_queries"] += 1
                print(f"  [FAIL] Error: {str(e)[:80]}")

            results[query_name] = result_entry

    finally:
        conn.close()
        print("Database connection closed.")

    return {
        "run_metadata": run_metadata,
        "results": results,
    }


def main():
    eval_dir = Path(__file__).parent
    eval_input = eval_dir / "sample_profiles.json"

    if not eval_input.exists():
        print(f"ERROR: {eval_input} not found")
        sys.exit(1)

    print(f"Loading eval set from: {eval_input}")

    # Run evaluation
    output_data = run_evaluation(eval_input, top_k=10)

    # Write output
    timestamp = output_data["run_metadata"]["timestamp"]
    output_file = eval_dir / f"eval_{timestamp}.json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False, default=str)

    # Print summary
    meta = output_data["run_metadata"]
    print("\n" + "=" * 70)
    print("EVALUATION SUMMARY")
    print("=" * 70)
    print(f"Output file:        {output_file}")
    print(f"Timestamp:          {meta['timestamp']}")
    print(f"Total queries:      {meta['total_queries']}")
    print(f"Successful:         {meta['successful_queries']}")
    print(f"Failed:             {meta['failed_queries']}")
    print(f"Top-K:              {meta['top_k']}")
    print("=" * 70)

    # Verify output file is valid JSON
    try:
        with open(output_file, "r", encoding="utf-8") as f:
            json.load(f)
        print("[OK] Output JSON is valid and parseable")
    except Exception as e:
        print(f"[ERROR] Output JSON is invalid: {e}")
        sys.exit(1)

    if meta["successful_queries"] == 0:
        print("[WARNING] No successful queries! Check database connection and logs.")
        sys.exit(1)

    print(f"\n[OK] Evaluation complete. Results written to: {output_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
