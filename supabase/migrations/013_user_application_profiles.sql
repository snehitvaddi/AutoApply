-- 013_user_application_profiles.sql
-- Multi-profile architecture: split role-targeting / resume / apply-email
-- out of user_job_preferences into 1..N named bundles per user.
--
-- Why: users need distinct "application profile bundles" (e.g. "AI Engineer"
-- with resume_ai.pdf + aieng@gmail.com, and "Data Analyst" with
-- resume_da.pdf + daeng@gmail.com). At apply time the worker picks the
-- matching bundle. Single-profile users keep one default bundle — identical
-- behavior to today.

CREATE TABLE IF NOT EXISTS public.user_application_profiles (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  name text NOT NULL,
  slug text NOT NULL,
  is_default boolean NOT NULL DEFAULT false,

  -- Role targeting
  target_titles text[] NOT NULL DEFAULT '{}',
  target_keywords text[] NOT NULL DEFAULT '{}',
  excluded_titles text[] NOT NULL DEFAULT '{}',
  excluded_companies text[] NOT NULL DEFAULT '{}',
  excluded_role_keywords text[] NOT NULL DEFAULT '{}',
  excluded_levels text[] NOT NULL DEFAULT '{}',

  -- Location + pay
  preferred_locations text[] NOT NULL DEFAULT ARRAY['United States']::text[],
  remote_only boolean NOT NULL DEFAULT false,
  min_salary integer,

  -- Board overrides
  ashby_boards text[],
  greenhouse_boards text[],

  -- Per-bundle identity
  resume_id uuid REFERENCES public.user_resumes(id) ON DELETE SET NULL,
  application_email text,
  application_email_app_password_enc text,

  -- Queue knobs
  auto_apply boolean NOT NULL DEFAULT true,
  max_daily integer,

  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),

  UNIQUE (user_id, slug)
);

-- Exactly one default profile per user
CREATE UNIQUE INDEX IF NOT EXISTS uniq_default_profile_per_user
  ON public.user_application_profiles(user_id)
  WHERE is_default;

CREATE INDEX IF NOT EXISTS idx_uap_user_id
  ON public.user_application_profiles(user_id);

-- updated_at trigger
CREATE OR REPLACE FUNCTION public.touch_user_application_profiles_updated_at()
RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_uap_updated_at ON public.user_application_profiles;
CREATE TRIGGER trg_uap_updated_at
  BEFORE UPDATE ON public.user_application_profiles
  FOR EACH ROW EXECUTE FUNCTION public.touch_user_application_profiles_updated_at();

-- RLS: users can only see/manage their own bundles
ALTER TABLE public.user_application_profiles ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS uap_select_own ON public.user_application_profiles;
CREATE POLICY uap_select_own ON public.user_application_profiles
  FOR SELECT USING (auth.uid() = user_id);

DROP POLICY IF EXISTS uap_insert_own ON public.user_application_profiles;
CREATE POLICY uap_insert_own ON public.user_application_profiles
  FOR INSERT WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS uap_update_own ON public.user_application_profiles;
CREATE POLICY uap_update_own ON public.user_application_profiles
  FOR UPDATE USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

-- Deleting the default profile is forbidden — enforced at API layer AND here
DROP POLICY IF EXISTS uap_delete_own_nondefault ON public.user_application_profiles;
CREATE POLICY uap_delete_own_nondefault ON public.user_application_profiles
  FOR DELETE USING (auth.uid() = user_id AND is_default = false);

COMMENT ON TABLE public.user_application_profiles IS
  'Named application bundles per user. Each bundle binds its own target roles, resume, apply-from email, and Gmail app password. Worker picks the matching bundle at apply time based on job title.';

COMMENT ON COLUMN public.user_application_profiles.application_email_app_password_enc IS
  'AES-256-CBC encrypted Gmail app password. Worker decrypts in memory only; never exposed to the UI.';
