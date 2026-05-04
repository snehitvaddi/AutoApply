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
    """Take an accessibility snapshot of the current page. Returns parsed fields as JSON.
    Auto-dismisses stray tabs first so hijacking popups (LinkedIn trackers, reCAPTCHA
    webworkers) don't capture the snapshot."""
    _browser.dismiss_stray_tabs()
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
    """Upload a local file and click the upload button.

    `path` is absolute. Files outside the OpenClaw sandbox
    (/tmp/openclaw/uploads/) are auto-copied in before arming, so resumes
    living under ~/.autoapply/workspace/resumes/ work transparently.

    Raises if the source file is missing or openclaw rejects the upload —
    the agent sees a real tool error instead of a misleading "ok".
    """
    _browser.upload_file(path, ref)
    return "ok"


@mcp.tool()
def browser_gateway_restart() -> str:
    """Restart the OpenClaw browser gateway. Returns JSON {ok, detail}.

    Use when browser_snapshot returns empty, the active tab keeps
    flipping to about:blank, or browser_click times out on visible
    elements — those are signs the Chrome session is wedged. The
    restart spawns a fresh Chrome so the wedge clears.

    Do NOT call mid-form (it kills the open tab). Use it between
    apply attempts as a recovery action when the standard primitives
    misbehave for ≥2 consecutive calls.
    """
    ok, detail = _browser.gateway_restart()
    return json.dumps({"ok": ok, "detail": detail})


@mcp.tool()
def browser_select_react(selector: str, label: str, value: str = "") -> str:
    """Commit a value to a React-Select / fiber-driven combobox.

    Greenhouse country dropdown, Ashby comboboxes, and any React-Select
    v5 widget keep the selected value in React fiber, not the DOM.
    Clicking the visible option fires events that React often treats
    as a no-op — the form looks selected but submission still throws
    "field required". This tool walks the fiber up from `selector`
    until it finds a node whose memoizedProps.onChange is a function,
    then calls it with `{value, label}` directly so React state
    actually updates.

    `selector` should target ANY element inside the combobox container
    (`.select__control`, `.select__input`, the rendered input itself).
    `value` is optional; if omitted the tool uses `label` as the value.

    Returns: 'ok' / 'ok_no_meta' on success, otherwise a diagnostic
    string ('no_element', 'no_fiber', 'no_onChange', 'onChange_threw:
    <msg>'). Doesn't raise — caller decides whether to retry.
    """
    out = _browser.select_react_value(selector, label, value or None)
    return out


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


@mcp.tool()
def browser_health_check() -> str:
    """Check end-to-end browser reachability. Returns JSON {ok, detail}.
    Attempts a gateway restart + retry if the first snapshot probe fails.
    Call before claiming a job to confirm the browser pipeline is live."""
    ok, detail = _browser.health_check()
    return json.dumps({"ok": ok, "detail": detail})


# ── queue ─────────────────────────────────────────────────────────────────

@mcp.tool()
def queue_claim_next() -> str:
    """Claim the next pending job for this worker (row-lock). Returns job dict or {empty: true}."""
    from worker import claim_next_job_locally, WORKER_ID
    user_id = os.environ.get("APPLYLOOP_USER_ID", "")
    job = claim_next_job_locally(user_id, WORKER_ID)
    return json.dumps(job or {"empty": True}, default=str)


@mcp.tool()
def queue_update_status(
    queue_id: str = "",
    status: str = "",
    error: str = "",
    attempts: int = 0,
    local_id: str = "",
) -> str:
    """Update an application row's status — local-first, then cloud.

    `queue_id` is the cloud UUID (may be empty for jobs claimed via the
    local-first path). `local_id` is the local SQLite integer id, also
    optional but RECOMMENDED so the desktop Kanban flips immediately
    without waiting for cloud round-trip.

    Statuses: queued | applying | submitted | failed | cancelled | skipped.
    Pass at least one of queue_id or local_id; passing both is the safest
    pattern when claim_next returned an _local job dict.
    """
    from db import update_queue_status
    update_queue_status(
        queue_id,
        status,
        error=error or None,
        attempts=attempts or None,
        local_id=local_id or None,
    )
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


