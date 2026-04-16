-- 022_unseed_max_daily.sql
--
-- The column `user_job_preferences.max_daily` has had `DEFAULT 25` since
-- migration 001. Together with:
--   - packages/web/src/app/api/onboarding/preferences/route.ts's
--     `max_daily ?? 50` hardcoded fallback (now fixed to ?? null)
--   - migration 014_backfill_default_profile.sql copying
--     user_job_preferences.max_daily into user_application_profiles.max_daily
-- every user signed up before today inherited a silent 25-or-50 daily
-- apply cap without ever seeing a UI that exposed the setting, and every
-- migration 014 backfill seeded the per-bundle `max_daily` column the
-- same way.
--
-- `null` is the correct semantic for "no cap" — the ProfilesTab UI
-- already handles it (empty input → placeholder "no cap" → stored null
-- → worker enforces nothing). Drop the column default so fresh rows
-- going forward default to null. Existing rows keep their 25 (we don't
-- touch data — users may have intentionally set 25) but new signups
-- get null, and any user clearing the ProfilesTab input gets null too.
--
-- Note: `user_application_profiles.max_daily` is already nullable with
-- no default (migration 013). Nothing to change there.

ALTER TABLE public.user_job_preferences ALTER COLUMN max_daily DROP DEFAULT;

COMMENT ON COLUMN public.user_job_preferences.max_daily IS
  'Legacy per-tenant daily-apply cap. NULL = no cap. Superseded by '
  'user_application_profiles.max_daily in multi-profile setups. Kept '
  'nullable with no default since 022 — onboarding no longer seeds a '
  'hardcoded value, and existing bundles reuse whatever the user set '
  'explicitly in the ProfilesTab UI.';
