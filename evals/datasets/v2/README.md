# Golden retrieval dataset v2 (Supabase corpus)

**Version:** v2.0 · **Date:** 2026-11-15 · **Status:** draft, labelled by Claude and **not checked by a person**

v1 (`../g2_relevance.jsonl`) was labelled against the local corpus: 675 rows, 66 parent policies. The Supabase database holds a different corpus: **330 rows, 22 parent policies**. Only 8 of those parents and 27 of the 310 `(parent, incentive)` keys also appear in v1. The v1 labels can't be used to score retrieval against Supabase, so v2 relabels the same profiles against the Supabase corpus.

A domain expert should review these labels before the metrics are used to make decisions. Labels were judged from the policy text stored in the database, not from the source PDFs.

## Files

| File | What it holds |
|---|---|
| `corpus.json` | Read-only dump of the Supabase `policies` table (330 rows), ordered by `parent_policy_name, policy_name, incentive_name`. The labels in the builder point at row indices in this file. |
| `build_g2_v2.py` | Hand labels plus the builder. Run `python evals/datasets/v2/build_g2_v2.py` to regenerate the JSONL. |
| `g2_relevance_v2.jsonl` | 284 graded labels, one per `(profile, incentive key)` |

**Profiles are unchanged.** v2 reuses `../g1_profiles.jsonl` (P001–P047) as is.

The schema, grading rubric (3 / 2 / 1, unlabelled = 0) and labelling rules are the same as v1 (see `../README.md`):
- Geography is a hard requirement. The builder asserts it: a profile from another state can only match rows tagged `National`.
- A profile with no geography (`geo_null`) is treated as open to any state, with a maximum grade of 2. The builder asserts this too.
- A superseded policy version usually gets 2. Examples are the EV Policy 2017 vs Clean Mobility 2025-30, and the Tourism 2020-26 guidelines vs the 2024-29 policy.
- Labels are keyed by `(parent_policy_name, incentive_name)`, copied exactly from the database. When several rows share a key, the highest grade is kept.
- The retriever, embeddings and reranker were **not** used, and no LLM calls were made. Every incentive was read against every profile.

## How to run against Supabase

```
python -m evals.retrieval_eval --labels evals/datasets/v2/g2_relevance_v2.jsonl
```

`retrieval_eval` opens the database read-only. `.env` must point at Supabase.

`validate_datasets.py` still checks the v1 file, so don't use it for v2. The builder runs the equivalent checks itself: every key exists in the dump, grades and rationales are well formed, and the geography and geo_null rules hold.

## Coverage

**Labels by grade:** 3: 40 · 2: 79 · 1: 165 (284 in total). Every one of the 22 parent policies has at least one label.

**Profiles with at least one label:** 36 of 47. **Profiles with a grade-2-or-higher label:** 29 of 47.

**Profiles with no grade-2-or-higher label (18):**
- P001, P007, P017, P018, P019, P020, P021, P022, P023, P024, P040, P041, P042, P043 and P046 are outside Karnataka, or out of scope (P046).
- P015 (solar EPC), P016 (women's incubator) and P045 (vague) have nothing that fits.

These profiles return `None` for recall, MRR and similar metrics, and are skipped in averages. They are still useful for the geography‑violation check and as "should return nothing strong" cases.

## Why v2 is much thinner than v1

- **The corpus is Karnataka only.** All 330 rows are tagged `Karnataka`. Only the 2 MSE‑CDP rows (Common Facility Center Grant and Infrastructure Development Grant) are also tagged `National`. There are no other central schemes (CLCSS, CGTMSE, PMEGP, SISFS and so on) and no Goa or Odisha policies. The 21 non‑Karnataka profiles can therefore only match those two cluster grants.
- **No biotech or startup seed grants.** Seed funding and incubator support (ELEVATE, SISFS, KITVEN deep‑tech funds) are missing. KITVEN appears only as the AVGC fund.
- **No sector policies for data centres, textiles, food processing (current) or coir.**

## Corpus quirks to know about

- **Mojibake in names.** Some parent names contain `ΓÇô` where an en dash should be: "Karnataka Global Capability Centre (GCC) Policy 2024 ΓÇô 2029" and "Micro, Small enterprises ΓÇô Cluster Development Programme". It's stored that way in the database, and the labels copy it exactly. If the names are ever cleaned up, these labels must be regenerated.
- **Copies under the wrong parent.**
  - Rows 0–13 sit under "Engineering Research & Development (Engineering R&D) Policy 2021" but describe ER&D GCC incentives beyond Bengaluru.
  - Rows 48–51 are ESDM incentives filed under "Karnataka Aerospace and Defence Policy 2022-27". They get equal grades to their ESDM originals.
- **Duplicate keys.** 330 rows map to 310 unique `(parent, incentive)` keys. For example, the EV policy 2017 repeats "Concessional Registration Charges" and "Investment Promotion Subsidy" for each sub‑sector. The evaluator collapses these to unique keys.
- **Category tags are often wrong.** Many R&D grants are tagged `Capital Subsidy` (Space policy), many Biotech rows are tagged `Other`, and A&D GCC incentives are tagged `R&D and Innovation Grant`.
- **Size tags are loose.** Many rows carry `All`, and "Startup" is attached to Mega/GCC rows.
