# PoliSense
This is an intelligent policy filtering and ranking system, to help you find government grants/schemes and policies based on your requirements.  
All you have to do is give this a priliminary details about your company and what you are looking for. And, this will do the rest!
***


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