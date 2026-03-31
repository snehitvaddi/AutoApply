-- Migration 007: Worker tokens for per-user worker authentication
-- Allows workers to authenticate via token instead of Supabase auth

DO $$ BEGIN

CREATE TABLE IF NOT EXISTS public.worker_tokens (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE UNIQUE,
  token_hash text NOT NULL,
  created_at timestamptz DEFAULT now(),
  revoked_at timestamptz
);

CREATE INDEX IF NOT EXISTS idx_worker_tokens_hash ON public.worker_tokens(token_hash);
CREATE INDEX IF NOT EXISTS idx_worker_tokens_user_id ON public.worker_tokens(user_id);

END $$;

-- Enable RLS
ALTER TABLE public.worker_tokens ENABLE ROW LEVEL SECURITY;

-- Admin can read all worker tokens
CREATE POLICY IF NOT EXISTS worker_tokens_admin_select ON public.worker_tokens
  FOR SELECT USING (
    EXISTS (SELECT 1 FROM public.users WHERE id = auth.uid() AND is_admin = true)
  );

-- Admin can insert worker tokens
CREATE POLICY IF NOT EXISTS worker_tokens_admin_insert ON public.worker_tokens
  FOR INSERT WITH CHECK (
    EXISTS (SELECT 1 FROM public.users WHERE id = auth.uid() AND is_admin = true)
  );

-- Admin can update worker tokens (for revocation)
CREATE POLICY IF NOT EXISTS worker_tokens_admin_update ON public.worker_tokens
  FOR UPDATE USING (
    EXISTS (SELECT 1 FROM public.users WHERE id = auth.uid() AND is_admin = true)
  );
