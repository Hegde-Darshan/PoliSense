"""
Assessment pipeline — paid, triggered after client payment.

Orchestrates policy grouping, eligibility checking, benefit calculation,
and PDF generation for a batch of Zoho submissions.

Entry point:
    generate_assessment(zoho_data, top_k, output_dir)
"""

from __future__ import annotations

import logging
import logging.config
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Optional

from polisense_core.utils.postgres_utils import get_connection
from polisense_core.utils.logger import LOGGING_CONFIG
from polisense_core.RetrievalPipeline.pg_retriever import retrieve_policies
from polisense_core.retrieval_pipeline import _FILTER_KEYS, RETRIEVALS_DIR, _build_filename
from polisense_core.RetrievalPipeline.models import (
    FullPolicyResult,
    Tier2Report,
)
from polisense_core.RetrievalPipeline.eligibility_checker import check_policy_eligibility
from polisense_core.RetrievalPipeline.benefit_calculator import (
    check_and_calculate_incentive,
    extract_cost_breakup,
)
from polisense_core.PDF_utils.assessment_report import generate_assessment_pdf

logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger(__name__)

_MAX_WORKERS = 5


# ── Policy grouping ────────────────────────────────────────────────────────────

def _group_by_policy(tier1_results: list[dict]) -> list[dict]:
    """
    Group tier-1 rows by policy_name.
    Returns list of PolicyGroup dicts:
      {policy_name, parent_policy_name, max_similarity_score,
       policy_details, incentive_rows}
    """
    groups: dict[str, dict] = {}
    for row in tier1_results:
        key = row.get("policy_name") or row.get("parent_policy_name") or str(row.get("policy_id"))
        if key not in groups:
            groups[key] = {
                "policy_name":        row.get("policy_name") or "",
                "parent_policy_name": row.get("parent_policy_name") or "",
                "max_similarity_score": 0.0,
                "policy_details":     row.get("policy_details") or {},
                "incentive_rows":     [],
            }
        score = row.get("similarity_score") or 0.0
        if score > groups[key]["max_similarity_score"]:
            groups[key]["max_similarity_score"] = score
        groups[key]["incentive_rows"].append(row)

    return list(groups.values())


# ── Per-policy processing ──────────────────────────────────────────────────────

def _process_policy_group(group: dict, profile: dict) -> FullPolicyResult:
    """
    Run eligibility check + incentive selection + benefit calc for one policy.
    Designed to be called in parallel via ThreadPoolExecutor.
    """
    policy_name        = group["policy_name"]
    parent_policy_name = group["parent_policy_name"]
    similarity_score   = group["max_similarity_score"]
    policy_details     = group["policy_details"]
    incentive_rows     = group["incentive_rows"]

    # 4a — policy eligibility
    eligibility = check_policy_eligibility(policy_details, profile)

    # 4b — per-incentive applicability + benefit calc
    incentive_results = []
    for row in incentive_rows:
        result = check_and_calculate_incentive(row, profile)
        incentive_results.append(result)

    applicable = [
        r for r in incentive_results if r.applicability in ("APPLICABLE", "UNCERTAIN")
    ]
    not_applicable = [
        r for r in incentive_results if r.applicability == "NOT_APPLICABLE"
    ]

    # Aggregate total benefit across applicable incentives
    amounts = [
        r.total_potential_benefit_lakhs
        for r in applicable
        if r.total_potential_benefit_lakhs is not None
    ]
    total = sum(amounts) if amounts else None

    # Aggregate missing fields from eligibility + incentives
    missing = set(eligibility.missing_profile_fields)
    for r in incentive_results:
        for s in r.benefit_slabs:
            if s.missing_field:
                missing.add(s.missing_field)

    return FullPolicyResult(
        policy_name=policy_name,
        parent_policy_name=parent_policy_name,
        similarity_score=similarity_score,
        eligibility=eligibility,
        applicable_incentives=applicable,
        not_applicable_incentives=not_applicable,
        total_potential_benefit_lakhs=total,
        missing_profile_fields=sorted(missing),
    )


# ── Result assembly ────────────────────────────────────────────────────────────

