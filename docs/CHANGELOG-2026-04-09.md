# Changes to Port into ApplyLoop SaaS — April 9, 2026

Two categories of changes were made today on the personal OpenClaw setup. These need to be adopted into the multi-user ApplyLoop SaaS so all users benefit.

---

## CHANGE 1: SQLite Local Application Database (replaces JSON logging)

### What Changed
The job-bot agent was logging applications to two flat JSON files:
- `memory/applications-log.json` (append-only array, 1,756 entries, 80+ inconsistent fields, 50+ status values)
- `/tmp/applied-dedup.json` (ephemeral dedup lookup, lost on reboot)

**Replaced with:** A proper SQLite database with clean schema, normalized statuses, indexes, and a query tool.

### Files Created/Changed

| File | Location | What It Does |
|------|----------|--------------|
| `applications.db` | `~/.openclaw/agents/job-bot/workspace/applications.db` | SQLite database — 1,617 migrated rows, 732 submitted, 575 companies |
| `migrate-to-sqlite.py` | `~/.openclaw/agents/job-bot/workspace/scripts/migrate-to-sqlite.py` | One-time migration from JSON → SQLite. Normalizes 50+ statuses → 7, deduplicates, maps inconsistent field names |
| `query-apps.py` | `~/.openclaw/agents/job-bot/workspace/scripts/query-apps.py` | CLI query tool: `stats`, `status`, `recent`, `today`, `search`, `company` |
| `SOUL.md` | `~/.openclaw/agents/job-bot/workspace/SOUL.md` | Updated 6 references: dedup section, application log format, cron mode, telegram status, persistence section, apply step logging |

### SQLite Schema (adopt for SaaS local DB)

```sql
CREATE TABLE applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT NOT NULL,
    role TEXT NOT NULL,
    url TEXT,
    ats TEXT,                    -- greenhouse, ashby, lever, workday, etc.
    source TEXT,                 -- linkedin, greenhouse-api, ashby-api, etc.
    location TEXT,
    posted_at TEXT,              -- ISO 8601
    scouted_at TEXT,             -- when first discovered
    applied_at TEXT,             -- when application was submitted
    updated_at TEXT,             -- last status change
    status TEXT NOT NULL DEFAULT 'scouted'
        CHECK(status IN ('scouted','queued','applying','submitted','failed','skipped','blocked','interview','rejected','offer')),
    notes TEXT,
    screenshot TEXT,             -- path to confirmation screenshot
    dedup_token TEXT UNIQUE      -- company|job_id for dedup
);

CREATE INDEX idx_status ON applications(status);
CREATE INDEX idx_company ON applications(company);
CREATE INDEX idx_applied_at ON applications(applied_at);
CREATE INDEX idx_dedup ON applications(dedup_token);
```

### How to Adopt in SaaS

#### 1. Desktop App — `packages/desktop/server/local_data.py`
**Already updated today** to read from `applications.db`. This file is the bridge between the local SQLite and the desktop UI. Current hardcoded path points to personal DB at `~/.openclaw/agents/job-bot/workspace/applications.db`.

**For SaaS users:** Change `DB_PATH` to be configurable via environment variable or config file:
```python
DB_PATH = Path(os.environ.get("APPLYLOOP_DB", Path.home() / ".autoapply" / "workspace" / "applications.db"))
```

Functions already implemented and working:
- `get_stats()` — dashboard stat cards (applied today, total, queue, success rate)
- `get_daily_breakdown()` — applications per day for area chart (last 30 days)
- `get_ats_breakdown()` — pie chart by ATS platform
- `get_recent_applications(limit)` — recent apps table with mixed submitted/failed
- `get_pipeline()` — pipeline/queue view grouped by status
- `delete_from_queue(job_id)` — remove queued items

#### 2. Worker — `packages/worker/db.py`
Currently routes everything through the API proxy (Supabase). Add a **local SQLite fallback** so the worker also writes to the local DB, giving the desktop app real-time data without waiting for API round-trips.

Add to `log_application()`:
```python
def log_application(user_id, job, result):
    # Existing: remote API call
    _api_call("log_application", ...)
    
    # NEW: also write to local SQLite for desktop dashboard
    _log_to_local_db(job, result)

def _log_to_local_db(job, result):
    import sqlite3
    from datetime import datetime, timezone
    db_path = os.environ.get("APPLYLOOP_DB", os.path.expanduser("~/.autoapply/workspace/applications.db"))
    conn = sqlite3.connect(db_path)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("""
        INSERT INTO applications (company, role, url, ats, applied_at, updated_at, status, screenshot, dedup_token)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(dedup_token) DO UPDATE SET status=excluded.status, applied_at=excluded.applied_at, updated_at=excluded.updated_at, screenshot=excluded.screenshot
    """, (
        job.get("company",""), job.get("title",""), job.get("apply_url",""),
        job.get("ats",""), now, now, result.get("status","submitted"),
        result.get("screenshot_url"), f"{job.get('company','').lower()}|{job.get('job_id','')}"
    ))
    conn.commit()
    conn.close()
```

#### 3. Worker SOUL.md — `packages/worker/SOUL.md`
**Updated references:**
- Line 76: `Dedup: check /tmp/applied-dedup.json` → `Dedup: check applications.db`
- Line 151: `Local dedup: /tmp/applied-dedup.json` → `Local dedup: applications.db (SQLite)`
- Line 174: `/tmp/applied-dedup.json — local dedup DB` → `applications.db — local SQLite database`

#### 4. Supabase Schema — `supabase/migrations/001_schema.sql`
The Supabase `applications` table (line 130) currently has limited status values:
```sql
CHECK (status IN ('submitted', 'failed', 'verified'))
```