@mcp.tool()
def queue_enqueue_jobs(jobs_json: str) -> str:
    """Enqueue scouted jobs into the local applications queue.

    `jobs_json` is a JSON array of job dicts in the shape produced by
    `scout_run_source` (keys: company, title, apply_url, ats, source,
    location, external_id, posted_at, application_profile_id).

    Persists each row as status='queued' in the local SQLite DB.
    Returns a typed summary the agent cannot misread:
      {
        "enqueued": <int>,      # net new rows actually queued
        "input_total": <int>,   # how many jobs you handed in
        "skipped_dedup": <int>, # collapsed by local dedup_token UNIQUE
      }
    The old shape used `submitted` for `input_total`, which read like a
    success metric; some agents logged "submitted: 34" as success when
    enqueued was 0. Renamed to be unambiguous.
    """
    from db import enqueue_to_local_db
    try:
        jobs = json.loads(jobs_json) if isinstance(jobs_json, str) else jobs_json
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"invalid jobs_json: {e}"})
    if not isinstance(jobs, list):
        return json.dumps({"error": "jobs_json must be a JSON array of job dicts"})
    total = len(jobs)
    inserted = enqueue_to_local_db(jobs)
    return json.dumps(
        {
            "enqueued": inserted,
            "input_total": total,
            "skipped_dedup": max(0, total - inserted),
        },
        default=str,
    )


@mcp.tool()
def tenant_filter_jobs(jobs_json: str) -> str:
    """Apply the tenant's default-profile filter to a list of jobs.

    `jobs_json` is a JSON array of job dicts. Returns the surviving
    subset plus a per-job verdict so the agent can see why something
    was rejected without re-implementing tenant rules in-prompt.

    Filter source: ApplyProfile.passes_filter on the default profile
    (falls back to the first profile if none is marked default).
    """
    from tenant import TenantConfig
    try:
        jobs = json.loads(jobs_json) if isinstance(jobs_json, str) else jobs_json
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"invalid jobs_json: {e}"})
    if not isinstance(jobs, list):
        return json.dumps({"error": "jobs_json must be a JSON array of job dicts"})

    user_id = os.environ.get("APPLYLOOP_USER_ID", "")
    tenant = TenantConfig.load(user_id)
    profiles = list(getattr(tenant, "profiles", []) or [])
    default_profile = next((p for p in profiles if getattr(p, "is_default", False)), None)
    if default_profile is None and profiles:
        default_profile = profiles[0]
    if default_profile is None:
        return json.dumps({
            "error": "no apply profile configured for tenant; cannot filter",
            "user_id": user_id,
        })

    survivors = []
    rejected = []
    for j in jobs:
        title = j.get("title", "") or ""
        company = j.get("company", "") or ""
        location = j.get("location", "") or ""
        if default_profile.passes_filter(title, company, location):
            survivors.append(j)
        else:
            rejected.append({"company": company, "title": title, "location": location})
    return json.dumps({
        "profile_id": getattr(default_profile, "id", ""),
        "passed": survivors,
        "rejected": rejected,
        "passed_count": len(survivors),
        "rejected_count": len(rejected),
    }, default=str)


