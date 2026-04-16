-- 024_worker_plan.sql
--
-- Central decision log for the cloud-planner architecture.
--
-- The worker is no longer a self-driving loop with hardcoded scout/apply
-- timers. Instead, every 60s it asks the cloud "what should I do next?" —
-- the planner writes the answer here with a reason, the worker executes,
-- reports outcome back to the same row.
--
-- This is the single source of truth for "why is the worker doing X right
-- now" and the basis of the Decision Log UI. One row per decision, with
-- outcome fields updated when the action completes.
--
-- Expiry: plans have a 10-minute TTL via expires_at. If the worker doesn't
-- pick up a plan in time (network drop, restart), the next planner call
-- issues a fresh one — we never execute a stale plan.

CREATE TABLE IF NOT EXISTS public.worker_plan (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  action      text NOT NULL CHECK (action IN (
    -- Scout actions — enqueue new discovered jobs
    'scout_primary',            -- ATS APIs (Ashby / Greenhouse / Lever / Workday)
    'scout_title_based',        -- Aggregators (LinkedIn / Himalayas / Indeed)
    'scout_expand_boards',      -- Probe ats_resolver for new company slugs
    -- Apply actions — submit a queued job
    'apply_next',
    -- Idle actions — no-op with different durations
    'idle_until_next_tick',     -- ~60s; no work to do right now
    'idle_until_midnight',      -- daily cap hit
    -- Recovery actions
    'restart_worker'
  )),
  params          jsonb NOT NULL DEFAULT '{}',
  decided_at      timestamptz NOT NULL DEFAULT now(),
  expires_at      timestamptz NOT NULL,
  reason          text NOT NULL,
  outcome         text CHECK (outcome IN ('success', 'empty', 'failed', 'skipped')),
  outcome_detail  text,
  outcome_at      timestamptz
);

-- Primary read path: "latest decisions for this user, newest first"
CREATE INDEX IF NOT EXISTS idx_worker_plan_user_decided
  ON public.worker_plan(user_id, decided_at DESC);

-- Secondary: quickly find the still-live plan for a user (expires in future,
-- outcome not yet set). Used by the worker poller to avoid double-executing.
CREATE INDEX IF NOT EXISTS idx_worker_plan_user_live
  ON public.worker_plan(user_id, expires_at)
  WHERE outcome IS NULL;

-- RLS: users can read their own plans only (dashboard Decision Log).
-- Service role + the worker proxy (service-role) can write.
ALTER TABLE public.worker_plan ENABLE ROW LEVEL SECURITY;

-- Drop-then-create so the migration is idempotent (e.g. when the table
-- was pre-populated via the Supabase MCP during development, the build
-- step re-running this file would otherwise error on duplicate policy).
DROP POLICY IF EXISTS worker_plan_select_own ON public.worker_plan;
CREATE POLICY worker_plan_select_own ON public.worker_plan
  FOR SELECT
  USING (auth.uid() = user_id);

COMMENT ON TABLE public.worker_plan IS
  'Cloud-planner decision log. One row per planner invocation. The '
  'worker polls the planner every 60s, executes the emitted action, '
  'and posts the outcome back to the same row. Single source of truth '
  'for "why is the worker doing X." Basis of the Decision Log UI.';
