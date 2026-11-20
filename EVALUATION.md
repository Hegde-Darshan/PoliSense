# PoliSense: Evaluation Framework (proposal)

Status: draft. This document describes what we can measure and how we could set it up. Nothing here exists in code yet.

## 1. What we are evaluating

PoliSense has four stages. Each can fail on its own, and errors carry forward into the next stage, so we score each stage separately and the whole system end to end.

| # | Stage | Code | Output | LLM? |
|---|---|---|---|---|
| 1 | **Ingestion**: PDF → structured policy | `ingestion_pipeline.py`, `IngestionPipeline/llm_extractor.py` | `PDFExtraction` → `policies`, `policy_documents` rows | Yes (Gemini, structured output) |
| 2 | **Retrieval**: profile + query → ranked incentives | `RetrievalPipeline/pg_retriever.py` | top‑k `policies` rows | No: BM25 + pgvector, RRF merge, cross‑encoder rerank, metadata boost |
| 3 | **Eligibility**: profile × policy → verdict | `RetrievalPipeline/eligibility_checker.py` | `PolicyEligibilityResult` (per criterion `MET / NOT_MET / UNCERTAIN`) | Hybrid: rules + LLM |
| 4 | **Benefit calculation**: profile × incentive → ₹ amount | `RetrievalPipeline/benefit_calculator.py` | `IncentiveResult` / `BenefitSlabResult` | Hybrid: rules + LLM |

These stages feed two products: the **discovery** report (free, stage 2 only, `discovery_pipeline.py`) and the **assessment** report (paid, stages 2–4, `assessment_pipeline.py`).

Errors carry forward. A wrong `applicable_geographies` value at ingestion becomes a missing result at retrieval. A missing `eligibility_criteria.raw_text` becomes an `UNCERTAIN` at eligibility. Scoring each stage separately is what lets us find where a bad final report went wrong.

## 2. Golden datasets (the foundation)

All metrics below need labelled data. These are the datasets to build, in order of value:

| Dataset | Content | Size to start | Source |
|---|---|---|---|
| **G1: Profiles** | Realistic business profiles | 30–50 | `BusinessProfile/Business_Profiles.json` (16 exist), real Zoho submissions (anonymised) |
| **G2: Retrieval relevance** | For each G1 profile: the policies that are relevant, with graded labels | 30–50 profiles × ~5–15 labels | Domain expert labels. Optionally bootstrap with an LLM, then have a human correct the labels |
| **G3: Extraction ground truth** | Hand‑checked `PDFExtraction` for a set of policies | 10–15 policies | Annotate from the PDFs. Cover simple, table‑heavy, multi‑scheme and scanned documents |
| **G4: Eligibility verdicts** | Profile × policy → expected overall verdict + per‑criterion status | 50–100 pairs | Expert labels, deliberately including edge cases (thresholds, women/SC‑ST, location) |
| **G5: Benefit amounts** | Profile × incentive → expected ₹ amount with working | 30–50 pairs | Calculated by hand from the policy text |

Labelling rules:
- **Label by `parent_policy_name` + `incentive_name`, not `policy_id`.** UUIDs are regenerated on every re‑ingestion, so labels keyed on them break.
- **Use graded relevance for G2:** `3` = eligible and directly matches the need, `2` = relevant but partially eligible, `1` = related but weak, `0` = irrelevant (unlabelled means 0).
- **Store datasets as JSONL in version control** (`evals/datasets/`), and record the dataset version with every eval run.

## 3. Retrieval evaluation (non‑LLM, deterministic)

Retrieval needs no LLM to score. Given G2, every metric is a cheap, repeatable calculation. These should run on every PR.

### 3.1 Ranking metrics

| Metric | What it answers | Notes |
|---|---|---|
| **Recall@k** | Of all relevant policies, how many are in the top k? | The main metric. A policy we never show can't be recommended. Report @5, @10, @20 (discovery uses `top_k=20`). |
| **Precision@k** | Of the top k, how many are relevant? | Matters for the 5‑result report. |
| **Hit Rate@k** | Is there at least one relevant policy in the top k? | Simple health metric. |
| **MRR** (Mean Reciprocal Rank) | How high is the first relevant result? | Good for "did the best scheme come first?". |
| **nDCG@k** | Are the *most* relevant results ranked highest? | Uses the graded labels (0–3). Best single number for ranking quality. |
| **MAP@k** (Mean Average Precision) | Precision averaged at each relevant hit | Rewards placing many relevant results early. |

