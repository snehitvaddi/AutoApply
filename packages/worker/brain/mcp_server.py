"""Stdio MCP server — exposes the 24 applyloop tools to PTY Claude Code.

Registered in .claude/settings.json so Claude Code can call scout_*,
queue_*, browser_*, tenant_*, notify_*, and knowledge_* tools directly
from the PTY terminal, without spawning brain/main.py.

Start command (called by Claude Code automatically via MCP config):
  $APPLYLOOP_HOME/venv/bin/python3 -m brain.mcp_server

Must be run from packages/worker/ (or with PYTHONPATH including it) so
relative imports resolve.
"""
from __future__ import annotations

import json
import os
import sys
import logging

# ── stdio guard ────────────────────────────────────────────────────────────
# FastMCP's stdio transport uses fd 1 (stdout) for JSON-RPC frames. Any
# stray write to stdout from an imported module (Playwright CDP chatter,
# accidental print, dependency warnings written via fd-level write) will
# corrupt the framing and Claude Code will silently disconnect the server
# mid-session. We've seen this happen after ~30 successful tool calls.
#
# Strategy:
#   1. Dup real stdout into a saved fd; point fd 1 at fd 2 (stderr) so any
#      C-level / subprocess write to fd 1 lands harmlessly on stderr.
#   2. Build _REAL_STDOUT as a TextIOWrapper around the saved fd — this is
#      what FastMCP will use for JSON-RPC.
#   3. Set sys.stdout = sys.stderr during imports so accidental prints
#      from any module loaded below are swallowed safely.
#   4. Right before mcp.run(), swap sys.stdout to _REAL_STDOUT so the
#      FastMCP transport finds the JSON-RPC pipe.
_real_stdout_fd = os.dup(1)
os.dup2(2, 1)  # accidental fd-1 writes now go to stderr
_REAL_STDOUT = os.fdopen(_real_stdout_fd, "w", buffering=1, encoding="utf-8")
sys.stdout = sys.stderr  # python-level prints during import → stderr

# Ensure logging never writes to the JSON-RPC channel
logging.basicConfig(stream=sys.stderr, level=logging.INFO)

# Ensure packages/worker is on the path when invoked as __main__
_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from mcp.server.fastmcp import FastMCP
from applier import browser as _browser
from brain import session_log
from brain.prompts import load_ats_playbook

logger = logging.getLogger(__name__)

mcp = FastMCP("applyloop")


# ── browser ───────────────────────────────────────────────────────────────

@mcp.tool()
def browser_navigate(url: str) -> str:
    """Navigate the browser to a URL."""
    session_log.log_tool_call("browser_navigate", {"url": url})
    _browser.navigate_url(url)
    return "ok"


@mcp.tool()
def browser_wait_load(timeout_ms: int = 5000) -> str:
    """Wait for network-idle up to timeout_ms milliseconds."""
    _browser.wait_load(timeout_ms)
    return "ok"


@mcp.tool()
def browser_snapshot() -> str:
    """Take an accessibility snapshot of the current page. Returns parsed fields as JSON."""
    raw = _browser.snapshot()
    fields = _browser.parse_snapshot(raw) if raw else []
    return json.dumps({"raw": raw, "fields": fields, "field_count": len(fields)}, default=str)


@mcp.tool()
def browser_click(ref: str) -> str:
    """Click an element by its ref (e.g. 'e42')."""
    _browser.click_ref(ref)
    return "ok"


@mcp.tool()
def browser_fill(fields: str) -> str:
    """Fill multiple text fields at once. `fields` is a JSON array of {ref, type, value}."""
    _browser.fill_fields(fields)
    return "ok"


@mcp.tool()
def browser_select(ref: str, value: str) -> str:
    """Select an option in a native <select> element."""
    _browser.select_option(ref, value)
    return "ok"


@mcp.tool()
def browser_type(ref: str, text: str) -> str:
    """Type text into a React/SPA input field (fires synthetic events)."""
    _browser.type_into(ref, text)
    return "ok"


@mcp.tool()
def browser_upload(path: str, ref: str) -> str:
    """Upload a local file. `path` is absolute, `ref` is the upload button ref."""
    _browser.upload_file(path, ref)
    return "ok"


@mcp.tool()
def browser_press_key(key: str) -> str:
    """Press one key (e.g. 'Enter', 'Tab', 'End')."""
    _browser.press_key(key)
    return "ok"


