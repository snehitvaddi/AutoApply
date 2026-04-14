-- 017_set_default_application_profile_rpc.sql
-- Atomic "make this bundle the default" operation. Prevents the race
-- window in the two-step fallback (clear all → set one) where two
-- concurrent calls could leave the user with zero defaults, or where an
-- in-flight POST /api/settings/profiles force-default on the first
-- bundle could collide on the partial unique index.
--
-- Single CASE UPDATE is safe because uniq_default_profile_per_user is
-- non-deferrable: Postgres checks uniqueness at STATEMENT end, not
-- row-by-row, so the transient state during the UPDATE doesn't violate.
--
-- SECURITY: SECURITY DEFINER + service_role-only execute. Called from
-- Next.js API routes that have already authenticated the user via
-- X-Worker-Token or session cookie. We do NOT use auth.uid() here because
-- service_role bypasses Supabase Auth. Instead we verify p_profile_id
-- actually belongs to p_user_id inside the function — belt-and-suspenders
-- against a future caller passing a wrong user id.

CREATE OR REPLACE FUNCTION public.set_default_application_profile(
  p_user_id uuid,
  p_profile_id uuid
) RETURNS void AS $$
DECLARE
  v_owner uuid;
BEGIN
  -- Ownership guard: refuse if the profile doesn't belong to p_user_id.
  -- Returns NULL if the profile doesn't exist at all → NOT FOUND.
  SELECT user_id INTO v_owner
    FROM public.user_application_profiles
    WHERE id = p_profile_id;

  IF v_owner IS NULL THEN
    RAISE EXCEPTION 'profile_not_found' USING ERRCODE = 'P0002';
  END IF;

  IF v_owner IS DISTINCT FROM p_user_id THEN
    RAISE EXCEPTION 'profile_not_owned' USING ERRCODE = '42501';
  END IF;

  UPDATE public.user_application_profiles
  SET is_default = (id = p_profile_id),
      updated_at = now()
  WHERE user_id = p_user_id
    AND (is_default = true OR id = p_profile_id);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

REVOKE ALL ON FUNCTION public.set_default_application_profile(uuid, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.set_default_application_profile(uuid, uuid) TO service_role;
