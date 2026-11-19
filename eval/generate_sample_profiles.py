#!/usr/bin/env python3
"""Regenerate eval/sample_profiles.json from live Zoho data.

Fixes the eval queries so they match what the production discovery pipeline
actually retrieves with: each entry's `query` and `profile` are rebuilt with the
SAME transform production uses (discovery_runner.transform_rows_to_batch), i.e.
the applicant's real free-text description as the query plus the full profile
(industry, geography, business_size, enquiry_purpose, and Tier-2 fields).

Scope: only the businesses already present in sample_profiles.json are updated
(matched by business name). Test/junk Zoho rows are not pulled in, so the curated
eval set stays intact. Businesses no longer found in Zoho keep their old entry and
are reported.

Run:  python eval/generate_sample_profiles.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from polisense_core.discovery_runner import (
    get_access_token,
    fetch_all_rows,
    transform_rows_to_batch,
)

SAMPLE_FILE = Path(__file__).parent / "sample_profiles.json"


def _norm(name: str) -> str:
    """Whitespace/case-insensitive key for robust name matching."""
    return " ".join((name or "").split()).lower()


def build_name_index(batch: dict) -> dict:
    """Map normalised business_name -> {query, profile}, keeping the latest submission."""
    idx: dict[str, dict] = {}
    best_ts: dict[str, object] = {}
    for entry in batch.values():
        profile = entry["profile"]
        key = _norm(profile.get("business_name") or "")
        if not key:
            continue
        ts = entry.get("submission_time")
        if key not in idx or (ts and (best_ts.get(key) is None or ts > best_ts[key])):
            idx[key] = {"query": entry["query"], "profile": profile}
            best_ts[key] = ts
    return idx


def main() -> int:
    existing = json.loads(SAMPLE_FILE.read_text(encoding="utf-8"))
    print(f"Curated eval set: {len(existing)} entries")

    token = get_access_token()
    rows = fetch_all_rows(token)
    batch = transform_rows_to_batch(rows)
    idx = build_name_index(batch)
    print(f"Zoho submissions indexed by name: {len(idx)}")

    updated: dict[str, dict] = {}
    matched, missing = 0, []
    for name, old_entry in existing.items():
        hit = idx.get(_norm(name))
        if hit:
            updated[name] = hit
            matched += 1
        else:
            updated[name] = old_entry  # keep old entry if the business is gone from Zoho
            missing.append(name)

    SAMPLE_FILE.write_text(
        json.dumps(updated, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    print(f"Updated {matched}/{len(existing)} entries from live Zoho")
    if missing:
        print("NOT found in Zoho (kept as-is):")
        for m in missing:
            print("  -", m)
    return 0


if __name__ == "__main__":
    sys.exit(main())
