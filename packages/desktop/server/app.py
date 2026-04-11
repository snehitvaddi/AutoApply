"""ApplyLoop Desktop — FastAPI backend server."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI, WebSocket, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

import json

import httpx

from .config import load_token, APP_URL, TOKEN_FILE, WORKSPACE_DIR
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
from .chat_bridge import chat_websocket
from . import stats

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
)
logger = logging.getLogger("desktop-server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    import time as _time
    from .message_router import message_router
    from .telegram_gateway import telegram_gateway
    from .chat_bridge import broadcast_to_chat_ui

    token = load_token()
    if token:
        logger.info("API token loaded")
    else:
        logger.warning("No API token found — set AUTOAPPLY_TOKEN or create ~/.autoapply/workspace/.api-token")
    logger.info(f"Remote API: {APP_URL}")
    # Auto-recover jobs stuck in 'applying' from a previous crash
    try:
        reset_count = local_data.reset_stuck_jobs()
        if reset_count > 0:
            logger.info(f"Startup: reset {reset_count} stuck job(s) back to queue")
    except Exception as e:
        logger.warning(f"Startup stuck-job reset failed: {e}")

    # Start the shared message router (serializes chat UI + Telegram → PTY)
    try:
        await message_router.start()
    except Exception as e:
        logger.warning(f"Message router failed to start: {e}")

    # Start the Telegram gateway — wires Telegram as a second input into the PTY.
    # Callbacks mirror Telegram traffic to the desktop chat UI in real time.
    async def _on_tg_in(text: str) -> None:
        await broadcast_to_chat_ui({
            "type": "telegram",
            "data": text,
            "from_bot": False,
            "timestamp": int(_time.time() * 1000),
        })

    async def _on_tg_out(text: str) -> None:
        await broadcast_to_chat_ui({
            "type": "telegram",
            "data": text,
            "from_bot": True,
            "timestamp": int(_time.time() * 1000),
        })

    telegram_gateway.on_message_in = _on_tg_in
    telegram_gateway.on_message_out = _on_tg_out
    try:
        await telegram_gateway.start()
    except Exception as e:
        logger.warning(f"Telegram gateway failed to start: {e}")

    # Auto-start the Claude Code PTY session so users don't have to
    # manually click "Start Session" on the Terminal tab every time
    # they relaunch. Guards, in this order:
    #
    #   1. Skip in headless mode — CI runners don't have `claude`
    #      installed and don't need the agent loop.
    #   2. Skip if there's no worker token — nothing useful to do.
    #   3. Skip if the user has no uploaded resume — the worker will
    #      fail every apply without one, so starting the agent loop is
    #      counterproductive. Tell the user to upload via Settings →
    #      Resume; the upload handler auto-starts the PTY on success
    #      so they don't have to relaunch.
    #   4. Skip if `claude` CLI isn't findable on PATH — log the
    #      install hint instead of trying to spawn a missing binary.
    #
    # Failures at any layer are swallowed with a warning. The server
    # must never fail to start because the agent loop is broken — the
    # rest of the app (dashboard, Kanban, Settings, Telegram gateway)
    # stays functional.
    import os as _os
    if not _os.environ.get("APPLYLOOP_HEADLESS") and token:
        try:
            from .pty_terminal import PTYSession as _PTYSession
            # Check resume existence via worker proxy — one round-trip,
            # ~50ms in practice. Cheap insurance against spinning up a
            # doomed apply loop.
            resume_result = await stats._proxy("list_resumes")
            resume_rows = (
                (resume_result or {}).get("data", {}).get("resumes", [])
                if not (resume_result or {}).get("error")
                else []
            )
            has_resume = len(resume_rows) > 0

            if not has_resume:
                logger.warning(
                    "No resume uploaded yet — skipping PTY auto-start. "
                    "Open Settings → Resume to upload one; the apply loop "
                    "will start automatically when the upload succeeds."
                )
            elif not _PTYSession._find_claude():
                logger.warning(
                    "claude CLI not found on PATH — skipping PTY auto-start. "
                    "Install from https://claude.com/product/claude-code "
                    "and click Start Session on the Terminal tab after."
                )
            elif session_manager.pty.is_alive:
                logger.info("PTY already alive; skipping auto-start")
            else:
                result = session_manager.new_session()
                if result.get("alive"):
                    logger.info(
                        f"Auto-started Claude Code PTY session "
                        f"(pid={result.get('pid')})"
                    )
                else:
                    logger.warning(
                        "PTY auto-start did not bring the session up — "
                        "user can click Start Session on the Terminal tab"
                    )
        except Exception as e:
            logger.warning(f"PTY auto-start failed: {e}")

    yield

    # Cleanup: stop gateway, router, PTY, worker
    try:
        await telegram_gateway.stop()
    except Exception as e:
        logger.debug(f"Telegram gateway stop error: {e}")
    try:
        await message_router.stop()
    except Exception as e:
        logger.debug(f"Message router stop error: {e}")
    if session_manager.pty.is_alive:
        logger.info("Shutting down PTY session...")
        session_manager.pty.stop()
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


@app.get("/api/auth/state")
async def auth_state():
    """Report the desktop's view of whether its worker token is still valid.

    Flipped to "revoked" by stats._proxy the first time the remote API
    returns 401/403 on a proxy call. The UI polls this and redirects to
    /setup when the state changes away from "ok".
    """
    token = load_token()
    if not token:
        return {"status": "no_token"}
    state = stats.get_auth_state()
    return {
        "status": state.get("status", "unknown"),
        "last_checked": state.get("last_checked"),
        "last_error": state.get("last_error"),
    }


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


@app.get("/api/pipeline/current")
async def get_current():
    try:
        return {"ok": True, "data": local_data.get_currently_applying()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/pipeline/stuck")
async def get_stuck():
    try:
        return {"ok": True, "data": local_data.get_stuck_jobs()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/pipeline/reset-stuck")
async def reset_stuck():
    try:
        count = local_data.reset_stuck_jobs()
        return {"ok": True, "reset": count}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/screenshots/{job_id}")
async def get_screenshot(job_id: int):
    """Serve the screenshot file for a job by its ID.

    Reads `screenshot` column from the applications table, then streams the file
    back with the correct MIME type. Returns 404 if missing.
    """
    from fastapi.responses import FileResponse
    from fastapi import HTTPException
    from pathlib import Path as _Path

    try:
        row = local_data._query_one(
            "SELECT screenshot FROM applications WHERE id = ?", (job_id,)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    path_str = (row or {}).get("screenshot")
    if not path_str:
        raise HTTPException(status_code=404, detail="no screenshot for this job")

    p = _Path(path_str).expanduser()
    if not p.is_file():
        raise HTTPException(status_code=404, detail=f"screenshot file not found: {p}")

    return FileResponse(str(p), media_type="image/png")


@app.post("/api/browser/focus")
async def focus_browser():
    """Bring the live Chromium/Chrome window to the foreground.

    Used by the Dashboard "Currently Applying" banner so the user can
    jump straight to the browser where the applier is filling out a
    form. macOS uses osascript to activate the app by bundle name;
    Windows uses PowerShell + Win32 SetForegroundWindow; Linux has no
    universal equivalent so we return an informative error there.

    This endpoint is a QoL feature, not critical to the apply loop —
    users can always alt-tab manually. Non-Darwin platforms degrade
    gracefully without breaking the dashboard.
    """
    import platform as _platform
    import subprocess
    system = _platform.system()

    if system == "Darwin":
        for app_name in ("Chromium", "Google Chrome", "Chrome"):
            try:
                r = subprocess.run(
                    ["osascript", "-e", f'tell application "{app_name}" to activate'],
                    capture_output=True, text=True, timeout=3,
                )
                if r.returncode == 0:
                    return {"ok": True, "focused": app_name}
            except Exception:
                continue
        return {"ok": False, "error": "no Chrome/Chromium window found"}

    if system == "Windows":
        # PowerShell one-liner: find a top-level window whose title contains
        # "Chrome" or "Chromium", call the Win32 SetForegroundWindow API
        # on its handle. If none found, return cleanly so the UI shows
        # the "not found" state instead of hanging or crashing.
        ps_script = (
            "Add-Type @'\n"
            "using System;\n"
            "using System.Runtime.InteropServices;\n"
            "public class Win32 {\n"
            "  [DllImport(\"user32.dll\")] public static extern bool SetForegroundWindow(IntPtr hWnd);\n"
            "}\n"
            "'@;\n"
            "$p = Get-Process | Where-Object { $_.MainWindowTitle -match 'Chrome|Chromium' } | Select-Object -First 1;\n"
            "if ($p) { [Win32]::SetForegroundWindow($p.MainWindowHandle) | Out-Null; Write-Output $p.ProcessName } else { exit 1 }"
        )
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0:
                return {"ok": True, "focused": (r.stdout or "").strip() or "chrome"}
        except Exception as e:
            return {"ok": False, "error": f"powershell focus failed: {e}"}
        return {"ok": False, "error": "no Chrome/Chromium window found"}

    # Linux or unknown platform
    return {
        "ok": False,
        "error": f"browser-focus not implemented on {system}",
    }


# ── First-run setup (activation code redemption) ─────────────────────────────

def _get_install_id() -> str:
    """Return a stable per-install UUID, generating one on first call."""
    import uuid
    install_file = WORKSPACE_DIR / ".install-id"
    if install_file.exists():
        try:
            return install_file.read_text().strip()
        except Exception:
            pass
    new_id = str(uuid.uuid4())
    try:
        install_file.parent.mkdir(parents=True, exist_ok=True)
        install_file.write_text(new_id)
    except Exception as e:
        logger.warning(f"Could not persist install id: {e}")
    return new_id


_SETUP_REMEDIATION = {
    "expired": "This activation code has expired. Ask the admin for a new one.",
    "not_found": "This code doesn't exist. Double-check the letters and numbers (no 0/O/1/I).",
    "used_up": "This code has been used the maximum number of times. Ask the admin for a new one.",
    "not_approved": "Your account is not approved yet. Wait for admin approval, then try again.",
    "network": "Can't reach the ApplyLoop server. Check your internet connection.",
    "empty_code": "Enter your activation code.",
    "no_token_returned": "The server didn't return a worker token. Ask the admin for a new code.",
    "unknown": "Something went wrong. Please try again, or ask the admin for help.",
}


async def _download_default_resume(token: str) -> bool:
    """Call the worker proxy to download the user's default resume PDF and save it locally."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{APP_URL}/api/worker/proxy",
                json={"action": "download_resume_url"},
                headers={"X-Worker-Token": token},
            )
            r.raise_for_status()
            payload = r.json().get("data", {}) or {}
            url = payload.get("url")
            file_name = payload.get("file_name", "resume.pdf")
            if not url:
                logger.warning("download_resume_url returned no URL")
                return False
            pdf = await client.get(url)
            pdf.raise_for_status()
            resume_path = WORKSPACE_DIR / "resume.pdf"
            resume_path.parent.mkdir(parents=True, exist_ok=True)
            resume_path.write_bytes(pdf.content)
            logger.info(f"Downloaded resume ({file_name}) → {resume_path}")
            return True
    except Exception as e:
        logger.warning(f"Resume download failed: {e}")
        return False


