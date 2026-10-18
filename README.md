# PoliSense
This is an intelligent policy filtering and ranking system, to help you find government grants/schemes and policies based on your requirements.  
All you have to do is give this a priliminary details about your company and what you are looking for. And, this will do the rest!
***

## Extraction Schema

The ingestion pipeline sends each policy PDF to Gemini 2.5 Pro and extracts a structured `PDFExtraction` object. The table below documents every field, its type, whether it is required, and its purpose. Fields marked **Tier 1** are displayed directly at retrieval time (no LLM call needed). Fields marked **Tier 2** are used by the in-depth analysis pipeline to calculate exact benefits against a specific company's inputs.

### PDFExtraction — root model

| Field | Type | Required | Purpose |
|---|---|---|---|
| `parent_policy_name` | `str` | ✓ | Official name of the parent policy or act |
| `issuing_authority` | `str` | ✓ | Ministry or department that issued it |
| `document_type` | `Literal` | ✓ | Policy Document / Operational Guidelines / Government Order / Scheme Notification / Budget Announcement / Amendment / Other |
| `policy_goals` | `List[str]` | ✓ | Top-level stated objectives of the policy |
| `policies` | `List[PolicyExtraction]` | ✓ | All schemes extracted from this document |

### PolicyExtraction — one per scheme or sub-policy

| Field | Type | Required | Purpose |
|---|---|---|---|
| `policy_name` | `str` | ✓ | Name of this scheme or sub-policy |
| `category` | `Literal` | ✓ | Capital Subsidy / Interest Subvention / Tax Incentive / Infrastructure Support / R&D and Innovation Grant / Skill Development / Export Promotion / Market Access and Marketing Support / Land and Building Concession / Power and Utility Concession / Employment Generation / Working Capital Assistance / Credit Guarantee / Other |
| `applicable_industries` | `List[IndustryTag]` | ✓ | Controlled 21-value vocab. `['All Sectors']` if unrestricted. Stored as `TEXT[]` in DB. |
| `applicable_geographies` | `List[str]` | ✓ | Full state names or `'National'`. Stored as `TEXT[]` in DB. |
| `applicable_business_sizes` | `List[BusinessSizeTag]` | ✓ | Micro / Small / Medium / MSME / Large / Mega / Startup / All. Stored as `TEXT[]` in DB. |
| `validity` | `ValidityPeriod` | ✓ | Structured year range (see below) |
| `policy_summary` | `str` | ✓ | Self-contained comprehensive summary |
| `benefit_headline` | `str` | ✓ | **Tier 1.** One sentence with key numbers for display to a prospective applicant |
| `eligibility_criteria` | `EligibilityCriteria` | ✓ | Structured thresholds + verbatim text (see below) |
| `incentives` | `List[IncentiveExtraction]` | ✓ | All individual incentives under this policy |
| `keywords` | `List[str]` | ✓ | 10–15 terms covering industry, benefit types, and target groups for semantic search |
| `special_focus_areas` | `List[str]` | — | e.g. Women-led enterprises, SC/ST entrepreneurs, Green manufacturing, Export-oriented units |

### ValidityPeriod

| Field | Type | Required | Purpose |
|---|---|---|---|
| `start_year` | `int` | — | Year the policy becomes effective, e.g. `2020` |
| `end_year` | `int` | — | Year it expires. `None` if open-ended. |
| `raw_text` | `str` | — | Verbatim text as written, e.g. `"2020-2025"`, `"Until further notice"` |

### EligibilityCriteria

| Field | Type | Required | Purpose |
|---|---|---|---|
| `enterprise_type` | `List[Literal[New/Existing/Expansion/Any]]` | — | Whether the policy targets new, existing, or expansion projects |
| `minimum_investment` | `MonetaryThreshold` | — | Minimum investment required to qualify |
| `maximum_investment` | `MonetaryThreshold` | — | Upper cap if any |
| `minimum_employees` | `NumericThreshold` | — | Headcount requirement |
| `maximum_turnover` | `MonetaryThreshold` | — | Turnover cap (common for MSME-targeted policies) |
| `location_requirements` | `str` | — | Zone / district / tier-city requirements |
| `registration_requirements` | `str` | — | e.g. DPIIT recognition, Udyam registration, ISO certification |
| `special_category_benefits` | `List[str]` | — | Groups that receive enhanced benefits |
| `exclusions` | `str` | — | Hard disqualifiers — entities explicitly excluded |
| `other_requirements` | `str` | — | Any conditions not captured by the structured fields |
| `raw_text` | `str` | ✓ | **Tier 2.** Verbatim eligibility section copied from the document — source of truth for LLM reasoning |

