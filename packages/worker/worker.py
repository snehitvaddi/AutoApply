from __future__ import annotations
import os
import random
import time
import signal
import logging
import subprocess
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from config import (
    WORKER_ID, POLL_INTERVAL, APPLY_COOLDOWN, ATS_COOLDOWNS,
    MAX_SYSTEM_APPS_PER_HOUR, BLOCKED_DOMAINS, COMPANY_PAUSES,
    BLOCKED_STAFFING, SCOUT_INTERVAL_MINUTES,
    MAX_COMPANY_APPS_PER_7_DAYS, QUEUE_STALE_HOURS,
)
from tenant import (
    TenantConfig, TenantConfigIncompleteError,
    DEFAULT_SECURITY_CLEARANCE_COMPANIES,
)
from scout import REGISTERED_SOURCES
from db import (
    claim_next_job, load_user_profile, update_queue_status, log_application,
    check_daily_limit, get_answer_key, download_resume, upload_screenshot,
    fetch_user_job_preferences, enqueue_discovered_jobs, update_heartbeat as db_heartbeat,
    check_company_rate as db_check_company_rate,
    update_local_status,
    WorkerAuthError,
)
from notifier import send_application_result, send_failure
from knowledge import build_answer_key, load_global_template
from applier.base import MissingResumeError
from applier.greenhouse import GreenhouseApplier
from applier.lever import LeverApplier
from applier.ashby import AshbyApplier
from applier.smartrecruiters import SmartRecruitersApplier
from applier.workday import WorkdayApplier

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(message)s')
logger = logging.getLogger(f'worker-{WORKER_ID}')

# In-memory dedup cache to avoid repeated DB queries for the same URL within a day
_seen_urls: set = set()
_seen_urls_date: str = ""

# Coded appliers — optimized form-fillers for specific ATS platforms.
# For unknown ATS, the SOUL.md "universal applier" approach is used by
# Claude Code directly (OpenClaw snapshot → fill → submit). These coded
# ones are faster because they don't need LLM reasoning per field.
APPLIERS = {
    'greenhouse': GreenhouseApplier,
    'lever': LeverApplier,
    'ashby': AshbyApplier,
    'smartrecruiters': SmartRecruitersApplier,
    'workday': WorkdayApplier,
}

# ATS detection from apply URLs — aggregators (Indeed, Himalayas, LinkedIn)
# link to the real ATS. Resolve before claiming so the right applier is used.
_ATS_URL_PATTERNS = {
    'greenhouse': ['greenhouse.io', 'boards-api.greenhouse.io'],
    'lever': ['lever.co', 'jobs.lever.co'],
    'ashby': ['ashbyhq.com', 'jobs.ashbyhq.com'],
    'smartrecruiters': ['smartrecruiters.com'],
    'workday': ['myworkdayjobs.com', 'myworkday.com', 'wd1.', 'wd2.', 'wd3.', 'wd4.', 'wd5.'],
}


def _resolve_ats_from_url(apply_url: str, tagged_ats: str) -> str:
    """If the job was tagged with an aggregator ATS (indeed, himalayas, linkedin),
    try to detect the real ATS from the apply URL. Returns the resolved ATS name
    or the original tag if no match found."""
    aggregators = {'indeed', 'himalayas', 'linkedin', 'jsearch', 'ziprecruiter'}
    if tagged_ats not in aggregators:
        return tagged_ats  # already a real ATS tag
    url_lower = (apply_url or '').lower()
    for ats_name, patterns in _ATS_URL_PATTERNS.items():
        if any(p in url_lower for p in patterns):
            return ats_name
    return tagged_ats  # couldn't resolve — keep original

running = True


def shutdown(signum, frame):
    global running
    logger.info("Shutdown signal received")
    running = False


signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)


def is_blocked_url(apply_url: str) -> bool:
    """Check if the apply URL is from a known aggregator/spam domain."""
    try:
        host = urlparse(apply_url).hostname or ""
        return any(domain in host for domain in BLOCKED_DOMAINS)
    except Exception:
        return False


def is_paused_company(company: str) -> bool:
    """Check if the company is temporarily paused."""
    company_lower = (company or "").lower().strip()
    pause_until = COMPANY_PAUSES.get(company_lower)
    if pause_until and date.today() < pause_until:
        return True
    return False


