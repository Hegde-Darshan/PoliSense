# Discovery retrieval evaluation: first baseline

Run date: 2026-11-14 · git `3d8de07` (branch `evals`) · 47 profiles, 836 graded labels · top_k = 20 (same as discovery)

## What was evaluated

- **Pipeline:** `retrieve_policies` in `RetrievalPipeline/pg_retriever.py`, called with the same query and filters as `discovery_pipeline.py`. Retrieval has 4 steps: vector + BM25 search, an RRF merge, a cross-encoder rerank, and a metadata boost.
- **Data:** the policies already in Postgres: 675 incentive rows under 66 parent policies. Nothing was re-ingested.
- **No LLM calls.** Nothing called Gemini or any other LLM, and every DB connection was read-only. The assessment pipeline was not evaluated.
- **Golden dataset** (`evals/datasets/`):
  - 47 business profiles: 16 from `Business_Profiles.json`, 31 new. About a quarter are hard cases (very short descriptions, no geography, only National schemes apply, niche schemes).
  - Each profile has incentives graded 1–3 for relevance (3 = eligible and directly matches the need). Unlabelled incentives count as 0. Labels are keyed by `parent_policy_name` + `incentive_name`.
  - "Relevant" in the binary metrics means grade ≥ 2.
- **Caveat:** Claude wrote the labels from the policy text in the DB. No domain expert has reviewed them yet, so treat these numbers as a first baseline. Karnataka makes up 26 of the 47 profiles; most other states have only 1–2.

## Headline results

| Level | Recall@10 | Recall@20 | nDCG@10 | MRR | Hit rate@5 |
|---|---|---|---|---|---|
| Per incentive | 0.33 | 0.45 | 0.42 | 0.63 | 0.78 |
| Per policy (deduped by parent) | 0.49 | 0.49 | 0.55 | 0.81 | 0.91 |

A relevant policy usually appears near the top, but more than half of the relevant incentives never appear at all.

## Ablations: which step helps?

| Config | Incentive nDCG@10 | Incentive Recall@20 | Policy Recall@20 |
|---|---|---|---|
| Vector only | 0.390 | 0.450 | 0.487 |
| BM25 only | 0.000 | 0.000 | 0.000 |
| RRF (vector + BM25) | 0.390 | 0.450 | 0.487 |
| RRF + rerank | 0.415 | 0.450 | 0.487 |
| RRF + rerank + boost (**production**) | 0.424 | 0.450 | 0.487 |
| Larger pool (fetch 5×, rerank 50) | 0.393 | 0.458 | **0.661** |

**Candidate recall** is the share of relevant items in the pool *before* the list is cut to the top 20:

| Pool | Per incentive | Per policy |
|---|---|---|
| Default | 0.58 | 0.61 |
| Larger pool | 0.81 | 0.85 |

## Main findings

1. **BM25 contributes nothing.** It returned 0 hits for all 47 profiles. `plainto_tsquery` requires every word in the query to match, so long Zoho-style queries (which end in "government grants subsidies and incentives") never do. Production is therefore the same as vector-only search.
2. **The vector search is weaker than it looks.**
   - Only 301 of the 675 rows have a distinct embedding. For example, the 22 Karnataka Aerospace incentive rows share 2 vectors.
   - Likely cause: in `ingest_policy`, the embedding text starts with a long policy-level block. bge-small reads only the first 512 tokens, and the incentive-specific text comes after that, so it is never embedded.
   - Effect: vector search can't tell incentives within one policy apart.
3. **Most misses happen before ranking.**
   - 207 of the 330 misses were never in the candidate pool.
   - A larger pool raises policy Recall@20 from 0.49 to 0.66. The catch is latency: the cross-encoder already takes about 14s per query (p50), so reranking 50 candidates on CPU would be much slower.
