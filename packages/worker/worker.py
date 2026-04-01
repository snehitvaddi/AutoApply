import os
import time
import signal
import logging
import subprocess
import threading
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse
import re
from config import (
    WORKER_ID, POLL_INTERVAL, APPLY_COOLDOWN, ATS_COOLDOWNS,
    MAX_SYSTEM_APPS_PER_HOUR, BLOCKED_DOMAINS, COMPANY_PAUSES, BLOCKED_COMPANIES,
    BLOCKED_STAFFING, SCOUT_INTERVAL_MINUTES, MAX_COMPANY_APPS_PER_30_DAYS,
    SKIP_LEVELS, SKIP_COMPANIES_SENIOR, AI_KEYWORDS, AI_KEYWORDS_SHORT,
    SKIP_LOCATIONS, SKIP_ROLE_KEYWORDS,
    ASHBY_SLUGS, GREENHOUSE_NO_RECAPTCHA, GREENHOUSE_RECAPTCHA,
)
from db import (
    claim_next_job, load_user_profile, update_queue_status, log_application,
    check_daily_limit, get_answer_key, download_resume, upload_screenshot,
    fetch_user_job_preferences, enqueue_discovered_jobs, update_heartbeat as db_heartbeat,
    check_company_rate as db_check_company_rate,
)
from notifier import send_application_result, send_failure
from knowledge import build_answer_key, load_global_template
from scanner.linkedin import scan_linkedin
from scanner.indeed import scan_indeed
from scanner.himalayas import scan_himalayas
from scanner.jsearch import scan_jsearch
from applier.greenhouse import GreenhouseApplier
from applier.lever import LeverApplier
from applier.ashby import AshbyApplier
from applier.smartrecruiters import SmartRecruitersApplier

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(message)s')
logger = logging.getLogger(f'worker-{WORKER_ID}')

# In-memory dedup cache to avoid repeated DB queries for the same URL within a day
_seen_urls: set = set()
_seen_urls_date: str = ""

APPLIERS = {
    'greenhouse': GreenhouseApplier,
    'lever': LeverApplier,
    'ashby': AshbyApplier,
    'smartrecruiters': SmartRecruitersApplier,
}

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


def is_blocked_company(company: str) -> bool:
    """Check if the company is permanently blocked (defense/clearance)."""
    company_lower = (company or "").lower().strip()
    return any(blocked in company_lower for blocked in BLOCKED_COMPANIES)


# ─── Company Rate Limiting (via API proxy) ─────────────────────────────────

def check_company_rate(user_id: str, company: str) -> bool:
    """Return True if user can still apply to this company (< 5 in 30 days)."""
    return db_check_company_rate(user_id, company)


# ─── Heartbeat (via API proxy) ──────────────────────────────────────────────

def update_heartbeat(user_id: str, action: str, details: str = ""):
    """Update worker heartbeat via API."""
    db_heartbeat(user_id, action, details)


# ─── Job Filter (title/company/location rules) ──────────────────────────────

