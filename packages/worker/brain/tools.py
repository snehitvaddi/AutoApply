"""MCP tools exposed to the ApplyLoop brain.

Each `@tool` is an async wrapper around an existing helper in
`applier/browser.py`, `db.py`, `scout/__init__.py`, `notifier.py`,
`tenant.py`, or `knowledge/ats-playbook.md`. The brain cannot do
anything the Python layer doesn't already know how to do — this file
is the surface, not new behavior.

Convention: tool handlers catch their own exceptions and return
`{"content": [{"type": "text", "text": <str>}], "is_error": True}` on
failure, so the SDK agent loop keeps making progress instead of
halting on a raised exception.
"""
from __future__ import annotations

import json
import os
import logging
from typing import Any

from claude_agent_sdk import tool, create_sdk_mcp_server

from applier import browser as _browser
from brain import session_log
from brain.prompts import load_ats_playbook

logger = logging.getLogger(__name__)


# ───────── helpers ────────────────────────────────────────────────────────

def _ok(text: str | dict) -> dict:
    if isinstance(text, dict):
        text = json.dumps(text, default=str)
    return {"content": [{"type": "text", "text": text}]}


def _err(msg: str) -> dict:
    return {"content": [{"type": "text", "text": msg}], "is_error": True}


def _log_and_run(name: str, args: dict, fn):
    session_log.log_tool_call(name, args)
    try:
        result = fn()
    except Exception as e:
        session_log.log_error(name, str(e))
        return _err(f"{name} failed: {e}")
    session_log.log_tool_result(name, result if isinstance(result, (dict, str)) else str(result))
    return _ok(result if isinstance(result, (dict, str)) else str(result))


# ───────── browser.* ──────────────────────────────────────────────────────

@tool("browser_navigate", "Navigate the browser to a URL.", {"url": str})
async def browser_navigate(args: dict[str, Any]) -> dict:
    return _log_and_run("browser_navigate", args, lambda: _browser.navigate_url(args["url"]))


@tool("browser_wait_load", "Wait for network-idle up to timeout_ms.", {"timeout_ms": int})
async def browser_wait_load(args: dict[str, Any]) -> dict:
    ms = int(args.get("timeout_ms") or 5000)
    return _log_and_run("browser_wait_load", {"timeout_ms": ms}, lambda: (_browser.wait_load(ms) or "ok"))


@tool(
    "browser_snapshot",
    "Take an accessibility snapshot of the current page. Returns both the raw tree and a parsed list of {ref, label, type} elements.",
    {},
)
async def browser_snapshot(args: dict[str, Any]) -> dict:
    def _do():
        raw = _browser.snapshot()
        fields = _browser.parse_snapshot(raw) if raw else []
        return {"raw": raw, "fields": fields, "field_count": len(fields)}
    return _log_and_run("browser_snapshot", {}, _do)


@tool("browser_click", "Click an element by its ref (e.g. 'e42').", {"ref": str})
async def browser_click(args: dict[str, Any]) -> dict:
    return _log_and_run("browser_click", args, lambda: _browser.click_ref(args["ref"]))


@tool(
    "browser_fill",
    "Fill multiple text fields at once. `fields` is a JSON array of {ref, type, value} — type is usually 'textbox'.",
    {"fields": str},
)
async def browser_fill(args: dict[str, Any]) -> dict:
    return _log_and_run("browser_fill", args, lambda: _browser.fill_fields(args["fields"]))


@tool("browser_select", "Select an option in a native <select>.", {"ref": str, "value": str})
async def browser_select(args: dict[str, Any]) -> dict:
    return _log_and_run("browser_select", args, lambda: _browser.select_option(args["ref"], args["value"]))


@tool("browser_type", "Type text into a React/SPA input field (fires synthetic events).", {"ref": str, "text": str})
async def browser_type(args: dict[str, Any]) -> dict:
    return _log_and_run("browser_type", args, lambda: _browser.type_into(args["ref"], args["text"]))


@tool("browser_upload", "Upload a local file. `path` is absolute, `ref` is the click-target (e.g. 'Resume' button).", {"path": str, "ref": str})
async def browser_upload(args: dict[str, Any]) -> dict:
    return _log_and_run("browser_upload", args, lambda: _browser.upload_file(args["path"], args["ref"]))


@tool("browser_press_key", "Press one key (e.g. 'Enter', 'Tab', 'End').", {"key": str})
async def browser_press_key(args: dict[str, Any]) -> dict:
    return _log_and_run("browser_press_key", args, lambda: _browser.press_key(args["key"]))


@tool(
    "browser_evaluate_js",
    "Run an arrow function against the page. Use for edge cases the standard verbs can't reach (controlled React components, shadow DOM, synthetic events). `code` must be a self-contained `() => { ... }`.",
    {"code": str},
)
async def browser_evaluate_js(args: dict[str, Any]) -> dict:
    return _log_and_run("browser_evaluate_js", args, lambda: _browser.evaluate_js(args["code"]))


