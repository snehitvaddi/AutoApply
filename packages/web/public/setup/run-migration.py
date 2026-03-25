#!/usr/bin/env python3
"""
ApplyLoop - Database Migration Runner
Connects to Supabase PostgreSQL and runs migration SQL.
Called by setup-mac.sh and setup-windows.ps1 after .env is configured.
"""

import os
import sys
import re

# Fix Windows encoding issues (cp1252 can't handle Unicode)
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

def get_env_value(env_file, key):
    """Read a value from a .env file."""
    try:
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line.startswith(f"{key}="):
                    return line.split("=", 1)[1].strip()
    except FileNotFoundError:
        pass
    return os.environ.get(key, "")


def extract_project_ref(supabase_url):
    """Extract project ref from Supabase URL like https://abcdef.supabase.co"""
    match = re.search(r"https?://([^.]+)\.supabase\.co", supabase_url)
    return match.group(1) if match else None


MIGRATION_SQL = """
-- Migration 003: Worker Config Sync & Worker Logs (idempotent)

-- Ensure updated_at trigger function exists
CREATE OR REPLACE FUNCTION update_modified_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Worker Config table
CREATE TABLE IF NOT EXISTS public.worker_config (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    llm_provider TEXT DEFAULT 'none',
    llm_model TEXT DEFAULT '',
    llm_api_key TEXT DEFAULT '',
    llm_backend_provider TEXT DEFAULT 'none',
    llm_backend_model TEXT DEFAULT '',
    llm_backend_api_key TEXT DEFAULT '',
    ollama_base_url TEXT DEFAULT 'http://localhost:11434',
    resume_tailoring BOOLEAN DEFAULT false,
    cover_letters BOOLEAN DEFAULT false,
    smart_answers BOOLEAN DEFAULT false,
    monthly_limit INTEGER DEFAULT 50,
    monthly_spent NUMERIC(10,2) DEFAULT 0,
    monthly_reset_date DATE DEFAULT CURRENT_DATE,
    worker_id TEXT DEFAULT 'worker-1',
    poll_interval INTEGER DEFAULT 10,
    apply_cooldown INTEGER DEFAULT 30,
    auto_apply BOOLEAN DEFAULT true,
    max_daily_apps INTEGER DEFAULT 20,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id)
);

-- Worker Logs table
CREATE TABLE IF NOT EXISTS public.worker_logs (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID REFERENCES public.users(id) ON DELETE SET NULL,
    worker_id TEXT NOT NULL,
    level TEXT NOT NULL DEFAULT 'info',
    category TEXT NOT NULL DEFAULT 'general',
    message TEXT NOT NULL,
    details JSONB,
    job_id UUID,
    queue_id UUID,
    ats TEXT,
    company TEXT,
    resolved BOOLEAN DEFAULT false,
    resolved_at TIMESTAMPTZ,
    resolved_by UUID REFERENCES public.users(id) ON DELETE SET NULL,
    resolution_note TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Indexes (IF NOT EXISTS not supported for indexes in older PG, use DO block)
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_worker_logs_level') THEN
        CREATE INDEX idx_worker_logs_level ON public.worker_logs(level, created_at DESC);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_worker_logs_user') THEN
        CREATE INDEX idx_worker_logs_user ON public.worker_logs(user_id, created_at DESC);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_worker_logs_unresolved') THEN
        CREATE INDEX idx_worker_logs_unresolved ON public.worker_logs(resolved, level, created_at DESC)
            WHERE resolved = false;
    END IF;
END $$;

-- Trigger for updated_at on worker_config
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'set_worker_config_updated_at') THEN
        CREATE TRIGGER set_worker_config_updated_at
            BEFORE UPDATE ON public.worker_config
            FOR EACH ROW EXECUTE FUNCTION update_modified_column();
    END IF;
END $$;

-- Enable RLS
ALTER TABLE public.worker_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.worker_logs ENABLE ROW LEVEL SECURITY;

-- RLS Policies (use DO blocks to avoid duplicates)
DO $$ BEGIN
    -- worker_config policies
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Users can read own worker config') THEN
        CREATE POLICY "Users can read own worker config"
            ON public.worker_config FOR SELECT USING (auth.uid() = user_id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Users can update own worker config') THEN
        CREATE POLICY "Users can update own worker config"
            ON public.worker_config FOR UPDATE USING (auth.uid() = user_id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Users can insert own worker config') THEN
        CREATE POLICY "Users can insert own worker config"
            ON public.worker_config FOR INSERT WITH CHECK (auth.uid() = user_id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Service role full access to worker_config') THEN
        CREATE POLICY "Service role full access to worker_config"
            ON public.worker_config FOR ALL USING (auth.role() = 'service_role');
    END IF;

    -- worker_logs policies
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Users can read own worker logs') THEN
        CREATE POLICY "Users can read own worker logs"
            ON public.worker_logs FOR SELECT USING (auth.uid() = user_id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Service role full access to worker_logs') THEN
        CREATE POLICY "Service role full access to worker_logs"
            ON public.worker_logs FOR ALL USING (auth.role() = 'service_role');
    END IF;

    -- Admin policies
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Admins can read all worker configs') THEN
        CREATE POLICY "Admins can read all worker configs"
            ON public.worker_config FOR SELECT
            USING (EXISTS (SELECT 1 FROM public.users WHERE id = auth.uid() AND is_admin = true));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Admins can read all worker logs') THEN
        CREATE POLICY "Admins can read all worker logs"
            ON public.worker_logs FOR SELECT
            USING (EXISTS (SELECT 1 FROM public.users WHERE id = auth.uid() AND is_admin = true));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Admins can update worker logs') THEN
        CREATE POLICY "Admins can update worker logs"
            ON public.worker_logs FOR UPDATE
            USING (EXISTS (SELECT 1 FROM public.users WHERE id = auth.uid() AND is_admin = true));
    END IF;
END $$;

-- Auto-create worker_config on user creation
CREATE OR REPLACE FUNCTION create_default_worker_config()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.worker_config (user_id)
    VALUES (NEW.id)
    ON CONFLICT (user_id) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'on_user_created_add_worker_config') THEN
        CREATE TRIGGER on_user_created_add_worker_config
            AFTER INSERT ON public.users
            FOR EACH ROW EXECUTE FUNCTION create_default_worker_config();
    END IF;
END $$;
"""