def passes_filter(title: str, company: str, location: str, user_prefs: dict | None = None) -> bool:
    """Check if a job passes all filter rules (AI/ML, level, company, location)."""
    tl = title.lower()
    cl = company.lower()
    ll = (location or "").lower()

    # GLOBAL SAFETY — always enforced
    if any(sc in cl for sc in BLOCKED_COMPANIES):
        return False
    if any(sc in cl for sc in BLOCKED_STAFFING):
        return False

    # Skip irrelevant role types (sales, legal, marketing, recruiter, etc.)
    if any(rk in tl for rk in SKIP_ROLE_KEYWORDS):
        return False

    # PER-USER or DEFAULT keyword filter (with word-boundary for short keywords)
    keywords = AI_KEYWORDS  # default
    if user_prefs and user_prefs.get("target_keywords"):
        keywords = [k.lower() for k in user_prefs["target_keywords"]]
    elif user_prefs and user_prefs.get("target_titles"):
        keywords = [t.lower() for t in user_prefs["target_titles"]]

    def _kw_matches(kw: str, text: str) -> bool:
        if kw in AI_KEYWORDS_SHORT:
            return bool(re.search(rf'\b{re.escape(kw)}\b', text))
        return kw in text

    if not any(_kw_matches(kw, tl) for kw in keywords):
        return False

    # PER-USER or DEFAULT level skip
    skip_levels = SKIP_LEVELS  # default
    if user_prefs and user_prefs.get("excluded_titles"):
        skip_levels = [t.lower() for t in user_prefs["excluded_titles"]]
    if any(lvl in tl for lvl in skip_levels):
        return False

    # PER-USER excluded companies (in addition to global)
    if user_prefs and user_prefs.get("excluded_companies"):
        if any(ec.lower() in cl for ec in user_prefs["excluded_companies"]):
            return False

    # PER-USER or DEFAULT location filter
    if user_prefs and user_prefs.get("remote_only") and "remote" not in ll:
        return False
    if user_prefs and user_prefs.get("preferred_locations"):
        # Only pass if location matches one of preferred
        locs = [loc.lower() for loc in user_prefs["preferred_locations"]]
        if ll and not any(loc in ll for loc in locs):
            return False
    else:
        # Default: skip non-US
        if ll and any(loc in ll for loc in SKIP_LOCATIONS):
            return False

    # Senior at FAANG (keep as global rule)
    if "senior" in tl and any(f in cl for f in SKIP_COMPANIES_SENIOR):
        return False

    return True


# ─── Freshness Filter ────────────────────────────────────────────────────────

def _is_fresh_24h(date_value) -> bool:
    """Check if a date is within the last 24 hours. Handles multiple formats."""
    if not date_value:
        return True  # no date = assume fresh (let other filters handle it)

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)

    try:
        if isinstance(date_value, (int, float)):
            # Unix epoch (seconds or milliseconds)
            ts = date_value if date_value < 1e12 else date_value / 1000
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            return dt >= cutoff

        s = str(date_value).strip()
        # ISO 8601 (2026-03-30T12:00:00Z or 2026-03-30T12:00:00.000Z)
        if "T" in s:
            s = s.replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt >= cutoff

        # YYYY-MM-DD
        if len(s) == 10 and s[4] == "-":
            dt = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return dt >= cutoff

    except Exception:
        pass

    return True  # can't parse = assume fresh


# ─── Scout Functions ─────────────────────────────────────────────────────────

def scout_ashby_boards(user_prefs: dict | None = None) -> list[dict]:
    """Scout Ashby API for AI/ML jobs across all known boards."""
    import httpx
    jobs = []
    with httpx.Client(timeout=10, follow_redirects=True) as client:
        for slug in ASHBY_SLUGS:
            try:
                resp = client.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
                if resp.status_code != 200:
                    continue
                for job in resp.json().get("jobs", []):
                    # Freshness: only jobs published in last 24h
                    if not _is_fresh_24h(job.get("publishedAt")):
                        continue
                    title = job.get("title", "")
                    loc = job.get("location", "")
                    if isinstance(loc, dict):
                        loc = loc.get("name", "")
                    if not passes_filter(title, slug, loc, user_prefs):
                        continue
                    apply_url = job.get("applicationUrl") or f"https://jobs.ashbyhq.com/{slug}/application?jobId={job['id']}"
                    jobs.append({
                        "title": title, "company": slug, "location": loc,
                        "apply_url": apply_url, "external_id": job.get("id", ""),
                        "ats": "ashby",
                    })
            except Exception:
                pass
            time.sleep(0.5)
    return jobs


