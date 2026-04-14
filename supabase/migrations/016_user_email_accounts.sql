-- 016_user_email_accounts.sql
-- Shared pool of {email, app_password} pairs per user. Profiles reference
-- an entry by id so that rotating the app password in one place updates
-- every bundle that uses that email.
--
-- Why: without this, an app password is stored inline on every profile
-- that uses the same email. Rotating means editing N rows and risking
-- drift.

CREATE TABLE IF NOT EXISTS public.user_email_accounts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  email text NOT NULL,
  app_password_enc text,
  label text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, email)
);

CREATE INDEX IF NOT EXISTS idx_uea_user ON public.user_email_accounts(user_id);

-- Bundles may optionally reference a pooled email account. When set,
-- application_email + application_email_app_password_enc on the profile
-- are ignored in favor of the pool row.
ALTER TABLE public.user_application_profiles
  ADD COLUMN IF NOT EXISTS email_account_id uuid
    REFERENCES public.user_email_accounts(id) ON DELETE SET NULL;

CREATE OR REPLACE FUNCTION public.touch_user_email_accounts_updated_at()
RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_uea_updated_at ON public.user_email_accounts;
CREATE TRIGGER trg_uea_updated_at
  BEFORE UPDATE ON public.user_email_accounts
  FOR EACH ROW EXECUTE FUNCTION public.touch_user_email_accounts_updated_at();

ALTER TABLE public.user_email_accounts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS uea_select_own ON public.user_email_accounts;
CREATE POLICY uea_select_own ON public.user_email_accounts
  FOR SELECT USING (auth.uid() = user_id);

DROP POLICY IF EXISTS uea_insert_own ON public.user_email_accounts;
CREATE POLICY uea_insert_own ON public.user_email_accounts
  FOR INSERT WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS uea_update_own ON public.user_email_accounts;
CREATE POLICY uea_update_own ON public.user_email_accounts
  FOR UPDATE USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS uea_delete_own ON public.user_email_accounts;
CREATE POLICY uea_delete_own ON public.user_email_accounts
  FOR DELETE USING (auth.uid() = user_id);

COMMENT ON TABLE public.user_email_accounts IS
  'Shared pool of Gmail {email, app_password} pairs per user. Profiles reference by email_account_id so rotating a password updates all bundles that share the email.';
