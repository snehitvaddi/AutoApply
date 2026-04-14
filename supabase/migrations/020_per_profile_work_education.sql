-- 020_per_profile_work_education.sql
-- Move work_experience[], education[], skills[] from the shared
-- user_profiles row to per-bundle user_application_profiles rows.
--
-- Why: each application profile tells a different story. An AI Engineer
-- bundle emphasizes ML projects + pytorch/llm achievements; a Data
-- Analyst bundle emphasizes SQL pipelines + dashboard wins. Forcing
-- one shared history meant both bundles had to use the same resume
-- narrative, defeating the point of per-role tailoring.
--
-- Backward compat: user_profiles.work_experience / education / skills
-- stay in place as a read-only fallback so older worker builds during
-- rolling deploy still work.

-- Match the source column types on user_profiles exactly so the backfill
-- UPDATE doesn't need casts and worker code can treat both tables
-- identically. work_experience/education = jsonb, skills = text[].
ALTER TABLE public.user_application_profiles
  ADD COLUMN IF NOT EXISTS work_experience jsonb,
  ADD COLUMN IF NOT EXISTS education jsonb,
  ADD COLUMN IF NOT EXISTS skills text[];

-- Backfill each user's default bundle from user_profiles so existing
-- single-profile users see zero data loss when they open the new UI.
UPDATE public.user_application_profiles uap
SET work_experience = up.work_experience,
    updated_at = now()
FROM public.user_profiles up
WHERE uap.user_id = up.user_id
  AND uap.is_default = true
  AND uap.work_experience IS NULL
  AND up.work_experience IS NOT NULL;

UPDATE public.user_application_profiles uap
SET education = up.education,
    updated_at = now()
FROM public.user_profiles up
WHERE uap.user_id = up.user_id
  AND uap.is_default = true
  AND uap.education IS NULL
  AND up.education IS NOT NULL;

UPDATE public.user_application_profiles uap
SET skills = up.skills,
    updated_at = now()
FROM public.user_profiles up
WHERE uap.user_id = up.user_id
  AND uap.is_default = true
  AND uap.skills IS NULL
  AND up.skills IS NOT NULL;

COMMENT ON COLUMN public.user_application_profiles.work_experience IS
  'Per-bundle work history. Overrides user_profiles.work_experience at apply time so each role bundle can tell its own story.';
COMMENT ON COLUMN public.user_application_profiles.education IS
  'Per-bundle education. Overrides user_profiles.education at apply time.';
COMMENT ON COLUMN public.user_application_profiles.skills IS
  'Per-bundle skills list. Overrides user_profiles.skills at apply time.';