@mcp.tool()
def queue_check_dedup(company: str, title: str = "", ats: str = "") -> str:
    """Check whether (company, title, ats) was already applied to.

    Hits the local SQLite `applications` table only — the cloud is the
    aggregate, the local DB is the source of truth for "did we already
    submit this?". Saves the ~90s round-trip of navigating to a known-
    duplicate ATS and waiting for "we already received your application."

    Returns a small JSON dict:
      {found: bool, status: <last status>, applied_at: <iso>, count: <int>}
    Match is case-insensitive on company; title is optional but if given
    it's matched as a substring (so "Senior ML Engineer" finds prior
    "ML Engineer" submissions). ats narrows further when provided.
    """
    from contextlib import closing as _closing
    from db import _get_local_conn
    where = ["LOWER(company) = LOWER(?)"]
    params: list = [company.strip()]
    if title:
        where.append("LOWER(role) LIKE ?")
        params.append(f"%{title.strip().lower()}%")
    if ats:
        where.append("LOWER(ats) = LOWER(?)")
        params.append(ats.strip())
    where.append("status IN ('submitted','applying','failed')")
    sql = (
        "SELECT status, applied_at, updated_at FROM applications "
        f"WHERE {' AND '.join(where)} "
        "ORDER BY COALESCE(applied_at, updated_at) DESC LIMIT 1"
    )
    count_sql = (
        "SELECT COUNT(*) FROM applications "
        f"WHERE {' AND '.join(where)}"
    )
    try:
        with _closing(_get_local_conn()) as conn:
            row = conn.execute(sql, params).fetchone()
            count_row = conn.execute(count_sql, params).fetchone()
    except Exception as e:
        return json.dumps({"error": str(e), "found": False})

    if not row:
        return json.dumps({"found": False, "count": 0})
    status, applied_at, updated_at = row
    return json.dumps({
        "found": True,
        "status": status,
        "applied_at": applied_at,
        "updated_at": updated_at,
        "count": int(count_row[0]) if count_row else 1,
    }, default=str)


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
    """Send a Telegram update. kind in {application_result, failure, scout_summary, session_event, generic}.
    Returns 'ok' on success or 'error: <detail>' on HTTP failure (401/403/timeout).
    The caller MUST surface an error response to the user — do NOT retry silently."""
    import httpx as _httpx
    from notifier import send_session_event, send_failure, send_application_result
    user_id = os.environ.get("APPLYLOOP_USER_ID", "")
    try:
        if kind == "application_result":
            job = {"company": company, "title": title}
            send_application_result(user_id, job, screenshot_url or None, profile_name=None)
        elif kind == "failure":
            send_failure(user_id, company, title, error, screenshot_url or None)
        else:
            send_session_event(user_id, kind, text)
        return "ok"
    except _httpx.HTTPStatusError as e:
        msg = f"Telegram HTTP {e.response.status_code}: {e.response.text[:200]}"
        logging.getLogger(__name__).error(msg)
        return f"error: {msg}"
    except Exception as e:
        msg = str(e)[:300]
        logging.getLogger(__name__).error(f"notify_telegram failed: {msg}")
        return f"error: {msg}"


# ── email (OTP + link reading via Himalaya CLI) ───────────────────────────

def _get_gmail_creds() -> tuple[str, str]:
    """Return (email, app_password) — always reads from .env file directly so
    that session-updated passwords are picked up without an MCP restart.
    Falls back to os.environ if the .env file is missing or the key is absent."""
    applyloop_home = os.environ.get("APPLYLOOP_HOME", os.path.expanduser("~/.applyloop"))
    env_file = os.path.join(applyloop_home, ".env")
    pairs: dict[str, str] = {}
    if os.path.isfile(env_file):
        try:
            with open(env_file, encoding="utf-8") as _f:
                for _line in _f:
                    _line = _line.strip()
                    if not _line or _line.startswith("#") or "=" not in _line:
                        continue
                    _k, _v = _line.split("=", 1)
                    pairs[_k.strip()] = _v.strip().strip('"').strip("'")
        except Exception:
            pass
    email = pairs.get("GMAIL_EMAIL") or os.environ.get("GMAIL_EMAIL", "")
    app_pw = pairs.get("GMAIL_APP_PASSWORD") or os.environ.get("GMAIL_APP_PASSWORD", "")
    return email, app_pw


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
    email, app_pw = _get_gmail_creds()
    if not email or not app_pw:
        return "error: GMAIL_EMAIL or GMAIL_APP_PASSWORD not set in ~/.applyloop/.env"
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
    email, app_pw = _get_gmail_creds()
    if not email or not app_pw:
        return "error: GMAIL_EMAIL or GMAIL_APP_PASSWORD not set in ~/.applyloop/.env"
    if not ensure_configured(email, app_pw):
        return "error: himalaya not installed or config write failed — run: brew install himalaya"
    link = find_link(sender_pattern, link_regex, timeout=timeout)
    return link or f"error: no link matching '{link_regex}' from '{sender_pattern}' within {timeout}s"


