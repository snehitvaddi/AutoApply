-- 027_fix_claim_aggregate.sql
--
-- Hotfix for migration 025: Postgres rejects FOR UPDATE on a query that
-- contains an aggregate (LATERAL COUNT(*) triggers this), so every
-- claim_next_job() call has been throwing `0A000: FOR UPDATE is not
-- allowed with aggregate functions`. The worker proxy swallowed the
-- error as a null result, which looked indistinguishable from "queue
-- empty" — so clients with 24 pending rows stalled at queue=24,
-- applied=0 forever. See 2026-04-18 incident.
--
-- Rewrite as two steps inside PL/pgSQL:
--   1. Pick the target row by ATS-diversity rank (no locking — aggregates OK)
--   2. UPDATE ... WHERE id = target AND status='pending' (re-check guards
--      against race with another worker; empty RETURN on race is fine, the
--      planner will tick again in ~60s)
--
-- Still atomic against concurrent claims: the UPDATE's WHERE status='pending'
-- only succeeds on one worker; losers see 0 rows affected, RETURN QUERY
-- yields empty, worker retries next planner tick.

CREATE OR REPLACE FUNCTION claim_next_job(p_worker_id text)
RETURNS SETOF application_queue AS $$
DECLARE
  v_target_id uuid;
BEGIN
  SELECT q.id INTO v_target_id
  FROM application_queue q
  LEFT JOIN discovered_jobs dj ON dj.id = q.job_id
  LEFT JOIN LATERAL (
    SELECT COUNT(*)::int AS n
    FROM applications a
    WHERE a.user_id = q.user_id
      AND a.ats = dj.ats
      AND a.applied_at > now() - interval '1 hour'
  ) recent ON true
  WHERE q.status = 'pending'
  ORDER BY recent.n ASC NULLS FIRST, q.priority DESC, q.created_at ASC
  LIMIT 1;

  IF v_target_id IS NULL THEN
    RETURN;
  END IF;

  RETURN QUERY
  UPDATE application_queue
  SET status = 'locked', locked_by = p_worker_id, locked_at = now(), updated_at = now()
  WHERE id = v_target_id
    AND status = 'pending'
  RETURNING *;
END;
$$ LANGUAGE plpgsql;
