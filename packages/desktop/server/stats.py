"""
Fetch data from the ApplyLoop backend using ONLY deployed proxy actions.

Available actions on live server: load_profile, load_preferences,
check_daily_limit, claim_job, update_queue, log_application, heartbeat,
enqueue_jobs, check_company_rate, get_answer_key, get_telegram_config,
download_resume_url.

Stats (get_stats, get_daily_breakdown, etc.) are NOT deployed yet,
so we use load_profile to get basic user data.
"""
from __future__ import annotations

import logging
import time
import httpx
from .config import APP_URL, load_token

logger = logging.getLogger(__name__)
PROXY_URL = f"{APP_URL}/api/worker/proxy"
TIMEOUT = 30.0

# Global auth state. Flips to "revoked" the first time the server rejects
# our worker token with 401/403 — the UI polls /api/auth/state and redirects
# the user to /setup when this happens, instead of silently showing empty
# dashboards forever.
_auth_state: dict = {
    "status": "ok",       # "ok" | "revoked" | "unknown"
    "last_checked": 0.0,
    "last_error": None,
}


def get_auth_state() -> dict:
    """Expose the latest auth state to the API layer."""
    return dict(_auth_state)


def _mark_auth_ok() -> None:
    _auth_state["status"] = "ok"
    _auth_state["last_checked"] = time.time()
    _auth_state["last_error"] = None


def _mark_auth_revoked(reason: str) -> None:
    _auth_state["status"] = "revoked"
    _auth_state["last_checked"] = time.time()
    _auth_state["last_error"] = reason
    logger.warning(f"Worker token revoked/invalid: {reason}")


async def _proxy(action: str, params: dict | None = None) -> dict:
    """Call the worker proxy endpoint with X-Worker-Token.

    On 401/403 we explicitly surface a "TOKEN_REVOKED" sentinel and flip
    the global auth state so the desktop UI can redirect to /setup.
    """
    token = load_token()
    if not token:
        _mark_auth_revoked("no_token")
        return {"error": "No API token configured", "auth": "no_token"}
    headers = {"X-Worker-Token": token}
    payload: dict = {"action": action}
    if params:
        payload.update(params)
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(PROXY_URL, json=payload, headers=headers)
        if resp.status_code in (401, 403):
            _mark_auth_revoked(f"HTTP {resp.status_code}")
            return {"error": "TOKEN_REVOKED", "auth": "revoked", "status": resp.status_code}
        resp.raise_for_status()
        _mark_auth_ok()
        return resp.json()
    except httpx.HTTPStatusError as e:
        logger.debug(f"Proxy {action} HTTP error: {e}")
        return {"error": str(e)}
    except Exception as e:
        logger.debug(f"Proxy {action} failed: {e}")
        return {"error": str(e)}


async def get_profile() -> dict:
    """Load user profile + preferences."""
    result = await _proxy("load_profile")
    return result.get("data", {})


async def get_preferences() -> dict:
    """Load user job preferences."""
    result = await _proxy("load_preferences")
    return result.get("data", {})


async def get_stats() -> dict:
    """Get stats using load_profile (deployed) or get_stats (if deployed)."""
    # Try new action first, fall back to basic data from load_profile
    result = await _proxy("get_stats")
    if "error" not in result and "data" in result:
        return result["data"]
    # Fallback: get basic info from load_profile + check_daily_limit
    profile = await _proxy("load_profile")
    daily = await _proxy("check_daily_limit")
    user = profile.get("data", {}).get("user", {})
    daily_data = daily.get("data", {})
    return {
        "applied_today": daily_data.get("current", 0),
        "total_applied": 0,  # Not available without get_stats
        "in_queue": 0,
        "success_rate": 0,
        "user_name": user.get("full_name", ""),
        "email": user.get("email", ""),
        "tier": user.get("tier", "free"),
        "daily_limit": daily_data.get("limit", user.get("daily_apply_limit", 5)),
    }


async def get_daily_breakdown() -> list:
    """Try get_daily_breakdown, return empty if not deployed."""
    result = await _proxy("get_daily_breakdown")
    if "error" not in result and "data" in result:
        return result["data"]
    return []


async def get_ats_breakdown() -> list:
    """Try get_ats_breakdown, return empty if not deployed."""
    result = await _proxy("get_ats_breakdown")
    if "error" not in result and "data" in result:
        return result["data"]
    return []


async def get_pipeline() -> dict:
    """Try get_pipeline, return empty if not deployed."""
    result = await _proxy("get_pipeline")
    if "error" not in result and "data" in result:
        return result["data"]
    return {"discovered": [], "queued": [], "applying": [], "submitted": [], "failed": []}


