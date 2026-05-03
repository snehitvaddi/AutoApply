-- Migration 029: hard dedup safety net for successful submissions.
--
-- App code (scout enqueue + worker preflight) already filters out
-- previously-submitted (company, title) pairs, but those checks are
-- both racy: two scout cycles or two worker iterations can read the
-- same "no row exists" snapshot and both write a 'submitted' row.
-- This index makes the database the final arbiter — a second insert
-- with the same (user_id, lower(company), lower(title)) at status
-- 'submitted' will hard-fail with a unique violation, which the proxy
-- bubbles back to the worker as an error (the local SQLite copy still
-- records the local truth).
--
-- Partial-unique on status='submitted' is intentional. Failed/blocked
-- rows are kept for visibility but are NOT used for dedup — per the
-- product rule "if it didn't reach the company's server, retrying is
-- safe". Restricting the constraint to submitted means a previously
-- failed (company, title) can be re-submitted without violating it.
CREATE UNIQUE INDEX IF NOT EXISTS idx_applications_user_company_title_submitted
  ON public.applications (user_id, lower(company), lower(title))
  WHERE status = 'submitted';
