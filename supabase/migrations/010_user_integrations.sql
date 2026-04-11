-- Migration 010: integrations_encrypted column on user_profiles
--
-- Stores per-user third-party integration credentials (Telegram bot token,
-- Gmail app password, AgentMail API key, Finetune Resume API key, etc.)
-- as a JSONB blob where each value is AES-256-CBC encrypted via
-- ENCRYPTION_KEY (the same scheme used by api/settings/gmail/callback).
--
-- Shape: { "telegram_bot_token": "salt:iv:ciphertext", "gmail_app_password": "...", ... }
--
-- Why a JSONB column instead of a sibling user_integrations table:
--   1. We already upsert user_profiles on every sync — one row per user
--      — and adding a second table means another join + another RLS policy.
--   2. Row-level access control is identical: whoever can read user_profiles
--      can read this blob. The ENCRYPTION_KEY-wrapped values are the actual
--      security layer.
--   3. Keeps the client-side serializer simple: one GET /api/settings/
--      cli-config call returns profile + preferences + integrations_encrypted.
--
-- Why not reuse answer_key_json:
--   worker.py's build_answer_key in packages/worker/knowledge.py does a
--   _deep_merge(answer_key, user_overrides) where user_overrides is the
--   full answer_key_json from the profile. A future applier that iterates
--   top-level keys (today's appliers use nested .get("text_fields") paths,
--   but there's no guarantee) would then see _integrations leak into ATS
--   form submissions. Dedicated column = strict semantic boundary.

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'user_profiles'
      AND column_name = 'integrations_encrypted'
  ) THEN
    ALTER TABLE public.user_profiles
      ADD COLUMN integrations_encrypted JSONB NOT NULL DEFAULT '{}'::jsonb;
  END IF;
END $$;

COMMENT ON COLUMN public.user_profiles.integrations_encrypted IS
  'AES-256-CBC encrypted third-party integration credentials. '
  'Keys: telegram_bot_token, telegram_chat_id, gmail_email, '
  'gmail_app_password, agentmail_api_key, finetune_resume_api_key. '
  'Encrypt/decrypt with ENCRYPTION_KEY env var; see packages/web/src/lib/crypto.ts.';