### IncentiveExtraction — one per distinct incentive

| Field | Type | Required | Purpose |
|---|---|---|---|
| `incentive_name` | `str` | ✓ | Official name of the incentive |
| `incentive_type` | `Literal` | ✓ | Capital Subsidy / Interest Subvention / Income Tax Exemption / GST Reimbursement / Stamp Duty Exemption / Land Cost Reimbursement / Power Tariff Concession / Grant / Soft Loan / Credit Guarantee / Employment Subsidy / R&D Reimbursement / Patent Support / Export Incentive / Technology Upgrade Support / Fee Waiver / Other |
| `description` | `str` | ✓ | Full description of the incentive |
| `benefit_headline` | `str` | ✓ | **Tier 1.** One sentence with numbers, e.g. `"25% capital subsidy up to ₹50 lakhs for new manufacturing units"` |
| `quantified_benefits` | `List[QuantifiedBenefit]` | ✓ | One item per slab or condition (see below) |
| `application_authority` | `str` | — | Department or body the applicant must approach |
| `application_process` | `str` | — | Key steps or portal name |
| `application_deadline` | `str` | — | Deadline or application window |
| `incentive_specific_eligibility` | `str` | — | Conditions specific to this incentive beyond policy-level criteria |

### QuantifiedBenefit — one per slab or benefit component

| Field | Type | Required | Purpose |
|---|---|---|---|
| `benefit_type` | `Literal` | ✓ | percentage_subsidy / fixed_grant / tax_exemption / loan / interest_reduction / fee_waiver / employment_incentive / reimbursement / other |
| `description` | `str` | ✓ | Plain-text description of what this component provides |
| `value_raw` | `str` | ✓ | Exact value as written in the document, e.g. `"25%"`, `"₹50 lakhs"`, `"5 years"` |
| `value_numeric` | `float` | — | **Tier 2.** Parsed number for computation, e.g. `25.0` for `"25%"` |
| `value_unit` | `str` | — | **Tier 2.** Unit of `value_numeric`, e.g. `"%"`, `"lakhs INR"`, `"years"` |
| `cap_raw` | `str` | — | Cap as written, e.g. `"subject to a maximum of ₹50 lakhs"` |
| `cap_numeric` | `float` | — | **Tier 2.** Parsed cap for computation |
| `cap_unit` | `str` | — | Unit of `cap_numeric` |
| `applicable_to` | `str` | — | Slab label, e.g. `"Micro enterprises"`, `"New enterprises only"` |
| `conditions` | `str` | — | Triggering conditions, e.g. `"within 3 years of incorporation"` |
| `source_text` | `str` | ✓ | **Tier 2.** Verbatim sentence(s) from the document — verification anchor for exact benefit computation |

### Supporting value types

**MonetaryThreshold** — `{ amount: { value: float, unit: lakhs | crores | absolute_INR }, comparator: min | max | exact }`

**NumericThreshold** — `{ value: float, unit: str (e.g. "employees", "sq ft", "MW"), comparator: min | max | exact }`

---

## Running the Zoho poller (retrieval pipeline trigger)

The poller is a long-running process that checks Zoho Sheets for new form submissions every 2 hours and automatically runs the retrieval pipeline against each new row.

### 1. Configure environment variables

Copy `.env.examples` to `.env` (if not already done) and fill in the Zoho credentials:

```
ZOHO_DC=com                   # data-centre your Zoho account is on: com | in | eu | au
ZOHO_CLIENT_ID=<client_id>
ZOHO_CLIENT_SECRET=<client_secret>
ZOHO_REFRESH_TOKEN=<refresh_token>
ZOHO_WORKBOOK_ID=<numeric workbook ID from the sheet URL>
ZOHO_SHEET_NAME=Sheet1        # exact name of the worksheet tab
```

