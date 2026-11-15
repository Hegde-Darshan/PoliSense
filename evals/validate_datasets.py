"""Validate evals/datasets/g1_profiles.jsonl and g2_relevance.jsonl against the DB and vocab.

Usage: python -m evals.validate_datasets   (exit code 1 on any error)
Read-only: opens the DB with readonly=True and makes no LLM calls.
"""
import ast
import json
import sys
from pathlib import Path

from polisense_core.utils.postgres_utils import get_connection

ROOT = Path(__file__).resolve().parents[1]
DS = Path(__file__).resolve().parent / "datasets"
SUFFIX = " government grants subsidies and incentives"
SIZES = {"Micro", "Small", "Medium", "Large", "Mega", "Startup"}


def _vocab():
    """Read tag dicts/sets from discovery_runner.py without importing it."""
    tree = ast.parse((ROOT / "polisense_core" / "discovery_runner.py").read_text(encoding="utf-8"))
    out = {}
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            target = node.targets[0] if isinstance(node, ast.Assign) else node.target
            name = getattr(target, "id", "")
            if name in ("_INDUSTRY_TAG", "_CATEGORY_TAG", "_SPECIAL_ATTRIBUTES_TAG"):
                out[name] = {v for v in ast.literal_eval(node.value).values() if v}
            elif name == "_INDIA_STATES":
                out[name] = set(ast.literal_eval(node.value.args[0]))
    return out


def _load(name):
    return [json.loads(line) for line in (DS / name).read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    v = _vocab()
    g1, g2 = _load("g1_profiles.jsonl"), _load("g2_relevance.jsonl")
    errors = []

    conn = get_connection()
    conn.set_session(readonly=True)
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT parent_policy_name, incentive_name FROM policies")
        db_keys = {(p, i) for p, i in cur.fetchall()}
    conn.close()

    ids = [p["profile_id"] for p in g1]
    if len(ids) != len(set(ids)):
        errors.append("duplicate profile_id in g1")
    for p in g1:
        pid, prof = p["profile_id"], p["profile"]
        if p["query"] != p["description"] + SUFFIX:
            errors.append(f"{pid}: query rule violated")
        if p["difficulty"] not in ("easy", "medium", "hard"):
            errors.append(f"{pid}: bad difficulty")
        if p["source"] not in ("business_profiles_json", "synthetic"):
            errors.append(f"{pid}: bad source")
        checks = [("industry", v["_INDUSTRY_TAG"]), ("special_attributes", v["_SPECIAL_ATTRIBUTES_TAG"]),
                  ("enquiry_purpose", v["_CATEGORY_TAG"])]
        for field, allowed in checks:
            val = prof.get(field)
            if val is not None and (not isinstance(val, list) or not val or set(val) - allowed):
                errors.append(f"{pid}: bad {field} {val}")
        if prof.get("geography") is not None and prof["geography"] not in v["_INDIA_STATES"]:
            errors.append(f"{pid}: bad geography {prof['geography']}")
        if prof.get("business_size") is not None and prof["business_size"] not in SIZES:
            errors.append(f"{pid}: bad business_size {prof['business_size']}")

    seen, best = set(), {}
    for r in g2:
        key = (r["parent_policy_name"], r["incentive_name"])
        if r["profile_id"] not in ids:
            errors.append(f"g2 unknown profile {r['profile_id']}")
        if key not in db_keys:
            errors.append(f"{r['profile_id']}: not in DB {key}")
        if r["relevance"] not in (1, 2, 3):
            errors.append(f"{r['profile_id']}: bad relevance {r['relevance']}")
        if (r["profile_id"], key) in seen:
            errors.append(f"{r['profile_id']}: duplicate label {key}")
        if len(r["rationale"].split()) > 20:
            errors.append(f"{r['profile_id']}: rationale > 20 words")
        seen.add((r["profile_id"], key))
        best[r["profile_id"]] = max(best.get(r["profile_id"], 0), r["relevance"])
    for p in g1:
        if best.get(p["profile_id"], 0) < 2 and "no_relevant" not in p["tags"]:
            errors.append(f"{p['profile_id']}: no grade>=2 label and not tagged no_relevant")

    for e in errors:
        print("ERROR", e)
    print(f"{len(g1)} profiles, {len(g2)} labels, {len(errors)} errors")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
