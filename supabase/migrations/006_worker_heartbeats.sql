-- ============================================================================
-- Migration 006: Worker Heartbeats
-- Per-user heartbeat tracking so the admin dashboard can show worker liveness
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'worker_heartbeats'
    ) THEN
        CREATE TABLE public.worker_heartbeats (
            user_id UUID REFERENCES public.users(id) ON DELETE CASCADE,
            last_action TEXT NOT NULL DEFAULT '',
            details TEXT DEFAULT '',
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id)
        );

        -- RLS
        ALTER TABLE public.worker_heartbeats ENABLE ROW LEVEL SECURITY;

        -- Admin can read all heartbeats
        CREATE POLICY "admin_read_all_heartbeats"
            ON public.worker_heartbeats FOR SELECT
            USING (
                EXISTS (
                    SELECT 1 FROM public.users u
                    WHERE u.id = auth.uid() AND u.role = 'admin'
                )
            );

        -- Users can read their own heartbeat
        CREATE POLICY "user_read_own_heartbeat"
            ON public.worker_heartbeats FOR SELECT
            USING (auth.uid() = user_id);

        -- Service role can upsert (worker uses service key)
        -- No explicit policy needed — service role bypasses RLS
    END IF;
END
$$;
