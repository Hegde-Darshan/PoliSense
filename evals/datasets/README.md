# Golden retrieval datasets (G1 profiles, G2 relevance)

**Version:** v0.1 · **Date:** 2026-11-14 · **Status:** draft, labelled by Claude and **not checked by a person**

> A domain expert (someone who knows Indian state and central incentive schemes) should review these labels
> before the metrics are used to make decisions. Labels were judged from the text of the policies stored in Postgres,
> not from the source PDFs or official scheme guidelines.

## Files

| File | Rows | What it holds |
|---|---|---|
| `g1_profiles.jsonl` | 47 | Business profiles shaped like the inputs to the discovery pipeline |
| `g2_relevance.jsonl` | 836 | Graded relevance labels, one per (profile, incentive) |
| `../validate_datasets.py` | n/a | Checks both files against the DB and the vocab (`python -m evals.validate_datasets`) |

### G1 schema (`g1_profiles.jsonl`)

```json
{"profile_id": "P001", "business_name": "str", "description": "str", "query": "str",
 "profile": {"industry": ["str"] | null, "geography": "str" | null, "business_size": "str" | null,
             "special_attributes": ["str"] | null, "enquiry_purpose": ["str"] | null},
 "difficulty": "easy|medium|hard", "tags": ["str"], "source": "business_profiles_json|synthetic"}
```

- `query` is always `description + " government grants subsidies and incentives"`. This is the same string that `discovery_runner.transform_rows_to_batch` builds.
- `industry` uses the `_INDUSTRY_TAG` values, `geography` uses `_INDIA_STATES`, and `business_size` is one of Micro, Small, Medium, Large, Mega or Startup. Turnover bands follow `_BUSINESS_SIZE_TAG`, and DPIIT registration becomes Startup.
- `special_attributes` uses the `_SPECIAL_ATTRIBUTES_TAG` values and `enquiry_purpose` uses the `_CATEGORY_TAG` values. They are recorded for analysis only, because retrieval does not filter on them.
- Retrieval receives only `industry`, `geography` and `business_size`. Null fields are left out of the filters.

### G2 schema (`g2_relevance.jsonl`)

```json
{"profile_id": "P001", "parent_policy_name": "str", "incentive_name": "str", "relevance": 1|2|3, "rationale": "str (<=20 words)"}
```

Labels are keyed by `(parent_policy_name, incentive_name)`, with names copied exactly from the `policies` table. They are never keyed by `policy_id`. Any incentive without a label counts as relevance 0.

## Grading rubric

| Grade | Meaning |
|---|---|
| 3 | The business is eligible and the incentive directly meets the stated need |
| 2 | Relevant and plausibly eligible, but it only partly meets the need or eligibility is unclear (age limits, incubation requirements, greenfield-only rules, coop vs company, superseded policy versions) |
| 1 | Related but weak: right geography or sector, but a different need, or a scheme aimed at institutions or clusters rather than this firm |
| 0 | Unlabelled |

Rules that were applied:
- **Geography is a hard requirement.** A state scheme for a different state is always 0. A script checked this for every label and found no violations.
- If a profile has no geography (`geo_null`), it is treated as "open to any state". Karnataka schemes can then score 1 or 2, but never 3.
- If an older policy version and a newer one both appear (for example the EV policies of 2017 and 2025-30), the superseded version usually gets 2.

## How it was built

1. Dumped all 675 rows of `policies` (66 parents) into a compact catalogue and read every incentive.
2. Turned the 16 entries in `BusinessProfile/Business_Profiles.json` into P001–P016. The turnover band gives the size, DPIIT status gives Startup, "National / Multiple" locations become geography null, and industries that are not in the vocab (handloom, FMCG, services) become null or the nearest tag. A realistic free-text description was written for each one.
3. Wrote 31 synthetic profiles, P017–P047, to fill coverage gaps.
4. Went through the whole corpus for each profile and labelled every incentive that scored 1 or more, with a short rationale. **The retriever, embeddings and reranker were not used**, so the labels do not reflect what the current system already returns. No LLM API calls were made.
5. Ran `python -m evals.validate_datasets`, which reported 0 errors. It checks that every key exists in the DB, every profile ID is valid, all vocab values are valid, the query rule holds, grades and rationales are well formed, and every profile has a label of grade 2 or higher unless it is tagged `no_relevant`.

