-- 028_screenshots_bucket.sql
--
-- Create the private 'screenshots' bucket used by upload_screenshot
-- (commit D of the local-first migration). Idempotent — safe to re-run.
--
-- Access pattern: worker proxy uploads with service-role key, returns
-- a time-limited signed URL (7-day expiry). Bucket stays private so
-- nobody can enumerate other users' screenshots.

INSERT INTO storage.buckets (id, name, public)
VALUES ('screenshots', 'screenshots', false)
ON CONFLICT (id) DO NOTHING;