def scout_greenhouse_boards(user_prefs: dict | None = None) -> list[dict]:
    """Scout Greenhouse API for AI/ML jobs (all boards — reCAPTCHA check happens at apply time)."""
    import httpx
    jobs = []
    with httpx.Client(timeout=10, follow_redirects=True) as client:
        for slug in GREENHOUSE_NO_RECAPTCHA + GREENHOUSE_RECAPTCHA:
            try:
                resp = client.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
                if resp.status_code != 200:
                    continue
                for job in resp.json().get("jobs", []):
                    # Freshness: only jobs updated in last 24h
                    if not _is_fresh_24h(job.get("updated_at")):
                        continue
                    title = job.get("title", "")
                    loc = job.get("location", {})
                    if isinstance(loc, dict):
                        loc = loc.get("name", "")
                    if not passes_filter(title, slug, loc, user_prefs):
                        continue
                    job_id = job.get("id", "")
                    jobs.append({
                        "title": title, "company": slug, "location": loc,
                        "apply_url": f"https://job-boards.greenhouse.io/embed/job_app?for={slug}&token={job_id}",
                        "external_id": str(job_id), "ats": "greenhouse",
                    })
            except Exception:
                pass
            time.sleep(0.5)
    return jobs


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


def run_scout_cycle(user_id: str):
    """Run one scout → filter → enqueue cycle for a user.

    Scouting sources are run in priority order:
      HIGH:   Ashby API, Greenhouse API (reliable, high submit rate)
      MEDIUM: Indeed, Himalayas (good volume, no auth)
      LOW:    JSearch (optional, quota limited), LinkedIn public (limited results)

    Higher priority sources are always run. Lower priority sources are
    randomly included to spread load and avoid rate limits.
    """
    import random

    update_heartbeat(user_id, "scouting")
    user_prefs = fetch_user_job_preferences(user_id) if user_id != "system" else None
    search_queries = (user_prefs or {}).get("target_titles") or ["AI Engineer", "ML Engineer", "Data Scientist"]

    counts = {}

    # ── HIGH PRIORITY (always run) ─────────────────────────────────────────
    logger.info("Scout: HIGH priority — Ashby + Greenhouse...")

    ashby_jobs = scout_ashby_boards(user_prefs)
    counts["Ashby"] = len(ashby_jobs)

    gh_jobs = scout_greenhouse_boards(user_prefs)
    counts["Greenhouse"] = len(gh_jobs)

    # ── MEDIUM PRIORITY (run 80% of the time) ──────────────────────────────
    indeed_jobs = []
    himalayas_jobs = []

    if random.random() < 0.8:
        logger.info("Scout: MEDIUM priority — Indeed...")
        try:
            indeed_jobs = scan_indeed(search_queries)
        except Exception as e:
            logger.warning(f"Indeed scout failed: {e}")
    counts["Indeed"] = len(indeed_jobs)

    if random.random() < 0.8:
        logger.info("Scout: MEDIUM priority — Himalayas...")
        try:
            himalayas_jobs = scan_himalayas(search_queries)
        except Exception as e:
            logger.warning(f"Himalayas scout failed: {e}")
    counts["Himalayas"] = len(himalayas_jobs)

    # ── LOW PRIORITY (run 40% of the time) ─────────────────────────────────
    jsearch_jobs = []
    linkedin_jobs = []

    if random.random() < 0.4:
        logger.info("Scout: LOW priority — JSearch...")
        try:
            jsearch_jobs = scan_jsearch(search_queries)
        except Exception as e:
            logger.warning(f"JSearch scout failed: {e}")
    counts["JSearch"] = len(jsearch_jobs)

    if random.random() < 0.4:
        logger.info("Scout: LOW priority — LinkedIn public...")
        try:
            linkedin_jobs = scan_linkedin(search_queries)
        except Exception as e:
            logger.warning(f"LinkedIn scout failed: {e}")
    counts["LinkedIn"] = len(linkedin_jobs)

    # ── Filter + enqueue ───────────────────────────────────────────────────
    # Ashby/Greenhouse are pre-filtered in their scout functions.
    # Others need filtering here.
    filtered_extra = [j for j in linkedin_jobs + indeed_jobs + himalayas_jobs + jsearch_jobs
                      if passes_filter(j["title"], j["company"], j["location"], user_prefs)]

    all_jobs = ashby_jobs + gh_jobs + filtered_extra

    summary = ", ".join(f"{v} {k}" for k, v in counts.items() if v > 0)
    logger.info(f"Scout: {summary} = {len(all_jobs)} total (after filter)")

    if not all_jobs:
        update_heartbeat(user_id, "idle", "No new jobs found")
        return 0

    enqueued = _enqueue_discovered_jobs(user_id, all_jobs)
    logger.info(f"Scout complete: {enqueued} new jobs enqueued (from {len(all_jobs)} raw)")
    update_heartbeat(user_id, "scouted", f"{enqueued} enqueued from {summary}")
    return enqueued


