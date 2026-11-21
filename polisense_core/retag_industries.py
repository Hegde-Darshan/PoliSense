"""Re-tag `applicable_industries` on already-ingested policies under the expanded,
government-sourced industry vocabulary (see IndustryTag in IngestionPipeline/llm_extractor.py).

Why: the vocabulary was broadened (NIC-2008 / Make-in-India sub-sectors — Leather, Rubber &
Plastics, Space, AVGC, Waste/Recycling, Dairy, Fisheries, …). Existing rows were tagged under the
old coarse vocab (everything physical → "Manufacturing"), so they can't benefit from the finer
retrieval signal until re-tagged. This does a targeted re-classification only — no full re-ingest,
no change to any other extracted field.

Per distinct (parent_policy_name, policy_name) sub-scheme:
  1. one Gemini call over the scheme context + source document text → new applicable_industries
  2. UPDATE that sub-scheme's rows
Then re-embed every row (industry tags are part of the embedding/BM25 text) via the shared
`backfill_quality.reembed`. Idempotent; safe to re-run.

Run:  python -m polisense_core.retag_industries [--dry-run] [--limit N]
  --dry-run : print old -> new tags, write nothing, skip re-embed.
  --limit N : only process the first N sub-schemes (for a quick dry-run).
Read-only on Supabase unless you omit --dry-run.
"""
import argparse
import logging
from typing import List

from psycopg2.extras import RealDictCursor
from pydantic import BaseModel, field_validator

from polisense_core.utils import postgres_utils as db_utils
from polisense_core.IngestionPipeline.llm_extractor import IndustryTag, initialize_llm_with_config
from polisense_core.backfill_quality import reembed

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("retag_industries")

_DOC_CHAR_CAP = 20000  # source-text excerpt per call


class IndustryRetag(BaseModel):
    """Minimal structured-output schema: just the re-classified industry list."""
    applicable_industries: List[IndustryTag]

    @field_validator("applicable_industries")
    @classmethod
    def _dedupe_drop_all_sectors(cls, v: List[str]) -> List[str]:
        seen, out = set(), []
        for s in v:
            if s not in seen:
                seen.add(s); out.append(s)
        if len(out) > 1 and "All Sectors" in out:          # redundant with specific tags
            out = [s for s in out if s != "All Sectors"]
        return out


_PROMPT = """You re-classify an Indian government policy/scheme into a controlled industry vocabulary.
Return `applicable_industries` using ONLY the allowed values (enforced by the schema).

Rules:
- Prefer the MOST SPECIFIC sector(s) the scheme actually targets (e.g. "Leather and Footwear",
  "Space", "Waste Management, Recycling and Environmental Services", "Dairy and Animal Husbandry").
- Use the broad "Manufacturing" tag ONLY as a fallback when no specific manufacturing sub-sector
  fits, OR in addition to a specific sub-sector when the scheme genuinely spans general manufacturing.
- Use ["All Sectors"] only when the scheme is explicitly open to all sectors.
- Return 1-4 industries, most specific first. Do not tag a sector the scheme does not actually serve.

Parent policy: {parent}
Scheme: {policy_name}
Summary: {summary}
Incentives: {incentives}

Source document (excerpt):
{doc}
"""


def _get_model():
    base = initialize_llm_with_config(is_structured_model=False)
    return base.with_structured_output(schema=IndustryRetag.model_json_schema(), method="json_schema")


def retag(conn, model, dry_run: bool = False, limit: int | None = None) -> int:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT parent_policy_name, policy_name,
                   array_agg(DISTINCT incentive_name)
                     FILTER (WHERE incentive_name IS NOT NULL) AS incentives,
                   (array_agg(policy_details))[1]        AS policy_details,
                   (array_agg(array_to_string(applicable_industries, '|')))[1] AS current_industries
            FROM policies
            GROUP BY parent_policy_name, policy_name
            ORDER BY parent_policy_name, policy_name
        """)
        groups = cur.fetchall()
    if limit:
        groups = groups[:limit]

    doc_cache: dict[str, str] = {}

    def doc_for(parent: str) -> str:
        if parent not in doc_cache:
            with conn.cursor() as c:
                c.execute("SELECT raw_text FROM policy_documents WHERE parent_policy_name = %s", (parent,))
                r = c.fetchone()
            doc_cache[parent] = ((r[0] if r and r[0] else "") or "")[:_DOC_CHAR_CAP]
        return doc_cache[parent]

    changed = 0
    for g in groups:
        pd = g.get("policy_details") or {}
        prompt = _PROMPT.format(
            parent=g["parent_policy_name"],
            policy_name=g["policy_name"],
            summary=(pd.get("policy_summary") or "")[:1500],
            incentives=", ".join(g.get("incentives") or []) or "(none)",
            doc=doc_for(g["parent_policy_name"]),
        )
        result = model.invoke(prompt)
        new_inds = result["applicable_industries"] if isinstance(result, dict) else result.applicable_industries
        new_inds = IndustryRetag(applicable_industries=new_inds).applicable_industries
        old_inds = (g.get("current_industries") or "").split("|") if g.get("current_industries") else []

        if set(new_inds) != set(old_inds):
            changed += 1
            logger.info(f"[{g['policy_name'] or '—'}] {old_inds} -> {new_inds}")
            if not dry_run:
                with conn.cursor() as cur:
                    if g["policy_name"] is None:
                        cur.execute(
                            "UPDATE policies SET applicable_industries = %s "
                            "WHERE parent_policy_name = %s AND policy_name IS NULL",
                            (new_inds, g["parent_policy_name"]),
                        )
                    else:
                        cur.execute(
                            "UPDATE policies SET applicable_industries = %s "
                            "WHERE parent_policy_name = %s AND policy_name = %s",
                            (new_inds, g["parent_policy_name"], g["policy_name"]),
                        )
        else:
            logger.info(f"[{g['policy_name'] or '—'}] unchanged: {old_inds}")

    if not dry_run:
        conn.commit()
    logger.info(f"retag: {changed}/{len(groups)} sub-scheme(s) changed{' (dry-run, not written)' if dry_run else ''}")
    return changed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print changes, write nothing, skip re-embed")
    ap.add_argument("--limit", type=int, default=None, help="only process the first N sub-schemes")
    args = ap.parse_args()

    conn = db_utils.get_connection()
    try:
        model = _get_model()
        changed = retag(conn, model, dry_run=args.dry_run, limit=args.limit)
        if not args.dry_run and changed:
            logger.info("re-embedding affected corpus (industry tags are part of the embedding text)...")
            reembed(conn)
    finally:
        conn.close()
    logger.info("done")


if __name__ == "__main__":
    main()
