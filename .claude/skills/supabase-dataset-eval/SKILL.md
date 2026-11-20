---
name: supabase-dataset-eval
description: Run the discovery retrieval evaluation against the Supabase policies DB using the golden LABELLED profiles (evals/datasets/g1_profiles.jsonl, 47 profiles P001-P047) and the v2 relevance labels (evals/datasets/v2/g2_relevance_v2.jsonl), producing SCORED metrics (recall / nDCG / MRR) plus a summary of what works, what fails, and how to improve it. Use when asked to "run the supabase eval", "evaluate retrieval on supabase", "run the golden dataset eval", or /supabase-dataset-eval. For the real unlabelled Zoho submissions (qualitative, no scored metrics), use the submission-retrieval-eval skill instead. Read-only; no ingestion, no Gemini.
---

# Supabase dataset eval

Scores the **discovery retrieval** (`retrieve_policies` in `polisense_core/RetrievalPipeline/pg_retriever.py`, called with `top_k=20` and the same filters as `discovery_pipeline.py`) against the golden dataset, using the policies already in Supabase. Produces a summary a teammate can read.

## Hard rules (check before running anything)

- **Read-only on Supabase.** Follow `CLAUDE.md`: never ingest, insert, update, delete or alter anything. `evals/retrieval_eval.py` opens the connection with `set_session(readonly=True)`; don't change that.
- **No Gemini or other LLM calls.** Run only `evals/retrieval_eval.py`. It imports `postgres_utils`, `pg_retriever` (local sentence-transformers models) and reads the `_FILTER_KEYS` constant from `retrieval_pipeline`, which itself only imports those two modules. Don't import or run `ingestion_pipeline`, `assessment_pipeline`, `eligibility_checker`, `benefit_calculator` or `IngestionPipeline`.
- **The assessment pipeline is out of scope.**
- Don't edit the dataset files or the eval code to make numbers look better. If something looks broken, report it.

## Steps

1. **Check the target DB.** Read `POSTGRES_HOST` in `.env` (don't print the password). It should be the Supabase pooler host (`aws-0-ap-south-1.pooler.supabase.com`). If it isn't, stop and tell the user which DB `.env` points at, because the v2 labels only match the Supabase corpus.

2. **Check the inputs exist:** `evals/datasets/g1_profiles.jsonl` (47 profiles) and `evals/datasets/v2/g2_relevance_v2.jsonl` (v2 labels). Read `evals/datasets/v2/README.md` for what the labels mean and their known gaps.

3. **Self-test the metric code** (fast, no DB):
   ```bash
   venv/Scripts/python.exe -m evals.retrieval_eval --selftest
   ```
   It must print `selftest OK`. If not, stop and report it.

4. **Run the eval.** Use `-u` so progress isn't buffered, and run it in the background, since a full run with ablations takes several minutes (the cross-encoder dominates, about 10–15s per profile, plus Supabase network latency):
   ```bash
   venv/Scripts/python.exe -u -m evals.retrieval_eval \
     --profiles evals/datasets/g1_profiles.jsonl \
     --labels evals/datasets/v2/g2_relevance_v2.jsonl \
     > <scratchpad>/supabase_eval.log 2>&1
   ```
   (`--profiles` is the default, but pass it explicitly — this skill is the **golden labelled** set. For the real **unlabelled** Zoho submissions, use the `submission-retrieval-eval` skill, which points `--profiles` at `evals/datasets/submissions.jsonl`.)
   - Add `--no-ablations` only if the user asks for a quick run (production config only).
   - Defaults are `--top-k 20 --rel-threshold 2` (relevant = grade ≥ 2). Keep them unless the user asks otherwise.
   - Wait for the completion notification instead of polling.

5. **Read the outputs.** They are written to `evals/results/` (gitignored):
   - `retrieval_report_<timestamp>.md` (a new file each run): headline metrics, ablations (one `stage:X` row per pipeline stage plus knob ablations, with any skipped knob and its reason), stage reach, slices, PoliSense checks, worst cases with miss diagnoses, never-retrieved incentives, observations.
   - The report header lists the filter keys passed and the pipeline stages seen in the trace. Check the dataset warnings for "no `trace` parameter" or dropped filter keys, and the PoliSense checks for "Trace/return mismatches". Either means the retriever changed in a way the trace hook doesn't cover; say so in the summary.
   - `retrieval_eval_<timestamp>.json`: all numbers, per-profile rows, git SHA and dataset hashes.

   First check the run's **dataset warnings** for label keys missing from the DB. If the Supabase corpus has changed since `v2/corpus.json` was dumped, missing keys silently lower recall. Report the count and say whether the labels need regenerating (`evals/datasets/v2/build_g2_v2.py`).

6. **Write the summary** to `evals/results/supabase_eval_summary_<YYYY-MM-DD>.md`, for a teammate who wasn't in the session. Use this structure:
   - **What was run:** date, git SHA, DB (Supabase, read-only), dataset files and hashes, profile and label counts, how many profiles were scored (profiles with no grade-≥2 label are skipped in recall/MRR averages; v2 has 18 of them), and top_k.
   - **Headline metrics:** a table with Recall@10, Recall@20, nDCG@10, MRR and Hit rate@5, per incentive and per policy.
   - **What's working:** metrics, slices and checks that look good (for example geography violations at 0, strong tags or slices), each with its number.
   - **What's failing:** the worst slices and profiles, the miss-cause breakdown (`not_in_candidates`, `dropped_by_truncation`, `reranker_demoted`, `outranked_by_boost`, `duplicate_crowding`), BM25 hit count, duplicate rate, never-retrieved incentives, and latency. For the 3–5 worst profiles, show the query, what was expected and what came back.
   - **Ablations:** which pipeline step helps or hurts (vector, BM25, RRF, rerank, boost, larger pool), with the candidate-recall gap.
   - **How to improve:** concrete changes ranked by expected impact, each tied to the evidence above (for example "207 of 330 misses never reach the candidate pool → fix embedding text"). Point to code locations (`pg_retriever.py`, `postgres_utils.ingest_policy`) where relevant. Suggest them only; don't make the changes.
   - **Caveats:**
     - The labels were written by Claude and no person has checked them.
     - The Supabase corpus is Karnataka only, so non-Karnataka profiles can only match the 2 National MSE-CDP rows.
     - Slices with 1–2 profiles are noisy.
     - v1 numbers (local DB, `evals/results/retrieval_analysis.md`) come from a different corpus and are **not** directly comparable.
   - **How to reproduce:** the exact command from step 4.

   If an earlier `supabase_eval_summary_*.md` exists, add a short **Change since last run** table for the headline metrics. Only compare runs with the same dataset hashes; otherwise say the dataset changed.

7. **Reply to the user** with: the headline numbers, the top 3 failures, the top 3 improvements, and the path to the summary file. Note that `evals/results/` is gitignored, so they need to move the file or send it directly if they want to share it.
