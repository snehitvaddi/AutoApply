-- 011_tenant_config_columns.sql
-- Per-tenant scout/filter overrides so the worker pipeline never falls back
-- to admin defaults. NULL board arrays mean "use global default boards";
-- empty array means "use none"; populated array means "use these".
-- excluded_role_keywords + excluded_levels replace the deleted
-- SKIP_ROLE_KEYWORDS / SKIP_LEVELS admin-opinion constants in worker/config.py.

ALTER TABLE user_job_preferences
  ADD COLUMN IF NOT EXISTS excluded_role_keywords TEXT[] DEFAULT '{}'::TEXT[],
  ADD COLUMN IF NOT EXISTS excluded_levels        TEXT[] DEFAULT '{}'::TEXT[],
  ADD COLUMN IF NOT EXISTS ashby_boards           TEXT[] DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS greenhouse_boards      TEXT[] DEFAULT NULL;

COMMENT ON COLUMN user_job_preferences.excluded_role_keywords IS
  'Per-tenant role keyword blocklist. Jobs whose title contains any of these are filtered out before enqueue. Replaces the admin-opinion SKIP_ROLE_KEYWORDS constant.';

COMMENT ON COLUMN user_job_preferences.excluded_levels IS
  'Per-tenant seniority blocklist (e.g. ["intern", "director"]). Replaces the admin-opinion SKIP_LEVELS constant.';

COMMENT ON COLUMN user_job_preferences.ashby_boards IS
  'Optional per-tenant Ashby board slug override. NULL = use DEFAULT_ASHBY_BOARDS; empty = none.';

COMMENT ON COLUMN user_job_preferences.greenhouse_boards IS
  'Optional per-tenant Greenhouse board slug override. NULL = use DEFAULT_GREENHOUSE_BOARDS; empty = none.';
