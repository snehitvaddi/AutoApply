-- 021_fix_users_rls_recursion.sql
-- Break the infinite recursion in public.users RLS.
--
-- Old policy:
--   users_select USING (auth.uid() = id OR EXISTS (
--     SELECT 1 FROM users WHERE id = auth.uid() AND is_admin = true
--   ))
-- The EXISTS sub-select hits public.users which re-triggers users_select,
-- which runs the EXISTS again, ad infinitum. Postgres detects the cycle
-- and aborts every SELECT users with "infinite recursion detected in
-- policy for relation users" — surfaced to the browser as a 500.
--
-- This was the root cause of:
--   - GET /rest/v1/users?select=is_admin → 500 in the browser
--   - app-shell crashing on every dashboard mount
--   - /api/profile/extract-resume returning 500 (it auths via worker
--     proxy which eventually reads users)
--   - cascading silent failures wherever any code path reads users
--
-- Fix: replace the EXISTS with a SECURITY DEFINER helper that reads
-- public.users with RLS bypassed. The helper is the only place that
-- touches the table without policy — every other path still goes
-- through RLS, and the cycle is broken because the helper executes
-- with definer rights and skips policy evaluation on its own SELECT.

CREATE OR REPLACE FUNCTION public.is_user_admin(p_user_id uuid)
RETURNS boolean
LANGUAGE sql
SECURITY DEFINER
SET search_path = public, pg_temp
STABLE
AS $$
  SELECT COALESCE((SELECT is_admin FROM public.users WHERE id = p_user_id), false);
$$;

REVOKE ALL ON FUNCTION public.is_user_admin(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.is_user_admin(uuid) TO authenticated, service_role, anon;

DROP POLICY IF EXISTS users_select ON public.users;
CREATE POLICY users_select ON public.users
  FOR SELECT
  USING (auth.uid() = id OR public.is_user_admin(auth.uid()));

DROP POLICY IF EXISTS users_update ON public.users;
CREATE POLICY users_update ON public.users
  FOR UPDATE
  USING (auth.uid() = id OR public.is_user_admin(auth.uid()));