To get these values:
- Go to [Zoho API Console](https://api-console.zoho.com/) → Self Client → create OAuth credentials with scope `ZohoSheet.dataAPI.UPDATE`
- Generate a refresh token from the self-client grant flow
- The workbook ID is the number in the Zoho Sheet URL: `https://sheet.zoho.com/sheet/open/**{workbook_id}**/...`

### 2. Install dependencies

```bash
pip install -r requirements.txt
# or, if using the venv:
.venv/Scripts/pip install requests schedule
```

### 3. Start the poller

```bash
python polisense_core/zoho_poller.py
```

On startup it runs one poll immediately, then repeats every 2 hours.

**What happens each cycle:**
- Fetches all rows from the configured sheet
- Filters to rows with `form_submission_timestamp` newer than the last successful poll
- Builds a query + business profile from each row
- Runs the retrieval pipeline and writes results to `Retrievals/{business_name}.txt`
- Saves the poll timestamp to `documents/zoho_poll_state.json`

If a poll cycle fails (network error, bad token, etc.) it logs the error and retries at the next scheduled interval without crashing.

### 4. Stop the poller

Press `Ctrl+C` in the terminal.

To reset the poll state (re-process all rows on next start), delete `documents/zoho_poll_state.json`.

---

## Running the Zoho poller (retrieval pipeline trigger)

The poller is a long-running process that checks Zoho Sheets for new form submissions every 2 hours and automatically runs the retrieval pipeline against each new row.

### 1. Configure environment variables

Copy `.env.examples` to `.env` (if not already done) and fill in the Zoho credentials:

```
ZOHO_DC=com                   # data-centre your Zoho account is on: com | in | eu | au
ZOHO_CLIENT_ID=<client_id>
ZOHO_CLIENT_SECRET=<client_secret>
ZOHO_REFRESH_TOKEN=<refresh_token>
ZOHO_WORKBOOK_ID=<numeric workbook ID from the sheet URL>
ZOHO_SHEET_NAME=Sheet1        # exact name of the worksheet tab
```

To get these values:
- Go to [Zoho API Console](https://api-console.zoho.com/) → Self Client → create OAuth credentials with scope `ZohoSheet.dataAPI.UPDATE`
- Generate a refresh token from the self-client grant flow
- The workbook ID is the number in the Zoho Sheet URL: `https://sheet.zoho.com/sheet/open/**{workbook_id}**/...`

### 2. Install dependencies

```bash
pip install -r requirements.txt
# or, if using the venv:
.venv/Scripts/pip install requests schedule
```

### 3. Start the poller

```bash
python polisense_core/zoho_poller.py
```

On startup it runs one poll immediately, then repeats every 2 hours.

**What happens each cycle:**
- Fetches all rows from the configured sheet
- Filters to rows with `form_submission_timestamp` newer than the last successful poll
- Builds a query + business profile from each row
- Runs the retrieval pipeline and writes results to `Retrievals/{business_name}.txt`
- Saves the poll timestamp to `documents/zoho_poll_state.json`

If a poll cycle fails (network error, bad token, etc.) it logs the error and retries at the next scheduled interval without crashing.

### 4. Stop the poller

Press `Ctrl+C` in the terminal.

To reset the poll state (re-process all rows on next start), delete `documents/zoho_poll_state.json`.

---

## Running ChromaDB for the first time
- [ ] Install ChromaDB and make sure docker-compose.yml has chromadb service
- [ ] From project root, run - <docker compose up -d>
- [ ] To verify it's running, run - <docker ps> or check health with - <curl http://localhost:8000/api/v2/heartbeat>

## Booting up again or to restart
- [ ] To restart service, run - <docker compose down>
- [ ] To start service, run - <docker compose up -d>

## Using Makefile to run services
- [ ] Ensure Makefile exists and WSL is installed, and has <make> installed in it
- [ ] Docker Desktop is enabled with WSL2 engine
- [ ] Run <make help> to view available commands