## Coverage (v0.1)

**Profiles by difficulty:** easy 12, medium 23, hard 12 (about 26% hard).

**Profiles by source:** 16 from `business_profiles_json`, 31 synthetic.

**Profiles by geography:** Karnataka 26 · null 4 · Maharashtra 2 · Goa 2 · Rajasthan, Odisha, Gujarat, Tamil Nadu, Uttar Pradesh, West Bengal, Kerala, Himachal Pradesh, Telangana, Meghalaya, Jammu and Kashmir, Andhra Pradesh, Tripura: 1 each.
Every state that has policies in the corpus is covered. Rajasthan, West Bengal and Kerala have no state policies, so only National schemes can match them.

**Profiles by size:** Micro 14 · Small 13 · Startup 6 · Large 6 · Medium 3 · Mega 1 · null 4.

**Special attributes:** Women-led 11, SC/ST-led 3.

**Labels by grade:** 3: 139 · 2: 316 · 1: 381 (836 in total). Each profile has between 1 and 42 labels, 17.8 on average. Labels cover 58 of the 66 parents.

**Hard-case tags:** `terse`/`vague` (P023, P042, P045), `geo_null` (P008, P012, P015, P045), `industry_null` (P003, P016, P042, P045), `industry_mismatch` (P002, P013), `national_only` (11 profiles), `niche`/`exact_name` (Mahila Coir Yojana, Goan diaspora, cyber security, organic inputs, AMD-CF Himalayan), `city_tagged` (P028, a GCC in Mysuru), `multi_state_tag_trap` (non-Karnataka states that appear only on the Horticulture CDP row), `wrong_state_trap` (P043, an Andhra hatchery that must not match the Odisha pond scheme), `no_relevant` (P046, a crypto desk).

## Known corpus quirks that affect evaluation

- **Duplicate keys.** In 18 cases one `(parent, incentive_name)` maps to several rows. Most are harmless repeats, such as the three "Power Tariff Reimbursement" rows under the Special ESDM scheme. A few mix up different policies:
  - Under the Handbook parent, "Exemption from Electricity Duty" is both a Data Centre row and an EV row.
  - Under the Handbook parent, "Exemption from Stamp Duty" is both an EV row and an ESDM row.

  The evaluator should collapse retrieved rows to unique keys before computing metrics.
- **The corpus is mostly Karnataka.** Of 675 rows, 414 are Karnataka and 241 are National. Goa has 20 rows, Odisha has 1, and the other 11 states appear only on one multi-state "Horticulture Cluster Development Programme" row. As a result, non-Karnataka profiles get few labels.
- **Repeated content under different parents.** The Karnataka "Handbook on Digital Economy" repeats incentives from the IT, ESDM, EV, Data Centre, A&D and Startup policies under its own parent name. The same scheme also appears under several parents (Coir Vikas Yojana vs "(CVY)", NMCP variants, MSME Innovative, SISFS). The labels give equal grades to equivalent copies.
- **City geography tags.** Only the GCC policy carries city tags (Mysuru, Kalaburagi and so on), and it also carries "Karnataka", so the `ILIKE '%Karnataka%'` filter still matches. Many other Karnataka benefits only apply "Beyond Bengaluru" or "outside Zone 3", but that rule lives in the text, not in the metadata.
- **Category labels are often wrong.** Many interest subsidies, power concessions and R&D grants are tagged `Capital Subsidy`, many Karnataka IT incentives are tagged `Infrastructure Support`, and startup reimbursements are tagged `Tax Incentive`. This matters if `enquiry_purpose` is ever used as a filter.
- **Bad year values.** Some `start_year` values are invalid, such as 201282017, 20208 and 2007577531.