def scout_loop(user_id: str):
    """Background thread: runs scout cycle every SCOUT_INTERVAL_MINUTES."""
    while running:
        try:
            run_scout_cycle(user_id)
        except Exception as e:
            logger.exception(f"Scout cycle error: {e}")
            update_heartbeat(user_id, "error", str(e))

        # Sleep in small increments so we can respond to shutdown
        for _ in range(SCOUT_INTERVAL_MINUTES * 60):
            if not running:
                return
            time.sleep(1)


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


INSTALL_DIR = os.environ.get("INSTALL_DIR", os.path.expanduser("~/autoapply"))
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
    logger.info(f"Worker {WORKER_ID} starting...")
    global_template = load_global_template()
    hourly_count = 0
    hour_start = time.time()
    consecutive_timeouts = 0
    idle_backoff = POLL_INTERVAL  # Exponential backoff when queue is empty
    MAX_IDLE_BACKOFF = 300  # Cap at 5 minutes

    # Daily update check — runs on first execution of each new day
    check_and_pull_updates()

    # Start the scout → filter → enqueue background loop.
    # Uses a system-level user_id; per-user scouts run when jobs are claimed.
    system_user_id = os.environ.get("SYSTEM_USER_ID", "system")
    scout_thread = threading.Thread(
        target=scout_loop, args=(system_user_id,), daemon=True, name="scout-loop"
    )
    scout_thread.start()
    logger.info(f"Scout loop started (interval={SCOUT_INTERVAL_MINUTES}m)")

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

        job = claim_next_job(WORKER_ID)
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

        # Pre-flight checks: blocked URL, paused/blocked company
        if is_blocked_url(apply_url):
            logger.info(f"Skipping blocked aggregator URL: {apply_url}")
            update_queue_status(job['id'], 'cancelled', error='blocked aggregator domain')
            continue

        if is_blocked_company(company):
            logger.info(f"Skipping blocked company: {company}")
            update_queue_status(job['id'], 'cancelled', error='blocked company (defense/clearance)')
            continue

        # Staffing agency check
        company_lower = (company or "").lower().strip()
        if any(s in company_lower for s in BLOCKED_STAFFING):
            logger.info(f"Skipping staffing agency: {company}")
            update_queue_status(job['id'], 'cancelled', error='staffing agency')
            continue

        # Company rate limit (max 5 per 30 days)
        if not check_company_rate(user_id, company):
            logger.info(f"Company rate limit reached for {company}, skipping")
            update_queue_status(job['id'], 'cancelled', error='company rate limit (5/30d)')
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

        try:
            profile = load_user_profile(user_id)
            answer_key = build_answer_key(profile, global_template)
            resume_path = download_resume(user_id, job.get('title'))

            # Get ATS-specific cooldown
            ats = job.get('ats', 'greenhouse')
            cooldown = ATS_COOLDOWNS.get(ats, APPLY_COOLDOWN)

            # Get the right applier
            ApplierClass = APPLIERS.get(ats)
            if not ApplierClass:
                update_queue_status(job['id'], 'failed', error=f'Unknown ATS: {ats}')
                continue

            applier = ApplierClass(profile, answer_key, resume_path)
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
