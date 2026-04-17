-- 025_claim_ats_roundrobin.sql
--
-- Replace claim_next_job() with an ATS-diversity-aware variant.
--
-- The old ORDER BY priority DESC, created_at ASC was strict FIFO. When a
-- scout cycle enqueued 30 Greenhouse jobs before 2 Ashby jobs, Greenhouse
-- monopolised the apply loop for ~30 × APPLY_COOLDOWN minutes before the
-- worker ever touched an Ashby row. That's bad for platform diversity and
-- bad for PII/rate-limit blast radius (one ATS failing stuck the whole
-- queue behind it).
--
-- New behaviour: rank each pending queue row by how many applications
-- have already been submitted to its ATS in the last hour. Fewer recent
-- applies to that ATS → higher rank. Ties broken by priority DESC,
-- then created_at ASC (legacy).
--
-- Joins application_queue → discovered_jobs to read ATS (queue rows don't
-- carry ats directly). The applications.applied_at / submitted_at column
-- is used for the recency window; we use COALESCE on applied_at to handle
-- older rows.

CREATE OR REPLACE FUNCTION claim_next_job(p_worker_id text)
RETURNS SETOF application_queue AS $$
BEGIN
  RETURN QUERY
  UPDATE application_queue
  SET status = 'locked', locked_by = p_worker_id, locked_at = now(), updated_at = now()
  WHERE id = (
    SELECT q.id
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
    LIMIT 1
    FOR UPDATE SKIP LOCKED
  )
  RETURNING *;
END;
$$ LANGUAGE plpgsql;
