"""Worker global config — universal safety rules only.

Part 2 of the multi-tenant redesign deleted every role-opinion constant
from this file. What used to be AI_KEYWORDS / SKIP_LEVELS / SKIP_LOCATIONS
/ SKIP_ROLE_KEYWORDS / SKIP_COMPANIES_SENIOR now lives per-tenant on
TenantConfig (packages/worker/tenant.py). Board slug lists moved to
packages/worker/default_boards.py.

What remains here is strictly the universal-truth layer — spam aggregators,
staffing agencies that aren't direct employers, and the company rate limits.
If a constant belongs here it must be TRUE for every tenant regardless of
role, level, location, work auth, or profile shape.
"""
import os
from datetime import date

# Supabase keys are no longer needed by the worker — all DB access goes through
# the API proxy at /api/worker/proxy using the worker token.
# These are kept for backward compatibility but default to empty.
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
WORKER_ID = os.environ.get("WORKER_ID", f"worker-{os.getpid()}")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "10"))
APPLY_COOLDOWN = int(os.environ.get("APPLY_COOLDOWN", "30"))
# Default to the per-user workspace on any platform. /tmp doesn't exist
# on Windows, and even on macOS /tmp is wiped on reboot — losing a
# freshly-downloaded resume mid-run. The workspace dir matches what the
# desktop launcher creates at startup.
_WORKSPACE = os.path.expanduser("~/.autoapply/workspace")
RESUME_DIR = os.environ.get("RESUME_DIR") or os.path.join(_WORKSPACE, "resumes")
SCREENSHOT_DIR = os.environ.get("SCREENSHOT_DIR") or os.path.join(_WORKSPACE, "screenshots")

ATS_COOLDOWNS = {
    "greenhouse": 30,
    "lever": 20,
    "ashby": 15,
    "smartrecruiters": 20,
}

MAX_SYSTEM_APPS_PER_HOUR = 60

# ─── GLOBAL SAFETY FILTERS (universal truths, NOT role opinions) ───────────

# Aggregator/spam domains — jobs from these sites are never real employers.
# Universal: every tenant wants these filtered regardless of their profile.
BLOCKED_DOMAINS = [
    "jobright.ai",
    "wiraa.com",
    "bestjobtool.com",
    "hirenza.com",
    "mygwork.com",
    "haystackapp.io",
    "indeed.com",
]

# Temporary company pauses — admin-managed global pauses after rate-limit
# incidents. Could be moved to a DB table in the future; leaving here for now.
COMPANY_PAUSES: dict[str, date] = {
    "stripe": date(2026, 3, 25),
    "ramp": date(2026, 6, 9),
}

# Staffing agencies — not direct employers. Universal business rule; apps
# go to recruiters instead of real hiring managers, so no tenant wants them.
# Matched as substrings against lowered company names (worker.py), so generic
# patterns like "consulting" and "staffing" catch the long tail of
# body-shops without needing every slug in an allowlist.
BLOCKED_STAFFING = [
    # Named staffing platforms / body-shops
    "hackajob", "lensa", "jobright", "kforce", "dice", "collabera",
    "wiraa", "synergistic", "aditi", "hirenza", "jobot",
    "insight global", "teksystems", "mphasis", "data annotation",
    "technosoft", "sysinc",
    # Generic consultancy / staffing suffixes — substring-matched so they
    # catch "Take2 Consulting LLC", "Radiance Sysinc", "Acme Staffing", etc.
    "consulting", "consultants", "consulting group", "consulting llc",
    "staffing", "it services", "solutions llc", "solutions inc",
    "software inc",
]

# ─── Scout → Filter → Apply cycle config ────────────────────────────────────

SCOUT_INTERVAL_MINUTES = int(os.environ.get("SCOUT_INTERVAL_MINUTES", "30"))
# Rolling 7-day cap per company. Simpler than the old 2/day + 5/15d pair —
# matches real submission behavior and easier for Claude to reason about.
MAX_COMPANY_APPS_PER_7_DAYS = 3
# Queue entries older than this are pruned at the start of each apply loop
# iteration (24h freshness rule — listings expire fast, don't apply to stale ones).
QUEUE_STALE_HOURS = 24
# Rows stuck in `applying` for this long are assumed orphaned (applier
# crashed mid-run — reCAPTCHA, timeout, LinkedIn redirect loop — without
# cleanly calling update_queue_status). Watchdog resets them to `queued`
# so claim_next_job picks them up again. A real apply rarely exceeds
# 5 min, so 15 min is provably orphaned.
APPLY_STALE_MINUTES = 15
JOB_TIMEOUT_SECONDS = 120  # Max time per application before skip

# Backward-compat aliases — any external callers still importing the old
# names still work for one release cycle. Remove after v1.2.
MAX_COMPANY_APPS_PER_DAY = MAX_COMPANY_APPS_PER_7_DAYS
MAX_COMPANY_APPS_PER_15_DAYS = MAX_COMPANY_APPS_PER_7_DAYS

# NOTE: Role/level/location/company opinions moved to TenantConfig.
# See packages/worker/tenant.py for the frozen per-tenant dataclass and
# packages/worker/default_boards.py for the global board slug pools.
#
# The appliers (applier/greenhouse.py) need to know at apply time whether a
# company has a reCAPTCHA submit gate — that's a scrape-time property, not
# a role opinion, so the set re-exports here for backward compat. Scanner
# legacy code also imports the plain board lists via this path. New code
# should import from default_boards directly.
from default_boards import (
    DEFAULT_ASHBY_BOARDS as ASHBY_SLUGS,
    DEFAULT_GREENHOUSE_SUBMITTABLE as GREENHOUSE_SUBMITTABLE,
    DEFAULT_GREENHOUSE_RECAPTCHA as GREENHOUSE_RECAPTCHA,
)