def is_blocked_company(company: str, tenant: TenantConfig | None = None) -> bool:
    """Return True if the tenant is visa-blocked from this company.

    Only applies the security-clearance company list to tenants whose
    work_auth forbids it (OPT/H1B etc.). US citizens and green-card
    holders can apply freely — no hardcoded blocklist for them.

    If tenant is None (per-job apply path where we haven't loaded the
    tenant yet because the queue may span multiple users), fall back to
    the global clearance list. Per-job load_user_profile + visa check
    can refine this further upstream if needed.
    """
    company_lower = (company or "").lower().strip()
    if tenant is not None:
        return tenant.security_clearance_blocked(company)
    return any(blocked in company_lower for blocked in DEFAULT_SECURITY_CLEARANCE_COMPANIES)


# ─── Company Rate Limiting (via API proxy) ─────────────────────────────────

def check_company_rate(user_id: str, company: str) -> bool:
    """Return True if user can still apply to this company (< 3 in last 7 days)."""
    return db_check_company_rate(user_id, company)


# ─── Heartbeat (via API proxy) ──────────────────────────────────────────────

def update_heartbeat(user_id: str, action: str, details: str = ""):
    """Update worker heartbeat via API."""
    db_heartbeat(user_id, action, details)


# ─── Job filter + freshness + scout sources ─────────────────────────────────
#
# All of these used to live inline as passes_filter / _is_fresh_24h /
# scout_ashby_boards / scout_greenhouse_boards with hardcoded admin defaults
# (AI_KEYWORDS, SKIP_LEVELS, SKIP_ROLE_KEYWORDS, SKIP_LOCATIONS). They now
# live in packages/worker/scout/ as plugins and tenant.py::TenantConfig:
#
#   - passes_filter()      →  tenant.passes_filter(title, company, location)
#   - _is_fresh_24h()      →  scout/ashby.py::_is_fresh_24h (private)
#   - scout_ashby_boards() →  scout/ashby.py::AshbyScout
#   - scout_greenhouse_boards() → scout/greenhouse.py::GreenhouseScout
#
# Every scout source reads queries from tenant.search_queries and filters
# through tenant.passes_filter(). No admin defaults remain. The registry
# in scout/__init__.py enumerates all sources so adding a new one (e.g.
# Dice) never requires touching worker.py.


def _enqueue_discovered_jobs(user_id: str, jobs: list[dict]):
    """Insert discovered jobs via API proxy. Local URL cache for fast dedup."""
    global _seen_urls, _seen_urls_date

    today = date.today().isoformat()
    if _seen_urls_date != today:
        _seen_urls = set()
        _seen_urls_date = today

    # Filter out locally-cached URLs first
    new_jobs = []
    for job in jobs:
        url = job.get("apply_url", "")
        if url and url not in _seen_urls:
            new_jobs.append(job)
            _seen_urls.add(url)

    if not new_jobs:
        return 0

    # Send to API proxy for server-side dedup + enqueue
    return enqueue_discovered_jobs(user_id, new_jobs)