@app.get("/api/setup/status")
async def setup_status():
    """First-run check: is this desktop install provisioned with a worker token?

    We force the setup wizard when:
      - No token file on disk
      - The worker or desktop dropped a .needs-reauth marker after a 401
      - stats._proxy has flipped its in-memory auth state to "revoked"

    Transient network errors are ignored — only a positive 401/403 from
    the remote API (or a totally missing token) forces re-activation.
    """
    token = load_token()
    if not token:
        return {"setup_complete": False, "reason": "no_token"}

    # Worker-side reauth marker: dropped by worker/db.py::_api_call on 401/403.
    reauth_marker = WORKSPACE_DIR / ".needs-reauth"
    if reauth_marker.exists():
        try:
            detail = reauth_marker.read_text().strip()
        except Exception:
            detail = "worker reported 401/403"
        return {"setup_complete": False, "reason": "token_revoked", "detail": detail}

    # Desktop-side auth state: flipped by stats._proxy on 401/403.
    state = stats.get_auth_state()
    if state.get("status") == "revoked":
        return {
            "setup_complete": False,
            "reason": "token_revoked",
            "detail": state.get("last_error") or "desktop proxy saw 401/403",
        }

    return {"setup_complete": True}


@app.post("/api/setup/clear-reauth")
async def clear_reauth():
    """Delete the .needs-reauth marker — called after a successful re-activate."""
    marker = WORKSPACE_DIR / ".needs-reauth"
    try:
        marker.unlink(missing_ok=True)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True}


