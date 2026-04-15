"""Database access layer — routes all operations through the ApplyLoop API proxy.

The worker never connects to Supabase directly. All reads/writes go through:
  POST /api/worker/proxy  (with X-Worker-Token header)

This ensures:
  - Users never need the Supabase service role key
  - All writes are scoped to the authenticated user
  - Admin can monitor and revoke access via worker tokens
"""
from __future__ import annotations

import os
import time
import json
import logging
import sqlite3
from datetime import datetime, timezone
import httpx

logger = logging.getLogger(__name__)

APP_URL = os.environ.get("NEXT_PUBLIC_APP_URL", "https://applyloop.vercel.app")
WORKER_TOKEN = os.environ.get("WORKER_TOKEN", "")
RESUME_DIR = os.environ.get("RESUME_DIR", "/tmp/autoapply/resumes")
LOCAL_DB_PATH = os.environ.get("APPLYLOOP_DB", os.path.expanduser("~/.autoapply/workspace/applications.db"))

_http_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _http_client
    if _http_client is None:
        _http_client = httpx.Client(timeout=30, follow_redirects=True)
    return _http_client


class WorkerAuthError(RuntimeError):
    """Raised when the remote API rejects the worker token (401/403).

    The worker's main loop catches this and exits loudly instead of
    continuing to poll with dead credentials. A reauth marker file is
    written into the workspace so the desktop UI can detect the state
    even if it didn't see the crash directly.
    """


# Marker file the desktop UI (server/app.py::setup_status) reads to
# surface "needs reauth" without having to watch the worker's stdout.
_REAUTH_MARKER = os.path.expanduser(os.environ.get(
    "APPLYLOOP_REAUTH_MARKER",
    os.path.join(os.path.dirname(LOCAL_DB_PATH), ".needs-reauth"),
))


def _write_reauth_marker(reason: str) -> None:
    try:
        os.makedirs(os.path.dirname(_REAUTH_MARKER), exist_ok=True)
        with open(_REAUTH_MARKER, "w", encoding="utf-8") as f:
            f.write(reason)
    except Exception as e:
        logger.debug(f"Failed to write reauth marker: {e}")


def _api_call(action: str, **params) -> dict:
    """Make an authenticated call to the worker proxy API.

    Raises WorkerAuthError on 401/403 so the worker main loop can
    terminate cleanly instead of burning through the queue with a dead
    token. All other non-200 responses still degrade to {} for
    compatibility with existing callers.
    """
    client = _get_client()
    resp = client.post(
        f"{APP_URL}/api/worker/proxy",
        json={"action": action, **params},
        headers={"X-Worker-Token": WORKER_TOKEN, "Content-Type": "application/json"},
    )
    if resp.status_code in (401, 403):
        msg = f"HTTP {resp.status_code} from /api/worker/proxy ({action}): worker token revoked or invalid"
        logger.error(msg)
        _write_reauth_marker(msg)
        raise WorkerAuthError(msg)
    if resp.status_code != 200:
        logger.error(f"API call {action} failed: HTTP {resp.status_code} — {resp.text[:200]}")
        return {}
    data = resp.json()
    if data.get("error"):
        logger.error(f"API call {action} error: {data['error']}")
        return {}
    return data.get("data", {})


# ── Preferences cache ──────────────────────────────────────────────────────

_prefs_cache: dict = {}
PREFS_CACHE_TTL = 300  # 5 minutes


def fetch_user_job_preferences(user_id: str) -> dict:
    """Fetch user job preferences with a 5-minute TTL cache."""
    now = time.time()
    if user_id in _prefs_cache:
        prefs, ts = _prefs_cache[user_id]
        if now - ts < PREFS_CACHE_TTL:
            return prefs

    result = _api_call("load_preferences")
    prefs = result.get("preferences", {})
    _prefs_cache[user_id] = (prefs, now)
    return prefs


# ── Job queue ──────────────────────────────────────────────────────────────

def claim_next_job(worker_id: str) -> dict | None:
    """Claim next pending job from the queue."""
    result = _api_call("claim_job", worker_id=worker_id)
    return result.get("job")


def update_queue_status(queue_id: str, status: str, error: str | None = None):
    """Update application queue row status."""
    params: dict = {"queue_id": queue_id, "status": status}
    if error:
        params["error"] = error
    _api_call("update_queue", **params)


# ── Application logging ───────────────────────────────────────────────────