def run_migration(db_url):
    """Run migration SQL against the database."""
    try:
        import psycopg2
    except ImportError:
        print("  Installing psycopg2-binary...")
        os.system(f"{sys.executable} -m pip install --quiet psycopg2-binary")
        import psycopg2

    print("  Connecting to database...")
    try:
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        cur = conn.cursor()

        print("  Running migration...")
        cur.execute(MIGRATION_SQL)

        # Verify tables were created
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_name IN ('worker_config', 'worker_logs')
            ORDER BY table_name;
        """)
        tables = [row[0] for row in cur.fetchall()]

        cur.close()
        conn.close()

        if "worker_config" in tables and "worker_logs" in tables:
            print("  [OK] Migration complete — worker_config and worker_logs tables ready")
            return True
        else:
            print(f"  [WARN] Only found tables: {tables}")
            return False

    except Exception as e:
        print(f"  [FAIL] Migration failed: {e}")
        return False


def check_tables_exist(supabase_url, service_key):
    """Quick check if tables already exist using REST API."""
    try:
        import httpx
    except ImportError:
        return False

    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
    }
    try:
        r = httpx.get(
            f"{supabase_url}/rest/v1/worker_config?select=id&limit=1",
            headers=headers,
            timeout=10,
        )
        return r.status_code != 404 and "does not exist" not in r.text
    except Exception:
        return False


def main():
    # Find .env file
    install_dir = os.path.expanduser("~/autoapply")
    env_file = os.path.join(install_dir, ".env")

    # Can also be passed as argument
    if len(sys.argv) > 1:
        env_file = sys.argv[1]

    print("")
    print("  ==============================================")
    print("  ApplyLoop -- Database Migration")
    print("  ==============================================")

    # Read Supabase config from .env
    supabase_url = get_env_value(env_file, "NEXT_PUBLIC_SUPABASE_URL") or get_env_value(env_file, "SUPABASE_URL")
    service_key = get_env_value(env_file, "SUPABASE_SERVICE_ROLE_KEY") or get_env_value(env_file, "SUPABASE_SERVICE_KEY")

    if not supabase_url:
        print("  [FAIL] SUPABASE_URL not found in .env")
        return False

    # Check if tables already exist
    print("  Checking existing tables...")
    if check_tables_exist(supabase_url, service_key):
        print("  [OK] Tables already exist — skipping migration")
        return True

    # Need database password for direct connection
    project_ref = extract_project_ref(supabase_url)
    if not project_ref:
        print(f"  [FAIL] Could not extract project ref from {supabase_url}")
        return False

    # Check if DATABASE_URL is in .env
    db_url = get_env_value(env_file, "DATABASE_URL")

    if not db_url:
        print("")
        print("  To run the migration, we need the database password.")
        print("  Find it at: Supabase Dashboard -> Settings -> Database -> Connection string")
        print("")
        db_password = input("  Database password (from Supabase dashboard): ").strip()

        if not db_password:
            print("  [SKIP] No password provided — run migration manually from Supabase SQL Editor")
            print(f"  SQL file: {install_dir}/packages/web/public/setup/run-migration.py")
            return False

        db_url = f"postgresql://postgres.{project_ref}:{db_password}@aws-0-us-east-1.pooler.supabase.com:6543/postgres"

    return run_migration(db_url)


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
