-- 018_repair_application_email.sql
-- Repair migration 014's backfill blunder.
--
-- Migration 014 populated user_application_profiles.application_email with
-- COALESCE(user_profiles.email, users.email). But users.email is the
-- SIGNUP email, which for most users is DIFFERENT from the Gmail address
-- they want their applications sent FROM (that's the whole point of the
-- multi-profile refactor). Combined with worker.py overriding
-- os.environ["GMAIL_EMAIL"] per job, every existing user would have
-- started applying from the wrong address after the refactor shipped.
--
-- Fix: null out application_email on backfilled rows where the value
-- equals users.email. With application_email=NULL, the worker falls
-- through to whatever GMAIL_EMAIL is set in ~/.applyloop/.env (the value
-- install.sh wrote at setup time — the user's real apply address). The
-- UI picker lets users explicitly re-bind via the email-accounts pool.
--
-- Also: harden migration 014's ON CONFLICT DO NOTHING edge case. If any
-- user somehow has a slug='default' row with is_default=false AND no
-- other default row, promote it to is_default=true so the
-- uniq_default_profile_per_user invariant holds.

-- Step 1: clear bogus application_email on backfilled rows.
UPDATE public.user_application_profiles uap
SET application_email = NULL,
    updated_at = now()
FROM public.users u
WHERE uap.user_id = u.id
  AND uap.slug = 'default'
  AND uap.application_email = u.email
  AND uap.email_account_id IS NULL;

-- Step 2: for any user missing a default, promote their 'default'-slugged
-- row (or the oldest row) to default. Idempotent.
WITH missing AS (
  SELECT u.id AS user_id
  FROM public.users u
  WHERE NOT EXISTS (
    SELECT 1 FROM public.user_application_profiles p
    WHERE p.user_id = u.id AND p.is_default = true
  )
  AND EXISTS (
    SELECT 1 FROM public.user_application_profiles p
    WHERE p.user_id = u.id
  )
),
pick AS (
  SELECT DISTINCT ON (p.user_id) p.id, p.user_id
  FROM public.user_application_profiles p
  JOIN missing m ON m.user_id = p.user_id
  ORDER BY p.user_id,
           CASE WHEN p.slug = 'default' THEN 0 ELSE 1 END,
           p.created_at ASC
)
UPDATE public.user_application_profiles uap
SET is_default = true, updated_at = now()
FROM pick
WHERE uap.id = pick.id;