def run_scout_cycle(tenant: TenantConfig) -> int:
    """Run one scout → filter → enqueue cycle for THIS tenant.

    Iterates REGISTERED_SOURCES from packages/worker/scout/. Each source
    reads its queries from `tenant.search_queries` and filters results via
    `tenant.passes_filter()`. There is no fallback to admin defaults at
    any layer — if tenant has no target_titles, the worker refuses to boot
    at main() time before reaching this function.

    Priority dispatch:
      HIGH:    always run
      MEDIUM:  run 80% of cycles
      LOW:     run 40% of cycles

    Adding a new source only requires appending to scout.REGISTERED_SOURCES.
    """
    update_heartbeat(tenant.user_id, "scouting", tenant.profile_summary_hint())

    all_jobs: list[dict] = []
    counts: dict[str, int] = {}

    for source in REGISTERED_SOURCES:
        if not source.is_enabled_for(tenant):
            continue
        roll = random.random()
        if source.priority == "high":
            run_it = True
        elif source.priority == "medium":
            run_it = roll < 0.8
        else:  # "low"
            run_it = roll < 0.4
        if not run_it:
            continue
        try:
            logger.info(f"Scout: {source.priority.upper()} — {source.name} for {tenant.user_id[:8]}")
            jobs = source.scout(tenant)
            for j in jobs:
                j.setdefault("source", source.name)
            all_jobs.extend(jobs)
            counts[source.name] = len(jobs)
        except Exception as e:
            logger.warning(f"{source.name} scout failed: {e}")
            counts[source.name] = 0

    summary = ", ".join(f"{v} {k}" for k, v in counts.items() if v > 0)
    logger.info(f"Scout: {summary} = {len(all_jobs)} total (after per-source filter)")

    # Touch the scout heartbeat file so the PTY watchdog can detect that
    # scout is alive without relying on PTY byte flow.
    _touch_scout_heartbeat()

    if not all_jobs:
        update_heartbeat(tenant.user_id, "idle", "No new jobs matched tenant criteria")
        return 0

    enqueued = _enqueue_discovered_jobs(tenant.user_id, all_jobs)
    logger.info(f"Scout complete: {enqueued} new jobs enqueued (from {len(all_jobs)} raw)")
    update_heartbeat(tenant.user_id, "scouted", f"{enqueued} enqueued from {summary}")
    return enqueued


def scout_loop(tenant: TenantConfig) -> None:
    """Background thread: runs scout cycle every SCOUT_INTERVAL_MINUTES for
    the per-tenant TenantConfig. Never called with a 'system' user_id."""
    while running:
        try:
            run_scout_cycle(tenant)
        except Exception as e:
            logger.exception(f"Scout cycle error: {e}")
            update_heartbeat(tenant.user_id, "error", str(e))

        # Sleep in small increments so we can respond to shutdown
        for _ in range(SCOUT_INTERVAL_MINUTES * 60):
            if not running:
                return
            time.sleep(1)


# ─── Filesystem heartbeat for the PTY watchdog ──────────────────────────────
#
# The desktop PTY watchdog decides whether the apply loop is alive by
# reading two marker files in the workspace dir:
#   - worker.pid  — written once at main() boot
#   - scout.ts    — touched after every scout cycle
#
# Independent of PTY byte flow so the watchdog can detect a silent worker
# crash even if Claude Code is chatty.

_WORKSPACE_DIR = Path(
    os.environ.get("APPLYLOOP_WORKSPACE")
    or os.path.expanduser("~/.autoapply/workspace")
)


def _write_worker_pid() -> None:
    try:
        _WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
        (_WORKSPACE_DIR / "worker.pid").write_text(
            f"{os.getpid()}\n{int(time.time() * 1000)}\n"
        )
    except Exception as e:
        logger.debug(f"Failed to write worker.pid: {e}")


def _touch_scout_heartbeat() -> None:
    try:
        _WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
        (_WORKSPACE_DIR / "scout.ts").write_text(f"{int(time.time() * 1000)}\n")
    except Exception as e:
        logger.debug(f"Failed to touch scout.ts: {e}")


def _prune_stale_queue_locally() -> None:
    """Delete queue rows older than QUEUE_STALE_HOURS from the local
    applications.db. Prevents the apply loop from wasting attempts on
    expired job listings. Best-effort — SQLite errors are silently
    ignored so a transient DB issue doesn't crash the worker loop.
    """
    import sqlite3
    from datetime import datetime, timedelta, timezone
    db_path = os.environ.get(
        "APPLYLOOP_DB", os.path.expanduser("~/.autoapply/workspace/applications.db")
    )
    if not os.path.exists(db_path):
        return
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=QUEUE_STALE_HOURS)).isoformat()
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        try:
            cur = conn.execute(
                "DELETE FROM applications WHERE status='queued' AND scouted_at < ?",
                (cutoff,),
            )
            deleted = cur.rowcount
            conn.commit()
            if deleted:
                logger.info(f"Pruned {deleted} stale queue row(s) older than {QUEUE_STALE_HOURS}h")
        finally:
            conn.close()
    except Exception as e:
        logger.debug(f"Queue prune failed (non-fatal): {e}")


