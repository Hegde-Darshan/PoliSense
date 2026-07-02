# PoliSense — Retrieval Implementation Strategy

## Architecture

```
Business Profile (dict)
        │
        ▼
┌───────────────────┐
│  LLM Translation  │  LLM maps arbitrary profile keys → search intent
│  (questionnaire-  │  Output: semantic_query string + structured filters
│   agnostic)       │
└───────────────────┘
        │
   ┌────┴─────┐
   │          │
   ▼          ▼
Embed      Build SQL
query      WHERE clause
   │          │
   └────┬─────┘
        ▼
┌───────────────────┐
│  pgvector Search  │  Cosine similarity + metadata filters
│  (hybrid)         │  Returns top-K candidates
└───────────────────┘
        │
        ▼
┌───────────────────┐
│  LLM Reranking    │  LLM reranks, explains, flags eligibility gaps
│  & Explanation    │
└───────────────────┘
        │
        ▼
Ranked matches with explanations
```

## This design is questionnaire-agnostic

The key insight is that **no code knows the questionnaire field names**.
The LLM translation step (`build_search_intent`) receives the raw profile
dict and outputs a normalised search intent. When you update the questionnaire:

- Add new questions → the LLM picks them up automatically
- Rename fields → the LLM still understands the values semantically
- Change answer options → the LLM maps them to the right DB concepts

The only thing you'd update in code is the `SUPPORTED_FILTER_KEYS` comment
in the translation prompt if your DB schema changes.

## Database schema assumed

```sql
Schema (polisense_db_dev.policies):
    policy_id           UUID PK
    incentive_id        UUID
    parent_policy_name  TEXT
    policy_name         TEXT
    incentive_name      TEXT
    category            TEXT                  ← indexed
    industry            TEXT                  ← indexed
    sub_industry        TEXT                  ← indexed
    business_size       TEXT
    geography           TEXT                  ← indexed
    years               TEXT[]                ← GIN indexed
    policy_details      JSONB                 ← GIN indexed
                          .keywords []
                          .policy_goals []
                          .policy_summary
                          .eligibility_criteria
                          .special_attributes []
    incentive_details   JSONB
                          .description
                          .benefits {}
    embedding           VECTOR(N)             ← ivfflat cosine indexed
    created_at / updated_at

-- Required index for fast ANN search
CREATE INDEX ON policies USING hnsw (embedding vector_cosine_ops);
```

## Setup

```bash
pip install psycopg2-binary pgvector
```

```bash
export PG_HOST=localhost
export PG_DBNAME=polisense
export PG_USER=postgres
export PG_PASSWORD=yourpassword
```

## Usage

```python
from polisense_retrieval import find_matching_policies

profile = {
    # Any dict from your questionnaire — keys can be anything
    "industry": "Manufacturing",
    "sub_industry": "Leather goods",
    "msme_registration": "Yes — Small Enterprise",
    "state": "Rajasthan",
    "special_attributes": ["Women-led", "Export-oriented unit"],
    "policy_intent": ["Export promotion", "Capital investment subsidy"],
    # ... more fields
}

results = find_matching_policies(profile, top_k=10, final_n=5)

for match in results:
    print(match["scheme_name"], match["relevance_score"])
    print(match["match_reason"])
    print(match["eligibility_gaps"])
```

## Extending filters

To add a new filter (e.g. `year_of_scheme`), add it to:
1. The `"filters"` key description in `TRANSLATION_SYSTEM_PROMPT`
2. A new `if` block in `build_filter_clauses()`

That's it — the LLM will start populating it automatically from profile data.