def _assemble_report(
    policy_results: list[FullPolicyResult],
    profile: dict,
    query: str,
) -> Tier2Report:
    eligible, partial, not_eligible = [], [], []

    for r in policy_results:
        status = r.eligibility.overall_eligibility
        if status == "ELIGIBLE":
            eligible.append(r)
        elif status == "PARTIALLY_ELIGIBLE":
            partial.append(r)
        else:
            not_eligible.append(r)

    def _sort_key(r: FullPolicyResult):
        b = r.total_potential_benefit_lakhs
        return -(b if b is not None else 0.0)

    eligible.sort(key=_sort_key)
    partial.sort(key=_sort_key)
    not_eligible.sort(key=lambda r: -r.similarity_score)

    # Global missing fields (union across all policies)
    global_missing: set[str] = set()
    for r in policy_results:
        global_missing.update(r.missing_profile_fields)

    total_benefit_amounts = [
        r.total_potential_benefit_lakhs
        for r in eligible + partial
        if r.total_potential_benefit_lakhs is not None
    ]
    total_benefit = sum(total_benefit_amounts) if total_benefit_amounts else None

    return Tier2Report(
        business_name=profile.get("business_name") or query[:40],
        query=query,
        profile=profile,
        eligible_policies=eligible,
        partially_eligible_policies=partial,
        not_eligible_policies=not_eligible,
        total_eligible_count=len(eligible),
        total_potential_benefit_lakhs=total_benefit,
        global_missing_fields=sorted(global_missing),
    )


# ── Core single-query pipeline ─────────────────────────────────────────────────

def run_assessment(
    query: str,
    profile: dict,
    conn,
    top_k: int = 20,
) -> Tier2Report:
    """
    Run the full Tier-2 pipeline for one query+profile.

    Args:
        query:   Free-text search query (business description).
        profile: Extended company profile including tier-2 fields.
        conn:    Open psycopg2 connection (caller manages lifecycle).
        top_k:   Number of tier-1 results to process (default 20).

    Returns:
        Tier2Report with eligibility + benefit results for all policies.
    """
    # Step 1 — enrich profile with cost break-up extraction
    profile = extract_cost_breakup(profile)

    # Step 2 — tier-1 retrieval (unchanged)
    filters: dict = {}
    for key in _FILTER_KEYS:
        val = profile.get(key)
        if val:
            filters[key] = val
    if "enquiry_purpose" in profile and "category" not in filters:
        val = profile["enquiry_purpose"]
        if val:
            filters["category"] = val

    tier1_results = retrieve_policies(query=query, conn=conn, top_k=top_k, **filters)
    logger.info("Tier-1 returned %d rows for %s", len(tier1_results), profile.get("business_name"))

    if not tier1_results:
        return Tier2Report(
            business_name=profile.get("business_name") or query[:40],
            query=query,
            profile=profile,
        )

    # Step 3 — group by policy_name
    policy_groups = _group_by_policy(tier1_results)
    logger.info("Grouped into %d policies", len(policy_groups))

    # Step 4 — process each policy group in parallel
    policy_results: list[FullPolicyResult] = []
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
        futures = {
            executor.submit(_process_policy_group, group, profile): group["policy_name"]
            for group in policy_groups
        }
        for future in as_completed(futures):
            policy_name = futures[future]
            try:
                policy_results.append(future.result())
            except Exception as exc:
                logger.error("Processing failed for policy %s: %s", policy_name, exc)

    # Step 5 — assemble report
    return _assemble_report(policy_results, profile, query)


# ── Batch entry point ──────────────────────────────────────────────────────────

def generate_assessment(
    zoho_data: Dict[str, Dict],
    top_k: int = 20,
    output_dir: Path | str = RETRIEVALS_DIR,
) -> None:
    """
    Generate full eligibility & benefit quantum reports for a batch of queries.

    Args:
        zoho_data:  {query_name → {"query": str, "profile": dict, "submission_time": ...}}
                    profile should include the extended tier-2 fields parsed by discovery_runner.py.
        top_k:      Number of policies per query (default 20).
        output_dir: Output folder (default: project_root/Retrievals/).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    conn = get_connection()
    try:
        for query_name, entry in zoho_data.items():
            try:
                query   = entry["query"]
                profile = entry.get("profile") or {}

                report = run_assessment(query=query, profile=profile, conn=conn, top_k=top_k)

                report_path = output_dir / (_build_filename(entry) + "_assessment.pdf")
                generate_assessment_pdf(
                    query_name=query_name,
                    report=report,
                    submission_time=entry.get("submission_time"),
                    output_path=str(report_path),
                )
                logger.info(
                    "Full report written: %s (%d eligible, %d partial, %d not eligible)",
                    report_path.name,
                    report.total_eligible_count,
                    len(report.partially_eligible_policies),
                    len(report.not_eligible_policies),
                )
                print(
                    f"  OK  {query_name}  ->  {report_path.name}  "
                    f"({report.total_eligible_count} eligible)"
                )
            except Exception as e:
                logger.exception("Full report failed for %s", query_name)
                print(f"  FAIL  {query_name}: {e}")
    finally:
        conn.close()
