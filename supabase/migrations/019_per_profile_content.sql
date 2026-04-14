-- 019_per_profile_content.sql
-- Move role-specific content (answer_key_json, cover_letter_template) from
-- the shared user_profiles row to per-bundle user_application_profiles rows.
--
-- Why: "Why are you interested in this role?" answers and cover letter
-- templates are USELESS across roles. An AI Engineer "why interested" is
-- the wrong thing to send to a Data Analyst job. These have been shared
-- since the original schema — the multi-profile refactor exposed the gap.
--
-- Backward compat: the columns stay on user_profiles as a read-only
-- fallback so older worker builds and the legacy /api/settings/preferences
-- path still work. A follow-up migration can drop them after two weeks.

ALTER TABLE public.user_application_profiles
  ADD COLUMN IF NOT EXISTS answer_key_json jsonb,
  ADD COLUMN IF NOT EXISTS cover_letter_template text;

-- Backfill: copy shared content into every user's default bundle so
-- existing single-profile users don't lose their answers on the first
-- open of Settings after deploy. Idempotent via the NULL guard.
UPDATE public.user_application_profiles uap
SET answer_key_json = up.answer_key_json,
    cover_letter_template = up.cover_letter_template,
    updated_at = now()
FROM public.user_profiles up
WHERE uap.user_id = up.user_id
  AND uap.is_default = true
  AND uap.answer_key_json IS NULL
  AND up.answer_key_json IS NOT NULL;

UPDATE public.user_application_profiles uap
SET cover_letter_template = up.cover_letter_template,
    updated_at = now()
FROM public.user_profiles up
WHERE uap.user_id = up.user_id
  AND uap.is_default = true
  AND uap.cover_letter_template IS NULL
  AND up.cover_letter_template IS NOT NULL;

COMMENT ON COLUMN public.user_application_profiles.answer_key_json IS
  'Per-bundle answer key — overrides user_profiles.answer_key_json at apply time. Worker picks the bundle for a job via pick_profile_for_job() then reads this.';
COMMENT ON COLUMN public.user_application_profiles.cover_letter_template IS
  'Per-bundle cover letter template. Falls back to user_profiles.cover_letter_template when null.';
