-- PoliSense database schema
-- Run this on a fresh database (or after migrate_v2.sql on an existing one)

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS policies (
    policy_id                  SERIAL PRIMARY KEY,
    parent_policy_name         TEXT,
    policy_name                TEXT,
    incentive_name             TEXT,
    category                   TEXT,
    applicable_industries      TEXT[],   -- controlled vocab: see IndustryTag in llm_extractor.py
    applicable_geographies     TEXT[],   -- full state/region names or 'National'
    applicable_business_sizes  TEXT[],   -- controlled vocab: see BusinessSizeTag in llm_extractor.py
    start_year                 INTEGER,
    end_year                   INTEGER,
    policy_details             JSONB,    -- keys: policy_goals, special_focus_areas, keywords,
                                         --       policy_summary, eligibility_criteria (structured),
                                         --       benefit_headline, issuing_authority, document_type
    incentive_details          JSONB,    -- keys: description, incentive_type, benefit_headline,
                                         --       quantified_benefits (list), application_authority,
                                         --       application_process, application_deadline,
                                         --       incentive_specific_eligibility
    embedding                  VECTOR(384)
);

-- GIN index for fast array containment queries on filter columns
CREATE INDEX IF NOT EXISTS idx_policies_industries
    ON policies USING GIN (applicable_industries);

CREATE INDEX IF NOT EXISTS idx_policies_geographies
    ON policies USING GIN (applicable_geographies);

CREATE INDEX IF NOT EXISTS idx_policies_business_sizes
    ON policies USING GIN (applicable_business_sizes);

-- IVFFLAT index for approximate nearest-neighbour vector search
-- lists=100 is a reasonable starting point for up to ~10k rows;
-- rebuild with higher lists if the table grows significantly.
CREATE INDEX IF NOT EXISTS idx_policies_embedding
    ON policies USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);


CREATE TABLE IF NOT EXISTS review_queue (
    review_id        SERIAL PRIMARY KEY,
    parent_policy_name TEXT,
    policy_summary   TEXT,
    policy_goals     TEXT[],
    approval_status  BOOLEAN DEFAULT FALSE,
    created_at       TIMESTAMP DEFAULT NOW()
);
