-- Migration 009: Activation codes + payments placeholder
-- Part of Phase 1 — Activation Code Flow (see plans/shimmying-swimming-dongarra.md)
--
-- `activation_codes` replaces the manual "admin copies worker token + user pastes in terminal"
-- flow. Admin generates a short, human-friendly code like AL-X4B9-T2Q7. User enters it
-- directly into the ApplyLoop desktop app's first-run setup wizard. The /api/activate
-- endpoint validates the code, generates a fresh worker token, and returns it with the
-- user's profile so the desktop can hydrate itself.
--
-- `payments` is a Stripe placeholder — empty schema ready for Phase 5 Stripe integration.

-- ============================================================================
-- activation_codes
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.activation_codes (
  code text PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  created_by uuid REFERENCES public.users(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  uses_remaining integer NOT NULL DEFAULT 5 CHECK (uses_remaining >= 0),
  last_used_at timestamptz,
  notes text
);

CREATE INDEX IF NOT EXISTS idx_activation_codes_user ON public.activation_codes(user_id);
CREATE INDEX IF NOT EXISTS idx_activation_codes_expires ON public.activation_codes(expires_at);

-- Lock down public access entirely. Only the service-role key (used server-side by
-- /api/admin/activation-code and /api/activate) can read/write this table.
ALTER TABLE public.activation_codes ENABLE ROW LEVEL SECURITY;

-- ============================================================================
-- payments (Stripe placeholder — Phase 5)
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.payments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  amount_cents integer,
  currency text DEFAULT 'usd',
  provider text DEFAULT 'stripe',
  provider_payment_id text,
  provider_customer_id text,
  status text DEFAULT 'pending' CHECK (status IN ('pending', 'succeeded', 'failed', 'refunded', 'canceled')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  metadata jsonb DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_payments_user ON public.payments(user_id);
CREATE INDEX IF NOT EXISTS idx_payments_status ON public.payments(status);
CREATE INDEX IF NOT EXISTS idx_payments_provider_id ON public.payments(provider_payment_id);

ALTER TABLE public.payments ENABLE ROW LEVEL SECURITY;

-- Users can see their own payment history
CREATE POLICY payments_select_own ON public.payments
  FOR SELECT USING (auth.uid() = user_id);

CREATE TRIGGER set_updated_at_payments
  BEFORE UPDATE ON public.payments
  FOR EACH ROW EXECUTE FUNCTION update_timestamp();
