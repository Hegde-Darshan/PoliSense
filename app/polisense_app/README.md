# PoliSense — Streamlit Policy Discovery App

A standalone Streamlit app that takes a business profile through a guided
questionnaire, runs it through a rule-based retrieval pipeline (SQL filters
+ local embeddings + MMR reranking, no LLM calls) against a Postgres +
pgvector `policies` table, and shows the top matching government policies.

Everything needed to run this lives in this one folder — no dependency on
any external project package.

## Folder contents

```
polisense_app/
├── app.py                 # Streamlit UI — renders the questionnaire, calls retrieval, shows results
├── retrieval.py            # Self-contained retrieval pipeline (filters → embed → search → MMR rerank)
├── questionnaire.py        # Declarative definition of the questionnaire (mirrors the .docx)
├── config.py                # All configuration, loaded from environment variables
├── logging_config.py       # Logging setup — writes to logs.log + stdout
├── tests/
│   └── test_retrieval.py   # Unit tests for the non-DB parts of the pipeline
├── requirements.txt
├── .env.example             # Copy to .env and fill in your DB credentials
├── .gitignore
├── Dockerfile
└── .streamlit/config.toml  # Headless server config for deployment
```

## 1. Setup

```bash
cd polisense_app
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# then edit .env with your real PG_HOST / PG_PORT / PG_DBNAME / PG_USER / PG_PASSWORD
```

The embedding model (`BAAI/bge-small-en-v1.5` by default) is downloaded
automatically the first time it's used (lazy-loaded on the first search, not
at app startup), and cached locally by `sentence-transformers` /
`huggingface_hub` afterwards.

## 2. Run locally

```bash
streamlit run app.py
```

Open the URL Streamlit prints (default `http://localhost:8501`). Use the
sidebar's **"Test DB connection"** button to confirm your `.env` credentials
work before filling out the form.

## 3. Logging

All pipeline activity — form submissions, extracted filters, embedding
steps, SQL search timing, MMR reranking, and any errors — is logged to:

- **`logs.log`** in the project root (rotating: 5 MB per file, 5 backups kept)
- **stdout**, so it also shows up in `streamlit run` output or your
  container/platform logs

Control verbosity via `LOG_LEVEL` in `.env` (`DEBUG`, `INFO`, `WARNING`,
`ERROR`). Each log line includes a timestamp, level, module name, and — for
app-level events — the Streamlit session ID, so you can trace one user's
journey through a busy log file.

## 4. Tests

```bash
python -m pytest tests/ -v
```

These cover the deterministic parts of the pipeline (filter extraction,
profile-to-text flattening, SQL clause building, MMR reranking) without
needing a live database or the embedding model.

## 5. Deploying

**Important — GitHub Pages will not work for this app.** GitHub Pages only
serves static files (HTML/CSS/JS); it cannot run a Python process, so it
can't host Streamlit, connect to Postgres, or run the embedding model. Use
one of these instead:

| Option | Notes |
| --- | --- |
| **Streamlit Community Cloud** | Free, easiest for a Streamlit app. Connect your GitHub repo, set `.env` values as "Secrets" in the app settings, deploy. |
| **Hugging Face Spaces** (Streamlit SDK) | Similar to above, good if you also want the embedding model cached in the same ecosystem. |
| **Render / Railway / Fly.io** | Use the included `Dockerfile`. Set the same env vars from `.env.example` as platform environment variables. |
| **Your own VM / EC2 + Docker** | `docker build -t polisense . && docker run -p 8501:8501 --env-file .env polisense`, then put nginx/Caddy in front for TLS + your domain. |

In all cases:
- Your Postgres+pgvector database needs to be reachable from wherever the
  app runs (a managed Postgres like RDS/Supabase/Neon with `PG_SSLMODE=require`
  is the simplest path — avoid `localhost` in production).
- Set `LOG_TO_CONSOLE=true` so your platform's log viewer captures activity
  even if `logs.log` isn't persisted across restarts (most PaaS filesystems
  are ephemeral) — mount a volume if you want `logs.log` to persist.
- Never commit `.env` — only `.env.example` is checked in.

## 6. Customizing

- **Add/remove questionnaire fields:** edit `questionnaire.py`. Field
  `key`s flow straight into the `business_profile` dict passed to
  `retrieval.py`.
- **Add new alias field names** (e.g. a new questionnaire version renames
  `"state"` to `"operating_region"`): add the alias to `FIELD_ALIASES` in
  `retrieval.py` — no other code changes needed.
- **Swap the embedding model:** change `EMBEDDING_MODEL` in `.env`. Must
  match the dimension of the `embedding VECTOR(N)` column in your DB.
- **Tune relevance vs. diversity:** adjust `MMR_LAMBDA` (or use the sidebar
  slider per-search) — 1.0 = pure relevance, 0.0 = pure diversity.
