-- AutoApply SaaS Database Schema
-- Migration 001: Initial schema

-- ============================================================================
-- TABLES
-- ============================================================================

-- 1. users — extends Supabase auth.users
CREATE TABLE public.users (
  id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  email text NOT NULL,
  tier text NOT NULL DEFAULT 'free' CHECK (tier IN ('free', 'starter', 'pro')),
  stripe_customer_id text,
  stripe_subscription_id text,
  subscription_status text DEFAULT 'none',
  subscription_current_period_end timestamptz,
  telegram_chat_id text,
  gmail_connected boolean DEFAULT false,
  onboarding_completed boolean DEFAULT false,
  daily_apply_limit integer NOT NULL DEFAULT 5,
  is_admin boolean DEFAULT false,
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

-- 2. user_profiles — all form-fill data
CREATE TABLE public.user_profiles (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE UNIQUE,
  first_name text,
  last_name text,
  phone text,
  linkedin_url text,
  github_url text,
  portfolio_url text,
  current_company text,
  current_title text,
  years_experience integer,
  education_level text,
  school_name text,
  degree text,
  graduation_year integer,
  work_authorization text,
  requires_sponsorship boolean DEFAULT true,
  gender text,
  race_ethnicity text,
  veteran_status text,
  disability_status text,
  cover_letter_template text,
  answer_key_json jsonb DEFAULT '{}',
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

-- 3. user_resumes — resume storage
CREATE TABLE public.user_resumes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  storage_path text NOT NULL,
  file_name text NOT NULL,
  is_default boolean DEFAULT false,
  target_keywords text[] DEFAULT '{}',
  created_at timestamptz DEFAULT now()
);

-- 4. user_job_preferences
CREATE TABLE public.user_job_preferences (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE UNIQUE,
  target_titles text[] DEFAULT '{}',
  target_keywords text[] DEFAULT '{}',
  excluded_titles text[] DEFAULT '{}',
  excluded_companies text[] DEFAULT '{}',
  min_salary integer,
  preferred_locations text[] DEFAULT '{"United States"}',
  remote_only boolean DEFAULT false,
  auto_apply boolean DEFAULT true,
  max_daily integer DEFAULT 25,
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

-- 5. discovered_jobs — shared job data from ATS API scans
CREATE TABLE public.discovered_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  external_id text NOT NULL,
  ats text NOT NULL CHECK (ats IN ('greenhouse', 'lever', 'ashby', 'workday')),
  title text NOT NULL,
  company text NOT NULL,
  location text,
  department text,
  apply_url text NOT NULL,
  description_snippet text,
  posted_at timestamptz,
  discovered_at timestamptz DEFAULT now(),
  board_token text,
  is_active boolean DEFAULT true,
  UNIQUE(external_id, ats)
);

-- 6. user_job_matches — per-user relevance
CREATE TABLE public.user_job_matches (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  job_id uuid NOT NULL REFERENCES public.discovered_jobs(id) ON DELETE CASCADE,
  match_score real,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'skipped', 'queued', 'applied')),
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now(),
  UNIQUE(user_id, job_id)
);

-- 7. application_queue — the PostgreSQL job queue
CREATE TABLE public.application_queue (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  job_id uuid NOT NULL REFERENCES public.discovered_jobs(id) ON DELETE CASCADE,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'locked', 'processing', 'submitted', 'failed', 'cancelled')),
  locked_by text,
  locked_at timestamptz,
  attempts integer DEFAULT 0,
  max_attempts integer DEFAULT 3,
  error text,
  priority integer DEFAULT 0,
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

-- 8. applications — permanent log
CREATE TABLE public.applications (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  job_id uuid NOT NULL REFERENCES public.discovered_jobs(id),
  queue_id uuid REFERENCES public.application_queue(id),
  company text NOT NULL,
  title text NOT NULL,
  ats text NOT NULL,
  apply_url text,
  status text NOT NULL DEFAULT 'submitted' CHECK (status IN ('submitted', 'failed', 'verified')),
  screenshot_url text,
  error text,
  applied_at timestamptz DEFAULT now(),
  metadata jsonb DEFAULT '{}'
);

-- 9. gmail_tokens — encrypted OAuth tokens
CREATE TABLE public.gmail_tokens (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE UNIQUE,
  access_token_encrypted text NOT NULL,
  refresh_token_encrypted text NOT NULL,
  token_expiry timestamptz,
  email text,
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

-- 10. invite_codes
CREATE TABLE public.invite_codes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code text NOT NULL UNIQUE,
  max_uses integer DEFAULT 1,
  used_count integer DEFAULT 0,
  created_by uuid REFERENCES public.users(id),
  expires_at timestamptz,
  is_active boolean DEFAULT true,
  created_at timestamptz DEFAULT now()
);