### 3.2 PoliSense‑specific retrieval checks

| Metric | Why it matters here |
|---|---|
| **Geography violation rate**: % of results whose `applicable_geographies` is neither the profile's state nor `National` | Geography is a hard filter. This should be 0. It also catches bad geography tags from ingestion. |
| **Duplicate rate / unique parents@k**: number of distinct `parent_policy_name` in the top k | One policy has many incentive rows. In testing, 3 of the top 5 were the same ESDM policy. Decide whether metrics are counted per incentive or per policy (recommend: dedupe by policy for the report). |
| **Industry / size match rate** | Checks the soft boosts (`_INDUSTRY_BOOST=1.0`, `_SIZE_BOOST=0.5`) are doing their job without swamping relevance. |
| **Validity rate**: % of results whose `end_year` is past or `NULL` | Expired schemes should be ranked lower or flagged. |
| **Corpus coverage**: % of ingested policies that appear in at least one top‑k across G1 | Finds policies that can never be retrieved because of bad embedding text or bad tags. |
| **Latency p50/p95** and **cold‑start time** | Cross‑encoder plus model loading time. |

### 3.3 Ablations (the most useful experiment)

Run the same G2 metrics with each component switched on or off. This tells us whether each piece of the hybrid pipeline is worth its cost:

1. vector only
2. BM25 only
3. RRF (vector + BM25)
4. RRF + cross‑encoder rerank
5. RRF + rerank + metadata boost (current production)

Also worth measuring: **candidate recall** (recall of the RRF pool *before* rerank). The current code reranks only `top_k` results from a pool of `fetch_n = top_k * 2`, so the reranker can't recover a relevant policy that RRF placed outside the top k. If candidate recall is much higher than final recall, rerank a larger pool.

Tunable values to sweep with this setup: RRF `k=60`, `fetch_n` multiplier, boost weights, the BGE query prefix, and the Zoho‑boilerplate stripping before rerank.

## 4. Ingestion evaluation

Ingestion is the most expensive stage to re‑run, and every later stage depends on it, so it pays to check it closely.

### 4.1 Deterministic checks (no labels needed, run on every ingested policy)

| Check | How |
|---|---|
| **Extraction success rate** | `policy_queried / (policy_queried + policy_failed)`. The current run had 65 succeed and 18 fail. |
| **Failure taxonomy** | Count failures by cause: runaway‑number JSON (Gemini emits a 60k‑digit number), `integer out of range` on insert, timeout/504, schema validation. |
| **Sanity bounds** | `1950 ≤ start_year ≤ end_year ≤ 2100`. Percentages 0–100. Amounts below a sane ceiling. Non‑empty `eligibility_criteria.raw_text`. At least 1 incentive. These checks would have caught the runaway‑number cases before they reached the DB. |
| **Source‑text faithfulness** (cheap and strong) | For every `quantified_benefits[].source_text` and `eligibility_criteria.raw_text`, check that it appears (after whitespace normalisation, or by fuzzy match ≥ 90%) in `policy_documents.raw_text`. Text that doesn't appear in the document was invented by the model. |
| **Value ↔ source consistency** | Check that `value_numeric` appears in `value_raw` / `source_text` (e.g. "25%" ↔ 25.0). |
| **Vocabulary conformity** | Industries, sizes, categories within the `Literal` sets. Pydantic already enforces this; track how often `Other` is used as a quality signal. |
| **PDF text quality** | Distribution of `policy_documents.extraction_quality` (`full / partial / empty`). Scanned PDFs mean the model and our checks are working without the text. |

### 4.2 Field‑level accuracy against G3