**Expand to match the new local schema:**
Create a new migration `008_expand_application_statuses.sql`:
```sql
ALTER TABLE public.applications DROP CONSTRAINT applications_status_check;
ALTER TABLE public.applications ADD CONSTRAINT applications_status_check
  CHECK (status IN ('scouted', 'queued', 'applying', 'submitted', 'failed', 'skipped', 'blocked', 'interview', 'rejected', 'offer', 'verified'));

-- Add missing columns to match local schema
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS source text;
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS location text;
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS posted_at timestamptz;
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS scouted_at timestamptz;
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS updated_at timestamptz DEFAULT now();
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS notes text;
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS dedup_token text UNIQUE;

CREATE INDEX IF NOT EXISTS idx_applications_status ON public.applications(status);
CREATE INDEX IF NOT EXISTS idx_applications_company ON public.applications(company);
CREATE INDEX IF NOT EXISTS idx_applications_dedup ON public.applications(dedup_token);

-- Add trigger for updated_at
CREATE TRIGGER set_updated_at_applications
  BEFORE UPDATE ON public.applications
  FOR EACH ROW EXECUTE FUNCTION update_timestamp();
```

#### 5. Setup Script — Create DB on First Run
When a new user sets up ApplyLoop, the setup script should create the local SQLite DB:
```python
# In setup.py or worker startup
import sqlite3, os
db_path = os.path.expanduser("~/.autoapply/workspace/applications.db")
os.makedirs(os.path.dirname(db_path), exist_ok=True)
conn = sqlite3.connect(db_path)
conn.executescript("""
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT NOT NULL, role TEXT NOT NULL, url TEXT, ats TEXT,
    source TEXT, location TEXT, posted_at TEXT, scouted_at TEXT,
    applied_at TEXT, updated_at TEXT,
    status TEXT NOT NULL DEFAULT 'scouted'
        CHECK(status IN ('scouted','queued','applying','submitted','failed','skipped','blocked','interview','rejected','offer')),
    notes TEXT, screenshot TEXT, dedup_token TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_status ON applications(status);
CREATE INDEX IF NOT EXISTS idx_company ON applications(company);
CREATE INDEX IF NOT EXISTS idx_applied_at ON applications(applied_at);
CREATE INDEX IF NOT EXISTS idx_dedup ON applications(dedup_token);
""")
conn.close()
```

---

## CHANGE 2: Desktop UI Updates (v0 Export)

### What Changed
The desktop app UI was rebuilt/updated via v0.dev export. 42 component files were updated in `v0-ui-export/`.

### Files Changed

| Directory | Files | Purpose |
|-----------|-------|---------|
| `v0-ui-export/components/dashboard/` | Multiple `.tsx` files | Dashboard stat cards, charts, recent applications table |
| `v0-ui-export/components/pipeline/` | Pipeline view components | Kanban-style pipeline: scouted → queued → applying → submitted |
| `v0-ui-export/components/ui/` | Shadcn UI components | Base component library |
| `v0-ui-export/components/sidebar.tsx` | 1 file | Navigation sidebar |
| `v0-ui-export/components/app-shell.tsx` | 1 file | Main app layout shell |
| `v0-ui-export/components/theme-provider.tsx` | 1 file | Dark/light theme provider |

### Desktop Server Files Updated (all at `packages/desktop/server/`)

| File | Size | What It Does |
|------|------|--------------|
| `app.py` | 11K | Main FastAPI app — routes for stats, pipeline, auth, worker control, websockets, static UI serving |
| `chat_bridge.py` | 10K | WebSocket bridge to Claude/OpenClaw CLI sessions |
| `local_data.py` | 6.5K | **SQLite reader** — reads `applications.db` for dashboard stats, pipeline, recent apps |
| `process_manager.py` | 5.5K | Worker process start/stop/restart management |
| `stats.py` | 4.4K | Remote API proxy for profile, preferences, heartbeat |
| `config.py` | 1.8K | Token loading, APP_URL config |
| `terminal_stream.py` | 1.0K | Terminal output WebSocket streaming |

### How to Adopt in SaaS

The desktop app is already structured correctly for multi-user:
- `local_data.py` reads from SQLite (local, fast, works offline)
- `stats.py` reads from remote API (Supabase, for cloud dashboard)
- `app.py` exposes both via REST endpoints

**For SaaS users, the desktop app needs:**
1. `DB_PATH` in `local_data.py` should use `~/.autoapply/workspace/applications.db` (not the hardcoded OpenClaw path)
2. Worker writes to both local SQLite AND remote API (dual-write)
3. Desktop UI reads from local SQLite (fast, no latency)
4. Web dashboard reads from Supabase (cloud, accessible from any device)

---

## Summary of All Files to Update in SaaS

| Priority | File | Action |
|----------|------|--------|
| HIGH | `packages/desktop/server/local_data.py` | Make DB_PATH configurable, not hardcoded to personal OpenClaw path |
| HIGH | `packages/worker/db.py` | Add `_log_to_local_db()` dual-write to local SQLite |
| HIGH | `packages/worker/SOUL.md` | Update dedup/logging references from JSON → SQLite |
| HIGH | New: `supabase/migrations/008_expand_application_statuses.sql` | Expand status enum, add missing columns |
| MEDIUM | `packages/worker/worker.py` | Ensure DB is created on startup if missing |
| MEDIUM | `setup.sh` | Add SQLite DB creation to setup script |
| LOW | `packages/desktop/server/app.py` | Already correct, no changes needed |
| LOW | `packages/desktop/server/stats.py` | Already correct, no changes needed |
