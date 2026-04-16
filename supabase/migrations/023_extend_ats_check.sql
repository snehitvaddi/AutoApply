-- 023_extend_ats_check.sql
--
-- Migration 001's discovered_jobs.ats CHECK constraint only allows four
-- values: (greenhouse, lever, ashby, workday). But the scout pipeline
-- emits aggregator sources too — indeed, himalayas, linkedin,
-- linkedin_public, ziprecruiter, jsearch — and every such row was
-- silently rejected by Postgres before Fix 7 surfaced upsert errors.
--
-- With Fix 7 (58f34e2) the failure is now visible in the drops[] array,
-- but the rows still can't be stored. This migration extends the
-- allow-set to include every ats value our scout sources actually
-- produce, plus a generic "other" bucket for future surfaces.
--
-- Admin note: the By-Platform donut chart (applications table) resolves
-- aggregator tags to the real ATS via _resolve_ats_for_log at log time,
-- so downstream analytics still partition correctly. This migration
-- only affects the pre-apply discovered_jobs table, where knowing the
-- SOURCE of a scout hit is useful — not the eventual ATS destination.

ALTER TABLE public.discovered_jobs DROP CONSTRAINT IF EXISTS discovered_jobs_ats_check;

ALTER TABLE public.discovered_jobs ADD CONSTRAINT discovered_jobs_ats_check
  CHECK (ats IN (
    -- Direct ATS (scout sources that hit the board API directly)
    'greenhouse',
    'lever',
    'ashby',
    'workday',
    'smartrecruiters',
    'icims',
    'jobvite',
    -- Aggregator sources (scout sources that surface jobs they didn't host)
    'linkedin',
    'linkedin_public',
    'indeed',
    'himalayas',
    'ziprecruiter',
    'jsearch',
    -- Catch-all for future sources. Normalize unknown to this rather
    -- than failing the row outright.
    'other'
  ));

COMMENT ON COLUMN public.discovered_jobs.ats IS
  'Scout source that surfaced this job. For aggregator sources '
  '(linkedin/indeed/himalayas/etc.) the real destination ATS is '
  'resolved from apply_url at application-log time via '
  '_resolve_ats_for_log. The set is extended in migration 023 — '
  'migration 001 was too narrow (greenhouse/lever/ashby/workday only) '
  'and silently rejected every aggregator scout hit.';
