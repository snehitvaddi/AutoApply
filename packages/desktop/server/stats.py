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
import httpx
from .config import APP_URL, load_token

logger = logging.getLogger(__name__)
PROXY_URL = f"{APP_URL}/api/worker/proxy"
TIMEOUT = 30.0


async def _proxy(action: str, params: dict | None = None) -> dict:
    """Call the worker proxy endpoint with X-Worker-Token."""
    token = load_token()
    if not token:
        return {"error": "No API token configured"}
    headers = {"X-Worker-Token": token}
    payload: dict = {"action": action}
    if params:
        payload.update(params)
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(PROXY_URL, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()
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
    """Update not available via worker token — return error."""
    return {"error": "Profile updates require the web dashboard"}


async def update_preferences(prefs_data: dict) -> dict:
    """Update not available via worker token — return error."""
    return {"error": "Preference updates require the web dashboard"}


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
    """Parse PROFILE.md from local workspace to extract profile fields."""
    from pathlib import Path
    import re

    # Check both possible locations
    for candidate in [
        Path.home() / ".openclaw" / "agents" / "job-bot" / "workspace" / "PROFILE.md",
        Path.home() / ".autoapply" / "workspace" / "PROFILE.md",
    ]:
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
