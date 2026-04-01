"""Database access layer — routes all operations through the ApplyLoop API proxy.

The worker never connects to Supabase directly. All reads/writes go through:
  POST /api/worker/proxy  (with X-Worker-Token header)

This ensures:
  - Users never need the Supabase service role key
  - All writes are scoped to the authenticated user
  - Admin can monitor and revoke access via worker tokens
"""

import os
import time
import json
import logging
import httpx

logger = logging.getLogger(__name__)

APP_URL = os.environ.get("NEXT_PUBLIC_APP_URL", "https://applyloop.vercel.app")
WORKER_TOKEN = os.environ.get("WORKER_TOKEN", "")
RESUME_DIR = os.environ.get("RESUME_DIR", "/tmp/autoapply/resumes")

_http_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _http_client
    if _http_client is None:
        _http_client = httpx.Client(timeout=30, follow_redirects=True)
    return _http_client


def _api_call(action: str, **params) -> dict:
    """Make an authenticated call to the worker proxy API."""
    client = _get_client()
    resp = client.post(
        f"{APP_URL}/api/worker/proxy",
        json={"action": action, **params},
        headers={"X-Worker-Token": WORKER_TOKEN, "Content-Type": "application/json"},
    )
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
    """Log a submitted/failed application."""
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


# ── User profile ──────────────────────────────────────────────────────────

def load_user_profile(user_id: str) -> dict:
    """Fetch user profile + resumes."""
    return _api_call("load_profile")


# ── Daily limits ──────────────────────────────────────────────────────────

def check_daily_limit(user_id: str) -> bool:
    """Return True if user hasn't exceeded daily limit."""
    result = _api_call("check_daily_limit")
    return result.get("within_limit", True)


def check_company_rate(user_id: str, company: str) -> bool:
    """Return True if user can still apply to this company (< 5 in 30 days)."""
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

def download_resume(user_id: str, job_title: str | None = None) -> str:
    """Download the best-matching resume to local path."""
    os.makedirs(RESUME_DIR, exist_ok=True)

    result = _api_call("download_resume_url", job_title=job_title or "")
    url = result.get("url")
    file_name = result.get("file_name", "resume.pdf")

    if not url:
        raise ValueError(f"No resume found for user {user_id}")

    local_path = os.path.join(RESUME_DIR, f"{user_id}_{file_name}")
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
    """Insert discovered jobs via API proxy (dedup + rate limit handled server-side)."""
    if not jobs:
        return 0
    result = _api_call("enqueue_jobs", jobs=jobs)
    return result.get("enqueued", 0)


# ── Heartbeat ─────────────────────────────────────────────────────────────

def update_heartbeat(user_id: str, action: str, details: str = ""):
    """Update worker heartbeat via API proxy."""
    _api_call("heartbeat", last_action=action, details=details)


# ── Legacy compatibility (used by some imports) ──────────────────────────

def get_client():
    """Legacy — returns the HTTP client instead of Supabase client."""
    return _get_client()
