-- 026_recover_stale_processing.sql
--
-- recover_stale_locks() previously only covered status='locked'. If a row
-- ever slips into 'processing' and the worker dies, that row is stuck
-- forever. Extend the recovery to both states. 10-minute threshold stays
-- the same — an apply that legit takes >10min is almost always a broken
-- browser session, not real work.

CREATE OR REPLACE FUNCTION recover_stale_locks()
RETURNS integer AS $$
DECLARE
  recovered integer;
BEGIN
  UPDATE application_queue
  SET status = 'pending', locked_by = NULL, locked_at = NULL, updated_at = now()
  WHERE status IN ('locked', 'processing')
    AND locked_at < now() - interval '10 minutes';
  GET DIAGNOSTICS recovered = ROW_COUNT;
  RETURN recovered;
END;
$$ LANGUAGE plpgsql;
