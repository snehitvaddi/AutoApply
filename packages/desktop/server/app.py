"""ApplyLoop Desktop — FastAPI backend server."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .config import load_token, APP_URL
from . import local_data
from .pty_terminal import pty_terminal_websocket, session_manager

# Static UI build directory (Next.js static export → /out)
# Check multiple locations: .app bundle Resources, or dev location
_server_dir = Path(__file__).resolve().parent
UI_BUILD_DIR = None
for _candidate in [
    _server_dir.parent / "ui" / "out",          # .app bundle: Resources/ui/out
    _server_dir.parent.parent / "ui" / "out",    # dev: packages/desktop/ui/out (extra level)
]:
    if _candidate.exists() and (_candidate / "index.html").exists():
        UI_BUILD_DIR = _candidate
        break
from .process_manager import worker
from .terminal_stream import terminal_websocket
from .chat_bridge import chat_websocket, session as cli_session
from . import stats

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
)
logger = logging.getLogger("desktop-server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    token = load_token()
    if token:
        logger.info("API token loaded")
    else:
        logger.warning("No API token found — set AUTOAPPLY_TOKEN or create ~/.autoapply/workspace/.api-token")
    logger.info(f"Remote API: {APP_URL}")
    yield
    # Cleanup: stop worker and CLI session
    if cli_session.is_alive:
        logger.info("Shutting down CLI session...")
        await cli_session.stop()
    if worker.is_running:
        logger.info("Shutting down worker...")
        await worker.stop()


app = FastAPI(title="ApplyLoop Desktop", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"ok": True, "worker": worker.status()}


# ── Auth ─────────────────────────────────────────────────────────────────────

@app.get("/api/auth/token-masked")
async def get_masked_token():
    """Return the saved token with middle characters masked."""
    token = load_token()
    if not token:
        return {"has_token": False, "masked": ""}
    if len(token) > 10:
        masked = token[:6] + "•" * (len(token) - 10) + token[-4:]
    else:
        masked = token[:2] + "•" * max(0, len(token) - 4) + token[-2:] if len(token) > 4 else "••••"
    return {"has_token": True, "masked": masked}


@app.get("/api/auth/status")
async def auth_status():
    token = load_token()
    if not token:
        return {"authenticated": False}
    try:
        profile = await stats.get_settings_profile()
        return {"authenticated": True, "profile": profile.get("data", {})}
    except Exception:
        return {"authenticated": False, "error": "Invalid token"}


@app.post("/api/auth/token")
async def set_token(body: dict):
    """Save API token to disk."""
    from .config import TOKEN_FILE
    token = body.get("token", "").strip()
    if not token:
        return {"ok": False, "error": "Token is required"}
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(token)
    TOKEN_FILE.chmod(0o600)
    return {"ok": True}


# ── Worker Control ───────────────────────────────────────────────────────────

@app.get("/api/worker/status")
async def worker_status():
    return worker.status()


@app.post("/api/worker/start")
async def worker_start():
    return await worker.start()


@app.post("/api/worker/stop")
async def worker_stop():
    return await worker.stop()


@app.post("/api/worker/restart")
async def worker_restart():
    return await worker.restart()


# ── Stats & Data (reads from local JSON log — the real data) ─────────────────

@app.get("/api/stats")
async def get_stats():
    try:
        return {"ok": True, "data": local_data.get_stats()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/stats/daily")
async def get_daily():
    try:
        return {"ok": True, "data": local_data.get_daily_breakdown()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/stats/platforms")
async def get_platforms():
    try:
        return {"ok": True, "data": local_data.get_ats_breakdown()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/pipeline")
async def get_pipeline():
    try:
        return {"ok": True, "data": local_data.get_pipeline()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/activity")
async def get_activity(since: str = "", limit: int = 20):
    try:
        return {"ok": True, "data": local_data.get_recent_activity(since or None, limit)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.delete("/api/queue/{job_id}")
async def delete_queue_item(job_id: int):
    try:
        deleted = local_data.delete_from_queue(job_id)
        return {"ok": deleted, "error": None if deleted else "Not found or not in queue"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.delete("/api/queue")
async def clear_entire_queue():
    try:
        count = local_data.clear_queue()
        return {"ok": True, "deleted": count}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/applications/recent")
async def get_recent(limit: int = 20):
    try:
        return {"ok": True, "data": local_data.get_recent_applications(limit)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/heartbeat")
async def get_heartbeat():
    try:
        return {"ok": True, "data": await stats.get_heartbeat()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Profile & Settings ───────────────────────────────────────────────────────

@app.get("/api/profile")
async def get_profile():
    try:
        return {"ok": True, "data": await stats.get_settings_profile()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.put("/api/profile")
async def put_profile(body: dict):
    try:
        return {"ok": True, "data": await stats.update_profile(body)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/preferences")
async def get_preferences():
    try:
        return {"ok": True, "data": await stats.get_settings_preferences()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.put("/api/preferences")
async def put_preferences(body: dict):
    try:
        return {"ok": True, "data": await stats.update_preferences(body)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── CLI Session Control ──────────────────────────────────────────────────────

@app.get("/api/session/status")
async def session_status():
    return cli_session.status()


@app.post("/api/session/start")
async def session_start():
    ok = await cli_session.start()
    return {"ok": ok, **cli_session.status()}


@app.post("/api/session/stop")
async def session_stop():
    await cli_session.stop()
    return {"ok": True}


@app.post("/api/session/restart")
async def session_restart():
    await cli_session.restart()
    return {"ok": True, **cli_session.status()}


# ── Background Jobs ──────────────────────────────────────────────────────────

@app.get("/api/jobs/background")
async def background_jobs():
    """Return all background processes and their status."""
    processes = []

    # Worker process
    ws = worker.status()
    processes.append({
        "id": "worker",
        "name": "Application Worker",
        "description": "Applies to queued jobs automatically",
        "type": "process",
        "running": ws["running"],
        "pid": ws["pid"],
        "uptime": ws["uptime"],
    })

    # CLI session
    ss = cli_session.status()
    processes.append({
        "id": "cli_session",
        "name": f"{ss['cli'] or 'Claude'} Session",
        "description": "AI assistant for managing applications",
        "type": "session",
        "running": ss["alive"],
        "uptime": ss["uptime"],
        "state": ss["state"],
    })

    # Scout cycle (inferred from worker heartbeat)
    try:
        hb = await stats.get_heartbeat()
        scout_running = hb.get("last_action") in ("scouting", "scouted")
        processes.append({
            "id": "scout",
            "name": "Job Scout",
            "description": "Discovers new jobs every 30 minutes",
            "type": "cron",
            "running": scout_running,
            "last_action": hb.get("last_action", "unknown"),
            "details": hb.get("details", ""),
            "last_run": hb.get("updated_at"),
            "interval": "30m",
        })
    except Exception:
        processes.append({
            "id": "scout",
            "name": "Job Scout",
            "description": "Discovers new jobs every 30 minutes",
            "type": "cron",
            "running": False,
            "interval": "30m",
        })

    return {"ok": True, "processes": processes}


# ── WebSockets ───────────────────────────────────────────────────────────────

@app.websocket("/ws/terminal")
async def ws_terminal(ws: WebSocket):
    await terminal_websocket(ws)


@app.websocket("/ws/pty")
async def ws_pty(ws: WebSocket):
    await pty_terminal_websocket(ws)


@app.get("/api/pty/status")
async def pty_status():
    return session_manager.pty.status()


@app.post("/api/pty/start")
async def pty_start():
    if session_manager.pty.is_alive:
        return {"ok": True, **session_manager.pty.status()}
    result = session_manager.new_session()
    return {"ok": True, **result}


@app.post("/api/pty/stop")
async def pty_stop():
    session_manager.pty.stop()
    return {"ok": True}


@app.get("/api/pty/sessions")
async def get_pty_sessions():
    """List all sessions created by this UI instance."""
    return {
        "ok": True,
        "current": session_manager.pty.status(),
        "active_session_id": session_manager.active_session_id,
        "history": session_manager.get_sessions(),
        "total": len(session_manager.sessions),
    }


@app.post("/api/pty/sessions/new")
async def create_pty_session():
    return {"ok": True, **session_manager.new_session()}


@app.delete("/api/pty/sessions/{session_id}")
async def delete_pty_session(session_id: str):
    return session_manager.delete_session(session_id)


@app.post("/api/pty/restart")
async def pty_restart():
    session_manager.pty.restart()
    return {"ok": True, **session_manager.pty.status()}


@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket):
    await chat_websocket(ws)


# ── Static UI Serving ────────────────────────────────────────────────────────
# Must be LAST — catches all non-API routes and serves the static Next.js export

import mimetypes
mimetypes.init()

if UI_BUILD_DIR:
    logger.info(f"Serving UI from: {UI_BUILD_DIR}")

    # Mount _next/static as a static files directory for proper MIME types
    _next_dir = UI_BUILD_DIR / "_next"
    if _next_dir.exists():
        app.mount("/_next", StaticFiles(directory=str(_next_dir)), name="next-static")

    @app.get("/{path:path}")
    async def serve_ui(path: str):
        # Try exact file first
        file_path = UI_BUILD_DIR / path
        if file_path.is_file():
            return FileResponse(file_path)
        # Try path/index.html (Next.js trailing slash pages)
        index_path = UI_BUILD_DIR / path / "index.html"
        if index_path.is_file():
            return FileResponse(index_path)
        # Try path.html
        html_path = UI_BUILD_DIR / f"{path}.html"
        if html_path.is_file():
            return FileResponse(html_path)
        # Fallback to root index.html
        root_index = UI_BUILD_DIR / "index.html"
        if root_index.is_file():
            return FileResponse(root_index)
        return {"error": "Not found"}
else:
    logger.warning("No UI build found — run 'npm run build' in packages/desktop/ui/")