# ── worker lifecycle ──────────────────────────────────────────────────────
# Brain-callable wrappers around the desktop server's /api/worker/* HTTP
# endpoints. The python worker.py loop carries every per-ATS recipe in
# packages/worker/applier/*.py — Greenhouse dropzone uploads, Ashby
# combobox refresh, Workday multi-page wizard, etc. When it dies the
# brain loses all of that and has to reinvent each quirk in real time.
# These tools let the brain revive the loop instead of hand-driving.

def _desktop_url() -> str:
    explicit = os.environ.get("APPLYLOOP_DESKTOP_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    port = os.environ.get("APPLYLOOP_PORT", "18790").strip() or "18790"
    return f"http://127.0.0.1:{port}"


def _worker_api(method: str, path: str) -> dict:
    import httpx as _httpx
    url = _desktop_url() + path
    try:
        with _httpx.Client(timeout=15.0) as c:
            r = c.request(method, url)
        if r.status_code >= 400:
            return {"ok": False, "status": r.status_code, "error": (r.text or "")[:300]}
        try:
            return r.json()
        except Exception:
            return {"ok": True, "raw": (r.text or "")[:300]}
    except Exception as e:
        return {
            "ok": False,
            "error": f"could not reach desktop server at {url}: {e}",
            "hint": "Is the ApplyLoop desktop app running? Try `applyloop start`.",
        }


@mcp.tool()
def worker_status() -> str:
    """Report the python worker.py loop state: {running, pid, uptime,
    restart_count}. Call BEFORE hand-driving an apply — if running=true,
    use queue_claim_next + the worker's deterministic ATS recipes
    instead of MCP browser_* primitives."""
    return json.dumps(_worker_api("GET", "/api/worker/status"), default=str)


@mcp.tool()
def worker_start() -> str:
    """Start the python worker.py loop via the desktop FastAPI server.
    The worker reads the queue and applies jobs deterministically using
    ATS-specific recipes (way more reliable than driving the browser by
    hand through MCP). Returns {ok, pid, ...}."""
    return json.dumps(_worker_api("POST", "/api/worker/start"), default=str)


@mcp.tool()
def worker_stop() -> str:
    """Stop the python worker.py loop. SIGTERM with up to 10s graceful
    window before SIGKILL. Returns {ok, pid}."""
    return json.dumps(_worker_api("POST", "/api/worker/stop"), default=str)


@mcp.tool()
def worker_restart() -> str:
    """Stop-then-start the python worker.py loop. Use after pulling
    code or rotating credentials."""
    return json.dumps(_worker_api("POST", "/api/worker/restart"), default=str)


# ── local pipeline + scout url verification ───────────────────────────────

@mcp.tool()
def queue_get_local_pipeline(limit: int = 50, since_hours: int = 168) -> str:
    """Read recent rows from the LOCAL SQLite applications table.

    The cloud-backed queue_get_pipeline only sees discovered_jobs +
    application_queue rows; many submitted/failed/skipped applications
    live ONLY in local SQLite. Use this to answer "what have I applied
    to in the past <since_hours> hours" without calling
    queue_check_dedup once per company.

    Returns {since_hours, counts, submitted: [], failed: [], skipped: []}.
    Each row has {id, company, role, ats, url, applied_at, updated_at, notes}.
    """
    import sqlite3
    from contextlib import closing as _closing
    from db import LOCAL_DB_PATH
    rows: dict[str, list[dict]] = {"submitted": [], "failed": [], "skipped": []}
    try:
        with _closing(sqlite3.connect(LOCAL_DB_PATH, timeout=5.0)) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "SELECT id, company, role, url, ats, status, applied_at, updated_at, notes "
                "FROM applications "
                "WHERE status IN ('submitted','failed','skipped') "
                "  AND COALESCE(updated_at, applied_at) >= datetime('now', ?) "
                "ORDER BY COALESCE(updated_at, applied_at) DESC LIMIT ?",
                (f"-{int(since_hours)} hours", max(1, min(500, int(limit)))),
            )
            for r in cur.fetchall():
                bucket = rows.get(r["status"])
                if bucket is None:
                    continue
                bucket.append({
                    "id": r["id"], "company": r["company"], "role": r["role"],
                    "ats": r["ats"], "url": r["url"],
                    "applied_at": r["applied_at"], "updated_at": r["updated_at"],
                    "notes": r["notes"],
                })
    except Exception as e:
        return json.dumps({"error": f"local sqlite read failed: {e}", **{k: [] for k in rows}})
    return json.dumps(
        {"since_hours": since_hours,
         "counts": {k: len(v) for k, v in rows.items()},
         **rows},
        default=str,
    )