| Field type | Metric |
|---|---|
| Enums (`category`, `document_type`, `incentive_type`, `benefit_type`) | Exact‑match accuracy |
| Lists (`applicable_industries`, `applicable_geographies`, `applicable_business_sizes`, `keywords`) | Set precision / recall / F1 |
| Numbers (`value_numeric`, `cap_numeric`, thresholds, years) | Exact match + within ±1% tolerance, with unit conversion (lakhs/crores) |
| Incentive completeness | Incentive‑level recall (how many of the document's incentives were extracted) and precision (were any invented?) |
| Free text (`policy_summary`, `benefit_headline`) | LLM‑as‑judge (section 5): faithfulness + completeness |

### 4.3 Stability

Run extraction twice on the same documents and diff the outputs. Flaky fields such as amounts and years that change between runs are where the model is guessing. This also matters because the retry logic now uses temperature 0.3 or 0.6.

## 5. LLM‑based evaluation

Use these for outputs where string or number matching isn't enough: summaries, eligibility reasoning and benefit explanations.

### 5.1 Eligibility (stage 3)

With G4 labels, most of this is still deterministic. The LLM produces a label, and we compare labels.

| Metric | Notes |
|---|---|
| **Overall verdict accuracy + macro‑F1** over `ELIGIBLE / PARTIALLY_ELIGIBLE / NOT_ELIGIBLE` | Always look at the confusion matrix alongside this. |
| **False‑eligible rate** (predicted ELIGIBLE, truly NOT_ELIGIBLE) | **The most important number.** Telling a paying client they qualify when they don't is the worst failure. Track it separately and set a strict threshold. |
| **Per‑criterion accuracy** on `MET / NOT_MET / UNCERTAIN` | Split by source: rule‑based (`_rule_based_checks`) vs LLM (`_llm_checks`), to see which half is weaker. |
| **UNCERTAIN rate** and **missing‑field precision** | Too many UNCERTAINs makes the report useless. Check that `missing_profile_fields` names fields that really are missing and would really resolve the question. |
| **Hard‑blocker correctness** | Checks that `_HARD_BLOCKERS` fields produce NOT_ELIGIBLE as intended. |

### 5.2 Benefit calculation (stage 4)

| Metric | Notes |
|---|---|
| **Absolute / relative error** of `effective_amount_lakhs` vs G5 | Report median and p90. |
| **Within‑tolerance rate** (±5%) | The headline accuracy number. |
| **Cap application accuracy** | Was `cap_applied` correct, and was the capped value right? |
| **Applicability accuracy** (`APPLICABLE / NOT_APPLICABLE / UNCERTAIN`) | Same false‑positive concern as eligibility. |
| **Rule vs LLM split** | Accuracy of `_rule_calc_slab` vs `_llm_calc_incentive`. Good evidence for moving more cases to rules. |
| **Arithmetic check** | Re‑compute from `calculation_steps` in code, and flag where the LLM's stated working doesn't add up to its answer. |

### 5.3 LLM‑as‑judge metrics (for free text and reasoning)

| Metric | Question the judge answers | Applies to |
|---|---|---|
| **Faithfulness / groundedness** | Is every claim supported by the source document / `raw_text`? | Summaries, headlines, eligibility gaps, recommendations |
| **Hallucination rate** | Share of claims with no support | Same |
| **Completeness** | Did it capture all material eligibility conditions / incentives? | Extraction summaries |
| **Answer relevance** | Does the output address this profile's need? | Report sections |
| **Context relevance / precision** | Are the retrieved policies useful for answering? (RAG‑style; overlaps with section 3 without needing labels) | Retrieval when G2 labels are missing |
| **Reasoning correctness** | Does the eligibility reasoning follow from the criteria and profile? | `gap`, `recommendation` fields |
| **Actionability** | Are recommendations specific and doable? | `recommendation` |

Making judges trustworthy:
- **Use a rubric with a 1–5 scale or pass/fail per claim**, not "rate this", and ask the judge to cite the supporting text.
- **Use a different model or prompt from the one that generated the output**, to avoid self‑preference.
- **Calibrate against humans.** Have humans label about 50 items and measure judge–human agreement (Cohen's κ, or accuracy on pass/fail). Don't rely on a judge until κ ≥ ~0.6.
- **Check judge stability.** Run it twice. A judge that disagrees with itself is noise.
- **Track cost.** Log tokens and cost per eval run.

### 5.4 Operational metrics (all LLM stages)

- **Latency, tokens and cost** per policy (ingestion) and per report (assessment).
- **Retry rate and timeout rate.**
- **Schema‑parse failure rate.**

## 6. End‑to‑end evaluation

For the full assessment report on a G1 profile:
- **Report‑level judge:** is it correct, complete and safe to send to the client? Combine with the false‑eligible checks from 5.1.
- **Human spot check:** a domain expert reviews N reports per release on a simple rubric (correct schemes? correct verdicts? correct amounts?). These scores calibrate everything else.
- **Production feedback**, if available: which recommended schemes clients actually applied for or received. This is the true north metric, and it becomes the source of new G2/G4 labels.

## 7. How to set it up

### 7.1 Layout

```
evals/
  datasets/            # G1–G5 as JSONL, versioned
  retrieval_eval.py    # stage 2 metrics + ablations (deterministic)
  ingestion_checks.py  # 4.1 checks over the DB (no labels needed)
  extraction_eval.py   # 4.2 field accuracy vs G3
  eligibility_eval.py  # 5.1
  benefit_eval.py      # 5.2
  judges/              # LLM‑as‑judge prompts + rubrics
  results/             # run outputs (gitignored), one JSON per run
```

Each run records the **git SHA, dataset version, model name and key settings** (`top_k`, RRF `k`, boosts, temperature) next to its scores, so runs can be compared.

### 7.2 Tooling

- **LangSmith** is already a dependency and traces the ingestion graph (`@traceable`). Its *datasets + experiments* feature can hold G1–G5 and compare runs side by side, so we don't need to build a results UI.
- **Retrieval metrics** are about 50 lines of plain Python (recall, MRR, nDCG). A library such as `ranx` or `pytrec_eval` is optional.
- **LLM‑judge metrics:** our own judge prompts give the most control. Frameworks such as RAGAS or DeepEval provide ready‑made faithfulness, context precision and similar metrics if we want a faster start.
- **Use a separate eval database** (or a fixed DB dump), so retrieval scores don't change every time someone re‑ingests.

### 7.3 When each eval runs

| Trigger | What runs | Cost |
|---|---|---|
| Every PR | Retrieval metrics on G2, ingestion sanity checks, unit tests for rule‑based eligibility/benefit | Free, seconds |
| After each ingestion run | 4.1 deterministic checks over newly ingested rows | Free |
| Nightly / before release | Extraction vs G3, eligibility vs G4, benefit vs G5, LLM judges | LLM calls |
| On model or prompt change | Full suite + extraction stability (4.3) | LLM calls |

**Regression gates** (example starting points, to be tuned once a baseline exists): Recall@10 must not drop by more than 2 points, geography violations = 0, false‑eligible rate ≤ 2%, benefit within‑tolerance rate must not drop.

## 8. Suggested order of work

1. **Ingestion sanity checks (4.1).** No labels needed. These directly cover the failures we see today (runaway numbers, out‑of‑range years) and the hallucinated `source_text` risk.
2. **G1 + G2, then the retrieval metrics and ablations (section 3).** The highest return: deterministic, cheap, and they guide tuning of the hybrid search.
3. **G4 + eligibility metrics, especially the false‑eligible rate (5.1).** The biggest business risk in the paid report.
4. **G5 + benefit metrics (5.2).**
5. **G3 + extraction field accuracy (4.2), then LLM judges with human calibration (5.3).**
6. **Wire into CI and LangSmith experiments (7.3).**

## Appendix: issues observed during the current ingestion run

These are worth turning into tracked metrics straight away:
- **18 of 83 policy folders failed extraction.** Most failures were Gemini returning a runaway number of about 64,000 digits in structured JSON. A few were `integer out of range` on insert, probably the same garbage number landing in a year field, and one was a 504 timeout.
- **44 entries in the data folder are never ingested.** These are loose PDFs at the top level (scheme compendiums, booklets, guidelines), `.docx`/`.xlsx` files and empty folders. The ingestion code only reads PDFs inside policy sub‑folders.
- **Retrieval returns many rows from the same policy**, one row per incentive. Decide on dedup before defining per‑policy metrics.
- **The database schema is currently reconstructed from code**, and it doesn't match the official `schema.sql` yet. Fix the schema before trusting any baseline numbers.