@tool("browser_screenshot", "Take a full-page PNG. Returns the local file path.", {})
async def browser_screenshot(args: dict[str, Any]) -> dict:
    return _log_and_run("browser_screenshot", {}, lambda: (_browser.take_screenshot() or ""))


@tool("browser_list_tabs", "List all currently open browser tabs (for detecting popup hijacks).", {})
async def browser_list_tabs(args: dict[str, Any]) -> dict:
    return _log_and_run("browser_list_tabs", {}, lambda: {"tabs": _browser.list_tabs()})


@tool(
    "browser_dismiss_stray_tabs",
    "Close any tab whose URL does not contain `keep_url_substring` (usually the apply ATS hostname). Popups opened by privacy/terms links stole focus from Roblox-class flows — call this between steps.",
    {"keep_url_substring": str},
)
async def browser_dismiss_stray_tabs(args: dict[str, Any]) -> dict:
    keep = args.get("keep_url_substring") or None
    return _log_and_run(
        "browser_dismiss_stray_tabs",
        {"keep_url_substring": keep},
        lambda: {"closed": _browser.dismiss_stray_tabs(keep)},
    )


# ───────── queue.* ────────────────────────────────────────────────────────
# Deferred imports so `brain.tools` can be imported for `--dry-run` (list
# tools) without blowing up when db.py's sqlite + supabase deps aren't set.


@tool("queue_claim_next", "Claim the next pending job for this worker. Returns the locked row or {empty: true}.", {})
async def queue_claim_next(args: dict[str, Any]) -> dict:
    def _do():
        from worker import claim_next_job_locally, WORKER_ID  # deferred
        user_id = os.environ.get("APPLYLOOP_USER_ID", "")
        job = claim_next_job_locally(user_id, WORKER_ID)
        return job or {"empty": True}
    return _log_and_run("queue_claim_next", {}, _do)


@tool(
    "queue_update_status",
    "Update an application_queue row. status in {pending,submitted,failed,cancelled}. Optional error string. Optional attempts integer.",
    {"queue_id": str, "status": str, "error": str, "attempts": int},
)
async def queue_update_status(args: dict[str, Any]) -> dict:
    def _do():
        from db import update_queue_status  # deferred
        update_queue_status(
            args["queue_id"], args["status"],
            error=args.get("error") or None,
            attempts=args.get("attempts"),
        )
        return "ok"
    return _log_and_run("queue_update_status", args, _do)


@tool(
    "queue_log_application",
    "Log an application outcome. Mirrors db.log_application — writes local SQLite + best-effort cloud insert.",
    {"job_id": str, "queue_id": str, "company": str, "title": str, "ats": str, "apply_url": str, "status": str, "screenshot_url": str, "error": str},
)
async def queue_log_application(args: dict[str, Any]) -> dict:
    def _do():
        from db import log_application  # deferred
        user_id = os.environ.get("APPLYLOOP_USER_ID", "")
        job = {
            "job_id": args.get("job_id"),
            "id": args.get("queue_id"),
            "company": args.get("company", ""),
            "title": args.get("title", ""),
            "ats": args.get("ats", ""),
            "apply_url": args.get("apply_url", ""),
        }
        result = {
            "status": args.get("status", "submitted"),
            "screenshot_url": args.get("screenshot_url") or None,
            "error": args.get("error") or None,
        }
        log_application(user_id, job, result)
        return "ok"
    return _log_and_run("queue_log_application", args, _do)


@tool("queue_get_pipeline", "Return queue counts per status + recent rows for situational awareness.", {})
async def queue_get_pipeline(args: dict[str, Any]) -> dict:
    def _do():
        from db import _api_call  # deferred
        return _api_call("get_pipeline") or {}
    return _log_and_run("queue_get_pipeline", {}, _do)


# ───────── scout.* ────────────────────────────────────────────────────────

@tool("scout_list_sources", "List available scout sources (name, priority, requires_auth).", {})
async def scout_list_sources(args: dict[str, Any]) -> dict:
    def _do():
        from scout import REGISTERED_SOURCES  # deferred
        return {"sources": [{"name": s.name, "priority": s.priority, "requires_auth": s.requires_auth} for s in REGISTERED_SOURCES]}
    return _log_and_run("scout_list_sources", {}, _do)


@tool("scout_run_source", "Run one scout source against the current tenant. Returns the list of JobPost dicts (pre-enqueue).", {"name": str})
async def scout_run_source(args: dict[str, Any]) -> dict:
    def _do():
        from scout import REGISTERED_SOURCES  # deferred
        from tenant import TenantConfig  # deferred
        user_id = os.environ.get("APPLYLOOP_USER_ID", "")
        tenant = TenantConfig.load(user_id)
        name = args["name"]
        source = next((s for s in REGISTERED_SOURCES if s.name == name), None)
        if source is None:
            return {"error": f"unknown source: {name}", "available": [s.name for s in REGISTERED_SOURCES]}
        jobs = source.scout(tenant) or []
        return {"count": len(jobs), "jobs": jobs[:50]}  # cap the payload
    return _log_and_run("scout_run_source", args, _do)