@app.post("/api/setup/activate")
async def setup_activate(body: dict):
    """Redeem an activation code → save the returned worker token → download the resume.

    Flow:
      1. POST {code, install_id} to applyloop.vercel.app/api/activate
      2. On success: persist worker_token to TOKEN_FILE, download default resume,
         stash the profile JSON to disk, return a short {ok, user} payload
      3. On failure: return {ok: false, error: <key>, suggestion: <human text>}
    """
    code = (body or {}).get("code", "").strip().upper() if body else ""
    if not code:
        return {
            "ok": False,
            "error": "empty_code",
            "suggestion": _SETUP_REMEDIATION["empty_code"],
        }

    payload = {
        "code": code,
        "install_id": _get_install_id(),
        "app_version": "1.0.0",
    }

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(f"{APP_URL}/api/activate", json=payload)
    except Exception as e:
        logger.warning(f"Activation request failed: {e}")
        return {
            "ok": False,
            "error": "network",
            "suggestion": _SETUP_REMEDIATION["network"],
            "detail": str(e),
        }

    if r.status_code >= 400:
        # apiError from Next.js returns a flat body {statusCode, name, message, details}
        try:
            err_body = r.json() or {}
        except Exception:
            err_body = {}
        detail_code = None
        if isinstance(err_body.get("details"), dict):
            detail_code = err_body["details"].get("code")
        error_key = detail_code or err_body.get("name") or "unknown"
        return {
            "ok": False,
            "error": error_key,
            "suggestion": _SETUP_REMEDIATION.get(error_key, _SETUP_REMEDIATION["unknown"]),
            "message": err_body.get("message"),
        }

    try:
        result = r.json() or {}
        data = result.get("data", {}) or {}
    except Exception as e:
        return {
            "ok": False,
            "error": "unknown",
            "suggestion": _SETUP_REMEDIATION["unknown"],
            "detail": f"invalid server response: {e}",
        }

    worker_token = data.get("worker_token")
    if not worker_token:
        return {
            "ok": False,
            "error": "no_token_returned",
            "suggestion": _SETUP_REMEDIATION["no_token_returned"],
        }

    # Persist the worker token to disk (600 perms so only the user can read it).
    try:
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(worker_token)
        try:
            TOKEN_FILE.chmod(0o600)
        except Exception:
            pass
        # Clear any prior reauth marker + reset the in-memory auth state so
        # the dashboard stops redirecting to /setup on the next poll.
        try:
            (WORKSPACE_DIR / ".needs-reauth").unlink(missing_ok=True)
        except Exception:
            pass
        try:
            stats._mark_auth_ok()
        except Exception:
            pass
        logger.info("Activation successful — worker token saved")
    except Exception as e:
        return {
            "ok": False,
            "error": "disk",
            "suggestion": f"Could not write token file: {e}",
        }

    # Download the default resume (best-effort).
    resume_ok = await _download_default_resume(worker_token)

    # Persist the profile JSON locally for quick reads.
    try:
        (WORKSPACE_DIR / "profile.json").write_text(json.dumps(data, indent=2, default=str))
    except Exception as e:
        logger.debug(f"Could not persist profile.json: {e}")

    return {
        "ok": True,
        "user": {
            "email": data.get("email"),
            "name": data.get("full_name"),
            "tier": data.get("tier"),
        },
        "resume_downloaded": resume_ok,
    }


