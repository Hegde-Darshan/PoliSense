-- Migration: v1 schema → v2 schema
--
-- The column types changed fundamentally (TEXT → TEXT[]) and the old data
-- used free-text values that are incompatible with the new controlled vocab.
-- A full re-ingest is required regardless, so this migration drops and
-- recreates the policies table.
--
-- review_queue is unaffected.
--
-- Run:
--   psql -U <user> -d PoliSense_dev -f db/migrate_v2.sql

BEGIN;

DROP TABLE IF EXISTS policies CASCADE;

CREATE TABLE policies (
    policy_id                  SERIAL PRIMARY KEY,
    parent_policy_name         TEXT,
    policy_name                TEXT,
    incentive_name             TEXT,
    category                   TEXT,
    applicable_industries      TEXT[],
    applicable_geographies     TEXT[],
    applicable_business_sizes  TEXT[],
    start_year                 INTEGER,
    end_year                   INTEGER,
    policy_details             JSONB,
    incentive_details          JSONB,
    embedding                  VECTOR(384)
);

CREATE INDEX idx_policies_industries
    ON policies USING GIN (applicable_industries);

CREATE INDEX idx_policies_geographies
    ON policies USING GIN (applicable_geographies);

CREATE INDEX idx_policies_business_sizes
    ON policies USING GIN (applicable_business_sizes);

-- IVFFLAT index is created after data is loaded (requires rows to train).
-- Run this after ingestion completes:
--   CREATE INDEX idx_policies_embedding ON policies
--       USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

COMMIT;