@mcp.tool()
def scout_verify_url(url: str) -> str:
    """Probe an apply URL — HEAD with redirect follow, falling back to
    GET if HEAD returns 405 or the body has to be sniffed. Returns
    {ok, status, final_url, reason}.

    Detects common dead-listing markers in the response body:
    'Job not found', 'this job is no longer', 'no longer accepting',
    'posting not found'. Ashby + Greenhouse return HTTP 200 on dead
    listings, so plain status-code checks aren't enough.

    Use BEFORE browser_navigate — a stale URL costs you a tab + a
    snapshot + an LLM step before the agent realizes the listing is
    dead.
    """
    import httpx as _httpx
    if not (url or "").strip():
        return json.dumps({"ok": False, "status": 0, "final_url": "", "reason": "empty_url"})
    try:
        with _httpx.Client(follow_redirects=True, timeout=8.0) as c:
            r = c.head(url)
            if r.status_code == 405:
                r = c.get(url)
            ok = 200 <= r.status_code < 400
            reason = "ok"
            if ok and "text/html" in (r.headers.get("content-type") or "").lower():
                try:
                    body = (c.get(str(r.url)).text if r.request.method == "HEAD" else (r.text or "")).lower()
                except Exception:
                    body = ""
                for marker in ("job not found", "this job is no longer",
                               "no longer accepting", "posting not found"):
                    if marker in body:
                        ok = False
                        reason = f"dead_marker:{marker}"
                        break
        return json.dumps({"ok": ok, "status": r.status_code,
                           "final_url": str(r.url), "reason": reason})
    except Exception as e:
        return json.dumps({"ok": False, "status": 0, "final_url": url,
                           "reason": f"exception:{type(e).__name__}:{e}"})


# ── knowledge ─────────────────────────────────────────────────────────────

@mcp.tool()
def knowledge_get_ats_playbook(name: str) -> str:
    """Return the ATS playbook section. Names: greenhouse, lever, ashby, smartrecruiters, workday, linkedin, universal.

    Hand-written prose AND any auto-recorded learned patterns for that
    ATS are merged in the section text — one call gets you everything
    the brain knows about this ATS.
    """
    section = load_ats_playbook(name.strip())
    if section is None:
        return json.dumps({"found": False, "name": name})
    return json.dumps({"found": True, "name": name, "section": section})