@mcp.tool()
def browser_evaluate_js(code: str) -> str:
    """Run a JS arrow function against the page. `code` must be `() => { ... }`."""
    result = _browser.evaluate_js(code)
    return str(result) if result is not None else "null"


@mcp.tool()
def browser_screenshot() -> str:
    """Take a full-page PNG screenshot. Returns the local file path."""
    path = _browser.take_screenshot() or ""
    return path


@mcp.tool()
def browser_list_tabs() -> str:
    """List all currently open browser tabs."""
    tabs = _browser.list_tabs()
    return json.dumps({"tabs": tabs}, default=str)


@mcp.tool()
def browser_dismiss_stray_tabs(keep_url_substring: str = "") -> str:
    """Close any tab whose URL does not contain keep_url_substring. Call between apply steps."""
    keep = keep_url_substring or None
    closed = _browser.dismiss_stray_tabs(keep)
    return json.dumps({"closed": closed}, default=str)


# ── queue ─────────────────────────────────────────────────────────────────

@mcp.tool()
def queue_claim_next() -> str:
    """Claim the next pending job for this worker (row-lock). Returns job dict or {empty: true}."""
    from worker import claim_next_job_locally, WORKER_ID
    user_id = os.environ.get("APPLYLOOP_USER_ID", "")
    job = claim_next_job_locally(user_id, WORKER_ID)
    return json.dumps(job or {"empty": True}, default=str)


@mcp.tool()
def queue_update_status(queue_id: str, status: str, error: str = "", attempts: int = 0) -> str:
    """Update an application_queue row. status in {pending,submitted,failed,cancelled}."""
    from db import update_queue_status
    update_queue_status(queue_id, status, error=error or None, attempts=attempts or None)
    return "ok"


@mcp.tool()
def queue_log_application(
    job_id: str, queue_id: str, company: str, title: str,
    ats: str, apply_url: str, status: str,
    screenshot_url: str = "", error: str = "",
) -> str:
    """Log an application outcome to SQLite + best-effort cloud insert."""
    from db import log_application
    user_id = os.environ.get("APPLYLOOP_USER_ID", "")
    job = {"job_id": job_id, "id": queue_id, "company": company,
           "title": title, "ats": ats, "apply_url": apply_url}
    result = {"status": status, "screenshot_url": screenshot_url or None, "error": error or None}
    log_application(user_id, job, result)
    return "ok"


@mcp.tool()
def queue_get_pipeline() -> str:
    """Return queue counts per status + recent rows for situational awareness."""
    from db import _api_call
    data = _api_call("get_pipeline") or {}
    return json.dumps(data, default=str)


# ── scout ─────────────────────────────────────────────────────────────────

@mcp.tool()
def scout_list_sources() -> str:
    """List available scout sources (name, priority, requires_auth)."""
    from scout import REGISTERED_SOURCES
    sources = [{"name": s.name, "priority": s.priority, "requires_auth": s.requires_auth}
               for s in REGISTERED_SOURCES]
    return json.dumps({"sources": sources}, default=str)


@mcp.tool()
def scout_run_source(name: str) -> str:
    """Run one scout source against the current tenant. Returns list of JobPost dicts."""
    from scout import REGISTERED_SOURCES
    from tenant import TenantConfig
    user_id = os.environ.get("APPLYLOOP_USER_ID", "")
    tenant = TenantConfig.load(user_id)
    source = next((s for s in REGISTERED_SOURCES if s.name == name), None)
    if source is None:
        available = [s.name for s in REGISTERED_SOURCES]
        return json.dumps({"error": f"unknown source: {name}", "available": available})
    jobs = source.scout(tenant) or []
    return json.dumps({"count": len(jobs), "jobs": jobs[:50]}, default=str)


# ── tenant ────────────────────────────────────────────────────────────────

@mcp.tool()
def tenant_load() -> str:
    """Load the current tenant config snapshot (profiles, preferences, daily limits)."""
    from tenant import TenantConfig
    user_id = os.environ.get("APPLYLOOP_USER_ID", "")
    t = TenantConfig.load(user_id)
    data = {
        "user_id": user_id,
        "search_queries": list(t.search_queries),
        "preferred_locations": list(t.preferred_locations),
        "profiles": [{"id": p.id, "name": p.name, "is_default": p.is_default}
                     for p in getattr(t, "profiles", [])],
        "daily_apply_limit": getattr(t, "daily_apply_limit", None),
    }
    return json.dumps(data, default=str)


