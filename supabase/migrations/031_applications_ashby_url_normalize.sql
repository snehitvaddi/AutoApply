-- One-shot rewrite for legacy Ashby URLs that landed in the queue / log.
--
-- The scout had two bugs that combined to produce dead URLs:
--   1. wrong API field (`applicationUrl` instead of Ashby's real `applyUrl`)
--   2. wrong fallback format (`/{slug}/application?jobId={id}`)
-- Ashby's React SPA does NOT route the legacy fallback path — it renders
-- "Job not found". The public apply form lives at `/{slug}/{id}/application`.
--
-- This migration rewrites every dead URL to the working format, in:
--   - public.discovered_jobs.apply_url   (where the proxy reads from on claim)
--   - public.applications.apply_url      (historical record, for thumbnail UI)
--   - public.application_queue           (no apply_url col — joins discovered_jobs;
--                                         left intact)
--
-- Idempotent: the regex predicate only matches the broken format, so re-runs
-- are a no-op. Safe to apply against a populated table — single full-table
-- pass under an exclusive write lock for the duration of each UPDATE.

BEGIN;

UPDATE public.discovered_jobs
   SET apply_url = regexp_replace(
         apply_url,
         '^(https?://jobs\.ashbyhq\.com/[^/]+)/application\?jobId=([a-f0-9-]+).*$',
         '\1/\2/application'
       )
 WHERE apply_url ~* '^https?://jobs\.ashbyhq\.com/[^/]+/application\?jobId=[a-f0-9-]+';

UPDATE public.applications
   SET apply_url = regexp_replace(
         apply_url,
         '^(https?://jobs\.ashbyhq\.com/[^/]+)/application\?jobId=([a-f0-9-]+).*$',
         '\1/\2/application'
       )
 WHERE apply_url ~* '^https?://jobs\.ashbyhq\.com/[^/]+/application\?jobId=[a-f0-9-]+';

COMMIT;
