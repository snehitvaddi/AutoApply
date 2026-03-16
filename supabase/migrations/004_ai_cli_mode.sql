-- Migration 004: Add AI CLI mode for setup script
-- Admin sets this per user to control whether they get a shared API key or use their own account

ALTER TABLE public.users
  ADD COLUMN ai_cli_mode text NOT NULL DEFAULT 'own_account'
    CHECK (ai_cli_mode IN ('provided_key', 'own_account'));

COMMENT ON COLUMN public.users.ai_cli_mode IS
  'provided_key = admin shares API key (charged to admin), own_account = user logs in with their own OpenAI account';
