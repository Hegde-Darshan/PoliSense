---
name: submission-retrieval-eval
description: Run the discovery retrieval evaluation against the Supabase policies DB using the REAL Zoho submission profiles (evals/datasets/submissions.jsonl, S001-S021, unlabelled), then write a qualitative report of whether the top matches fit each real business. These profiles carry no relevance labels, so recall/MRR/nDCG are not computed — the value is per-profile top-k inspection plus the geography, duplicate-crowding and latency checks. Use when asked to "eval the real submissions", "run the submission eval", "evaluate retrieval on the Zoho submissions", or /submission-retrieval-eval. For the labelled golden set (scored metrics), use the supabase-dataset-eval skill instead. Read-only; no ingestion, no Gemini.
---

# Submission retrieval eval

Runs the same harness as `supabase-dataset-eval` (`retrieve_policies` in `polisense_core/RetrievalPipeline/pg_retriever.py`, `top_k=20`, the production `_FILTER_KEYS`), but over the **real Zoho submissions** in `evals/datasets/submissions.jsonl` instead of the golden set. These 21 profiles (`S001`-`S021`, `source: "zoho_submission"`) are actual form submissions and carry **no relevance labels**, so this is a **qualitative** eval: judge whether each submission's top matches fit its real sector, geography and stated purpose. Recall / MRR / nDCG come back `None` by design — do **not** treat that as a failure or a broken run.

## Hard rules (check before running anything)

- **Read-only on Supabase.** Follow `CLAUDE.md`: never ingest, insert, update, delete or alter anything. `evals/retrieval_eval.py` opens the connection read-only; don't change that.
- **No Gemini or other LLM calls.** Run only `evals/retrieval_eval.py`. Don't import or run `ingestion_pipeline`, `assessment_pipeline`, `eligibility_checker`, `benefit_calculator` or `IngestionPipeline`.
- Don't edit the dataset files or the eval code to make output look better. If something looks broken, report it.

## Steps

1. **Check the target DB.** Read `POSTGRES_HOST` in `.env` (don't print the password). It must be the Supabase pooler host (`aws-0-ap-south-1.pooler.supabase.com`). If it isn't, stop and tell the user which DB `.env` points at.

2. **Check the inputs exist:** `evals/datasets/submissions.jsonl` (21 real submissions, `S001`-`S021`). The `--labels` file is passed only so the harness has one to load — none of its keys match the `S0xx` ids, and that is expected.

3. **Self-test the metric code** (fast, no DB):
   ```bash
   python -m evals.retrieval_eval --selftest
   ```
   Must print `selftest OK`. (Use `venv/Scripts/python.exe` instead of `python` if a venv exists.) If not, stop and report it.

4. **Run the eval** in the background (several minutes; ~15-40s per profile, cross-encoder + Supabase latency):
   ```bash
   python -u -m evals.retrieval_eval \
     --profiles evals/datasets/submissions.jsonl \
     --labels evals/datasets/v2/g2_relevance_v2.jsonl \
     > <scratch>/submission_eval.log 2>&1
   ```
   - Add `--no-ablations` — ablations are meaningless without labels, so skipping them is faster and loses nothing here.
   - Keep `--top-k 20`. Wait for the completion notification instead of polling.

5. **Read the outputs** in `evals/results/` (gitignored): `retrieval_report_<timestamp>.md` + `retrieval_eval_<timestamp>.json`. The headline Recall/nDCG/MRR tables will be empty / `None` — expected, no labels. Use these parts instead:
   - **per-profile `top10`** (in the JSON `per_profile[].top10`): the schemes returned for each submission — this is the main signal.
   - **checks**: geography-violation rate (must be 0), duplicate rate@10 and unique parents@10, profiles with no results, profiles with zero BM25 hits, latency p50/p95.
   - Note any non-Karnataka submission: the corpus is Karnataka-only (+2 National MSE-CDP rows), so those can only match the two cluster grants.

6. **Write a qualitative summary** to `evals/results/submission_eval_summary_<YYYY-MM-DD>.md`, for a teammate:
   - **What was run:** date, git SHA, DB (Supabase, read-only), `submissions.jsonl` hash, 21 profiles, top_k. State up front that these are **unlabelled**, so only the qualitative read + checks apply (no scored metrics).
   - **Per-submission verdict:** one line per `S0xx` — the business (sector / geography / stated purpose from its profile) → its top-1 and a couple of top-3 schemes → **sensible / questionable / wrong**, with a one-line reason.
   - **Checks:** geography violations (should be 0), duplicate crowding, any submission with no results, and which out-of-Karnataka submissions only get the National MSE-CDP rows.
   - **Patterns:** recurring good/bad behaviour across submissions (e.g. a sector that consistently gets off-topic matches, or ETP/Organic rows surfacing for unrelated businesses).
   - **Caveats:** Karnataka-only corpus; no labels, so this is judgement, not measurement.
   - **How to reproduce:** the exact command from step 4.

7. **Reply to the user** with: how many of the 21 submissions got sensible vs questionable/wrong top matches, the 3 most off matches (business → wrong scheme), and the summary path. Note that `evals/results/` is gitignored, so they must move/send the file to share it.
