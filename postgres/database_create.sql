CREATE DATABASE "PoliSense_dev";

\c PoliSense_dev;

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

-- Create schema documentation

CREATE TABLE policies(
    policy_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    incentive_id UUID DEFAULT uuid_generate_v4(),
    -- Rest of the schema to be defined. 
    -- Schema flexibility is the priority for this, and next comes query performance.
    -- For schema flexibility, we can use JSONB to store the policy details, and create fields to only those keys that are highly deterministic,
    -- and subject to very little change
    -- For query performance, think about creating indexes on the most commonly queried fields
    
    -- Top-level Deterministic fields
    parent_policy_name  TEXT,                        -- PDFSummary.ParentPolicyName
    policy_name         TEXT NOT NULL,               -- PolicySummary.PolicyName
    incentive_name      TEXT,                        -- IncentiveSummary.IncentiveName
    category            TEXT,                        -- PolicySummary.Category
    industry            TEXT,                        -- PolicySummary.Industry
    sub_industry        TEXT,                        -- PolicySummary.SubIndustry
    business_size       TEXT,                        -- PolicySummary.BusinessSize (keep as text, LLM returns freeform)
    geography           TEXT,                        -- PolicySummary.Geography
    years               TEXT[],                      -- PolicySummary.Year

    -- Fields that can be put into policy JSONB column 
    policy_details      JSONB,                       -- holds: policy_goals, special_attributes,
                                                     --        keywords, policy_summary, eligibility_criteria

    -- Fields that can be put into Incentives JSONB column
    incentive_details   JSONB,                       -- holds: description, benefits (dict[str,str])

    -- Embedding
    embedding           VECTOR(768),
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);

-- Indexes on deterministic filter columns
CREATE INDEX idx_policies_industry       ON policies (industry);
CREATE INDEX idx_policies_sub_industry   ON policies (sub_industry);
CREATE INDEX idx_policies_geography      ON policies (geography);
CREATE INDEX idx_policies_category       ON policies (category);

-- GIN indexes for JSONB and array columns
CREATE INDEX idx_policies_years          ON policies USING GIN (years);
CREATE INDEX idx_policies_details        ON policies USING GIN (policy_details);
CREATE INDEX idx_policies_incentives     ON policies USING GIN (incentive_details);

-- Vector index
CREATE INDEX idx_policies_embedding      ON policies USING ivfflat (embedding vector_cosine_ops)
                                         WITH (lists = 100);


