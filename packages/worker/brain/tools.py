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
from brain.prompts import load_ats_playbook, load_operating_manual

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
    "browser_gateway_restart",
    "Restart the OpenClaw browser gateway. Use when browser_snapshot returns empty, the active tab keeps flipping to about:blank, or browser_click times out on visible elements — those are signs the Chrome session is wedged. Spawns a fresh Chrome and clears the bad state. Do NOT call mid-form (it kills any open tab); use between apply attempts.",
    {},
)
async def browser_gateway_restart(args: dict[str, Any]) -> dict:
    def _do():
        ok, detail = _browser.gateway_restart()
        return {"ok": ok, "detail": detail}
    return _log_and_run("browser_gateway_restart", {}, _do)


@tool(
    "browser_select_react",
    "Commit a value to a React-Select / fiber-driven combobox by walking the React fiber from `selector` and calling onChange directly. Use when a normal click on the option succeeds visually but the form still complains about a missing value (Greenhouse country dropdown, Ashby combobox).",
    {"selector": str, "label": str, "value": str},
)
async def browser_select_react(args: dict[str, Any]) -> dict:
    return _log_and_run(
        "browser_select_react", args,
        lambda: _browser.select_react_value(
            args["selector"], args["label"], args.get("value") or None,
        ),
    )


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


