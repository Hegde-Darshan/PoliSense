#!/usr/bin/env python3
"""
PoliSense Retrieval Eval Runner

Loads query-profile pairs from eval/sample_profiles.json, runs the retrieval
pipeline against each pair, and writes results to a timestamped JSON file.
"""

import sys
import json
import datetime
from pathlib import Path
from typing import Dict, Any, List

# Add parent directory to path so we can import polisense_core
sys.path.insert(0, str(Path(__file__).parent.parent))

from polisense_core.utils.postgres_utils import get_connection
from polisense_core.RetrievalPipeline.pg_retriever import retrieve_policies


def load_eval_inputs(eval_file: Path) -> Dict[str, Dict[str, Any]]:
    """
    Load query-profile pairs from the eval input file.

    Expected format:
    {
      "query_name": {
        "query": "<string>",
        "profile": {
          "industry": [<list>] or None,
          "geography": "<string>" or None,
          "business_size": "<string>" or None
        }
      }
    }
    """
    with open(eval_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Validate structure
    for query_name, entry in data.items():
        if 'query' not in entry or not isinstance(entry['query'], str):
            print(f"WARNING: Entry '{query_name}' missing or invalid 'query' field, skipping")
            continue
        if 'profile' not in entry or not isinstance(entry['profile'], dict):
            print(f"WARNING: Entry '{query_name}' missing or invalid 'profile' field, skipping")
            continue

    return data


def normalize_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize profile dict for retrieval pipeline.

    - industry: can be list or string; retrieve_policies expects list or string
    - geography: can be None; pipeline handles this
    - business_size: can be None; pipeline handles this

    Returns normalized profile ready for retrieve_policies(**profile).
    """
    normalized = {}

    # industry: may be None or a list
    if profile.get('industry'):
        normalized['industry'] = profile['industry']

    # geography: may be None
    if profile.get('geography'):
        normalized['geography'] = profile['geography']

    # business_size: may be None
    if profile.get('business_size'):
        normalized['business_size'] = profile['business_size']

    return normalized


def run_eval(eval_file: Path, top_k: int = 10) -> Dict[str, Any]:
    """
    Run the full evaluation: load inputs, call retrieve_policies for each,
    aggregate results.
    """
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    print(f"Loading eval inputs from {eval_file}")
    eval_data = load_eval_inputs(eval_file)

    total_queries = len(eval_data)
    print(f"Loaded {total_queries} query-profile pairs")

    # Open one DB connection for the entire batch
    print("Connecting to PostgreSQL...")
    conn = get_connection()

    results = {}
    successful_queries = 0
    failed_queries = 0

    try:
        for query_idx, (query_name, entry) in enumerate(eval_data.items(), 1):
            query = entry['query']
            profile = entry.get('profile', {})

            print(f"[{query_idx}/{total_queries}] Processing '{query_name}': {query[:60]}...")

            # Normalize profile for the retrieval API
            normalized_profile = normalize_profile(profile)

            try:
                # Call retrieve_policies with normalized profile
                retrieved_policies = retrieve_policies(
                    query=query,
                    conn=conn,
                    top_k=top_k,
                    **normalized_profile
                )

                # Structure results with rank and all fields
                ranked_results = []
                for rank, policy in enumerate(retrieved_policies, 1):
                    ranked_results.append({
                        'rank': rank,
                        'policy_id': policy.get('policy_id'),
                        'parent_policy_name': policy.get('parent_policy_name'),
                        'policy_name': policy.get('policy_name'),
                        'incentive_name': policy.get('incentive_name'),
                        'final_score': policy.get('incentive_score') or policy.get('similarity_score', 0.0),
                        'metadata_boost': policy.get('metadata_boost', 0.0),
                        'category': policy.get('category'),
                        'applicable_industries': policy.get('applicable_industries', []),
                        'applicable_geographies': policy.get('applicable_geographies', []),
                        'applicable_business_sizes': policy.get('applicable_business_sizes', [])
                    })

                results[query_name] = {
                    'query': query,
                    'profile': profile,
                    'retrieved_policies': ranked_results,
                    'error': None
                }

                successful_queries += 1
                print(f"  [OK] Retrieved {len(ranked_results)} policies")

            except Exception as e:
                failed_queries += 1
                error_msg = f"{type(e).__name__}: {str(e)}"
                results[query_name] = {
                    'query': query,
                    'profile': profile,
                    'retrieved_policies': [],
                    'error': error_msg
                }
                print(f"  [FAIL] Error: {error_msg}")

    finally:
        conn.close()
        print("Database connection closed")

    # Build output structure
    output = {
        'run_metadata': {
            'timestamp': timestamp,
            'top_k': top_k,
            'total_queries': total_queries,
            'successful_queries': successful_queries,
            'failed_queries': failed_queries,
            'eval_source': str(eval_file.relative_to(eval_file.parent.parent))
        },
        'results': results
    }

    return output


def main():
    eval_file = Path(__file__).parent / 'sample_profiles.json'

    if not eval_file.exists():
        print(f"ERROR: Eval file not found: {eval_file}")
        return 1

    print(f"Starting PoliSense Retrieval Eval Runner")
    print(f"Eval file: {eval_file}")
    print()

    # Run eval
    output = run_eval(eval_file, top_k=10)

    # Generate output filename with UTC timestamp
    timestamp_str = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')
    output_file = eval_file.parent / f'eval_{timestamp_str}.json'

    # Write output
    print()
    print(f"Writing results to {output_file}")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)

    # Print summary
    print()
    print("=" * 70)
    print(f"Evaluation Complete")
    print("=" * 70)
    print(f"Output file: {output_file}")
    print(f"Total queries: {output['run_metadata']['total_queries']}")
    print(f"Successful: {output['run_metadata']['successful_queries']}")
    print(f"Failed: {output['run_metadata']['failed_queries']}")
    print(f"Timestamp: {output['run_metadata']['timestamp']}")
    print("=" * 70)

    # Quality checks
    if output['run_metadata']['successful_queries'] == 0:
        print("WARNING: No successful queries! Check DB connection and logs above.")
        return 1

    # Verify output JSON is valid
    try:
        with open(output_file, 'r') as f:
            _ = json.load(f)
        print("[OK] Output JSON is valid")
    except json.JSONDecodeError as e:
        print(f"[FAIL] Output JSON is invalid: {e}")
        return 1

    # Verify metadata
    if output['run_metadata']['total_queries'] != len(output['results']):
        print(f"[FAIL] Mismatch: total_queries={output['run_metadata']['total_queries']} vs results={len(output['results'])}")
        return 1

    print("[OK] All quality checks passed")
    return 0


if __name__ == '__main__':
    sys.exit(main())
