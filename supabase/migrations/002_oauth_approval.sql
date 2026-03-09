-- AutoApply SaaS Database Schema
-- Migration 002: Google OAuth + Admin Approval Flow
-- Replaces invite code + magic link auth with Google OAuth sign-in
-- and an admin approval gate for new users.

-- ============================================================================
-- ADD COLUMNS TO users TABLE
-- ============================================================================

-- approval_status: gates access until an admin approves the user
ALTER TABLE public.users
  ADD COLUMN approval_status text NOT NULL DEFAULT 'pending'
    CHECK (approval_status IN ('pending', 'approved', 'rejected'));

-- Auto-approve any existing admin users
UPDATE public.users SET approval_status = 'approved' WHERE is_admin = true;

-- Google OAuth profile fields
ALTER TABLE public.users ADD COLUMN full_name text;
ALTER TABLE public.users ADD COLUMN avatar_url text;

-- Signup timestamp (when the user first registered via OAuth)
ALTER TABLE public.users ADD COLUMN requested_at timestamptz DEFAULT now();

-- Approval audit trail
ALTER TABLE public.users ADD COLUMN approved_at timestamptz;
ALTER TABLE public.users ADD COLUMN approved_by uuid REFERENCES public.users(id);

-- ============================================================================
-- RLS POLICY UPDATES
-- ============================================================================

-- Drop existing users SELECT/UPDATE policies (too restrictive for admin)
DROP POLICY IF EXISTS users_select ON public.users;
DROP POLICY IF EXISTS users_update ON public.users;

-- users SELECT: own row always visible; admins can see all rows
CREATE POLICY users_select ON public.users FOR SELECT USING (
  auth.uid() = id
  OR EXISTS (SELECT 1 FROM public.users WHERE id = auth.uid() AND is_admin = true)
);

-- users UPDATE: own row always editable; admins can update any row
-- (admin needs this to change approval_status on other users)
CREATE POLICY users_update ON public.users FOR UPDATE USING (
  auth.uid() = id
  OR EXISTS (SELECT 1 FROM public.users WHERE id = auth.uid() AND is_admin = true)
);

-- ============================================================================
-- FUNCTIONS
-- ============================================================================

-- approve_user() — admin approves a pending user (with admin check)
CREATE OR REPLACE FUNCTION approve_user(p_user_id uuid, p_admin_id uuid)
RETURNS void AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM public.users WHERE id = p_admin_id AND is_admin = true) THEN
    RAISE EXCEPTION 'Only admins can approve users';
  END IF;
  UPDATE public.users
  SET approval_status = 'approved',
      approved_at = now(),
      approved_by = p_admin_id,
      updated_at = now()
  WHERE id = p_user_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- reject_user() — admin rejects a pending user (with admin check)
CREATE OR REPLACE FUNCTION reject_user(p_user_id uuid, p_admin_id uuid)
RETURNS void AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM public.users WHERE id = p_admin_id AND is_admin = true) THEN
    RAISE EXCEPTION 'Only admins can reject users';
  END IF;
  UPDATE public.users
  SET approval_status = 'rejected',
      approved_at = now(),
      approved_by = p_admin_id,
      updated_at = now()
  WHERE id = p_user_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ============================================================================
-- INDEXES
-- ============================================================================

CREATE INDEX idx_users_approval_status ON public.users(approval_status);

-- Composite index for claim_next_job performance
CREATE INDEX idx_application_queue_claim ON public.application_queue(status, priority DESC, created_at ASC);

-- Index for application counting by job_id
CREATE INDEX idx_applications_job_id ON public.applications(job_id);