@mcp.tool()
def knowledge_record_pattern(
    ats: str,
    hostname: str,
    fields_json: str = "[]",
    quirks_json: str = "[]",
    notes: str = "",
) -> str:
    """Record a successful brain-driven apply on a (possibly novel)
    ATS so future applies are deterministic.

    CALL THIS RIGHT AFTER a successful apply on an ATS that the
    hand-written playbook doesn't deeply cover. Future brain runs
    pick up the entry via knowledge_get_ats_playbook automatically
    and won't re-derive the form.

    fields_json: JSON array of {label, selector, value_source,
        input_kind} dicts — capture the key fields you filled, in
        the order you filled them. Skip the boring ones (firstName /
        lastName / email) unless their selectors were non-obvious.
    quirks_json: JSON array of strings, each a free-text gotcha
        ("submit disabled until upload completes", "country needs
        React-Select fiber commit").
    notes: anything else worth knowing — multi-page wizard, a
        captcha kind, an unexpected validation, etc.
    """
    from knowledge.learned import record_pattern
    try:
        fields = json.loads(fields_json) if fields_json else []
        quirks = json.loads(quirks_json) if quirks_json else []
    except json.JSONDecodeError as e:
        return json.dumps({"ok": False, "error": f"invalid JSON: {e}"})
    if not isinstance(fields, list) or not isinstance(quirks, list):
        return json.dumps({"ok": False, "error": "fields_json and quirks_json must be JSON arrays"})
    return json.dumps(
        record_pattern(
            ats=ats, hostname=hostname,
            fields=fields, quirks=quirks, notes=notes,
        ),
        default=str,
    )


@mcp.tool()
def queue_claim_brain_fallback() -> str:
    """Claim the next job handed off for brain-driven apply.

    Two job sources land here:
      1. ATSes with no hardcoded recipe (iCIMS, Taleo, Jobvite, etc.)
         — worker.py marks them awaiting_brain on dispatch.
      2. Recipe-failed jobs when WORKER_BRAIN_FALLBACK=1 is set —
         worker.py routes the failure here instead of giving up.

    Returns the same job dict shape queue_claim_next gives you, plus
    a `fallback_reason` field describing WHY this job ended up in
    your hands. Returns {"empty": true} if nothing's waiting.

    Workflow after claiming:
      1. browser_navigate to apply_url, drive the form via primitives.
      2. On success: queue_log_application(submitted) +
         queue_update_status(submitted) + knowledge_record_pattern.
      3. On failure: queue_update_status(failed, error=...).

    The claim flips the row to 'applying' atomically so two brain
    sessions can't race on the same job.
    """
    import sqlite3
    from contextlib import closing as _closing
    from datetime import datetime, timezone
    from db import LOCAL_DB_PATH

    now = datetime.now(timezone.utc).isoformat()
    try:
        with _closing(sqlite3.connect(LOCAL_DB_PATH, timeout=5.0)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                UPDATE applications
                SET status = 'applying', updated_at = ?
                WHERE id = (
                    SELECT id FROM applications
                    WHERE status = 'skipped'
                      AND notes LIKE 'awaiting_brain:%'
                    ORDER BY scouted_at ASC
                    LIMIT 1
                )
                RETURNING id, company, role, url, ats, source, location,
                          posted_at, scouted_at, dedup_token, application_profile_id, notes
                """,
                (now,),
            ).fetchone()
            conn.commit()
    except Exception as e:
        return json.dumps({"error": f"local sqlite claim failed: {e}"})
    if not row:
        return json.dumps({"empty": True})
    external_id = ""
    dedup = row["dedup_token"]
    if dedup and "|" in dedup:
        external_id = dedup.split("|", 1)[1]
    return json.dumps(
        {
            "id": str(row["id"]),
            "company": row["company"] or "",
            "title": row["role"] or "",
            "ats": row["ats"] or "",
            "source": row["source"] or "",
            "apply_url": row["url"] or "",
            "location": row["location"] or "",
            "posted_at": row["posted_at"],
            "scouted_at": row["scouted_at"],
            "external_id": external_id,
            "application_profile_id": row["application_profile_id"],
            "fallback_reason": (row["notes"] or "").replace("awaiting_brain:", "", 1),
            "_local": True,
        },
        default=str,
    )


# ── entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Restore real stdout for the JSON-RPC transport. From here on, any
    # accidental Python print() writes to JSON-RPC — but the imports above
    # are audited and tool bodies never print, so this window is safe.
    sys.stdout = _REAL_STDOUT
    mcp.run(transport="stdio")