4. **A few parents crowd the top results.** On average the top 10 contains only 3.6 distinct parent policies, and 64% of the top 10 are repeats of a parent already shown. The rerank adds only +0.025 nDCG@10 and the metadata boost changes almost nothing.
5. **These cases fail worst:**
   - very short descriptions (nDCG@10 ≈ 0.02)
   - profiles where only National schemes apply
   - profiles with no geography
   - export: every International Cooperation Scheme incentive is never retrieved
   - renewable energy, organic inputs and cold chain, which score 0

   Geography violations were 0, so the hard filter works.

## Other retrieval checks

| Check | Value |
|---|---|
| Geography violation rate | 0.000 |
| Distinct parents in top 5 / 10 / 20 | 2.5 / 3.6 / 4.8 |
| Duplicate rate in top 10 | 0.64 |
| Industry / size match rate | 0.86 / 0.93 |
| Corpus coverage (rows / parents ever retrieved) | 65% / 79% |
| Latency: cold start / p50 / p95 | 22s / 14s / 20s |

## Why each relevant incentive was missed

Each relevant incentive that missed the top 10 was tagged with a likely cause:

| Cause | Count |
|---|---|
| Not in candidate pool (vector search didn't find it) | 207 |
| In pool, cut when RRF trimmed to top 20 | 64 |
| Pushed down by the cross-encoder | 37 |
| Ranked low for other reasons | 21 |
| Pushed down by the metadata boost | 1 |

13 profiles had a top 10 dominated by 2 or fewer parent policies.

## Ingestion data quality (affects retrieval)

From `evals/ingestion_checks.py`:

- **`start_year` is wrong on 48% of rows** (`20202025`, `20218`, `2007577531`), and `end_year` is NULL on 665 of 675 rows. Any validity or expiry filter is effectively broken.
- **Source text often doesn't match the stored PDF text.** 91% of `eligibility_criteria.raw_text` and 32% of `quantified_benefits.source_text` don't appear in `policy_documents.raw_text`. Either the model paraphrased or invented them, or they came from a different PDF than the one stored.
- **Geography holds city names on 133 rows** (Bengaluru, Mysuru, …). Today these rows also carry "Karnataka", so the filter still matches.
- **PDF text extraction is weak:** 29 of the 66 documents are `partial` and 2 are `empty`.
- **Corpus quirks:**
  - 12 duplicate rows.
  - The Karnataka "Handbook on Digital Economy" repeats incentives from other Karnataka policies, which adds to the crowding.
  - Category tags are often wrong; for example, interest and power subsidies are tagged `Capital Subsidy`.
- The checks for NaN, placeholder strings, digits where text is expected and runaway numbers all came back clean.

## Suggested next steps (in order)

1. **Fix the embedding text.** Put the incentive name and description first, or embed the incentive text on its own, then re-embed. This should help most, because most misses happen at the candidate stage.
2. **Fix BM25.** Use `websearch_to_tsquery` or OR'ed terms, and strip the Zoho suffix before the query.
3. **Before the report, keep only the best few incentives per parent policy**, so the top 5 shows more distinct policies.
4. **Fix the `start_year`/`end_year` values** at ingestion (add the bounds check from EVALUATION.md §4.1).
5. **Retest a larger candidate pool** after steps 1–2, and measure the latency cost of the cross-encoder.
6. **Have a domain expert review the golden labels**, starting with the hard profiles.

## How to reproduce

```bash
venv/Scripts/python.exe -m evals.validate_datasets        # check the dataset against the DB
venv/Scripts/python.exe -m evals.retrieval_eval            # full run with ablations, ~30 min
venv/Scripts/python.exe -m evals.retrieval_eval --no-ablations   # production config only, ~10 min
venv/Scripts/python.exe -m evals.ingestion_checks          # data-quality audit, ~4 min
```

Full per-profile detail, the worst cases with their returned results, and the list of never-retrieved incentives are in `evals/results/retrieval_report.md`. All numbers are also in the matching `retrieval_eval_<timestamp>.json`.