# ───────── tenant.* ───────────────────────────────────────────────────────

@tool("tenant_load", "Load the current tenant config snapshot (profiles, resumes, daily limits).", {})
async def tenant_load(args: dict[str, Any]) -> dict:
    def _do():
        from tenant import TenantConfig  # deferred
        user_id = os.environ.get("APPLYLOOP_USER_ID", "")
        t = TenantConfig.load(user_id)
        return {
            "user_id": user_id,
            "search_queries": list(t.search_queries),
            "preferred_locations": list(t.preferred_locations),
            "profiles": [{"id": p.id, "name": p.name, "is_default": p.is_default} for p in getattr(t, "profiles", [])],
            "daily_apply_limit": getattr(t, "daily_apply_limit", None),
        }
    return _log_and_run("tenant_load", {}, _do)


# ───────── notify.* ───────────────────────────────────────────────────────

@tool("notify_heartbeat", "Send a heartbeat so the dashboard shows you're alive.", {"last_action": str, "details": str})
async def notify_heartbeat(args: dict[str, Any]) -> dict:
    def _do():
        from db import update_heartbeat  # deferred
        user_id = os.environ.get("APPLYLOOP_USER_ID", "")
        update_heartbeat(user_id, args.get("last_action", ""), args.get("details", ""))
        return "ok"
    return _log_and_run("notify_heartbeat", args, _do)


@tool("notify_upload_screenshot", "Upload a local PNG to Supabase storage; returns a 7-day signed URL.", {"local_path": str})
async def notify_upload_screenshot(args: dict[str, Any]) -> dict:
    def _do():
        from db import upload_screenshot  # deferred
        user_id = os.environ.get("APPLYLOOP_USER_ID", "")
        url = upload_screenshot(user_id, args["local_path"])
        return {"url": url}
    return _log_and_run("notify_upload_screenshot", args, _do)


@tool(
    "notify_telegram",
    "Send a Telegram update. kind in {application_result, failure, scout_summary, session_event, generic}.",
    {"kind": str, "company": str, "title": str, "error": str, "screenshot_url": str, "text": str},
)
async def notify_telegram(args: dict[str, Any]) -> dict:
    def _do():
        from notifier import send_session_event, send_failure, send_application_result  # deferred
        user_id = os.environ.get("APPLYLOOP_USER_ID", "")
        kind = args.get("kind", "generic")
        if kind == "application_result":
            job = {"company": args.get("company", ""), "title": args.get("title", "")}
            send_application_result(user_id, job, args.get("screenshot_url"), profile_name=None)
        elif kind == "failure":
            send_failure(user_id, args.get("company", ""), args.get("title", ""), args.get("error", ""), args.get("screenshot_url"))
        else:
            send_session_event(user_id, kind, args.get("text", ""))
        return "ok"
    return _log_and_run("notify_telegram", args, _do)


# ───────── knowledge.* ────────────────────────────────────────────────────

@tool(
    "knowledge_get_ats_playbook",
    "Return the operator playbook section for one ATS. Names: greenhouse, lever, ashby, smartrecruiters, workday, linkedin, universal.",
    {"name": str},
)
async def knowledge_get_ats_playbook(args: dict[str, Any]) -> dict:
    def _do():
        name = args.get("name", "").strip()
        section = load_ats_playbook(name)
        if section is None:
            return {"found": False, "name": name}
        return {"found": True, "name": name, "section": section}
    return _log_and_run("knowledge_get_ats_playbook", args, _do)


# ───────── server assembly ────────────────────────────────────────────────

ALL_TOOLS = [
    # browser
    browser_navigate, browser_wait_load, browser_snapshot, browser_click,
    browser_fill, browser_select, browser_type, browser_upload,
    browser_press_key, browser_evaluate_js, browser_screenshot,
    browser_list_tabs, browser_dismiss_stray_tabs,
    # queue
    queue_claim_next, queue_update_status, queue_log_application,
    queue_get_pipeline,
    # scout
    scout_list_sources, scout_run_source,
    # tenant
    tenant_load,
    # notify
    notify_heartbeat, notify_upload_screenshot, notify_telegram,
    # knowledge
    knowledge_get_ats_playbook,
]


def build_server():
    """Return the MCP server config the SDK expects in
    `ClaudeAgentOptions.mcp_servers`."""
    return create_sdk_mcp_server(name="applyloop", version="0.1.0", tools=ALL_TOOLS)


def allowed_tool_names() -> list[str]:
    """Names in the `mcp__applyloop__<tool>` form the SDK expects in
    `allowed_tools`. Every tool decorated above is whitelisted."""
    return [f"mcp__applyloop__{t.name}" for t in ALL_TOOLS]
