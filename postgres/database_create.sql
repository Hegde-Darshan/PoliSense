CREATE DATABASE "PoliSense_dev";

\c PoliSense_dev;

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

-- Create schema documentation

CREATE TABLE policies(
    policy_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    policy_name TEXT NOT NULL,);
    -- Rest of the schema to be defined. 
    -- Schema flexibility is the priority for this, and next comes query performance.
    -- For schema flexibility, we can use JSONB to store the policy details, and create fields to only those keys that are highly deterministic,
    -- and subject to very little change
    -- For query performance, think about creating indexes on the most commonly queried fields