-- 11. knowledge_base — key-value store
CREATE TABLE public.knowledge_base (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  key text NOT NULL UNIQUE,
  value jsonb NOT NULL,
  updated_at timestamptz DEFAULT now()
);

-- 12. system_config
CREATE TABLE public.system_config (
  key text PRIMARY KEY,
  value jsonb NOT NULL,
  updated_at timestamptz DEFAULT now()
);

-- ============================================================================
-- FUNCTIONS
-- ============================================================================

-- update_timestamp() — trigger function for updated_at columns
CREATE OR REPLACE FUNCTION update_timestamp()
RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- claim_next_job() — atomically claims next pending job using FOR UPDATE SKIP LOCKED
CREATE OR REPLACE FUNCTION claim_next_job(p_worker_id text)
RETURNS SETOF application_queue AS $$
BEGIN
  RETURN QUERY
  UPDATE application_queue
  SET status = 'locked', locked_by = p_worker_id, locked_at = now(), updated_at = now()
  WHERE id = (
    SELECT id FROM application_queue
    WHERE status = 'pending'
    ORDER BY priority DESC, created_at ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED
  )
  RETURNING *;
END;
$$ LANGUAGE plpgsql;

-- recover_stale_locks() — resets jobs locked > 10 min ago
CREATE OR REPLACE FUNCTION recover_stale_locks()
RETURNS integer AS $$
DECLARE
  recovered integer;
BEGIN
  UPDATE application_queue
  SET status = 'pending', locked_by = NULL, locked_at = NULL, updated_at = now()
  WHERE status = 'locked' AND locked_at < now() - interval '10 minutes';
  GET DIAGNOSTICS recovered = ROW_COUNT;
  RETURN recovered;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- ROW LEVEL SECURITY
-- ============================================================================

-- Enable RLS on all user-facing tables
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_resumes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_job_preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.discovered_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_job_matches ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.application_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.applications ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.gmail_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.invite_codes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.knowledge_base ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.system_config ENABLE ROW LEVEL SECURITY;

-- users: own data only
CREATE POLICY users_select ON public.users FOR SELECT USING (auth.uid() = id);
CREATE POLICY users_update ON public.users FOR UPDATE USING (auth.uid() = id);
CREATE POLICY users_insert ON public.users FOR INSERT WITH CHECK (auth.uid() = id);

-- user_profiles: own data only
CREATE POLICY user_profiles_select ON public.user_profiles FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY user_profiles_insert ON public.user_profiles FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY user_profiles_update ON public.user_profiles FOR UPDATE USING (auth.uid() = user_id);
CREATE POLICY user_profiles_delete ON public.user_profiles FOR DELETE USING (auth.uid() = user_id);

-- user_resumes: own data only
CREATE POLICY user_resumes_select ON public.user_resumes FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY user_resumes_insert ON public.user_resumes FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY user_resumes_update ON public.user_resumes FOR UPDATE USING (auth.uid() = user_id);
CREATE POLICY user_resumes_delete ON public.user_resumes FOR DELETE USING (auth.uid() = user_id);

-- user_job_preferences: own data only
CREATE POLICY user_job_preferences_select ON public.user_job_preferences FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY user_job_preferences_insert ON public.user_job_preferences FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY user_job_preferences_update ON public.user_job_preferences FOR UPDATE USING (auth.uid() = user_id);
CREATE POLICY user_job_preferences_delete ON public.user_job_preferences FOR DELETE USING (auth.uid() = user_id);

-- discovered_jobs: public read
CREATE POLICY discovered_jobs_select ON public.discovered_jobs FOR SELECT USING (true);

-- user_job_matches: own data only
CREATE POLICY user_job_matches_select ON public.user_job_matches FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY user_job_matches_insert ON public.user_job_matches FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY user_job_matches_update ON public.user_job_matches FOR UPDATE USING (auth.uid() = user_id);

-- application_queue: own data only
CREATE POLICY application_queue_select ON public.application_queue FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY application_queue_insert ON public.application_queue FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY application_queue_update ON public.application_queue FOR UPDATE USING (auth.uid() = user_id);

