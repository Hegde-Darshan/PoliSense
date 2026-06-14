# PoliSense — Policy Retrieval Strategy

## Overview

PoliSense implements two independent retrieval pipelines that can be run side-by-side for comparison, A/B testing, or as fallback layers. Both pipelines share the same PostgreSQL + pgvector database and the same hybrid search architecture (SQL metadata filters + cosine vector similarity), but they differ in how they translate a business profile into a search query and how they rerank the results.

| | LLM Pipeline | No-LLM Pipeline |
|---|---|---|
| **File** | `polisense_retrieval.py` | `polisense_retrieval_nomllm.py` |
| **Profile → filters** | Claude (semantic) | Rule-based alias matching |
| **Query vector** | LLM-generated semantic paragraph | Templated profile text |
| **Reranking** | Claude (judgment + explanation) | Maximal Marginal Relevance (MMR) |
| **Output** | Ranked matches with explanations and eligibility gaps | Ranked matches with similarity and MMR scores |
| **External API calls** | 2 (translation + rerank) + 1 (embed) | 1 (embed only) |
| **Deterministic** | No | Yes |

---

## Shared Foundation: Hybrid Search

Both pipelines converge at the same database query. The hybrid search combines two signals:

**Metadata filters (SQL WHERE)** narrow the candidate pool using indexed columns before the vector search runs. This is fast and precise. The filters map to these indexed columns:

- `industry` — B-tree index (`idx_policies_industry`)
- `sub_industry` — B-tree index (`idx_policies_sub_industry`)
- `category` — B-tree index (`idx_policies_category`)
- `geography` — B-tree index (`idx_policies_geography`); always includes `National` policies alongside state-specific ones
- `business_size` — unindexed text, ILIKE partial match
- `years` — GIN index on `TEXT[]` (`idx_policies_years`), array overlap (`&&`)
- `special_attributes` — GIN index on `policy_details` JSONB (`idx_policies_details`), containment check (`@>`)

**Vector similarity** ranks the filtered candidates by cosine distance between the query embedding and the stored `embedding VECTOR(N)` column, using the ivfflat index (`idx_policies_embedding`). The final SQL looks like:

```sql
SELECT ..., 1 - (embedding <=> %s::vector) AS similarity
FROM policies
WHERE {metadata_filters}
ORDER BY embedding <=> %s::vector
LIMIT {top_k};
```

If metadata filters return zero results, both pipelines automatically retry without filters to preserve recall.

---

## Pipeline 1 — LLM-Assisted Retrieval

```
Business Profile
      │
      ▼
┌─────────────────────┐
│  Step 1: LLM        │  Claude reads the raw profile dict and outputs:
│  Translation        │  (a) a 150–250 word semantic query paragraph
│  (claude-sonnet)    │  (b) a structured filters dict
└─────────────────────┘
      │
   ┌──┴──────────────┐
   │                 │
   ▼                 ▼
Embed query      Build SQL
(OpenAI)         WHERE clause
   │                 │
   └──────┬──────────┘
          ▼
┌─────────────────────┐
│  Step 3: Hybrid     │  top_k=15 candidates
│  pgvector Search    │
└─────────────────────┘
          │
          ▼
┌─────────────────────┐
│  Step 4: LLM        │  Claude reranks, explains each match,
│  Rerank + Explain   │  and flags eligibility gaps
│  (claude-sonnet)    │
└─────────────────────┘
          │
          ▼
  final_n=5 results with
  match_reason + eligibility_gaps
```

### Step 1 — LLM Profile Translation

The profile dict is passed verbatim to Claude with a system prompt that instructs it to produce two outputs. This is the step that makes the pipeline questionnaire-agnostic: Claude understands the *meaning* of values regardless of what the key is named, so renaming `"state"` to `"operating_state"` or adding new questionnaire sections requires no code changes.

The semantic query is written as dense prose — not JSON — because policy embeddings in the database were generated from policy description text. Embedding a paragraph that reads like a policy beneficiary description produces higher cosine similarity against those stored vectors than embedding a raw JSON object would.

The filters dict uses a fixed set of keys matching the DB schema (`industry`, `sub_industry`, `category`, `geography`, `business_size`, `years`, `special_attributes`). Claude only populates a key when it is confident of the value, leaving ambiguous fields as null rather than guessing.

### Step 4 — LLM Reranking

After the hybrid search returns up to 15 candidates, a second Claude call reranks them and produces a structured explanation for each. The payload sent to Claude is slimmed down (top 4 policy goals, eligibility criteria text, benefits dict, similarity score) to stay within token budget while giving the model enough signal to reason about fit.

The output for each result includes:
- `relevance_score` — 0.0–1.0 judgment of overall fit
- `match_reason` — 2–3 sentences explaining why the policy fits this specific business
- `eligibility_gaps` — concrete things the business needs to verify before applying
- `benefits_summary` — one sentence on the key financial or non-financial benefit

---

## Pipeline 2 — No-LLM Retrieval (Rule-Based + MMR)

```
Business Profile
      │
      ▼
┌─────────────────────┐
│  Step 1: Rule-based │  FIELD_ALIASES dict maps known key variants
│  Filter Extraction  │  to filter dimensions; first match wins
└─────────────────────┘
      │
   ┌──┴──────────────┐
   │                 │
   ▼                 ▼
profile_to_text()  Build SQL
→ embed (OpenAI)   WHERE clause
   │                 │
   └──────┬──────────┘
          ▼
┌─────────────────────┐
│  Step 3: Hybrid     │  top_k=30 candidates (wider pool)
│  pgvector Search    │  + fetch embeddings for MMR
└─────────────────────┘
          │
          ▼
┌─────────────────────┐
│  Step 4: MMR        │  Maximal Marginal Relevance reranking
│  Reranking          │  balances relevance vs. result diversity
└─────────────────────┘
          │
          ▼
  final_n=5 results with
  similarity + mmr_score
```

