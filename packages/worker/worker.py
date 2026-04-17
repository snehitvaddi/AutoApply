from __future__ import annotations
import json
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
    is_staffing_agency, SCOUT_INTERVAL_MINUTES,
    MAX_COMPANY_APPS_PER_7_DAYS, QUEUE_STALE_HOURS, APPLY_STALE_MINUTES,
)
from tenant import (
    TenantConfig, TenantConfigIncompleteError,
    DEFAULT_SECURITY_CLEARANCE_COMPANIES,
)
from scout import REGISTERED_SOURCES
from db import (
    claim_next_job, load_user_profile, update_queue_status, log_application,
    fetch_next_plan, report_plan_outcome,
    check_daily_limit, count_profile_applied_today,
    get_answer_key, download_resume, download_resume_by_url, upload_screenshot,
    fetch_user_job_preferences, enqueue_discovered_jobs, update_heartbeat as db_heartbeat,
    check_company_rate as db_check_company_rate,
    update_local_status, cleanup_stale_queued_shadows,
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


# SIGTERM isn't defined on Windows (only SIGINT/SIGBREAK are reliable).
# Guard the registration so the worker boots cross-platform.
for _sig_name in ("SIGTERM", "SIGINT"):
    _sig = getattr(signal, _sig_name, None)
    if _sig is not None:
        try:
            signal.signal(_sig, shutdown)
        except (ValueError, OSError):
            pass


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


# ── Title-scout → ATS slug expansion ─────────────────────────────────────
#
# When a title-based source returns a hit at "Acme Corp," try to resolve
# Acme to an Ashby/Greenhouse/Lever slug so the NEXT scout cycle hits
# Acme's full board directly instead of waiting to stumble on another
# LinkedIn post. Discovered slugs are persisted to user_job_preferences
# via the existing update_preferences proxy action and picked up by
# TenantConfig's 5-minute reload thread.
#
# Probe budget per cycle — resolver is network-bound and we never want
# it to block scout progress. Cap at 8 unique new companies per cycle.
_ATS_EXPAND_PROBE_CAP = 8
# Title-based sources we want to enrich. Company-based sources already
# know their slug, so there's nothing to resolve.
_TITLE_SOURCES = {"linkedin", "himalayas", "indeed", "linkedin_public"}
# Hard cap on the persisted slug set so nothing runaway-grows.
_BOARDS_LIST_CAP = 500


def _expand_tenant_boards(tenant: "TenantConfig", jobs: list[dict]) -> None:
    """For every unique new company seen via a title-based source, probe
    Ashby/Greenhouse/Lever and append any resolved slugs to the active
    tenant's board lists. Persisted via update_preferences proxy action.

    Best-effort: any network error, missing helper, or proxy 4xx is
    swallowed — this is enrichment, not a correctness-critical path.
    """
    from scout.ats_resolver import try_resolve_ats_slug

    known_ashby = {s.lower() for s in (getattr(tenant, "ashby_boards", None) or [])}
    known_gh = {s.lower() for s in (getattr(tenant, "greenhouse_boards", None) or [])}
    # lever_boards column doesn't exist in user_job_preferences yet —
    # lever slugs are still resolved but only logged, not persisted.

    seen_companies: set[str] = set()
    to_probe: list[str] = []
    for j in jobs:
        src = (j.get("source") or j.get("ats") or "").lower()
        if src not in _TITLE_SOURCES:
            continue
        company = (j.get("company") or "").strip()
        if not company or company.lower() in seen_companies:
            continue
        seen_companies.add(company.lower())
        to_probe.append(company)
        if len(to_probe) >= _ATS_EXPAND_PROBE_CAP:
            break

    if not to_probe:
        return

    new_ashby: list[str] = []
    new_gh: list[str] = []
    lever_discoveries: list[str] = []
    for company in to_probe:
        hit = try_resolve_ats_slug(company)
        if not hit:
            continue
        slug = hit["slug"].lower()
        platform = hit["platform"]
        if platform == "ashby" and slug not in known_ashby:
            known_ashby.add(slug)
            new_ashby.append(hit["slug"])
        elif platform == "greenhouse" and slug not in known_gh:
            known_gh.add(slug)
            new_gh.append(hit["slug"])
        elif platform == "lever":
            # lever_boards isn't persisted (schema gap); log for visibility.
            lever_discoveries.append(hit["slug"])

    if lever_discoveries:
        logger.info(f"lever slugs resolved (not persisted): {lever_discoveries}")
    if not (new_ashby or new_gh):
        return

    def _merge_and_cap(existing: list[str] | None, additions: list[str]) -> list[str]:
        merged = list(existing or []) + additions
        # De-dup preserving order; newest-first cap so long-tail additions
        # survive and ancient entries get pruned.
        seen: set[str] = set()
        deduped: list[str] = []
        for s in reversed(merged):
            key = s.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(s)
        deduped.reverse()
        if len(deduped) > _BOARDS_LIST_CAP:
            deduped = deduped[-_BOARDS_LIST_CAP:]
        return deduped

    payload = {}
    if new_ashby:
        payload["ashby_boards"] = _merge_and_cap(getattr(tenant, "ashby_boards", None), new_ashby)
    if new_gh:
        payload["greenhouse_boards"] = _merge_and_cap(getattr(tenant, "greenhouse_boards", None), new_gh)
    try:
        from db import _api_call  # type: ignore
        _api_call("update_preferences", preferences=payload)
        logger.info(
            "tenant boards expanded: +%d ashby, +%d greenhouse",
            len(new_ashby), len(new_gh),
        )
    except Exception as e:
        logger.debug(f"update_preferences failed during board expansion: {e}")


def _enqueue_discovered_jobs(user_id: str, jobs: list[dict]):
    """Insert discovered jobs via API proxy. Local URL cache for fast dedup.

    Also runs the staffing/consulting filter BEFORE enqueue so the queue
    never gets polluted by body-shops. The apply loop also runs this check
    at claim time (defense-in-depth), but filtering at enqueue saves the
    cloud round-trip and keeps queue counts honest.
    """
    global _seen_urls, _seen_urls_date

    today = date.today().isoformat()
    if _seen_urls_date != today:
        _seen_urls = set()
        _seen_urls_date = today

    # Filter out locally-cached URLs + staffing agencies
    new_jobs = []
    staffing_dropped = 0
    for job in jobs:
        url = job.get("apply_url", "")
        if not url or url in _seen_urls:
            continue
        if is_staffing_agency(job.get("company") or ""):
            staffing_dropped += 1
            continue
        new_jobs.append(job)
        _seen_urls.add(url)

    if staffing_dropped:
        logger.info(f"Filtered {staffing_dropped} staffing/consulting jobs pre-enqueue")

    if not new_jobs:
        return 0

    # Send to API proxy for server-side dedup + enqueue
    return enqueue_discovered_jobs(user_id, new_jobs)


# Style classification for scout sources — the cloud planner uses this
# to route between "company-based" (hit known ATS slugs) and "title-based"
# (search aggregators). If a new source is added to scout/, add it here
# or it defaults to the unfiltered pool.
_SCOUT_STYLE = {
    "ashby": "company",
    "greenhouse": "company",
    "lever": "company",
    "indeed": "title",
    "himalayas": "title",
    "linkedin_public": "title",
    "linkedin": "title",
}


def run_scout_cycle(tenant: TenantConfig, style_filter: str | None = None) -> int:
    """Run one scout → filter → enqueue cycle for THIS tenant.

    Iterates REGISTERED_SOURCES from packages/worker/scout/. Each source
    reads its queries from `tenant.search_queries` and filters results via
    `tenant.passes_filter()`. There is no fallback to admin defaults at
    any layer — if tenant has no target_titles, the worker refuses to boot
    at main() time before reaching this function.

    `style_filter` routes the planner's scout_primary / scout_title_based
    actions to the right source subset. When None, runs all sources
    (legacy behavior; used by the pre-planner scout_loop).

    Priority dispatch:
      HIGH:    always run
      MEDIUM:  always run (was 0.8; throughput tuning — 2026-04)
      LOW:     run 80% of cycles (was 0.4)

    Adding a new source only requires appending to scout.REGISTERED_SOURCES.
    """
    update_heartbeat(tenant.user_id, "scouting", tenant.profile_summary_hint())

    all_jobs: list[dict] = []
    counts: dict[str, int] = {}

    for source in REGISTERED_SOURCES:
        if not source.is_enabled_for(tenant):
            continue
        if style_filter is not None:
            source_style = _SCOUT_STYLE.get(source.name, "title")
            if source_style != style_filter:
                continue
        if source.priority == "high" or source.priority == "medium":
            run_it = True
        else:  # "low"
            run_it = random.random() < 0.8
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

    # Tag every job with the best-matching profile bundle (multi-profile).
    # Single-profile users: every job gets default.id. Jobs no bundle
    # accepts fall back to the default so scout behavior is unchanged.
    if tenant.profiles:
        default = tenant.default_profile()
        tagged: list[dict] = []
        for j in all_jobs:
            picked = tenant.pick_profile_for_job(
                j.get("title", ""), j.get("company", ""), j.get("location", "")
            )
            if not picked:
                picked = default
            j["application_profile_id"] = picked.id
            tagged.append(j)
        all_jobs = tagged

    summary = ", ".join(f"{v} {k}" for k, v in counts.items() if v > 0)
    logger.info(f"Scout: {summary} = {len(all_jobs)} total (after per-source filter)")

    raw_count = len(all_jobs)
    if not all_jobs:
        _touch_scout_heartbeat(enqueued=0, raw=0)
        update_heartbeat(tenant.user_id, "idle", "No new jobs matched tenant criteria")
        return 0

    # Expand tenant ATS board set with companies discovered via title-based
    # sources (LinkedIn / Himalayas / Indeed). Each unique new company gets
    # one shot at slug resolution; successful hits are persisted back to
    # user_job_preferences via the existing update_preferences proxy action,
    # and picked up on the next TenantConfig reload (≤5 min). Capped to
    # avoid blowing scout budget on probes.
    try:
        _expand_tenant_boards(tenant, all_jobs)
    except Exception as e:
        logger.debug(f"tenant board expansion skipped: {e}")

    enqueued = _enqueue_discovered_jobs(tenant.user_id, all_jobs)
    _touch_scout_heartbeat(enqueued=enqueued, raw=raw_count)
    logger.info(f"Scout complete: {enqueued} new jobs enqueued (from {raw_count} raw)")
    update_heartbeat(tenant.user_id, "scouted", f"{enqueued} enqueued from {summary}")
    return enqueued


# ── Live tenant reference + reload thread ──────────────────────────────────
#
# The worker used to call TenantConfig.load() exactly once at main() boot
# and hold the frozen dataclass for the process lifetime. That meant a user
# rotating their Gmail app password, creating a new bundle, or changing
# target_titles on the web dashboard would NOT be picked up until worker
# restart — silent staleness that only surfaced as "SMTP failed" with no
# explanation.
#
# Now: `_current_tenant` is a module-level ref that both the scout thread
# and the apply loop read. A background thread refreshes it every
# TENANT_RELOAD_INTERVAL_SECS. Both loops pick up the new tenant at the top
# of their next iteration. TenantConfig is still frozen — we just replace
# the reference atomically.

_current_tenant: TenantConfig | None = None
_tenant_lock = threading.Lock()
TENANT_RELOAD_INTERVAL_SECS = int(os.environ.get("APPLYLOOP_TENANT_RELOAD_SECS", "300"))


def get_current_tenant() -> TenantConfig:
    """Return the most-recently-loaded TenantConfig. Raises if boot hasn't
    loaded one yet — that should never happen post-main()."""
    with _tenant_lock:
        if _current_tenant is None:
            raise RuntimeError("get_current_tenant() before main() loaded one")
        return _current_tenant


def _set_current_tenant(tc: TenantConfig) -> None:
    global _current_tenant
    with _tenant_lock:
        _current_tenant = tc


def tenant_reload_loop(user_id: str) -> None:
    """Background thread: periodically reload TenantConfig so mid-run
    edits (new bundles, rotated Gmail app passwords, new target_titles)
    propagate without a worker restart. Failures are logged but don't
    crash — we keep the last good tenant."""
    while running:
        for _ in range(TENANT_RELOAD_INTERVAL_SECS):
            if not running:
                return
            time.sleep(1)
        try:
            fresh = TenantConfig.load(user_id)
            prev = _current_tenant
            _set_current_tenant(fresh)
            if prev is not None and prev.profiles != fresh.profiles:
                logger.info(
                    f"Tenant reload: bundles changed "
                    f"({len(prev.profiles)} → {len(fresh.profiles)})"
                )
        except TenantConfigIncompleteError as e:
            logger.warning(f"Tenant reload skipped (incomplete): {e}")
        except Exception as e:
            logger.warning(f"Tenant reload failed (keeping previous): {e}")


def scout_loop(_initial_tenant: TenantConfig) -> None:
    """Background thread: runs scout cycle every SCOUT_INTERVAL_MINUTES.
    Reads the live tenant from `_current_tenant` at each cycle so bundle
    additions propagate without worker restart. The initial arg is kept
    only so the thread signature stays backward compatible for callers."""
    while running:
        try:
            tenant = get_current_tenant()
            run_scout_cycle(tenant)
        except Exception as e:
            logger.exception(f"Scout cycle error: {e}")
            try:
                update_heartbeat(get_current_tenant().user_id, "error", str(e))
            except Exception:
                pass

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


def _kill_stale_worker() -> None:
    """Kill any previous worker.py that's still running before we spawn.

    Prevents the overnight failure pattern observed in production: the
    desktop app relaunches (user quit + reopened, crash recovery, etc.)
    and a fresh worker.py spawns while an older one is still alive.
    Multiple workers race `claim_next_job` on the same application_queue
    rows — claims silently fail, heartbeats stomp on each other, and
    apply progress stalls while the bot "looks" running.

    Read the prior PID from worker.pid (if present), probe it with
    os.kill(pid, 0), SIGTERM it, wait up to 5s for graceful exit, then
    SIGKILL. Idempotent: no-op when the file is missing, unreadable, or
    points at a dead PID.
    """
    pid_file = _WORKSPACE_DIR / "worker.pid"
    try:
        raw = pid_file.read_text().strip().split()[0]
        prev_pid = int(raw)
    except (FileNotFoundError, ValueError, IndexError):
        return
    if prev_pid == os.getpid():
        return
    try:
        os.kill(prev_pid, 0)  # probe — raises if dead
    except ProcessLookupError:
        return  # stale file, process already gone
    except PermissionError:
        # PID belongs to another user (rare; shouldn't happen in the
        # single-user desktop app model). Don't try to kill it.
        logger.warning(f"Stale worker.pid={prev_pid} belongs to a different user, leaving alone")
        return

    logger.warning(
        f"Stale worker.pid={prev_pid} is still alive — terminating before spawning new worker"
    )
    try:
        os.kill(prev_pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    # Grace period for graceful exit.
    for _ in range(50):
        time.sleep(0.1)
        try:
            os.kill(prev_pid, 0)
        except ProcessLookupError:
            logger.info(f"Stale worker {prev_pid} exited after SIGTERM")
            return
    # Still alive after 5s — escalate.
    logger.warning(f"Stale worker {prev_pid} didn't exit on SIGTERM, sending SIGKILL")
    try:
        os.kill(prev_pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _touch_scout_heartbeat(enqueued: int = 0, raw: int = 0) -> None:
    """Append a JSON-line scout heartbeat. One line per scout cycle so the
    desktop watchdog can distinguish "scout ran, 0 enqueued" from "scout
    never ran" — both previously collapsed into the same signal.

    Schema: {"ts": <ms>, "enqueued": N, "raw": M}. Older single-number
    scout.ts files are still readable because get_scout_age_minutes()
    (desktop side) parses the LAST line and tolerates both shapes. File
    is trimmed to the last 50 lines to cap disk growth.
    """
    try:
        _WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
        path = _WORKSPACE_DIR / "scout.ts"
        line = json.dumps({"ts": int(time.time() * 1000), "enqueued": int(enqueued), "raw": int(raw)})
        existing: list[str] = []
        try:
            existing = path.read_text().splitlines()
        except FileNotFoundError:
            pass
        existing.append(line)
        if len(existing) > 50:
            existing = existing[-50:]
        path.write_text("\n".join(existing) + "\n")
    except Exception as e:
        logger.debug(f"Failed to write scout.ts: {e}")


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
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=QUEUE_STALE_HOURS)).isoformat()
    stale_apply_cutoff = (now - timedelta(minutes=APPLY_STALE_MINUTES)).isoformat()
    now_iso = now.isoformat()
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        try:
            # Reset rows that crashed mid-apply before deleting expired
            # queued rows — otherwise a stale applying row older than
            # QUEUE_STALE_HOURS would get deleted instead of recovered.
            reset_cur = conn.execute(
                "UPDATE applications SET status='queued', "
                "notes=COALESCE(notes,'') || ' [reset:stale applying]', "
                "updated_at=? "
                "WHERE status='applying' AND updated_at < ?",
                (now_iso, stale_apply_cutoff),
            )
            reset = reset_cur.rowcount
            cur = conn.execute(
                "DELETE FROM applications WHERE status='queued' AND scouted_at < ?",
                (cutoff,),
            )
            deleted = cur.rowcount
            conn.commit()
            if reset:
                logger.warning(
                    f"Reset {reset} stale 'applying' row(s) older than "
                    f"{APPLY_STALE_MINUTES}m — crashed applier or lock race recovered"
                )
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
    _set_current_tenant(tenant)
    _kill_stale_worker()
    _write_worker_pid()

    # One-shot cleanup of orphan 'queued'/'applying' rows left behind by the
    # pre-fix dedup-token bug. Idempotent — a no-op after the first boot
    # once the stale rows are gone.
    try:
        cleanup_stale_queued_shadows()
    except Exception as e:
        logger.debug(f"shadow cleanup skipped: {e}")

    # Start the tenant reload thread — refreshes _current_tenant every
    # TENANT_RELOAD_INTERVAL_SECS so password rotations / bundle edits
    # take effect without worker restart.
    reload_thread = threading.Thread(
        target=tenant_reload_loop, args=(user_id,), daemon=True, name="tenant-reload"
    )
    reload_thread.start()

    global_template = load_global_template()
    hourly_count = 0
    hour_start = time.time()
    consecutive_timeouts = 0
    idle_backoff = POLL_INTERVAL  # Exponential backoff when queue is empty
    MAX_IDLE_BACKOFF = 300  # Cap at 5 minutes

    # Daily update check — runs on first execution of each new day
    check_and_pull_updates()

    # Planner-driven mode is the default. Set WORKER_USE_LEGACY_LOOP=1 to
    # fall back to the old scout-thread + exponential-backoff main loop.
    use_planner = os.environ.get("WORKER_USE_LEGACY_LOOP", "").lower() not in ("1", "true", "yes")

    if use_planner:
        logger.info(
            f"Planner mode ON for {tenant.user_id[:8]} — scout is planner-directed, "
            f"not on a timer. Set WORKER_USE_LEGACY_LOOP=1 to revert."
        )
    else:
        # Legacy mode: start the standalone scout thread on a 30-min timer.
        scout_thread = threading.Thread(
            target=scout_loop, args=(tenant,), daemon=True, name="scout-loop"
        )
        scout_thread.start()
        logger.info(
            f"Legacy mode: scout loop started for {tenant.user_id[:8]} "
            f"(interval={SCOUT_INTERVAL_MINUTES}m, {len(REGISTERED_SOURCES)} sources)"
        )

    while running:
        # Planner dispatch — runs at the top of every iteration. Non-apply
        # actions (scout, idle) are handled here and the iteration skips.
        # apply_next falls through to the claim+apply code below; outcome
        # is reported at the end of the iteration via current_plan.
        current_plan: dict | None = None
        apply_outcome: str = "success"
        apply_outcome_detail: str | None = None

        if use_planner:
            current_plan = fetch_next_plan()
            if current_plan is None:
                # Planner unreachable — back off and retry. Worker never
                # burns a CPU loop waiting for the cloud.
                time.sleep(30)
                continue

            action = str(current_plan.get("action", ""))
            plan_id = str(current_plan.get("plan_id", ""))
            reason = str(current_plan.get("reason", ""))
            logger.info(f"[planner] {action} — {reason}")

            if action != "apply_next":
                # Every non-apply action reports its own outcome + continues.
                try:
                    if action == "idle_until_midnight":
                        report_plan_outcome(plan_id, "skipped", reason or "daily cap")
                        # Cap the sleep at 10 min so we re-check state
                        # frequently enough to notice a cap being raised.
                        time.sleep(600)
                    elif action == "idle_until_next_tick":
                        report_plan_outcome(plan_id, "skipped", reason or "no work")
                        time.sleep(60)
                    elif action in ("scout_primary", "scout_title_based", "scout_expand_boards"):
                        style = "company" if action == "scout_primary" else "title"
                        enqueued = run_scout_cycle(tenant, style_filter=style)
                        report_plan_outcome(
                            plan_id,
                            "empty" if enqueued == 0 else "success",
                            f"{enqueued} enqueued (style={style})",
                        )
                        time.sleep(5)
                    elif action == "restart_worker":
                        report_plan_outcome(plan_id, "skipped", "restart_worker not yet wired")
                        time.sleep(60)
                    else:
                        report_plan_outcome(plan_id, "skipped", f"unhandled action: {action}")
                        time.sleep(60)
                except Exception as e:
                    logger.warning(f"[planner] {action} failed: {e}")
                    try:
                        report_plan_outcome(plan_id, "failed", str(e)[:200])
                    except Exception:
                        pass
                    time.sleep(30)
                continue
            # action == apply_next: fall through to existing claim+apply code.
            # Outcome reporting happens at the bottom via a try/finally-style
            # end-of-iteration hook using the current_plan reference.
        # Refresh tenant reference at the top of each iteration. The
        # reload thread updates `_current_tenant` every N seconds; we just
        # read it here so each apply cycle uses the freshest bundle list +
        # decrypted app passwords. Never falls back to the boot-time
        # tenant — if reload ever nullified it, something's wrong and the
        # RuntimeError will surface rather than silently using stale creds.
        tenant = get_current_tenant()

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
            # Under planner mode, the planner should never issue apply_next
            # when the queue is empty — so hitting this branch means the
            # queue drained between plan issuance and claim. Report + short
            # sleep. The next planner tick will re-decide based on fresh
            # state. Legacy mode keeps the exponential backoff.
            if use_planner and current_plan:
                try:
                    report_plan_outcome(
                        str(current_plan.get("plan_id", "")),
                        "skipped",
                        "queue empty at claim time (race with drain)",
                    )
                except Exception:
                    pass
                # Prevent double-report at end-of-iteration finally.
                current_plan = None
                time.sleep(5)
                continue
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
        if is_staffing_agency(company):
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

        # Profile: first_name + last_name + email must exist.
        # load_user_profile returns {user, profile, resumes} — appliers
        # (greenhouse.py:753, workday.py:91) already read from the nested
        # `profile` key, so preflight must match. Reading top-level used
        # to silently flag every claim as awaiting_profile and back off.
        try:
            raw_profile_bundle = load_user_profile(user_id) or {}
        except WorkerAuthError:
            raise
        except Exception as e:
            logger.debug(f"Profile preflight load failed: {e}")
            raw_profile_bundle = {}
        preflight_profile = raw_profile_bundle.get("profile") or {}
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

        # Resolve the profile bundle for this job BEFORE resume + answer_key.
        # Multi-profile: the queue row carries application_profile_id tagged
        # at scout time. If the tag points at a bundle that was DELETED
        # after enqueue, we fail the job loudly rather than silently falling
        # back to default (which would apply with the wrong resume/creds).
        tagged_pid = job.get('application_profile_id')
        if tagged_pid:
            job_profile = tenant.profile_by_id(tagged_pid)
            if not job_profile:
                logger.warning(
                    f"Job {job['id']} tagged with bundle {tagged_pid[:8]} "
                    f"which no longer exists — marking failed"
                )
                update_queue_status(job['id'], 'failed', error='profile_deleted')
                update_local_status(job, 'failed', 'profile bundle was deleted')
                continue
        else:
            job_profile = tenant.default_profile()

        # Per-bundle daily cap. This is independent of the user-wide
        # daily_apply_limit checked upstream (which uses the cloud API's
        # aggregate count). A user can set max_daily on a bundle to
        # reserve slots for a second bundle (e.g. 10 AI apps + 10 DA
        # apps per day) or to cap spam. None OR 0 means "no cap" — to
        # pause a bundle entirely, use auto_apply=false instead. This
        # avoids the "0 means permanently blocked" ambiguity flagged in
        # the code audit.
        if job_profile.max_daily is not None and job_profile.max_daily > 0:
            applied_today = count_profile_applied_today(job_profile.id)
            if applied_today >= job_profile.max_daily:
                logger.info(
                    f"Bundle '{job_profile.name}' hit max_daily={job_profile.max_daily} "
                    f"(applied_today={applied_today}) — returning job {job['id']} to queue"
                )
                update_queue_status(job['id'], 'pending', error=f"bundle_max_daily:{job_profile.name}")
                time.sleep(30)
                continue

        # Creds are passed to applier + knowledge.py EXPLICITLY. We no
        # longer mutate os.environ — that pattern leaked plaintext app
        # passwords to subprocess/Chrome children via env inheritance,
        # and was a thread-safety footgun across scout/apply/heartbeat.
        # None means "fall back to .env" (legacy single-profile behavior).
        bundle_email = job_profile.application_email
        bundle_app_password = job_profile.application_email_app_password
        logger.info(
            f"Job {job['id']} bound to profile '{job_profile.name}' "
            f"(email={bundle_email or 'env-fallback'}, "
            f"resume={job_profile.resume_file_name or 'legacy-picker'})"
        )

        # Resume: prefer the bundle's bound resume. Fall back to the legacy
        # title-based picker only when the bundle has no resume_id.
        try:
            if job_profile.resume_signed_url:
                resume_path = download_resume_by_url(
                    job_profile.resume_signed_url,
                    job_profile.resume_file_name or "resume.pdf",
                    cache_key=job_profile.id[:8],
                )
            else:
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
            # Per-bundle work history override (mig 020). The profile dict
            # normally carries the shared user_profiles.work_experience —
            # but each bundle can have its own role-specific narrative.
            # Shallow-copy and override so the applier's profile_summary()
            # sees the bundle's history for every job this loop claims.
            if job_profile.work_experience is not None:
                profile = {**profile, "work_experience": job_profile.work_experience}
            if job_profile.education is not None:
                profile = {**profile, "education": job_profile.education}
            if job_profile.skills is not None:
                profile = {**profile, "skills": job_profile.skills}

            # Per-bundle answer key from mig 019. When the bundle has its
            # own answers (different "why interested" per role), use them;
            # otherwise knowledge.build_answer_key falls back to the
            # user_profiles.answer_key_json legacy shared value.
            answer_key = build_answer_key(
                profile, global_template,
                profile_email=bundle_email,
                bundle_answer_key=job_profile.answer_key_json,
            )

            # Per-bundle cover letter (mig 019). applier/base.py:134
            # already reads cover_letter_template from
            # answer_key["textarea_fields"]["cover_letter_template"] — we
            # just need to populate that path. Without this injection the
            # bundle's cover_letter_template column was dead code: loaded,
            # typed, saved, and silently ignored at apply time.
            if job_profile.cover_letter_template:
                answer_key.setdefault("textarea_fields", {})
                answer_key["textarea_fields"]["cover_letter_template"] = job_profile.cover_letter_template

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
                applier = ApplierClass(
                    profile, answer_key, resume_path,
                    profile_email=bundle_email,
                    profile_app_password=bundle_app_password,
                )
            except MissingResumeError as e:
                logger.error(f"Resume missing for job {job['id']}: {e}")
                update_queue_status(job['id'], 'failed', error=f"resume file missing: {e}")
                update_local_status(job, 'failed', f"resume missing: {e}")
                log_application(user_id, job, {'status': 'failed', 'error': f"resume missing: {e}"})
                update_heartbeat(user_id, "failed", f"{company} — resume missing")
                continue
            result = applier.apply(apply_url)

            # Tracks whether we've already persisted a final outcome to the
            # local `applications` table. If an exception fires after a
            # successful submit log (e.g., Telegram send or heartbeat throws),
            # we must NOT overwrite the 'submitted' row with 'failed'.
            outcome_logged = False

            if result.success:
                consecutive_timeouts = 0
                screenshot_url = None
                if result.screenshot:
                    screenshot_url = upload_screenshot(user_id, result.screenshot)
                update_queue_status(job['id'], 'submitted')
                log_application(user_id, job, {'status': 'submitted', 'screenshot_url': screenshot_url})
                outcome_logged = True
                # Only render the bundle name for multi-profile users so
                # single-profile users see the pre-refactor caption.
                _bundle_name = job_profile.name if len(tenant.profiles) > 1 else None
                send_application_result(user_id, job, result.screenshot, profile_name=_bundle_name)
                hourly_count += 1
                update_heartbeat(user_id, "applied", f"{company} — {job.get('title', '')}")
                apply_outcome = "success"
                apply_outcome_detail = f"submitted {company} — {job.get('title', '')[:80]}"
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
                    apply_outcome = "skipped"
                    apply_outcome_detail = f"retriable: {str(result.error)[:160]}"
                else:
                    update_queue_status(job['id'], 'failed', error=result.error)
                    update_local_status(job, 'failed', result.error)
                    log_application(user_id, job, {'status': 'failed', 'error': result.error})
                    outcome_logged = True
                    send_failure(user_id, company, job.get('title', ''), result.error)
                    update_heartbeat(user_id, "failed", f"{company} — {result.error[:80]}")
                    apply_outcome = "failed"
                    apply_outcome_detail = f"{company}: {str(result.error)[:160]}"

            time.sleep(cooldown)
            update_heartbeat(user_id, "sleep", f"cooldown {cooldown}s")

        except Exception as e:
            logger.exception(f"Error processing job {job['id']}")
            update_queue_status(job['id'], 'failed', error=str(e))
            # Only mirror the failure into local SQLite if we haven't already
            # logged a submitted/failed outcome — otherwise a post-submit
            # exception (telegram, heartbeat) would overwrite the submitted row.
            if not locals().get('outcome_logged', False):
                try:
                    update_local_status(job, 'failed', f"exception: {str(e)[:160]}")
                    log_application(user_id, job, {'status': 'failed', 'error': f"exception: {str(e)[:160]}"})
                except Exception as inner:
                    logger.debug(f"Exception-path local log failed (non-fatal): {inner}")
            apply_outcome = "failed"
            apply_outcome_detail = f"exception: {str(e)[:160]}"
            time.sleep(10)

        finally:
            # End-of-iteration planner outcome report. Fires for every apply
            # iteration under planner mode — whether the work completed
            # cleanly, hit a continue on a pre-flight skip, or raised.
            # Legacy mode leaves current_plan as None so this is a no-op.
            if use_planner and current_plan:
                try:
                    report_plan_outcome(
                        str(current_plan.get("plan_id", "")),
                        apply_outcome,
                        apply_outcome_detail,
                    )
                except Exception:
                    pass


if __name__ == '__main__':
    main()