-- applications: own data only
CREATE POLICY applications_select ON public.applications FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY applications_insert ON public.applications FOR INSERT WITH CHECK (auth.uid() = user_id);

-- gmail_tokens: own data only
CREATE POLICY gmail_tokens_select ON public.gmail_tokens FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY gmail_tokens_insert ON public.gmail_tokens FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY gmail_tokens_update ON public.gmail_tokens FOR UPDATE USING (auth.uid() = user_id);
CREATE POLICY gmail_tokens_delete ON public.gmail_tokens FOR DELETE USING (auth.uid() = user_id);

-- invite_codes: anyone can read active codes, only admins can create/update
CREATE POLICY invite_codes_select ON public.invite_codes FOR SELECT USING (is_active = true);
CREATE POLICY invite_codes_insert ON public.invite_codes FOR INSERT WITH CHECK (
  EXISTS (SELECT 1 FROM public.users WHERE id = auth.uid() AND is_admin = true)
);
CREATE POLICY invite_codes_update ON public.invite_codes FOR UPDATE USING (
  EXISTS (SELECT 1 FROM public.users WHERE id = auth.uid() AND is_admin = true)
);

-- knowledge_base: public read
CREATE POLICY knowledge_base_select ON public.knowledge_base FOR SELECT USING (true);

-- system_config: admin-only
CREATE POLICY system_config_select ON public.system_config FOR SELECT USING (
  EXISTS (SELECT 1 FROM public.users WHERE id = auth.uid() AND is_admin = true)
);
CREATE POLICY system_config_insert ON public.system_config FOR INSERT WITH CHECK (
  EXISTS (SELECT 1 FROM public.users WHERE id = auth.uid() AND is_admin = true)
);
CREATE POLICY system_config_update ON public.system_config FOR UPDATE USING (
  EXISTS (SELECT 1 FROM public.users WHERE id = auth.uid() AND is_admin = true)
);
CREATE POLICY system_config_delete ON public.system_config FOR DELETE USING (
  EXISTS (SELECT 1 FROM public.users WHERE id = auth.uid() AND is_admin = true)
);

-- ============================================================================
-- INDEXES
-- ============================================================================

CREATE INDEX idx_application_queue_status ON public.application_queue(status);
CREATE INDEX idx_application_queue_user_id ON public.application_queue(user_id);
CREATE INDEX idx_application_queue_created_at ON public.application_queue(created_at);

CREATE INDEX idx_discovered_jobs_ats ON public.discovered_jobs(ats);
CREATE INDEX idx_discovered_jobs_posted_at ON public.discovered_jobs(posted_at);
CREATE INDEX idx_discovered_jobs_external_id ON public.discovered_jobs(external_id);

CREATE INDEX idx_user_job_matches_user_id ON public.user_job_matches(user_id);
CREATE INDEX idx_user_job_matches_status ON public.user_job_matches(status);

CREATE INDEX idx_applications_user_id ON public.applications(user_id);
CREATE INDEX idx_applications_applied_at ON public.applications(applied_at);

CREATE INDEX idx_invite_codes_code ON public.invite_codes(code);

-- ============================================================================
-- TRIGGERS
-- ============================================================================

CREATE TRIGGER set_updated_at_users
  BEFORE UPDATE ON public.users
  FOR EACH ROW EXECUTE FUNCTION update_timestamp();

CREATE TRIGGER set_updated_at_user_profiles
  BEFORE UPDATE ON public.user_profiles
  FOR EACH ROW EXECUTE FUNCTION update_timestamp();

CREATE TRIGGER set_updated_at_user_job_preferences
  BEFORE UPDATE ON public.user_job_preferences
  FOR EACH ROW EXECUTE FUNCTION update_timestamp();

CREATE TRIGGER set_updated_at_user_job_matches
  BEFORE UPDATE ON public.user_job_matches
  FOR EACH ROW EXECUTE FUNCTION update_timestamp();

CREATE TRIGGER set_updated_at_application_queue
  BEFORE UPDATE ON public.application_queue
  FOR EACH ROW EXECUTE FUNCTION update_timestamp();

CREATE TRIGGER set_updated_at_gmail_tokens
  BEFORE UPDATE ON public.gmail_tokens
  FOR EACH ROW EXECUTE FUNCTION update_timestamp();

CREATE TRIGGER set_updated_at_system_config
  BEFORE UPDATE ON public.system_config
  FOR EACH ROW EXECUTE FUNCTION update_timestamp();