### Step 1 — Rule-Based Filter Extraction

Filter extraction uses a `FIELD_ALIASES` dictionary that maps each filter dimension to a prioritised list of candidate profile keys:

```python
FIELD_ALIASES = {
    "geography": ["state", "geography", "location_state", "operating_state", ...],
    "industry":  ["industry", "industry_sector", "primary_industry", "sector", ...],
    "business_size": ["msme_tier", "business_size", "msme_registration", ...],
    ...
}
```

For each dimension, the code walks the alias list and returns the first non-empty value found in the profile. This gives the pipeline meaningful resilience to questionnaire field renames — adding a new alias for a dimension is a one-line change.

Business size values are normalised through a token map before filtering, so all of `"Yes — Small Enterprise"`, `"Small"`, and `"msme_small"` resolve to the canonical `"Small"` used in the database.

When no alias matches a dimension, that filter is simply omitted (no clause added), keeping recall high rather than returning zero results.

### Step 2 — Profile Text Generation

Rather than embedding raw JSON, the profile is templated into structured prose before embedding:

```
Industry: Manufacturing (General) — specifically Handmade leather goods and accessories
Products / services: Leather bags, wallets, and belts — domestic + export
MSME tier: Small Enterprise
Location: Rajasthan, India
Location type: Industrial Park / Cluster
Growth stage: Early Growth
Special attributes: Women-led / Women-owned (> 51%), Export-oriented unit, R&D / IP-driven
Policy needs: Capital investment subsidy, Export promotion, Working capital / interest subsidy
Registrations held: GST Registration, Export Import Code (IEC)
```

This format mirrors the kind of beneficiary language found in policy documents, improving cosine alignment with stored policy embeddings. Any profile fields not covered by the template are appended at the end as `key: value` lines, ensuring no data is silently dropped when new questionnaire fields are added.

### Step 4 — MMR Reranking

Maximal Marginal Relevance (Carbonell & Goldstein, 1998) is applied to the top-k candidates. The formula at each selection step is:

```
MMR(dᵢ) = λ · sim(dᵢ, query) − (1 − λ) · max_{dⱼ ∈ S} sim(dᵢ, dⱼ)
```

where S is the set of already-selected results. The algorithm greedily picks the candidate that maximises this score, then moves it to the selected set and repeats.

The `λ` parameter controls the relevance/diversity trade-off:

| λ value | Behaviour |
|---|---|
| `1.0` | Pure relevance — same as cosine ranking |
| `0.6` | Default — balances relevance and diversity |
| `0.0` | Pure diversity — maximises spread across policy space |

MMR solves a practical problem specific to this dataset: many incentives are sub-schemes of the same parent policy and share very similar or identical embeddings. Without diversity penalisation, the top-5 results would often all be variants of the same scheme. MMR ensures the user sees policies drawn from different programmes.

The candidate embeddings are fetched from the database in the same SQL query (cast to text, then parsed back to float lists in Python) to avoid a second round-trip.

---

## Choosing Between Pipelines

Neither pipeline is strictly better — the right choice depends on the use case.

Use the **LLM pipeline** when:
- The questionnaire is changing frequently and you can't keep alias lists up to date
- You need explanations or eligibility gap analysis to show users
- Query quality matters more than latency (the LLM query takes 1–2 seconds)
- You're dealing with edge cases or unusual business profiles where rules may not map cleanly

Use the **no-LLM pipeline** when:
- You need deterministic, reproducible results (e.g. for testing or audit)
- Latency is critical and the embedding call is the only acceptable external dependency
- You want to establish a cost-free baseline to measure LLM quality gain against
- The questionnaire is stable enough that alias lists stay accurate

A sensible production strategy is to run both in parallel, serve the LLM results to the user, and log both result sets. Over time, comparing where they agree and diverge will reveal where the LLM adds genuine value vs. where the simpler pipeline suffices.

---

## Configuration Reference

### Shared

| Parameter | Default | Description |
|---|---|---|
| `EMBEDDING_MODEL` | `text-embedding-3-small` | OpenAI embedding model. Must match what was used to populate the DB. |
| `TOP_K` | 15 (LLM) / 30 (no-LLM) | Candidates fetched from pgvector before reranking. The no-LLM pipeline uses a wider pool since MMR is cheap. |
| `FINAL_N` | 5 | Results returned to the caller. |

### No-LLM Pipeline Only

| Parameter | Default | Description |
|---|---|---|
| `MMR_LAMBDA` | `0.6` | λ in the MMR formula. Tune between 0 and 1. |
| `FIELD_ALIASES` | see code | Maps filter dimensions to candidate profile key names. Extend freely. |
| `MSME_SIZE_NORMALISATION` | `{"micro": "Micro", ...}` | Token map for normalising free-text MSME size answers. |

---

## Extending the System

**Adding a new questionnaire field to filters:** add aliases to `FIELD_ALIASES` in the no-LLM pipeline, and add the new key to the `"filters"` section of `TRANSLATION_SYSTEM_PROMPT` in the LLM pipeline. Then add a new `if` block in `build_filter_clauses()` in both files.

**Swapping the embedding provider:** replace the body of `embed_text()` in either file. The only constraint is that the new model's output dimension must match the `VECTOR(N)` column in the database and the embeddings already stored there.

**Tuning MMR diversity:** start at `λ=0.6` and inspect the `parent_policy_name` field of returned results. If multiple results share the same parent, lower λ. If results feel too scattered and miss the most relevant match, raise λ.