# ── notify ────────────────────────────────────────────────────────────────

@mcp.tool()
def notify_heartbeat(last_action: str = "", details: str = "") -> str:
    """Send a heartbeat so the dashboard shows the agent is alive."""
    from db import update_heartbeat
    user_id = os.environ.get("APPLYLOOP_USER_ID", "")
    update_heartbeat(user_id, last_action, details)
    return "ok"


@mcp.tool()
def notify_upload_screenshot(local_path: str) -> str:
    """Upload a local PNG to Supabase storage (web dashboard only). Returns signed URL."""
    from db import upload_screenshot
    user_id = os.environ.get("APPLYLOOP_USER_ID", "")
    url = upload_screenshot(user_id, local_path)
    return json.dumps({"url": url}, default=str)


@mcp.tool()
def notify_telegram(
    kind: str = "generic", company: str = "", title: str = "",
    error: str = "", screenshot_url: str = "", text: str = "",
) -> str:
    """Send a Telegram update. kind in {application_result, failure, scout_summary, session_event, generic}."""
    from notifier import send_session_event, send_failure, send_application_result
    user_id = os.environ.get("APPLYLOOP_USER_ID", "")
    if kind == "application_result":
        job = {"company": company, "title": title}
        send_application_result(user_id, job, screenshot_url or None, profile_name=None)
    elif kind == "failure":
        send_failure(user_id, company, title, error, screenshot_url or None)
    else:
        send_session_event(user_id, kind, text)
    return "ok"


# ── email (OTP + link reading via Himalaya CLI) ───────────────────────────

@mcp.tool()
def email_read_otp(
    sender_pattern: str,
    subject_pattern: str = "",
    timeout: int = 60,
) -> str:
    """Read an OTP/verification code from Gmail via Himalaya CLI.

    sender_pattern: substring of the sender address to match (e.g. 'greenhouse-mail.io').
    subject_pattern: optional substring to also match in subject.
    timeout: max seconds to poll before giving up.
    Returns the code string, or 'error: ...' on failure.
    """
    from himalaya_reader import ensure_configured, find_otp
    email = os.environ.get("GMAIL_EMAIL", "")
    app_pw = os.environ.get("GMAIL_APP_PASSWORD", "")
    if not email or not app_pw:
        return "error: GMAIL_EMAIL or GMAIL_APP_PASSWORD not set in environment"
    if not ensure_configured(email, app_pw):
        return "error: himalaya not installed or config write failed — run: brew install himalaya"
    code = find_otp(sender_pattern, subject_pattern, timeout=timeout)
    return code or f"error: no OTP found from '{sender_pattern}' within {timeout}s"


@mcp.tool()
def email_read_link(
    sender_pattern: str,
    link_regex: str,
    timeout: int = 60,
) -> str:
    """Read a verification/reset link from Gmail via Himalaya CLI.

    sender_pattern: substring of the sender address to match (e.g. 'workday').
    link_regex: regex pattern the URL must match (e.g. 'passwordreset').
    timeout: max seconds to poll before giving up.
    Returns the URL string, or 'error: ...' on failure.
    """
    from himalaya_reader import ensure_configured, find_link
    email = os.environ.get("GMAIL_EMAIL", "")
    app_pw = os.environ.get("GMAIL_APP_PASSWORD", "")
    if not email or not app_pw:
        return "error: GMAIL_EMAIL or GMAIL_APP_PASSWORD not set in environment"
    if not ensure_configured(email, app_pw):
        return "error: himalaya not installed or config write failed — run: brew install himalaya"
    link = find_link(sender_pattern, link_regex, timeout=timeout)
    return link or f"error: no link matching '{link_regex}' from '{sender_pattern}' within {timeout}s"


# ── knowledge ─────────────────────────────────────────────────────────────

@mcp.tool()
def knowledge_get_ats_playbook(name: str) -> str:
    """Return the ATS playbook section. Names: greenhouse, lever, ashby, smartrecruiters, workday, linkedin, universal."""
    section = load_ats_playbook(name.strip())
    if section is None:
        return json.dumps({"found": False, "name": name})
    return json.dumps({"found": True, "name": name, "section": section})


# ── entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Restore real stdout for the JSON-RPC transport. From here on, any
    # accidental Python print() writes to JSON-RPC — but the imports above
    # are audited and tool bodies never print, so this window is safe.
    sys.stdout = _REAL_STDOUT
    mcp.run(transport="stdio")