def _read_user_id_from_profile_json() -> str | None:
    """Fallback path if APPLYLOOP_USER_ID isn't in env yet. Reads
    ~/.applyloop/profile.json which install.sh writes at activation.
    Returns None if the file doesn't exist or doesn't have a user_id.
    """
    import json
    candidates = [
        os.environ.get("APPLYLOOP_PROFILE"),
        os.path.expanduser("~/.applyloop/profile.json"),
    ]
    for path in candidates:
        if not path:
            continue
        try:
            with open(path) as f:
                data = json.load(f)
            uid = data.get("user_id") or data.get("id")
            if uid:
                return str(uid)
        except Exception:
            continue
    return None


def restart_browser_gateway() -> bool:
    """Restart OpenClaw browser gateway after a timeout/crash."""
    try:
        subprocess.run("openclaw gateway restart", shell=True, timeout=15, capture_output=True)
        time.sleep(3)
        r = subprocess.run("openclaw gateway status", shell=True, timeout=5, capture_output=True, text=True)
        if "running" in r.stdout.lower():
            logger.info("Browser gateway restarted successfully")
            return True
    except Exception as e:
        logger.error(f"Failed to restart browser gateway: {e}")
    return False


INSTALL_DIR = os.environ.get("INSTALL_DIR", os.environ.get("APPLYLOOP_HOME", os.path.expanduser("~/.applyloop")))
APP_URL = os.environ.get("NEXT_PUBLIC_APP_URL", "https://applyloop.vercel.app")
_last_update_date: str = ""  # tracks which date we last checked for updates


def check_and_pull_updates() -> bool:
    """Check for updates on first run of each new day. Returns True if updated."""
    global _last_update_date
    today = date.today().isoformat()

    if _last_update_date == today:
        return False  # already checked today

    _last_update_date = today
    logger.info(f"Daily update check ({today})...")

    # 1. Check the API for new version
    try:
        import httpx
        resp = httpx.get(f"{APP_URL}/api/updates/check", timeout=10)
        if resp.status_code != 200:
            logger.warning(f"Update check failed: HTTP {resp.status_code}")
            return False
        info = resp.json()
        logger.info(f"Remote version: {info.get('version')}, migration_needed: {info.get('migration_needed')}")
        changes = info.get("changes", [])
        if changes:
            logger.info(f"Changes: {', '.join(changes)}")
    except Exception as e:
        logger.warning(f"Update check failed: {e}")
        return False

    # 2. Git pull latest code
    try:
        result = subprocess.run(
            ["git", "pull", "--ff-only", "origin", "main"],
            cwd=INSTALL_DIR, capture_output=True, text=True, timeout=30,
        )
        if "Already up to date" in result.stdout:
            logger.info("Code is up to date")
            return False

        logger.info(f"Pulled updates: {result.stdout.strip()}")
    except Exception as e:
        logger.warning(f"Git pull failed: {e}")
        return False

    # 3. Update pip deps if requirements.txt changed
    try:
        req_file = os.path.join(INSTALL_DIR, "packages", "worker", "requirements.txt")
        if os.path.exists(req_file):
            subprocess.run(
                ["pip", "install", "-q", "-r", req_file],
                capture_output=True, timeout=60,
            )
            logger.info("Pip dependencies updated")
    except Exception as e:
        logger.warning(f"Pip update failed (non-fatal): {e}")

    # 4. Run migrations if needed
    if info.get("migration_needed"):
        try:
            migration_script = os.path.join(INSTALL_DIR, "packages", "web", "public", "setup", "run-migration.py")
            if os.path.exists(migration_script):
                subprocess.run(
                    ["python3", migration_script],
                    cwd=INSTALL_DIR, capture_output=True, timeout=30,
                )
                logger.info("Migrations applied")
        except Exception as e:
            logger.warning(f"Migration failed (non-fatal): {e}")

    # 5. Reload learnings + answer-key (they may have changed)
    logger.info("Update complete — new code/learnings active on next cycle")
    return True


