-- Add `lever_boards` to user_job_preferences so per-tenant Lever overrides
-- can persist (mirrors `ashby_boards` and `greenhouse_boards` from earlier
-- migrations). Without this column, the worker's _expand_tenant_boards()
-- could resolve a Lever slug for a discovered company but had nowhere to
-- store it — so the discovery was lost on the next scout cycle.
--
-- Empty array default = "use the global pool from default_boards.py". A
-- non-empty value means the tenant has overridden the global list.
-- Idempotent via IF NOT EXISTS.

ALTER TABLE public.user_job_preferences
  ADD COLUMN IF NOT EXISTS lever_boards text[] NOT NULL DEFAULT '{}';

-- Per-bundle override (mirrors ashby_boards / greenhouse_boards on
-- user_application_profiles from migration 013). NULL means "inherit
-- from user_job_preferences"; empty array would force the global pool.
ALTER TABLE public.user_application_profiles
  ADD COLUMN IF NOT EXISTS lever_boards text[];
