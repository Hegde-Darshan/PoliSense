-- Migration v3: add policy_documents table
--
-- Non-destructive — adds the new table only.
-- policies and review_queue are not touched.
--
-- Run:
--   psql -U <user> -d PoliSense_dev -f db/migrate_v3.sql

BEGIN;

CREATE TABLE IF NOT EXISTS policy_documents (
    doc_id              SERIAL PRIMARY KEY,
    parent_policy_name  TEXT NOT NULL UNIQUE,
    raw_text            TEXT,
    extraction_method   TEXT NOT NULL DEFAULT 'pypdf',
    page_count          INTEGER,
    extraction_quality  TEXT CHECK (extraction_quality IN ('full', 'partial', 'empty')),
    source_file_paths   TEXT[],
    ingested_at         TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_policy_documents_parent
    ON policy_documents (parent_policy_name);

COMMIT;