async def get_recent_applications(limit: int = 20) -> list:
    """Try get_recent_applications, return empty if not deployed."""
    result = await _proxy("get_recent_applications", {"limit": limit})
    if "error" not in result and "data" in result:
        return result["data"]
    return []


async def get_heartbeat() -> dict:
    """Get worker heartbeat — use heartbeat action."""
    result = await _proxy("heartbeat_status")
    if "error" not in result and "data" in result:
        return result["data"]
    return {}


async def update_profile(profile_data: dict) -> dict:
    """Persist profile edits from the desktop Settings page back to Supabase.

    The server-side update_profile action on the worker proxy derives
    user_id from the worker token header, so we just forward the column
    values. The proxy applies a column allowlist — fields we don't know
    about will be dropped silently (intended).
    """
    result = await _proxy("update_profile", profile_data)
    if "error" in result:
        return result
    return result.get("data", {"updated": True})


async def update_preferences(prefs_data: dict) -> dict:
    """Persist job-preference edits back to Supabase via the worker proxy.

    Same contract as update_profile: allowlisted columns, user-scoped upsert.
    """
    result = await _proxy("update_preferences", prefs_data)
    if "error" in result:
        return result
    return result.get("data", {"updated": True})


async def get_settings_profile() -> dict:
    """Get profile using worker proxy, with fallback to local PROFILE.md."""
    result = await _proxy("load_profile")
    data = result.get("data", {})
    profile = data.get("profile")
    user = data.get("user", {})

    # If Supabase profile is null/empty, build from user object + local PROFILE.md
    if not profile or not profile.get("first_name"):
        profile = profile or {}
        # Extract first/last name from user.full_name
        full_name = user.get("full_name", "")
        if full_name and not profile.get("first_name"):
            parts = full_name.strip().split(None, 1)
            profile["first_name"] = parts[0].title() if parts else ""
            profile["last_name"] = parts[1].title() if len(parts) > 1 else ""
        if user.get("email") and not profile.get("email"):
            profile["email"] = user["email"]

        # Try reading local PROFILE.md for richer data
        local_profile = _read_local_profile()
        if local_profile:
            # Only fill in fields that are still empty
            for key, value in local_profile.items():
                if value and not profile.get(key):
                    profile[key] = value

    return {"data": {"profile": profile}}


def _read_local_profile() -> dict:
    """Parse PROFILE.md from the current workspace only.

    SECURITY: previously scanned ~/.openclaw/agents/job-bot/workspace/PROFILE.md
    as a fallback. That file on developer machines contains real PII and was
    being merged into every user's profile response regardless of which
    workspace they booted with — a cross-tenant data leak. Now we only
    read the PROFILE.md that lives inside the current WORKSPACE_DIR.
    """
    from .config import WORKSPACE_DIR
    import re

    for candidate in [WORKSPACE_DIR / "PROFILE.md"]:
        if candidate.exists():
            try:
                text = candidate.read_text()
            except Exception:
                continue

            profile = {}
            # Extract key-value pairs from markdown like "- **First Name:** Snehit"
            field_map = {
                "First Name": "first_name",
                "Last Name": "last_name",
                "Email": "email",
                "Phone (Primary)": "phone",
                "Current Location": "location",
                "LinkedIn": "linkedin_url",
                "GitHub": "github_url",
                "Portfolio / Personal Website": "portfolio_url",
            }
            for line in text.splitlines():
                for md_key, profile_key in field_map.items():
                    if profile_key in profile:
                        continue  # Keep the first match only
                    pattern = rf"\*\*{re.escape(md_key)}:?\*\*\s*:?\s*(.+)"
                    m = re.search(pattern, line)
                    if m:
                        val = m.group(1).strip()
                        if val and val.lower() != "n/a" and not val.startswith("("):
                            profile[profile_key] = val

            # Extract current job info
            lines = text.splitlines()
            for i, line in enumerate(lines):
                if "Position 1" in line and "Current" in line:
                    # Scan next lines for title and company
                    for j in range(i + 1, min(i + 10, len(lines))):
                        jl = lines[j]
                        if "**Job Title:**" in jl:
                            val = jl.split("**Job Title:**")[-1].strip()
                            if val:
                                profile["current_title"] = val
                        if "**Company Name:**" in jl:
                            val = jl.split("**Company Name:**")[-1].strip()
                            if val:
                                profile["current_company"] = val
                    break

            return profile
    return {}


async def get_settings_preferences() -> dict:
    """Get preferences using worker proxy (load_preferences action)."""
    result = await _proxy("load_preferences")
    data = result.get("data", {})
    return {"data": {"preferences": data.get("preferences", data)}}