@tool(
    "queue_get_local_pipeline",
    "Read the LOCAL SQLite applications table directly — recent submitted/failed/skipped rows that the cloud-side queue_get_pipeline doesn't see. Use to answer 'what have I applied to this week' without per-company dedup probing.",
    {"limit": int, "since_hours": int},
)
async def queue_get_local_pipeline(args: dict[str, Any]) -> dict:
    def _do():
        import sqlite3
        from contextlib import closing
        from db import LOCAL_DB_PATH  # deferred
        limit = int(args.get("limit") or 50)
        since_hours = int(args.get("since_hours") or 168)  # default 7 days
        rows: dict[str, list[dict]] = {"submitted": [], "failed": [], "skipped": []}
        try:
            with closing(sqlite3.connect(LOCAL_DB_PATH, timeout=5.0)) as conn:
                conn.row_factory = sqlite3.Row
                # Pull recent rows ordered newest-first; bucket client-
                # side so a single query covers all three statuses.
                cur = conn.execute(
                    "SELECT id, company, role, url, ats, status, applied_at, updated_at, notes "
                    "FROM applications "
                    "WHERE status IN ('submitted','failed','skipped') "
                    "  AND COALESCE(updated_at, applied_at) >= datetime('now', ?) "
                    "ORDER BY COALESCE(updated_at, applied_at) DESC "
                    "LIMIT ?",
                    (f"-{since_hours} hours", max(1, min(500, limit))),
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
            return {"error": f"local sqlite read failed: {e}", "submitted": [], "failed": [], "skipped": []}
        return {
            "since_hours": since_hours,
            "counts": {k: len(v) for k, v in rows.items()},
            **rows,
        }
    return _log_and_run("queue_get_local_pipeline", args, _do)


# ───────── scout.* ────────────────────────────────────────────────────────

@tool("scout_list_sources", "List available scout sources (name, priority, requires_auth).", {})
async def scout_list_sources(args: dict[str, Any]) -> dict:
    def _do():
        from scout import REGISTERED_SOURCES  # deferred
        return {"sources": [{"name": s.name, "priority": s.priority, "requires_auth": s.requires_auth} for s in REGISTERED_SOURCES]}
    return _log_and_run("scout_list_sources", {}, _do)


@tool(
    "scout_verify_url",
    "Probe an apply URL to see if it's still live (HEAD with redirect follow). "
    "Returns {ok: bool, status: int, final_url: str, reason: str}. Use before "
    "navigating — Ashby/Greenhouse invalidate jobIds quickly and a stale URL "
    "wastes a tab + LLM steps.",
    {"url": str},
)
async def scout_verify_url(args: dict[str, Any]) -> dict:
    def _do():
        import re as _re
        import httpx as _httpx  # deferred
        url = (args.get("url") or "").strip()
        if not url:
            return {"ok": False, "status": 0, "final_url": "", "reason": "empty_url"}

        # Ashby / Greenhouse SPAs render the same HTML shell for live and
        # dead listings — body-sniffing misses the dead ones. For these
        # hosts hit the posting API instead and check authoritatively.
        ashby_re = _re.compile(
            r"^https?://jobs\.ashbyhq\.com/([^/]+)/(?:application\?jobId=)?([a-f0-9-]+)(?:/application)?/?$",
            _re.IGNORECASE,
        )
        gh_re = _re.compile(
            r"^https?://(?:www\.)?(?:boards|job-boards)\.greenhouse\.io/([^/]+)/jobs/(\d+)",
            _re.IGNORECASE,
        )
        try:
            m = ashby_re.match(url)
            if m:
                slug, job_id = m.group(1), m.group(2)
                with _httpx.Client(timeout=5.0, follow_redirects=True) as c:
                    r = c.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
                    if r.status_code != 200:
                        return {"ok": False, "status": r.status_code, "final_url": url,
                                "reason": f"ashby_api_status:{r.status_code}"}
                    for j in r.json().get("jobs", []) or []:
                        if j.get("id") == job_id:
                            if j.get("isListed") is False:
                                return {"ok": False, "status": 200, "final_url": url,
                                        "reason": "ashby_not_listed"}
                            return {"ok": True, "status": 200, "final_url": url,
                                    "reason": "ashby_api_listed"}
                    return {"ok": False, "status": 200, "final_url": url,
                            "reason": "ashby_id_not_in_board"}

            m = gh_re.match(url)
            if m:
                board, job_id = m.group(1), m.group(2)
                with _httpx.Client(timeout=5.0, follow_redirects=True) as c:
                    r = c.get(f"https://api.greenhouse.io/v1/boards/{board}/jobs/{job_id}")
                    if r.status_code == 200:
                        return {"ok": True, "status": 200, "final_url": url,
                                "reason": "greenhouse_api_listed"}
                    if r.status_code == 404:
                        return {"ok": False, "status": 404, "final_url": url,
                                "reason": "greenhouse_not_found"}
                    return {"ok": False, "status": r.status_code, "final_url": url,
                            "reason": f"greenhouse_api_status:{r.status_code}"}
        except Exception as e:
            return {"ok": False, "status": 0, "final_url": url,
                    "reason": f"api_exception:{type(e).__name__}:{e}"}

        try:
            # HEAD first; some ATSes serve 405 to HEAD, retry GET if so.
            with _httpx.Client(follow_redirects=True, timeout=8.0) as c:
                r = c.head(url)
                if r.status_code == 405:
                    r = c.get(url)
                ok = 200 <= r.status_code < 400
                reason = "ok"
                if ok and "text/html" in (r.headers.get("content-type") or "").lower():
                    try:
                        body = c.get(str(r.url)).text.lower() if r.request.method == "HEAD" else (r.text or "").lower()
                    except Exception:
                        body = ""
                    for marker in ("job not found", "this job is no longer", "no longer accepting", "posting not found"):
                        if marker in body:
                            ok = False
                            reason = f"dead_marker:{marker}"
                            break
            return {
                "ok": ok,
                "status": r.status_code,
                "final_url": str(r.url),
                "reason": reason,
            }
        except Exception as e:
            return {"ok": False, "status": 0, "final_url": url, "reason": f"exception:{type(e).__name__}:{e}"}
    return _log_and_run("scout_verify_url", args, _do)


@tool(
    "scout_set_plan",
    "Bias the next worker scout cycle. Brain calls this when it has "
    "signal that some sources are noisy / rate-limited / low-yield, OR "
    "to dedupe / narrow the tenant's search query list. `sources_json` "
    "is a JSON array of source NAMES (greenhouse, ashby, lever, "
    "linkedin_public, jsearch, himalayas, etc.) — null/empty = run all "
    "enabled. `queries_json` is a JSON array of search strings to use "
    "INSTEAD of tenant.search_queries — null/empty = keep tenant defaults. "
    "`max_per_source` caps results per source (None = unlimited). "
    "`ttl_minutes` is how long the plan stays in force (default 240 = "
    "4 hrs); after expiry, worker reverts to defaults. ALWAYS pass a "
    "`notes` string explaining WHY — future you (or the operator) "
    "needs to debug 'why didn't scout run X today'.",
    {"sources_json": str, "queries_json": str, "max_per_source": int, "ttl_minutes": int, "notes": str},
)
async def scout_set_plan(args: dict[str, Any]) -> dict:
    def _do():
        from scout.plan import set_plan  # deferred
        try:
            sources = json.loads(args.get("sources_json") or "null")
            queries = json.loads(args.get("queries_json") or "null")
        except json.JSONDecodeError as e:
            return {"ok": False, "error": f"invalid JSON in sources_json/queries_json: {e}"}
        return set_plan(
            sources=sources if sources else None,
            queries=queries if queries else None,
            max_per_source=args.get("max_per_source") or None,
            ttl_minutes=args.get("ttl_minutes") or 240,
            notes=args.get("notes") or "",
            set_by="brain",
        )
    return _log_and_run("scout_set_plan", args, _do)


@tool(
    "scout_get_plan",
    "Read the current scout plan (None / empty if no active plan or it's expired). Useful for the brain to inspect what bias is currently applied before deciding to overwrite.",
    {},
)
async def scout_get_plan(args: dict[str, Any]) -> dict:
    def _do():
        from scout.plan import get_active_plan, _read  # deferred
        active = get_active_plan()
        return {
            "active": active,
            "raw_present": _read() is not None,
            "is_stale": active is None and _read() is not None,
        }
    return _log_and_run("scout_get_plan", {}, _do)


@tool(
    "scout_clear_plan",
    "Remove the scout plan immediately (don't wait for TTL). Worker "
    "reverts to default REGISTERED_SOURCES + tenant.search_queries on "
    "the next cycle.",
    {},
)
async def scout_clear_plan(args: dict[str, Any]) -> dict:
    def _do():
        from scout.plan import clear_plan  # deferred
        return {"cleared": clear_plan()}
    return _log_and_run("scout_clear_plan", {}, _do)


@tool(
    "scout_get_stats",
    "Read scout/apply stats from the local SQLite to inform scout-plan "
    "decisions. Returns per-source enqueue counts + per-ATS submission "
    "counts over the last `since_hours` (default 168 = 7d). Brain uses "
    "this to decide which sources are worth running today: a source "
    "with high enqueue count but zero submitted is probably noisy; "
    "zero enqueued in 24h means it's rate-limited or broken.",
    {"since_hours": int},
)
async def scout_get_stats(args: dict[str, Any]) -> dict:
    def _do():
        import sqlite3
        from contextlib import closing as _closing
        from db import LOCAL_DB_PATH  # deferred
        since_hours = int(args.get("since_hours") or 168)
        out: dict[str, Any] = {"since_hours": since_hours, "by_source": {}, "by_ats": {}}
        try:
            with _closing(sqlite3.connect(LOCAL_DB_PATH, timeout=5.0)) as conn:
                # by source — count rows per source over the window
                cur = conn.execute(
                    "SELECT COALESCE(source,''), status, COUNT(*) FROM applications "
                    "WHERE COALESCE(updated_at, applied_at, scouted_at) >= datetime('now', ?) "
                    "GROUP BY 1, 2",
                    (f"-{since_hours} hours",),
                )
                for src, status, n in cur.fetchall():
                    out["by_source"].setdefault(src or "(none)", {})[status] = n
                cur = conn.execute(
                    "SELECT COALESCE(ats,''), status, COUNT(*) FROM applications "
                    "WHERE COALESCE(updated_at, applied_at, scouted_at) >= datetime('now', ?) "
                    "GROUP BY 1, 2",
                    (f"-{since_hours} hours",),
                )
                for ats_v, status, n in cur.fetchall():
                    out["by_ats"].setdefault(ats_v or "(none)", {})[status] = n
        except Exception as e:
            return {"error": f"local sqlite read failed: {e}", **out}
        return out
    return _log_and_run("scout_get_stats", args, _do)


@tool(
    "scout_search_google",
    "Search the web (DuckDuckGo HTML — no API key) for query and return "
    "the top results. Use to find ATS slugs / company career pages / "
    "verify a job exists when scout returned a stale URL. Returns "
    "`[{title, url, snippet}, ...]`. Defaults to 10 results.",
    {"query": str, "max_results": int},
)
async def scout_search_google(args: dict[str, Any]) -> dict:
    def _do():
        import re as _re
        import httpx as _httpx
        q = (args.get("query") or "").strip()
        if not q:
            return {"error": "query is required"}
        max_results = int(args.get("max_results") or 10)
        # DDG HTML endpoint — stable, no auth, returns scrapable HTML.
        # Avoids hitting Google directly (which requires API keys + has
        # aggressive bot detection).
        url = "https://duckduckgo.com/html/"
        try:
            with _httpx.Client(timeout=10.0, follow_redirects=True,
                               headers={"User-Agent": "Mozilla/5.0 (ApplyLoop scout)"}) as c:
                r = c.post(url, data={"q": q})
                html = r.text
        except Exception as e:
            return {"error": f"http error: {e}"}
        # Lightweight extraction: <a class="result__a" href="...">title</a>
        # plus <a class="result__snippet">snippet</a>. DDG's HTML shape
        # is stable enough for this; a real upgrade would parse with bs4
        # but adding a dep is overkill.
        results = []
        for m in _re.finditer(
            r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            html, _re.DOTALL,
        ):
            href = m.group(1)
            title = _re.sub(r"<[^>]+>", "", m.group(2)).strip()
            # DDG sometimes wraps the real URL in /l/?kh=-1&uddg=<encoded>
            if "uddg=" in href:
                from urllib.parse import unquote, parse_qs, urlparse
                qs = parse_qs(urlparse(href).query)
                href = unquote(qs.get("uddg", [href])[0])
            results.append({"title": title, "url": href, "snippet": ""})
            if len(results) >= max_results:
                break
        return {"query": q, "count": len(results), "results": results}
    return _log_and_run("scout_search_google", args, _do)


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


# ───────── worker.* ───────────────────────────────────────────────────────
# Lifecycle of the python worker.py loop, controlled via the desktop
# server's HTTP API (FastAPI on APPLYLOOP_PORT, default 18790). Brain
# couldn't previously revive a dead worker — it had to fall back to
# hand-driving the browser via MCP, which loses every per-ATS recipe
# encoded in packages/worker/applier/*.py. These tools restore parity.

def _desktop_url() -> str:
    """Resolve the local desktop FastAPI base URL.

    Priority:
      1. APPLYLOOP_DESKTOP_URL env var (explicit override).
      2. APPLYLOOP_PORT (matches packages/desktop/launch.py).
      3. 18790 (the install.sh / launch.py default).

    Always 127.0.0.1 — the desktop server binds locally only.
    """
    explicit = os.environ.get("APPLYLOOP_DESKTOP_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    port = os.environ.get("APPLYLOOP_PORT", "18790").strip() or "18790"
    return f"http://127.0.0.1:{port}"


def _worker_api(method: str, path: str) -> dict:
    """One-shot HTTP call to the desktop worker API. Short timeout —
    worker.start can spawn a subprocess in <2s; status is instant; stop
    waits up to 10s for graceful SIGTERM in process_manager but we
    don't block the brain on that."""
    import httpx as _httpx  # deferred
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


@tool(
    "worker_status",
    "Report the python worker.py loop state: running, pid, uptime, restart_count. "
    "Use BEFORE starting a hand-driven apply — if running=true, claim a queue row "
    "via queue_claim_next instead; the worker will handle ATS-specific quirks "
    "(React-Select, dropzone uploads, multi-page wizards) that brain has to work "
    "around manually.",
    {},
)
async def worker_status(args: dict[str, Any]) -> dict:
    return _log_and_run("worker_status", {}, lambda: _worker_api("GET", "/api/worker/status"))


@tool(
    "worker_start",
    "Start the python worker.py loop via the desktop server. The worker reads "
    "the queue and applies jobs deterministically using the ATS-specific "
    "recipes in packages/worker/applier/*.py — much more reliable than hand-"
    "driving the browser through MCP. Returns {ok, pid, ...}.",
    {},
)
async def worker_start(args: dict[str, Any]) -> dict:
    return _log_and_run("worker_start", {}, lambda: _worker_api("POST", "/api/worker/start"))


@tool(
    "worker_stop",
    "Stop the python worker.py loop. Returns {ok, pid}. Sends SIGTERM with up "
    "to 10s graceful window before SIGKILL.",
    {},
)
async def worker_stop(args: dict[str, Any]) -> dict:
    return _log_and_run("worker_stop", {}, lambda: _worker_api("POST", "/api/worker/stop"))


@tool(
    "worker_restart",
    "Stop-then-start the python worker.py loop. Use after pulling code or "
    "rotating credentials.",
    {},
)
async def worker_restart(args: dict[str, Any]) -> dict:
    return _log_and_run("worker_restart", {}, lambda: _worker_api("POST", "/api/worker/restart"))


# ───────── knowledge.* ────────────────────────────────────────────────────

@tool(
    "knowledge_record_pattern",
    "Record a successful brain-driven apply on a (possibly novel) ATS so future applies are deterministic. Call this RIGHT AFTER you log a successful application on an ATS that wasn't already deeply covered by the hand-written playbook. `fields` is a list of {label, selector, value_source, input_kind} — capture the key form fields you filled, in the order you filled them. `quirks` is a list of free-text gotchas (\"submit button is disabled until upload completes\", \"country dropdown needs React-Select fiber commit\"). `notes` is anything else worth knowing.",
    {"ats": str, "hostname": str, "fields": str, "quirks": str, "notes": str},
)
async def knowledge_record_pattern(args: dict[str, Any]) -> dict:
    def _do():
        from knowledge.learned import record_pattern  # deferred
        # fields/quirks come in as JSON strings (MCP scalar contract).
        # Tolerate raw lists too in case the SDK ever upgrades.
        fields_raw = args.get("fields") or "[]"
        quirks_raw = args.get("quirks") or "[]"
        try:
            fields = json.loads(fields_raw) if isinstance(fields_raw, str) else list(fields_raw)
        except json.JSONDecodeError:
            return {"ok": False, "error": "fields must be a JSON array"}
        try:
            quirks = json.loads(quirks_raw) if isinstance(quirks_raw, str) else list(quirks_raw)
        except json.JSONDecodeError:
            return {"ok": False, "error": "quirks must be a JSON array"}
        return record_pattern(
            ats=args.get("ats", ""),
            hostname=args.get("hostname", ""),
            fields=fields,
            quirks=quirks,
            notes=args.get("notes", "") or "",
        )
    return _log_and_run("knowledge_record_pattern", args, _do)


@tool(
    "worker_apply_one_job",
    "Run preflight + apply for ONE job synchronously. This is the brain-as-conductor path: brain calls this in a loop, gets a structured outcome each time, decides what to do next based on the outcome's `status` field. No daemon required. Outcome shapes: submitted (recipe applied successfully) | handoff (recipe missing or failed → brain should drive next, browser is on the failed page) | skipped (preflight rejected: blocked, rate-limited, daily cap) | empty (queue had nothing to claim) | profile_gap (user setup incomplete) | auth_expired | error. When status='handoff', `handoff_reason` is set (no_recipe / recipe_failed) and the queue row is marked `awaiting_brain` so a future call to queue_claim_brain_fallback will pick it up — OR brain can drive immediately right now since the browser is still open. `job_id` is optional (specific row); omit to claim oldest queued.",
    {"job_id": str, "enable_brain_fallback": bool},
)
async def worker_apply_one_job(args: dict[str, Any]) -> dict:
    def _do():
        from single_apply import apply_one_job  # deferred
        return apply_one_job(
            job_id=args.get("job_id") or None,
            enable_brain_fallback=args.get("enable_brain_fallback", True),
        )
    return _log_and_run("worker_apply_one_job", args, _do)


@tool(
    "worker_run_scout_cycle",
    "Run one scout → enqueue cycle synchronously. Honors the active "
    "scout_set_plan if any. Returns counts so brain can decide whether "
    "to scout again, change the plan, or move on to applying. No "
    "daemon required.",
    {},
)
async def worker_run_scout_cycle(args: dict[str, Any]) -> dict:
    def _do():
        from tenant import TenantConfig  # deferred
        from worker import run_scout_cycle  # deferred
        user_id = os.environ.get("APPLYLOOP_USER_ID", "").strip()
        if not user_id:
            return {"error": "APPLYLOOP_USER_ID not set"}
        try:
            tenant = TenantConfig.load(user_id)
        except Exception as e:
            return {"error": f"tenant load failed: {e}"}
        enqueued = run_scout_cycle(tenant)
        return {"enqueued": int(enqueued or 0)}
    return _log_and_run("worker_run_scout_cycle", {}, _do)


@tool(
    "queue_claim_brain_fallback",
    "Claim the next job that's been handed off for brain-driven apply. Returns the same job dict shape queue_claim_next gives you, or {empty: true} if nothing's waiting. Two sources: (a) ATSes with no hardcoded recipe (iCIMS, Taleo, Jobvite, etc.) and (b) recipe-failed jobs when WORKER_BRAIN_FALLBACK is enabled. After driving the apply, call queue_log_application + queue_update_status as usual; on success, call knowledge_record_pattern so the next apply on this ATS doesn't need to re-derive everything.",
    {},
)
async def queue_claim_brain_fallback(args: dict[str, Any]) -> dict:
    def _do():
        import sqlite3
        from contextlib import closing as _closing
        from datetime import datetime, timezone
        from db import LOCAL_DB_PATH  # deferred
        # Atomic-ish: pull the oldest 'skipped' row whose notes are the
        # awaiting_brain marker, then flip its status to 'applying' so
        # we don't hand the same job to two brain sessions. SQLite's
        # UPDATE...RETURNING gives us the row + the status flip in one
        # statement.
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
            return {"error": f"local sqlite claim failed: {e}"}
        if not row:
            return {"empty": True}
        external_id = ""
        dedup = row["dedup_token"]
        if dedup and "|" in dedup:
            external_id = dedup.split("|", 1)[1]
        return {
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
        }
    return _log_and_run("queue_claim_brain_fallback", {}, _do)


@tool(
    "brain_get_operating_manual",
    "Return the brain's full operating manual — your mission spec. The "
    "PTY already injects it as the system prompt at session start, so "
    "you have it. Re-read it MID-SESSION via this tool when you feel "
    "uncertain about the loop / outcomes / browser hygiene / recovery "
    "rules. Cheap (one file read), no side effects.",
    {},
)
async def brain_get_operating_manual(args: dict[str, Any]) -> dict:
    def _do():
        manual = load_operating_manual()
        return {"found": manual is not None, "manual": manual or ""}
    return _log_and_run("brain_get_operating_manual", {}, _do)


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
    browser_fill, browser_select, browser_select_react, browser_type,
    browser_upload, browser_press_key, browser_evaluate_js,
    browser_gateway_restart,
    browser_screenshot, browser_list_tabs, browser_dismiss_stray_tabs,
    # queue
    queue_claim_next, queue_update_status, queue_log_application,
    queue_get_pipeline, queue_get_local_pipeline,
    # scout
    scout_list_sources, scout_run_source, scout_verify_url,
    scout_set_plan, scout_get_plan, scout_clear_plan,
    scout_get_stats, scout_search_google,
    # tenant
    tenant_load,
    # notify
    notify_heartbeat, notify_upload_screenshot, notify_telegram,
    # worker lifecycle
    worker_status, worker_start, worker_stop, worker_restart,
    # brain-as-conductor (single-job + scout, no daemon required)
    worker_apply_one_job, worker_run_scout_cycle,
    # knowledge
    knowledge_get_ats_playbook, knowledge_record_pattern,
    brain_get_operating_manual,
    # brain fallback
    queue_claim_brain_fallback,
]


def build_server():
    """Return the MCP server config the SDK expects in
    `ClaudeAgentOptions.mcp_servers`."""
    return create_sdk_mcp_server(name="applyloop", version="0.1.0", tools=ALL_TOOLS)


def allowed_tool_names() -> list[str]:
    """Names in the `mcp__applyloop__<tool>` form the SDK expects in
    `allowed_tools`. Every tool decorated above is whitelisted."""
    return [f"mcp__applyloop__{t.name}" for t in ALL_TOOLS]
