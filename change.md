# Change: Ingestion data-quality fixes (#8 embeddings, #6 vocab, #9/#1 faithfulness + missing-fields)

## Context

The 2026-11-16 ingestion audit (`evals/ingestion_checks.py`, 330 `policies` rows) found issues present in both the **pipeline** (repeated on every server run) and the **330 rows already ingested**. This change fixes three of them; OCR (#11) and numeric verification (#10) are out of scope.

- **#8 — 268/330 rows share an identical embedding with a sibling incentive (high).** `ingest_policy()` builds the embedded string parent-text-first: the large `Summary` (`policy_summary`) and `Eligibility` (eligibility `raw_text`) blobs lead, and the incentive-specific lines are appended last. BGE `bge-small-en-v1.5` silently truncates at 512 tokens, so the incentive tail is cut off and siblings collapse to the same vector.
- **#6 — 159 vocab-conformity failures (medium).** The `Literal` enums include `"All"` / `"All Sectors"`, and nothing strips them when specific tags are also present.
- **#9/#1 — 526 faithfulness + 17 missing-field failures (high).** No post-extraction validation exists; `source_text` / eligibility `raw_text` are never checked against `policy_documents.raw_text`, and `start_year` NULLs pass.

**Decisions:** fix **both** pipeline and existing rows; failures are **non-blocking → flagged to `review_queue`** (never drop a policy). Backfill needs **no LLM calls** — all source data is already stored.

## Changes

### #8 — Embedding re-order + re-embed
- `polisense_core/utils/postgres_utils.py`: extract a pure `build_embedding_text(policy, incentive, summary_dict)` helper used by both pipeline and backfill. Reorder so incentive-specific text (`Incentive`, `Benefit`, `Description`, `Benefit detail`) leads and the two large shared blobs (`Summary`, `Eligibility`) come last so truncation hits them, not the incentive text. Cap `Summary`/`Eligibility` to ~1000 chars each. `ingest_policy()` calls the helper.
- Backfill (`polisense_core/backfill_quality.py`): re-embed every row from stored `policy_details`/`incentive_details` + columns via the same helper; `UPDATE embedding` and rebuild `search_vector`.

### #6 — Strip `'All'` / `'All Sectors'`
- `polisense_core/IngestionPipeline/llm_extractor.py`: Pydantic `field_validator`s on `PolicyExtraction.applicable_business_sizes` / `applicable_industries` dropping `'All'` / `'All Sectors'` when the list length > 1.
- Backfill: SQL `array_remove` passes on existing rows.

### #9/#1 — Faithfulness + missing-field gate → `review_queue`
- `db/migrate_v7.sql` (new) + `db/schema.sql`: add `review_type`, `review_reason`, `policy_name`, `incentive_name`, `details JSONB` to `review_queue`.
- `polisense_core/utils/postgres_utils.py`: add `check_text_faithfulness` (stdlib `difflib`; exact / ratio ≥ 0.90 / sentence-stitch), `validate_extraction`, and `flag_for_review`.
- `polisense_core/ingestion_pipeline.py`: in `db_ingestion`, after a successful insert, run `validate_extraction` against `policy_documents.raw_text` and `flag_for_review` for each flag — in an isolated `try/except` so flagging never blocks ingestion.
- Backfill: audit existing rows and populate `review_queue`.

## Files
- `polisense_core/utils/postgres_utils.py` — helper refactor + validation + flagging
- `polisense_core/IngestionPipeline/llm_extractor.py` — vocab validators
- `polisense_core/ingestion_pipeline.py` — post-insert gate wiring
- `db/migrate_v7.sql` (new), `db/schema.sql` — `review_queue` columns
- `polisense_core/backfill_quality.py` (new) — vocab cleanup → re-embed → faithfulness audit

## Verification
1. Apply `db/migrate_v7.sql` (or `db/migrate_to_current.sql`); confirm new columns.
2. `python polisense_core/backfill_quality.py`; re-run `evals/ingestion_checks.py` → check 8 ~0, check 6 'All'-mix 0, `review_queue` populated for #9/#1.
3. Single-policy pipeline run: no NULL/zero embeddings, siblings distinct, `'All'` stripped, non-verbatim `source_text` flagged without aborting ingest.
4. Retrieval eval before/after (eval-retrieval-runner → eval-comparator): sibling incentives rank distinctly.
