-- 014_backfill_default_profile.sql
-- For every existing user, create exactly one default application profile
-- row populated from their current user_job_preferences + default user_resumes
-- row + user_profiles.email. Idempotent: ON CONFLICT DO NOTHING.
--
-- Why: migration 013 added user_application_profiles but left it empty.
-- Worker code that reads profiles[] would see zero bundles and refuse to
-- boot. Backfill guarantees every current user has a working default
-- before any worker code switches to the new path.

INSERT INTO public.user_application_profiles (
  user_id,
  name,
  slug,
  is_default,
  target_titles,
  target_keywords,
  excluded_titles,
  excluded_companies,
  excluded_role_keywords,
  excluded_levels,
  preferred_locations,
  remote_only,
  min_salary,
  ashby_boards,
  greenhouse_boards,
  resume_id,
  application_email,
  auto_apply,
  max_daily
)
SELECT
  u.id AS user_id,
  'Default' AS name,
  'default' AS slug,
  true AS is_default,
  COALESCE(p.target_titles, '{}'),
  COALESCE(p.target_keywords, '{}'),
  COALESCE(p.excluded_titles, '{}'),
  COALESCE(p.excluded_companies, '{}'),
  COALESCE(p.excluded_role_keywords, '{}'),
  COALESCE(p.excluded_levels, '{}'),
  COALESCE(p.preferred_locations, ARRAY['United States']::text[]),
  COALESCE(p.remote_only, false),
  p.min_salary,
  p.ashby_boards,
  p.greenhouse_boards,
  (
    SELECT r.id FROM public.user_resumes r
    WHERE r.user_id = u.id
    ORDER BY r.is_default DESC NULLS LAST, r.created_at DESC
    LIMIT 1
  ) AS resume_id,
  COALESCE(up.email, u.email) AS application_email,
  COALESCE(p.auto_apply, true),
  p.max_daily
FROM public.users u
LEFT JOIN public.user_job_preferences p ON p.user_id = u.id
LEFT JOIN public.user_profiles up ON up.user_id = u.id
ON CONFLICT (user_id, slug) DO NOTHING;