# ── Resume upload / list ────────────────────────────────────────────────────

@app.get("/api/resumes")
async def list_resumes():
    """List the authenticated user's resumes via the worker proxy."""
    try:
        result = await stats._proxy("list_resumes")
        if "error" in result:
            return {"ok": False, "error": result["error"]}
        return {"ok": True, "data": result.get("data", {})}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/resumes/upload")
async def upload_resume(
    file: UploadFile = File(...),
    is_default: bool = Form(True),
    target_keywords: str = Form(""),
):
    """Accept a PDF upload from the desktop Settings page → forward to the
    worker proxy's upload_resume action → Supabase Storage.

    We read the bytes here, sanity-check size + PDF magic at the edge so
    obvious mistakes surface before a network round-trip, then base64-encode
    and hand off to the proxy. The proxy re-validates server-side
    (belt-and-suspenders).

    Params come in as multipart/form-data so the browser file picker works:
      file              UploadFile   the PDF
      is_default        bool         default True — set as the user's
                                     default resume (clears other rows'
                                     is_default flag for this user)
      target_keywords   str          comma-separated keywords for resume
                                     routing (e.g. "ml,ai,llm")
    """
    import base64 as _b64
    try:
        raw = await file.read()
    except Exception as e:
        return {"ok": False, "error": f"could not read uploaded file: {e}"}

    MAX_BYTES = 10 * 1024 * 1024
    if not raw:
        return {"ok": False, "error": "uploaded file is empty"}
    if len(raw) > MAX_BYTES:
        return {"ok": False, "error": f"resume exceeds 10 MB cap ({len(raw)} bytes)"}
    if raw[:4] != b"%PDF":
        return {
            "ok": False,
            "error": "file does not look like a PDF (missing %PDF magic bytes)",
        }

    keywords = [k.strip() for k in (target_keywords or "").split(",") if k.strip()]

    result = await stats._proxy("upload_resume", {
        "content_base64": _b64.b64encode(raw).decode("ascii"),
        "file_name": file.filename or "resume.pdf",
        "is_default": is_default,
        "target_keywords": keywords,
    })
    if "error" in result:
        return {"ok": False, "error": result["error"]}

    # Also refresh the local resume.pdf copy so the worker's applier can
    # read it without another round-trip. Best-effort — if we fail we still
    # return OK because the cloud upload itself succeeded.
    try:
        token = load_token()
        if token:
            await _download_default_resume(token)
    except Exception as e:
        logger.debug(f"Post-upload resume cache refresh failed: {e}")

    # If this is the user's FIRST resume upload, the PTY auto-start at
    # boot was almost certainly skipped (no resume → no apply loop).
    # Now that they have one, spin up the Claude Code session so they
    # don't have to relaunch the app. Same guards as the lifespan
    # handler: only when we have claude on PATH and nothing's already
    # running. Swallows all errors — upload succeeded either way.
    pty_auto_started = False
    try:
        if not session_manager.pty.is_alive:
            from .pty_terminal import PTYSession as _PTYSession
            if _PTYSession._find_claude():
                result_session = session_manager.new_session()
                pty_auto_started = bool(result_session.get("alive"))
                if pty_auto_started:
                    logger.info(
                        "PTY auto-started after first resume upload "
                        f"(pid={result_session.get('pid')})"
                    )
    except Exception as e:
        logger.debug(f"Post-upload PTY auto-start failed: {e}")

    return {
        "ok": True,
        "data": result.get("data", {}),
        "pty_auto_started": pty_auto_started,
    }


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



# (CLI Session endpoints removed — Chat now uses /btw via PTY)


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

    # PTY session (Claude Code)
    ps = session_manager.pty.status()
    processes.append({
        "id": "pty_session",
        "name": "Claude Code Session",
        "description": "AI agent scouting and applying for jobs",
        "type": "session",
        "running": ps["alive"],
        "uptime": ps.get("uptime", 0),
        "state": "running" if ps["alive"] else "stopped",
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
