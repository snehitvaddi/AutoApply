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
RESUME_DIR = os.environ.get("RESUME_DIR") or os.path.expanduser("~/.autoapply/workspace/resumes")
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
    """Claim next pending job from the cloud queue (legacy / planner mode)."""
    result = _api_call("claim_job", worker_id=worker_id)
    return result.get("job")


def claim_next_job_locally(user_id: str, worker_id: str) -> dict | None:
    """Local-first claim — atomically take the oldest 'queued' row from the
    local applications.db, mark it 'applying', and return it in the same
    shape the cloud claim_next_job produces so downstream apply code is
    unchanged.

    Uses SQLite 3.35+ UPDATE ... RETURNING for atomicity. Only one worker
    runs per user on a machine, so row-level contention is effectively zero.

    Returns None when the queue is empty. Returns a job dict when a row
    was claimed. Any SQLite error is surfaced via logger.warning and the
    call returns None so the caller sleeps a tick and retries.
    """
    try:
        conn = _get_local_conn()
        now = datetime.now(timezone.utc).isoformat()
        row = conn.execute(
            """
            UPDATE applications
            SET status = 'applying', updated_at = ?
            WHERE id = (
                SELECT id FROM applications
                WHERE status = 'queued'
                ORDER BY scouted_at ASC
                LIMIT 1
            )
            RETURNING id, company, role, url, ats, source, location,
                      posted_at, scouted_at, dedup_token, application_profile_id
            """,
            (now,),
        ).fetchone()
        conn.commit()
        conn.close()
        if not row:
            return None
        (lid, company, role, url, ats, source, location, posted_at,
         scouted_at, dedup_token, application_profile_id) = row
        # dedup_token format: "company|external_id". Parse out external_id
        # so the downstream log path can re-derive the same key.
        external_id = ""
        if dedup_token and "|" in dedup_token:
            external_id = dedup_token.split("|", 1)[1]
        return {
            "id": str(lid),            # local integer id, stringified
            "user_id": user_id,
            "job_id": None,            # only meaningful for cloud queue rows
            "company": company or "",
            "title": role or "",
            "ats": ats or "",
            "source": source or "",
            "apply_url": url or "",
            "location": location or "",
            "posted_at": posted_at,
            "scouted_at": scouted_at,
            "external_id": external_id,
            "application_profile_id": application_profile_id,
            "attempts": 0,             # local schema doesn't track retries yet
            "max_attempts": 3,
            "_local": True,            # marker so update_queue_status can route writes
        }
    except Exception as e:
        logger.warning(f"local claim failed: {e}")
        return None


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
    """Open (and auto-create) the local SQLite database.

    WAL + 30s busy timeout is required because the scout and apply
    threads each open their own connection and write concurrently
    (enqueue_to_local_db from scout, update_local_status + _log_to_local_db
    from apply). Default timeout=0 + rollback journal made the second
    writer fail immediately with `database is locked`, leaving rows
    stuck in `applying` state with no one to reset them.
    """
    os.makedirs(os.path.dirname(LOCAL_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.Error:
        pass
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
        # MUST mirror enqueue_to_local_db's token scheme (external_id first).
        # Mismatch here leaves every applied job orphaning a stale 'queued' row
        # under a different token → `in_queue` stat grows forever.
        job_id = job.get("external_id") or job.get("job_id") or ""
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
            # ApplyResult.screenshot is the source of truth; fall back to
            # screenshot_url for legacy callers that still use the old key.
            result.get("screenshot") or result.get("screenshot_url"),
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
    # Freshness guard. scout/ashby.py::_is_fresh_24h only filters the
    # scout source's output; manual injections (via /api/worker/proxy
    # enqueue_jobs → enqueue_discovered_jobs → enqueue_to_local_db)
    # bypass it. Without this, ghost postings 6+ months old get
    # enqueued and waste apply attempts. Jobs with NO posted_at still
    # pass (many sources don't surface it); only reject when we have
    # a concrete old date.
    from datetime import timedelta as _timedelta
    stale_cutoff = datetime.now(timezone.utc) - _timedelta(hours=24)
    try:
        conn = _get_local_conn()
        now = datetime.now(timezone.utc).isoformat()
        inserted = 0
        skipped_stale = 0
        for job in jobs:
            posted_at_raw = job.get("posted_at")
            if posted_at_raw:
                try:
                    posted_dt = datetime.fromisoformat(
                        str(posted_at_raw).replace("Z", "+00:00")
                    )
                    if posted_dt.tzinfo is None:
                        posted_dt = posted_dt.replace(tzinfo=timezone.utc)
                    if posted_dt < stale_cutoff:
                        skipped_stale += 1
                        continue
                except (ValueError, TypeError):
                    pass  # unparseable date = trust the caller, enqueue
            company = job.get("company", "")
            job_id = job.get("external_id") or job.get("job_id") or ""
            dedup_token = f"{company.lower().replace(' ', '-')}|{job_id}" if job_id else f"{company.lower().replace(' ', '-')}|{(job.get('title', '')).lower().replace(' ', '-')}"
            try:
                cur = conn.execute("""
                    INSERT INTO applications (company, role, url, ats, source, location, posted_at, scouted_at, updated_at, status, dedup_token, application_profile_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)
                    ON CONFLICT(dedup_token) DO NOTHING
                """, (
                    company, job.get("title", ""), job.get("apply_url", ""),
                    job.get("ats", ""), job.get("source", ""), job.get("location", ""),
                    job.get("posted_at"), now, now, dedup_token,
                    job.get("application_profile_id"),
                ))
                # cur.rowcount is 1 on insert, 0 on conflict. conn.total_changes
                # is cumulative, which produced triangular counts in the log.
                inserted += cur.rowcount if cur.rowcount > 0 else 0
            except sqlite3.IntegrityError:
                pass  # duplicate, skip
        conn.commit()
        conn.close()
        if skipped_stale:
            logger.info(f"enqueue_to_local_db: dropped {skipped_stale} stale (>24h) row(s)")
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
        # Mirror enqueue_to_local_db's token scheme (external_id first).
        job_id = job.get("external_id") or job.get("job_id") or ""
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


def cleanup_stale_queued_shadows() -> int:
    """Drop 'queued' rows that were orphaned by the pre-fix dedup-token bug.

    Before `fix(stats)` (commit 4891e62), _log_to_local_db and
    enqueue_to_local_db resolved different dedup tokens for the same job
    (external_id vs job_id UUID). Every applied job therefore left a stale
    'queued' shadow row in local SQLite, inflating the dashboard's
    `in_queue` count indefinitely.

    This cleanup runs at worker boot: for any (company, role) pair that
    has at least one terminal row (submitted/failed), delete any lingering
    'queued' or 'applying' row. Idempotent — re-running finds nothing.

    Case-insensitive match because `role` is the job title and ATS data
    is inconsistent about casing (Greenhouse returns Title Case, Lever
    sometimes all-caps). company is already lowercased by the enqueue
    path but we still LOWER() defensively.
    """
    try:
        conn = _get_local_conn()
        cur = conn.execute("""
            DELETE FROM applications
            WHERE status IN ('queued','applying')
              AND EXISTS (
                SELECT 1 FROM applications t
                WHERE LOWER(t.company) = LOWER(applications.company)
                  AND LOWER(t.role) = LOWER(applications.role)
                  AND t.status IN ('submitted','failed')
                  AND t.id != applications.id
              )
        """)
        conn.commit()
        deleted = cur.rowcount or 0
        conn.close()
        if deleted:
            logger.info(f"Cleaned up {deleted} stale queued/applying shadow rows")
        return deleted
    except Exception as e:
        logger.warning(f"Shadow-row cleanup failed (non-fatal): {e}")
        return 0


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

# Profile cache — same 5-min TTL as preferences. Before this, the apply
# loop called load_user_profile(user_id) twice per iteration (preflight
# + inside the loop body), costing ~2 cloud round-trips per job. With
# the cache a single apply cycle reads from memory after the first hit.
_profile_cache: dict = {}
PROFILE_CACHE_TTL = 300  # 5 minutes — matches preferences + tenant reload


def load_user_profile(user_id: str, force: bool = False) -> dict:
    """Fetch user profile + resumes. Cached for 5 min so the hot apply path
    doesn't round-trip the cloud on every iteration.

    Pass force=True to bust the cache (e.g., right after a profile update).
    """
    now = time.time()
    if not force and user_id in _profile_cache:
        data, ts = _profile_cache[user_id]
        if now - ts < PROFILE_CACHE_TTL:
            return data
    result = _api_call("load_profile")
    _profile_cache[user_id] = (result, now)
    return result


def refresh_config_caches() -> None:
    """Bust every in-memory config cache. Call after a settings change or
    when the worker has reason to believe the cloud has newer data."""
    _profile_cache.clear()
    _prefs_cache.clear()


# ── Daily limits ──────────────────────────────────────────────────────────

def check_daily_limit(user_id: str) -> bool:
    """Return True if user hasn't exceeded daily limit (cloud call)."""
    result = _api_call("check_daily_limit")
    return result.get("within_limit", True)


def check_daily_limit_locally(user_id: str, daily_cap: int | None) -> bool:
    """Local daily-cap check — counts submitted rows for today (user's local
    day) from the local SQLite mirror. daily_cap=None means no cap → True.

    Timezone matches count_profile_applied_today: strftime with 'localtime'
    so the cap aligns with the user's day, not UTC. Non-fatal on error:
    returns True so a cloud/SQLite hiccup doesn't stall the apply loop.
    """
    if daily_cap is None or daily_cap <= 0:
        return True
    try:
        conn = _get_local_conn()
        row = conn.execute(
            """
            SELECT COUNT(*) FROM applications
            WHERE status='submitted'
              AND strftime('%Y-%m-%d', applied_at, 'localtime') = date('now', 'localtime')
            """
        ).fetchone()
        conn.close()
        return int(row[0]) < daily_cap if row else True
    except Exception as e:
        logger.debug(f"local daily-limit check failed (allowing): {e}")
        return True


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
    """Return True if user can still apply to this company (cloud call)."""
    result = _api_call("check_company_rate", company=company)
    return result.get("within_limit", True)


def check_company_rate_locally(user_id: str, company: str) -> bool:
    """Local company-rate check — enforces MAX_COMPANY_APPS_PER_7_DAYS
    against the local applications mirror. Case-insensitive match on
    company (ATS data drifts between Title Case and lowercase).

    Non-fatal on error: returns True so a SQLite hiccup doesn't block
    the apply loop.
    """
    if not company:
        return True
    try:
        from config import MAX_COMPANY_APPS_PER_7_DAYS
        conn = _get_local_conn()
        row = conn.execute(
            """
            SELECT COUNT(*) FROM applications
            WHERE status='submitted'
              AND LOWER(company) = LOWER(?)
              AND applied_at >= datetime('now', '-7 days')
            """,
            (company.strip(),),
        ).fetchone()
        conn.close()
        return int(row[0]) < MAX_COMPANY_APPS_PER_7_DAYS if row else True
    except Exception as e:
        logger.debug(f"local company-rate check failed (allowing): {e}")
        return True


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
    """Upload screenshot to the cloud 'screenshots' bucket and return a
    7-day signed URL. Falls back to the local path if cloud is unreachable
    — the Telegram notifier can still attach the local file directly, and
    the desktop Kanban can display the local path via file://.

    Small by design: screenshots are capped at 5 MB (validated server-
    side). base64 overhead is ~33%, so <7 MB payload per call.
    """
    if not screenshot_path or not os.path.exists(screenshot_path):
        return None
    try:
        import base64 as _b64
        with open(screenshot_path, "rb") as f:
            b64 = _b64.b64encode(f.read()).decode("ascii")
        filename = os.path.basename(screenshot_path)
        result = _api_call("upload_screenshot", file_base64=b64, filename=filename)
        url = result.get("url")
        return url or screenshot_path
    except Exception as e:
        logger.debug(f"Screenshot cloud upload failed (falling back to local): {e}")
        return screenshot_path


def prune_old_screenshots(days: int = 7) -> int:
    """Delete local screenshot files older than N days. Prevents
    SCREENSHOT_DIR from growing unbounded on long-running installs.
    Idempotent; safe to call at every worker boot + periodically.
    """
    try:
        from config import SCREENSHOT_DIR
    except Exception:
        return 0
    if not os.path.isdir(SCREENSHOT_DIR):
        return 0
    cutoff = time.time() - days * 86400
    removed = 0
    try:
        for name in os.listdir(SCREENSHOT_DIR):
            p = os.path.join(SCREENSHOT_DIR, name)
            try:
                if os.path.isfile(p) and os.path.getmtime(p) < cutoff:
                    os.remove(p)
                    removed += 1
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"screenshot prune scan failed: {e}")
        return 0
    if removed:
        logger.info(f"Pruned {removed} local screenshots older than {days}d")
    return removed


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


# ── Cloud planner (Phase 1 of planner architecture) ──────────────────────

def fetch_next_plan() -> dict | None:
    """Ask the cloud planner what action to take next.

    Returns {plan_id, action, params, reason, expires_at, state} on success.
    None on any failure (caller should back off + retry). Never raises —
    the worker loop must survive planner outages.
    """
    try:
        result = _api_call("get_next_action")
        if not isinstance(result, dict) or "action" not in result:
            return None
        return result
    except Exception as e:
        logger.debug(f"fetch_next_plan failed: {e}")
        return None


def report_plan_outcome(plan_id: str, outcome: str, detail: str | None = None) -> None:
    """Post the result of executing a plan back to the cloud. Updates
    worker_plan.outcome{,_detail,_at} so the Decision Log reflects reality
    and the next planner call has fresh data to reason over.

    outcome values (match CHECK constraint): success | empty | failed | skipped.
    Swallows errors — worker keeps moving even if reporting fails.
    """
    try:
        _api_call("report_plan_outcome", plan_id=plan_id, outcome=outcome, outcome_detail=detail)
    except Exception as e:
        logger.debug(f"report_plan_outcome failed: {e}")


# ── Heartbeat ─────────────────────────────────────────────────────────────

def update_heartbeat(user_id: str, action: str, details: str = ""):
    """Update worker heartbeat via API proxy."""
    _api_call("heartbeat", last_action=action, details=details)


# ── Legacy compatibility (used by some imports) ──────────────────────────

def get_client():
    """Legacy — returns the HTTP client instead of Supabase client."""
    return _get_client()
