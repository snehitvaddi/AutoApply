-- 012_user_profile_email.sql
-- Add an application-email column to user_profiles. Distinct from
-- users.email (signup email, immutable via Supabase Auth).
--
-- Why two emails: a user may sign up with one address (personal@gmail.com)
-- but want a different address on job applications (professional@gmail.com
-- where they have the Gmail app password + their resume inbox configured).
-- Previously the desktop Settings → Personal → Email field had nowhere to
-- persist, so every Refresh overwrote the local change with the signup
-- email from users.email.

ALTER TABLE user_profiles
  ADD COLUMN IF NOT EXISTS email TEXT;

COMMENT ON COLUMN user_profiles.email IS
  'Application email shown on job forms. Distinct from users.email (signup). Prefer gmail_email from integrations_encrypted when present — that field is the authoritative email for verification codes.';