def log_application(user_id: str, job: dict, result: dict):
    """Log application to local SQLite (source of truth) + send only
    aggregate counts to the cloud for the web dashboard.

    Job details (company, title, URL) stay LOCAL. The cloud only gets:
    - status (submitted/failed)
    - count increment
    This keeps client data private and reduces cloud dependency."""
    # Primary: local SQLite (the source of truth for all job data)
    _log_to_local_db(job, result)
    # Secondary: cloud gets just the status for aggregate counting.
    # Best-effort — failure here doesn't lose data (it's in SQLite).
    try:
        _api_call(
            "log_application",
            job_id=job.get("job_id"),
            queue_id=job.get("id"),
            company=job.get("company", ""),
            title=job.get("title", ""),
            ats=job.get("ats", ""),
            apply_url=job.get("apply_url", ""),
            status=result.get("status", "submitted"),
            screenshot_url=result.get("screenshot_url"),
            error=result.get("error"),
        )
    except Exception as e:
        logger.debug(f"Cloud log failed (non-fatal, local SQLite has the data): {e}")


def _get_local_conn() -> sqlite3.Connection:
    """Open (and auto-create) the local SQLite database."""
    os.makedirs(os.path.dirname(LOCAL_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(LOCAL_DB_PATH)
    _ensure_local_schema(conn)
    return conn


def _resolve_ats_for_log(ats: str, apply_url: str) -> str:
    """Map aggregator tags (linkedin/indeed/himalayas/jsearch/ziprecruiter)
    to the real ATS by inspecting the apply_url. Jobs scouted from
    aggregators link to the actual company ATS (greenhouse/lever/ashby/
    workday/smartrecruiters). Without this, the By-Platform donut chart
    showed "100% LinkedIn" even when Claude actually submitted to Greenhouse
    via LinkedIn's external-apply redirect.
    """
    aggregators = {"linkedin", "indeed", "himalayas", "jsearch", "ziprecruiter", ""}
    if ats and ats.lower() not in aggregators:
        return ats
    url = (apply_url or "").lower()
    patterns = {
        "greenhouse": ["greenhouse.io", "boards.greenhouse.io", "job-boards.greenhouse.io"],
        "lever": ["lever.co"],
        "ashby": ["ashbyhq.com"],
        "workday": ["myworkdayjobs.com", "myworkday.com", "wd1.", "wd2.", "wd3.", "wd4.", "wd5."],
        "smartrecruiters": ["smartrecruiters.com"],
        "icims": ["icims.com"],
        "bamboohr": ["bamboohr.com"],
        "taleo": ["taleo.net"],
        "jobvite": ["jobvite.com"],
    }
    for real_ats, fragments in patterns.items():
        if any(frag in url for frag in fragments):
            return real_ats
    return ats or "other"


def _log_to_local_db(job: dict, result: dict):
    """Write application to local SQLite database for desktop UI.

    ATS is resolved from the apply_url before write — so a LinkedIn-scouted
    job that actually submitted to a Greenhouse page gets tagged 'greenhouse'
    in the stats, not 'linkedin'. Fixes the By-Platform donut showing 100%
    LinkedIn while the chart showed Greenhouse submissions.
    """
    try:
        conn = _get_local_conn()
        now = datetime.now(timezone.utc).isoformat()
        company = job.get("company", "")
        job_id = job.get("job_id") or job.get("external_id") or ""
        apply_url = job.get("apply_url", "")
        # Resolve aggregator → real ATS for accurate platform stats
        raw_ats = job.get("ats", "")
        resolved_ats = _resolve_ats_for_log(raw_ats, apply_url)
        if resolved_ats != raw_ats:
            logger.info(f"Logging ATS resolved: {raw_ats} → {resolved_ats} (from URL)")
        conn.execute("""
            INSERT INTO applications (company, role, url, ats, source, location, posted_at, applied_at, updated_at, status, notes, screenshot, dedup_token)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(dedup_token) DO UPDATE SET
                status=excluded.status, applied_at=excluded.applied_at,
                updated_at=excluded.updated_at, screenshot=excluded.screenshot,
                notes=excluded.notes, ats=excluded.ats
        """, (
            company, job.get("title", ""), apply_url,
            resolved_ats, job.get("source", "") or raw_ats, job.get("location", ""),
            job.get("posted_at"), now, now,
            result.get("status", "submitted"), result.get("error"),
            result.get("screenshot_url"),
            f"{company.lower().replace(' ', '-')}|{job_id}",
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Local DB write failed (non-fatal): {e}")


def enqueue_to_local_db(jobs: list[dict]) -> int:
    """Write discovered/scouted jobs to local SQLite as 'queued' for the desktop Kanban.

    This is called alongside the remote API enqueue so the desktop UI sees
    queued jobs in real-time without needing a remote round-trip.
    """
    if not jobs:
        return 0
    try:
        conn = _get_local_conn()
        now = datetime.now(timezone.utc).isoformat()
        inserted = 0
        for job in jobs:
            company = job.get("company", "")
            job_id = job.get("external_id") or job.get("job_id") or ""
            dedup_token = f"{company.lower().replace(' ', '-')}|{job_id}" if job_id else f"{company.lower().replace(' ', '-')}|{(job.get('title', '')).lower().replace(' ', '-')}"
            try:
                conn.execute("""
                    INSERT INTO applications (company, role, url, ats, source, location, posted_at, scouted_at, updated_at, status, dedup_token, application_profile_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)
                    ON CONFLICT(dedup_token) DO NOTHING
                """, (
                    company, job.get("title", ""), job.get("apply_url", ""),
                    job.get("ats", ""), job.get("source", ""), job.get("location", ""),
                    job.get("posted_at"), now, now, dedup_token,
                    job.get("application_profile_id"),
                ))
                inserted += conn.total_changes  # approximate
            except sqlite3.IntegrityError:
                pass  # duplicate, skip
        conn.commit()
        conn.close()
        return inserted
    except Exception as e:
        logger.warning(f"Local DB enqueue failed (non-fatal): {e}")
        return 0


def update_local_status(job: dict, status: str, error: str | None = None):
    """Update a job's status in local SQLite (for applying/cancelled/pending transitions).

    This keeps the desktop Kanban in sync with every status change, not just submit/fail.
    """
    try:
        conn = _get_local_conn()
        now = datetime.now(timezone.utc).isoformat()
        company = job.get("company", "")
        job_id = job.get("job_id") or job.get("external_id") or ""
        dedup_token = f"{company.lower().replace(' ', '-')}|{job_id}" if job_id else None

        if dedup_token:
            conn.execute("""
                UPDATE applications SET status = ?, updated_at = ?, notes = ?
                WHERE dedup_token = ?
            """, (status, now, error, dedup_token))
        else:
            # Fallback: match by company + title (pick most recent non-terminal row)
            conn.execute("""
                UPDATE applications SET status = ?, updated_at = ?, notes = ?
                WHERE id = (
                    SELECT id FROM applications
                    WHERE company = ? AND role = ? AND status NOT IN ('submitted', 'failed')
                    ORDER BY updated_at DESC LIMIT 1
                )
            """, (status, now, error, company, job.get("title", "")))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Local DB status update failed (non-fatal): {e}")


def _ensure_local_schema(conn: sqlite3.Connection):
    """Create the applications table if it doesn't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL, role TEXT NOT NULL, url TEXT, ats TEXT,
            source TEXT, location TEXT, posted_at TEXT, scouted_at TEXT,
            applied_at TEXT, updated_at TEXT,
            status TEXT NOT NULL DEFAULT 'scouted'
                CHECK(status IN ('scouted','queued','applying','submitted','failed','skipped','blocked','interview','rejected','offer')),
            notes TEXT, screenshot TEXT, dedup_token TEXT UNIQUE,
            application_profile_id TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_status ON applications(status);
        CREATE INDEX IF NOT EXISTS idx_company ON applications(company);
        CREATE INDEX IF NOT EXISTS idx_applied_at ON applications(applied_at);
        CREATE INDEX IF NOT EXISTS idx_dedup ON applications(dedup_token);
    """)
    # Additive column migration for existing databases. SQLite is fine
    # with duplicate ADD COLUMN failing — we swallow the exception.
    try:
        conn.execute("ALTER TABLE applications ADD COLUMN application_profile_id TEXT")
    except sqlite3.OperationalError:
        pass


# ── User profile ──────────────────────────────────────────────────────────

def load_user_profile(user_id: str) -> dict:
    """Fetch user profile + resumes."""
    return _api_call("load_profile")


# ── Daily limits ──────────────────────────────────────────────────────────

def check_daily_limit(user_id: str) -> bool:
    """Return True if user hasn't exceeded daily limit."""
    result = _api_call("check_daily_limit")
    return result.get("within_limit", True)


def count_profile_applied_today(profile_id: str) -> int:
    """Count how many applications this bundle has submitted today, from
    the local SQLite mirror. Used by the apply loop to enforce the
    per-bundle `max_daily` cap independently of the user-level daily_apply_limit.
    Returns 0 when the table or bundle has nothing to show."""
    try:
        conn = _get_local_conn()
        row = conn.execute(
            """
            SELECT COUNT(*) FROM applications
            WHERE status='submitted'
              AND application_profile_id = ?
              AND strftime('%Y-%m-%d', applied_at, 'localtime') = date('now', 'localtime')
            """,
            (profile_id,),
        ).fetchone()
        conn.close()
        return int(row[0]) if row else 0
    except Exception:
        return 0


def check_company_rate(user_id: str, company: str) -> bool:
    """Return True if user can still apply to this company (< 5 in 15 days)."""
    result = _api_call("check_company_rate", company=company)
    return result.get("within_limit", True)


# ── Answer key ────────────────────────────────────────────────────────────

def get_answer_key(user_id: str) -> dict:
    """Fetch the user's answer_key_json."""
    result = _api_call("get_answer_key")
    return result.get("answer_key", {})


# ── Telegram config ───────────────────────────────────────────────────────

def get_user_telegram_chat_id(user_id: str) -> str | None:
    """Return the Telegram chat_id for a user."""
    result = _api_call("get_telegram_config")
    return result.get("chat_id")


def get_global_knowledge(key: str):
    """Fetch global config. For telegram_bot_token, use the proxy."""
    if key == "telegram_bot_token":
        result = _api_call("get_telegram_config")
        return result.get("bot_token")
    return None


# ── Resume download ───────────────────────────────────────────────────────

def download_resume_by_url(signed_url: str, file_name: str, cache_key: str = "") -> str:
    """Download a bundle-bound resume by its signed URL. Used when the
    worker has a bundle's resume_signed_url in hand (multi-profile path)
    and wants to skip the legacy title-based picker.

    cache_key is folded into the local filename so different bundles don't
    clobber each other when they share a file_name.
    """
    os.makedirs(RESUME_DIR, exist_ok=True)
    # Sanitize file name and prefix with cache_key to avoid collisions.
    safe = "".join(c for c in file_name if c.isalnum() or c in "._-") or "resume.pdf"
    local_path = os.path.join(RESUME_DIR, f"{cache_key}_{safe}" if cache_key else safe)
    if not os.path.exists(local_path):
        client = _get_client()
        resp = client.get(signed_url)
        resp.raise_for_status()
        with open(local_path, "wb") as f:
            f.write(resp.content)
        logger.info(f"Downloaded bundle resume → {local_path}")
    return local_path


def download_resume(user_id: str, job_title: str | None = None) -> str:
    """Download the best-matching resume to local path."""
    os.makedirs(RESUME_DIR, exist_ok=True)

    result = _api_call("download_resume_url", job_title=job_title or "")
    url = result.get("url")
    file_name = result.get("file_name", "resume.pdf")

    if not url:
        raise ValueError(f"No resume found for user {user_id}")

    # Sanitize to the alnum+._- whitelist used by download_resume_by_url.
    # Windows forbids : ? * | < > " in filenames (Mac only bans /), so the
    # cloud-provided file_name can't be trusted verbatim cross-platform.
    safe = "".join(c for c in file_name if c.isalnum() or c in "._-") or "resume.pdf"
    local_path = os.path.join(RESUME_DIR, f"{user_id}_{safe}")
    if not os.path.exists(local_path):
        client = _get_client()
        resp = client.get(url)
        resp.raise_for_status()
        with open(local_path, "wb") as f:
            f.write(resp.content)
        logger.info(f"Downloaded resume to {local_path}")

    return local_path


# ── Screenshot upload ─────────────────────────────────────────────────────

def upload_screenshot(user_id: str, screenshot_path: str) -> str | None:
    """Upload screenshot — for now, return local path. Cloud upload via API TBD."""
    # Screenshots stay local for now. The Telegram notifier sends them directly.
    return screenshot_path


# ── Job enqueuing ─────────────────────────────────────────────────────────

def enqueue_discovered_jobs(user_id: str, jobs: list[dict]) -> int:
    """Insert discovered jobs via API proxy + local SQLite for desktop Kanban."""
    if not jobs:
        return 0
    result = _api_call("enqueue_jobs", jobs=jobs)
    # Surface server-side rejection reasons. Silent `enqueued: 0` was the
    # root cause of overnight self-recovery blackout — when the server
    # rejects, Claude needs the reason in the log to fix its payload.
    drops = result.get("drops") or []
    if drops:
        import logging as _lg
        _log = _lg.getLogger(__name__)
        by_reason: dict[str, int] = {}
        for d in drops:
            r = str(d.get("reason", "unknown"))
            by_reason[r] = by_reason.get(r, 0) + 1
        _log.warning(
            "enqueue_jobs dropped %d/%d: %s",
            len(drops), len(jobs),
            ", ".join(f"{k}×{v}" for k, v in by_reason.items()),
        )
    enqueue_to_local_db(jobs)
    return result.get("enqueued", 0)


# ── Heartbeat ─────────────────────────────────────────────────────────────

def update_heartbeat(user_id: str, action: str, details: str = ""):
    """Update worker heartbeat via API proxy."""
    _api_call("heartbeat", last_action=action, details=details)


# ── Legacy compatibility (used by some imports) ──────────────────────────

def get_client():
    """Legacy — returns the HTTP client instead of Supabase client."""
    return _get_client()
