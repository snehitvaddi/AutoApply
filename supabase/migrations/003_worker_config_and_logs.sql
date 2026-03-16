-- ============================================================================
-- Migration 003: Worker Config Sync & Worker Logs
-- Adds per-user worker configuration (LLM, features) and worker event logging
-- ============================================================================

-- ── Worker Config (per-user, synced between UI and worker) ────────────────

CREATE TABLE IF NOT EXISTS public.worker_config (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,

    -- LLM Level 1: User-Facing
    llm_provider TEXT DEFAULT 'none',
    llm_model TEXT DEFAULT '',
    llm_api_key TEXT DEFAULT '',

    -- LLM Level 2: Backend Automation
    llm_backend_provider TEXT DEFAULT 'none',
    llm_backend_model TEXT DEFAULT '',
    llm_backend_api_key TEXT DEFAULT '',

    -- Ollama (if local)
    ollama_base_url TEXT DEFAULT 'http://localhost:11434',

    -- LLM Features
    resume_tailoring BOOLEAN DEFAULT false,
    cover_letters BOOLEAN DEFAULT false,
    smart_answers BOOLEAN DEFAULT false,
    monthly_limit INTEGER DEFAULT 50,
    monthly_spent NUMERIC(10,2) DEFAULT 0,
    monthly_reset_date DATE DEFAULT CURRENT_DATE,

    -- Worker Settings
    worker_id TEXT DEFAULT 'worker-1',
    poll_interval INTEGER DEFAULT 10,
    apply_cooldown INTEGER DEFAULT 30,
    auto_apply BOOLEAN DEFAULT true,
    max_daily_apps INTEGER DEFAULT 20,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),

    UNIQUE(user_id)
);

-- Trigger for updated_at
CREATE TRIGGER set_worker_config_updated_at
    BEFORE UPDATE ON public.worker_config
    FOR EACH ROW EXECUTE FUNCTION update_modified_column();

-- RLS
ALTER TABLE public.worker_config ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can read own worker config"
    ON public.worker_config FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can update own worker config"
    ON public.worker_config FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own worker config"
    ON public.worker_config FOR INSERT
    WITH CHECK (auth.uid() = user_id);

-- Service role bypass for worker reads
CREATE POLICY "Service role full access to worker_config"
    ON public.worker_config FOR ALL
    USING (auth.role() = 'service_role');

-- ── Worker Logs (error/event tracking visible to admin) ───────────────────

CREATE TABLE IF NOT EXISTS public.worker_logs (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID REFERENCES public.users(id) ON DELETE SET NULL,
    worker_id TEXT NOT NULL,

    -- Event info
    level TEXT NOT NULL DEFAULT 'info',  -- info, warn, error, critical
    category TEXT NOT NULL DEFAULT 'general',  -- startup, apply, health, update, config, crash
    message TEXT NOT NULL,
    details JSONB,  -- extra structured data (stack traces, job info, etc.)

    -- Context
    job_id UUID REFERENCES public.discovered_jobs(id) ON DELETE SET NULL,
    queue_id UUID,
    ats TEXT,
    company TEXT,

    -- Resolution
    resolved BOOLEAN DEFAULT false,
    resolved_at TIMESTAMPTZ,
    resolved_by UUID REFERENCES public.users(id) ON DELETE SET NULL,
    resolution_note TEXT,

    created_at TIMESTAMPTZ DEFAULT now()
);

-- Index for admin queries
CREATE INDEX idx_worker_logs_level ON public.worker_logs(level, created_at DESC);
CREATE INDEX idx_worker_logs_user ON public.worker_logs(user_id, created_at DESC);
CREATE INDEX idx_worker_logs_unresolved ON public.worker_logs(resolved, level, created_at DESC)
    WHERE resolved = false;

-- RLS
ALTER TABLE public.worker_logs ENABLE ROW LEVEL SECURITY;

-- Users can see their own logs
CREATE POLICY "Users can read own worker logs"
    ON public.worker_logs FOR SELECT
    USING (auth.uid() = user_id);

-- Service role can do everything (worker writes, admin reads)
CREATE POLICY "Service role full access to worker_logs"
    ON public.worker_logs FOR ALL
    USING (auth.role() = 'service_role');

-- ── Admin policies for worker tables ──────────────────────────────────────

-- Admins can see all worker configs
CREATE POLICY "Admins can read all worker configs"
    ON public.worker_config FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.users
            WHERE id = auth.uid() AND is_admin = true
        )
    );

-- Admins can see and resolve all worker logs
CREATE POLICY "Admins can read all worker logs"
    ON public.worker_logs FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.users
            WHERE id = auth.uid() AND is_admin = true
        )
    );

CREATE POLICY "Admins can update worker logs"
    ON public.worker_logs FOR UPDATE
    USING (
        EXISTS (
            SELECT 1 FROM public.users
            WHERE id = auth.uid() AND is_admin = true
        )
    );

-- ── Helper: Create default worker_config on user creation ─────────────────

CREATE OR REPLACE FUNCTION create_default_worker_config()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.worker_config (user_id)
    VALUES (NEW.id)
    ON CONFLICT (user_id) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE TRIGGER on_user_created_add_worker_config
    AFTER INSERT ON public.users
    FOR EACH ROW EXECUTE FUNCTION create_default_worker_config();