def main():
    global running
    logger.info(f"Worker {WORKER_ID} starting...")

    # Load THIS tenant's config before anything else. No "system" fallback —
    # if the user hasn't finished setup, fail loud so they see the error in
    # the chat UI + Telegram and fix their profile. Silent fallback to admin
    # defaults is the exact bug Part 2 of the redesign exists to kill.
    user_id = (
        os.environ.get("APPLYLOOP_USER_ID")
        or _read_user_id_from_profile_json()
    )
    if not user_id:
        logger.error(
            "No APPLYLOOP_USER_ID in env and no user_id in ~/.applyloop/profile.json. "
            "The worker cannot run tenant-agnostic. Re-run the installer or "
            "set APPLYLOOP_USER_ID manually."
        )
        return

    try:
        tenant = TenantConfig.load(user_id)
    except TenantConfigIncompleteError as e:
        logger.error(f"Tenant config incomplete for {user_id[:8]}: {e}")
        logger.error(
            "Worker refuses to start with an incomplete tenant. Finish setup "
            "at https://applyloop.vercel.app/dashboard/settings and re-run."
        )
        update_heartbeat(user_id, "awaiting_setup", f"missing: {', '.join(e.missing)}")
        return
    except WorkerAuthError as e:
        logger.error(f"Worker token rejected — cannot load tenant: {e}")
        return
    except Exception as e:
        logger.exception(f"Failed to load tenant config: {e}")
        return

    logger.info(f"Tenant loaded: {tenant.profile_summary_hint()}")
    _write_worker_pid()

    global_template = load_global_template()
    hourly_count = 0
    hour_start = time.time()
    consecutive_timeouts = 0
    idle_backoff = POLL_INTERVAL  # Exponential backoff when queue is empty
    MAX_IDLE_BACKOFF = 300  # Cap at 5 minutes

    # Daily update check — runs on first execution of each new day
    check_and_pull_updates()

    # Start the per-tenant scout loop.
    scout_thread = threading.Thread(
        target=scout_loop, args=(tenant,), daemon=True, name="scout-loop"
    )
    scout_thread.start()
    logger.info(
        f"Scout loop started for {tenant.user_id[:8]} "
        f"(interval={SCOUT_INTERVAL_MINUTES}m, {len(REGISTERED_SOURCES)} sources)"
    )

    while running:
        # Daily update check — on first loop of each new day, pull latest code/learnings
        if check_and_pull_updates():
            global_template = load_global_template()  # reload after update

        # Reset hourly counter
        if time.time() - hour_start > 3600:
            hourly_count = 0
            hour_start = time.time()

        if hourly_count >= MAX_SYSTEM_APPS_PER_HOUR:
            logger.info("Hourly system limit reached, sleeping...")
            time.sleep(60)
            continue

        # Prune stale queue entries (>24h old) at the start of each apply
        # iteration. Job listings expire fast — better to drop old ones
        # than waste an application attempt on a closed posting.
        _prune_stale_queue_locally()

        try:
            job = claim_next_job(WORKER_ID)
        except WorkerAuthError as e:
            logger.error(f"Authentication failed — exiting worker loop: {e}")
            running = False
            break
        if not job:
            time.sleep(idle_backoff)
            # Exponential backoff: 10s → 20s → 40s → 80s → 160s → 300s (cap)
            idle_backoff = min(idle_backoff * 2, MAX_IDLE_BACKOFF)
            continue

        # Job found — reset backoff
        idle_backoff = POLL_INTERVAL

        user_id = job['user_id']
        company = job.get('company', '')
        apply_url = job.get('apply_url', '')
        logger.info(f"Processing job {job['id']} for user {user_id}: {company}")
        update_heartbeat(user_id, "applying", f"{company} — {job.get('title', '')}")
        # Sync to local SQLite so desktop Kanban shows "Applying" column
        update_local_status(job, 'applying')

        # Pre-flight checks: blocked URL, paused/blocked company
        if is_blocked_url(apply_url):
            logger.info(f"Skipping blocked aggregator URL: {apply_url}")
            update_queue_status(job['id'], 'cancelled', error='blocked aggregator domain')
            update_local_status(job, 'skipped', 'blocked aggregator domain')
            continue

        if is_blocked_company(company, tenant=tenant):
            logger.info(f"Skipping blocked company: {company}")
            update_queue_status(job['id'], 'cancelled', error='blocked company (defense/clearance)')
            update_local_status(job, 'skipped', 'blocked company')
            continue

        # Staffing agency check
        company_lower = (company or "").lower().strip()
        if any(s in company_lower for s in BLOCKED_STAFFING):
            logger.info(f"Skipping staffing agency: {company}")
            update_queue_status(job['id'], 'cancelled', error='staffing agency')
            update_local_status(job, 'skipped', 'staffing agency')
            continue

        # Company rate limit (max 3 per rolling 7 days)
        if not check_company_rate(user_id, company):
            logger.info(f"Company rate limit reached for {company}, skipping")
            update_queue_status(job['id'], 'cancelled', error='company rate limit (5/30d)')
            update_local_status(job, 'skipped', 'company rate limit')
            continue

        if is_paused_company(company):
            pause_until = COMPANY_PAUSES.get(company.lower().strip())
            logger.info(f"Skipping paused company {company} (until {pause_until})")
            update_queue_status(job['id'], 'pending', error=f'company paused until {pause_until}')
            continue

        # Check daily limit
        if not check_daily_limit(user_id):
            logger.info(f"User {user_id} daily limit reached, skipping")
            update_queue_status(job['id'], 'pending')  # put back
            time.sleep(5)
            continue

        # ── Pre-flight: profile, preferences, resume ──────────────────
        #
        # Before claiming expensive work, verify the user has the minimum
        # data the appliers need. Any failure pushes the job BACK to
        # 'pending' (not failed) + heartbeats the specific missing piece
        # + sleeps 120s so we don't spin. When the user completes the
        # missing step in the desktop Settings UI, the next cycle picks
        # the job right back up.
        #
        # v1.0.3 only checked resume. v1.0.4 also checks profile fields
        # + target_titles — matches packages/desktop/server/preflight.py
        # so the desktop wizard, lifespan PTY guard, and worker all
        # enforce the same "setup done" rules.

        # Profile: first_name + last_name + email must exist
        try:
            preflight_profile = load_user_profile(user_id) or {}
        except WorkerAuthError:
            raise
        except Exception as e:
            logger.debug(f"Profile preflight load failed: {e}")
            preflight_profile = {}
        missing_profile_fields = [
            f for f in ("first_name", "last_name", "email")
            if not (preflight_profile.get(f) or "").strip()
        ]
        if missing_profile_fields:
            logger.info(
                f"User {user_id} profile incomplete "
                f"(missing {', '.join(missing_profile_fields)}) — "
                f"job {job['id']} returned to queue, backing off 120s"
            )
            update_queue_status(
                job['id'], 'pending',
                error=f"awaiting_profile ({', '.join(missing_profile_fields)})",
            )
            try:
                update_local_status(job, 'queued', 'awaiting profile completion')
            except Exception:
                pass
            update_heartbeat(
                user_id, "awaiting_profile",
                f"Profile missing: {', '.join(missing_profile_fields)}",
            )
            time.sleep(120)
            continue

        # Preferences: target_titles must have at least one entry
        try:
            preflight_prefs = fetch_user_job_preferences(user_id) or {}
        except WorkerAuthError:
            raise
        except Exception as e:
            logger.debug(f"Preferences preflight load failed: {e}")
            preflight_prefs = {}
        if not (preflight_prefs.get("target_titles") or []):
            logger.info(
                f"User {user_id} has no target_titles — "
                f"job {job['id']} returned to queue, backing off 120s"
            )
            update_queue_status(
                job['id'], 'pending', error='awaiting_preferences',
            )
            try:
                update_local_status(job, 'queued', 'awaiting preferences')
            except Exception:
                pass
            update_heartbeat(
                user_id, "awaiting_preferences",
                "No target roles set — configure via Settings → Preferences",
            )
            time.sleep(120)
            continue

        # Resume: probe download_resume. Wave 3 fix preserved.
        try:
            resume_path = download_resume(user_id, job.get('title'))
        except WorkerAuthError:
            raise
        except Exception as e:
            msg = str(e).lower()
            if "no resume" in msg or "resume not found" in msg:
                logger.info(
                    f"User {user_id} has no resume — job {job['id']} "
                    f"returned to queue, backing off 120s"
                )
                update_queue_status(
                    job['id'], 'pending',
                    error='awaiting_resume_upload',
                )
                try:
                    update_local_status(job, 'queued', 'awaiting resume upload')
                except Exception:
                    pass
                update_heartbeat(
                    user_id, "awaiting_resume",
                    "No resume on file — upload via Settings → Resume",
                )
                time.sleep(120)
                continue
            # Other download errors (network, etc.) — fail this job only,
            # keep the worker loop alive.
            logger.warning(f"Resume download failed for job {job['id']}: {e}")
            update_queue_status(job['id'], 'failed', error=f"resume download: {e}")
            update_local_status(job, 'failed', f"resume download: {e}")
            continue

        try:
            profile = load_user_profile(user_id)
            answer_key = build_answer_key(profile, global_template)

            # Resolve real ATS from aggregator URLs (Indeed/Himalayas/LinkedIn
            # jobs link to real ATS pages — detect which one from the URL)
            raw_ats = job.get('ats', 'greenhouse')
            ats = _resolve_ats_from_url(apply_url, raw_ats)
            if ats != raw_ats:
                logger.info(f"ATS resolved: {raw_ats} → {ats} (from URL)")
            cooldown = ATS_COOLDOWNS.get(ats, APPLY_COOLDOWN)

            # Get the right applier. If no coded applier exists for this ATS,
            # skip it in the worker — Claude Code handles unknown ATS via the
            # universal approach (OpenClaw snapshot → intelligent fill → submit)
            # as described in SOUL.md STEP 4.
            ApplierClass = APPLIERS.get(ats)
            if not ApplierClass:
                logger.info(
                    f"No coded applier for ATS '{ats}' — marking for Claude Code "
                    f"universal fill (job {job['id']}: {company})"
                )
                # Don't fail the job — mark it as 'queued' so Claude Code can
                # pick it up via the terminal and apply using OpenClaw directly.
                # The nudge loop will surface these jobs to Claude.
                update_queue_status(job['id'], 'pending', error=f'needs_universal_fill:{ats}')
                update_local_status(job, 'queued', f'Needs Claude Code universal fill ({ats})')
                continue

            try:
                applier = ApplierClass(profile, answer_key, resume_path)
            except MissingResumeError as e:
                logger.error(f"Resume missing for job {job['id']}: {e}")
                update_queue_status(job['id'], 'failed', error=f"resume file missing: {e}")
                update_local_status(job, 'failed', f"resume missing: {e}")
                log_application(user_id, job, {'status': 'failed', 'error': f"resume missing: {e}"})
                update_heartbeat(user_id, "failed", f"{company} — resume missing")
                continue
            result = applier.apply(apply_url)

            if result.success:
                consecutive_timeouts = 0
                screenshot_url = None
                if result.screenshot:
                    screenshot_url = upload_screenshot(user_id, result.screenshot)
                update_queue_status(job['id'], 'submitted')
                log_application(user_id, job, {'status': 'submitted', 'screenshot_url': screenshot_url})
                send_application_result(user_id, job, result.screenshot)
                hourly_count += 1
                update_heartbeat(user_id, "applied", f"{company} — {job.get('title', '')}")
            else:
                # Browser timeout recovery
                if result.error and "timeout" in result.error.lower():
                    consecutive_timeouts += 1
                    if consecutive_timeouts >= 3:
                        logger.warning("3 consecutive timeouts — restarting browser gateway")
                        restart_browser_gateway()
                        consecutive_timeouts = 0
                else:
                    consecutive_timeouts = 0

                if result.retriable and job.get('attempts', 0) < job.get('max_attempts', 3):
                    update_queue_status(job['id'], 'pending', error=result.error)
                else:
                    update_queue_status(job['id'], 'failed', error=result.error)
                    log_application(user_id, job, {'status': 'failed', 'error': result.error})
                    send_failure(user_id, company, job.get('title', ''), result.error)
                    update_heartbeat(user_id, "failed", f"{company} — {result.error[:80]}")

            time.sleep(cooldown)
            update_heartbeat(user_id, "sleep", f"cooldown {cooldown}s")

        except Exception as e:
            logger.exception(f"Error processing job {job['id']}")
            update_queue_status(job['id'], 'failed', error=str(e))
            time.sleep(10)


if __name__ == '__main__':
    main()
