-- 015_profiles_downstream_fk.sql
-- Add nullable application_profile_id FK to downstream tables so every
-- application / queue row / match row can be attributed to the profile
-- bundle that produced it. NULL means "default profile" (backward compat
-- for rows created before multi-profile rollout).

ALTER TABLE public.applications
  ADD COLUMN IF NOT EXISTS application_profile_id uuid
    REFERENCES public.user_application_profiles(id) ON DELETE SET NULL;

ALTER TABLE public.application_queue
  ADD COLUMN IF NOT EXISTS application_profile_id uuid
    REFERENCES public.user_application_profiles(id) ON DELETE SET NULL;

ALTER TABLE public.user_job_matches
  ADD COLUMN IF NOT EXISTS application_profile_id uuid
    REFERENCES public.user_application_profiles(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_applications_profile
  ON public.applications(application_profile_id)
  WHERE application_profile_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_queue_profile
  ON public.application_queue(application_profile_id)
  WHERE application_profile_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_matches_profile
  ON public.user_job_matches(application_profile_id)
  WHERE application_profile_id IS NOT NULL;
