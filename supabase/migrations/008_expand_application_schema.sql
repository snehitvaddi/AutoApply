-- Migration 008: Expand applications table to match local SQLite schema
-- Adds missing columns, expands status enum, adds indexes

-- Expand status check constraint to include full pipeline statuses
ALTER TABLE public.applications DROP CONSTRAINT IF EXISTS applications_status_check;
ALTER TABLE public.applications ADD CONSTRAINT applications_status_check
  CHECK (status IN ('scouted', 'queued', 'applying', 'submitted', 'failed', 'skipped', 'blocked', 'interview', 'rejected', 'offer', 'verified'));

-- Add columns that exist in local SQLite but not in Supabase
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS source text;
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS location text;
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS posted_at timestamptz;
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS scouted_at timestamptz;
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS updated_at timestamptz DEFAULT now();
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS notes text;
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS dedup_token text;

-- Dedup token should be unique per user (not globally — different users can apply to same job)
CREATE UNIQUE INDEX IF NOT EXISTS idx_applications_user_dedup
  ON public.applications(user_id, dedup_token)
  WHERE dedup_token IS NOT NULL;

-- Additional useful indexes
CREATE INDEX IF NOT EXISTS idx_applications_status ON public.applications(status);
CREATE INDEX IF NOT EXISTS idx_applications_company ON public.applications(company);

-- Add updated_at trigger
CREATE TRIGGER set_updated_at_applications
  BEFORE UPDATE ON public.applications
  FOR EACH ROW EXECUTE FUNCTION update_timestamp();
