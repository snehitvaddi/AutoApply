#!/usr/bin/env python3
"""
ApplyLoop Desktop — Native window launcher using pywebview.

Architecture:
  - FastAPI serves the static UI + API + WebSocket on localhost:18790
  - pywebview creates a native macOS window (WKWebView) pointing to it
  - Window shows in Dock, closing it stops everything
  - Falls back to browser if pywebview isn't available

Environment variables (all optional):
  APPLYLOOP_HOST       FastAPI bind host (default 127.0.0.1)
  APPLYLOOP_PORT       FastAPI port (default 18790)
  APPLYLOOP_WORKSPACE  Per-user isolated workspace dir (default ~/.autoapply/workspace)
  APPLYLOOP_HEADLESS   "1"/"true"/"yes" to skip pywebview (for CI + multi-tenant tests)
"""
from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

HOST = os.environ.get("APPLYLOOP_HOST", "127.0.0.1")
PORT = int(os.environ.get("APPLYLOOP_PORT", "18790"))
# Headless mode is used by CI / multi-tenant tests — skip pywebview entirely
# and let the user hit the FastAPI server directly. Setting APPLYLOOP_HEADLESS=1
# (or running without a GUI) avoids a pywebview crash spiral on dev machines.
HEADLESS = os.environ.get("APPLYLOOP_HEADLESS", "").lower() in ("1", "true", "yes")


def _resolve_workspace() -> Path:
    """Mirror server/config.py::WORKSPACE_DIR resolution for the launcher.

    We can't import from server.config here because it would pull in the
    whole FastAPI app at launcher-boot time. Kept deliberately simple and
    in-sync with config.py — if that file changes, update both.
    """
    override = os.environ.get("APPLYLOOP_WORKSPACE")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".autoapply" / "workspace"


WORKSPACE_DIR = _resolve_workspace()


def _install_headless_logging() -> Path | None:
    """When HEADLESS=1, tee the root logger to $WORKSPACE/server.log so CI
    runs can collect the file as an artifact even after the process exits.

    Returns the log path on success, None otherwise.
    """
    if not HEADLESS:
        return None
    try:
        WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
        log_path = WORKSPACE_DIR / "server.log"
        handler = logging.FileHandler(str(log_path), mode="a", encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(name)s] %(levelname)s %(message)s")
        )
        root = logging.getLogger()
        root.addHandler(handler)
        if root.level > logging.INFO:
            root.setLevel(logging.INFO)
        return log_path
    except Exception as e:
        print(f"[ApplyLoop] WARN: could not attach file logger: {e}")
        return None


def _install_shutdown_handlers() -> None:
    """Write $WORKSPACE/shutdown.ok on SIGTERM/SIGINT so CI can wait on the
    marker to confirm a clean stop. Without this the daemon server thread
    is killed abruptly when the launcher process exits, which makes it
    impossible to distinguish a graceful stop from a crash in the workflow.
    """
    def _handler(signum, _frame):
        try:
            WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
            (WORKSPACE_DIR / "shutdown.ok").write_text(
                f"signal={signum} ts={time.time()}\n"
            )
        except Exception:
            pass
        print(f"[ApplyLoop] received signal {signum}, shutting down")
        # Use os._exit so the daemon uvicorn thread doesn't block shutdown.
        os._exit(0)

    # SIGTERM is what CI sends to stop the process. SIGINT is Ctrl+C.
    # Windows only supports SIGINT + SIGBREAK reliably — signal.signal is a
    # no-op for other signals there, so a try/except keeps it portable.
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _handler)
        except (ValueError, OSError, AttributeError):
            pass


def check_deps():
    """Ensure Python deps are importable.

    If we're running under the bundled .app venv (sys.executable lives inside
    the .app bundle at Contents/Resources/venv/...), a missing dep means the
    build itself is broken — pip-installing at launch time won't fix it and
    will fail anyway because pywebview needs a C compiler the user doesn't
    have. Just print a clear error and exit so the log is actionable instead
    of a pyobjc-core traceback dump.
    """
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
        import httpx    # noqa: F401
    except ImportError as exc:
        running_in_bundled_venv = ".app/Contents/Resources/venv" in sys.executable
        if running_in_bundled_venv:
            print(
                f"[ApplyLoop] FATAL: bundled venv is missing '{exc.name}'. "
                f"This is a build bug — please reinstall the latest .dmg from "
                f"https://github.com/snehitvaddi/AutoApply/releases",
                file=sys.stderr,
            )
            sys.exit(2)
        # Dev mode (user ran `python launch.py` from a checkout) — fall back
        # to installing into the current interpreter.
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-q", "-r",
             str(HERE / "requirements.txt")],
        )


def start_server():
    """Start FastAPI server in a background thread."""
    import uvicorn
    uvicorn.run(
        "server.app:app",
        host=HOST,
        port=PORT,
        log_level="warning",
    )


def wait_for_server(timeout: int = 15) -> bool:
    """Wait until the server is responding."""
    import urllib.request
    for _ in range(timeout * 4):
        try:
            urllib.request.urlopen(f"http://localhost:{PORT}/api/health", timeout=1)
            return True
        except Exception:
            time.sleep(0.25)
    return False


def main():
    check_deps()

    os.chdir(str(HERE))
    sys.path.insert(0, str(HERE))

    _install_shutdown_handlers()
    log_path = _install_headless_logging()

    # Start FastAPI server in background thread
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    # Wait for server to be ready
    if not wait_for_server():
        print("[ApplyLoop] Server failed to start")
        sys.exit(1)

    url = f"http://localhost:{PORT}"

    if HEADLESS:
        print(f"[ApplyLoop] HEADLESS mode — server running at {url}")
        if log_path:
            print(f"[ApplyLoop] Logging to {log_path}")
        print(f"[ApplyLoop] PID {os.getpid()} — send SIGTERM for graceful shutdown.")
        # Write readiness marker so CI workflows can block on its existence
        # instead of polling /api/health in a loop.
        try:
            WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
            (WORKSPACE_DIR / "ready.ok").write_text(f"pid={os.getpid()} ts={time.time()}\n")
        except Exception:
            pass
        try:
            server_thread.join()
        except KeyboardInterrupt:
            pass
        return

    # macOS Dock icon fix. When launched via `python3 launch.py` (dev mode
    # or from the .app bundle's bundled venv), the process inherits the
    # Python interpreter's Dock icon — which is the generic Python rocket,
    # not ApplyLoop's blue AL mark. pywebview doesn't expose a direct
    # per-window icon API on macOS, so we set it at the NSApplication
    # level via pyobjc before the GUI loop starts.
    #
    # Best-effort: non-macOS platforms, missing pyobjc, or a missing
    # AppIcon.icns all fail silently. The window still shows up, just
    # with the default icon.
    if sys.platform == "darwin":
        try:
            from AppKit import NSApplication, NSImage  # type: ignore
            icon_candidates = [
                Path(__file__).resolve().parent / "AppIcon.icns",
                Path(__file__).resolve().parent / "icon.svg",
                Path(__file__).resolve().parent / "Resources" / "AppIcon.icns",
            ]
            for icon_path in icon_candidates:
                if icon_path.is_file():
                    ns_img = NSImage.alloc().initWithContentsOfFile_(str(icon_path))
                    if ns_img is not None:
                        # Shared NSApplication must exist before we can set
                        # its icon. pywebview creates one during start(),
                        # but calling shared() now is safe and gives us the
                        # handle early so the first window already shows
                        # the blue icon in the Dock.
                        NSApplication.sharedApplication().setApplicationIconImage_(ns_img)
                        print(f"[ApplyLoop] Dock icon set from {icon_path.name}")
                        break
        except Exception as _icon_err:
            # pyobjc not installed, or .icns file couldn't be loaded.
            # pywebview still runs with the default icon.
            print(f"[ApplyLoop] Could not set macOS Dock icon: {_icon_err}")

    # Try pywebview (native window), fall back to browser
    try:
        import webview

        # Resolve the icon path for pywebview's create_window(icon=...).
        # On Windows + Linux this sets the titlebar icon; on macOS the
        # Dock icon is already handled by the NSApplication block above
        # but passing icon= is harmless (pywebview ignores it on Mac).
        _icon_path: str | None = None
        for _cand in [
            Path(__file__).resolve().parent / "AppIcon.icns",
            Path(__file__).resolve().parent / "icon.svg",
        ]:
            if _cand.is_file():
                _icon_path = str(_cand)
                break

        _window_kwargs: dict = {
            "title": "ApplyLoop",
            "url": url,
            "width": 1400,
            "height": 900,
            "min_size": (800, 600),
            "text_select": True,
        }
        # Newer pywebview versions accept icon=; older ones don't. Pass
        # only if the signature supports it so we don't crash on older
        # installs that shipped with the launcher.
        if _icon_path:
            try:
                import inspect
                _sig = inspect.signature(webview.create_window)
                if "icon" in _sig.parameters:
                    _window_kwargs["icon"] = _icon_path
            except Exception:
                pass

        window = webview.create_window(**_window_kwargs)

        # When window closes, exit the process (kills server thread)
        def on_closed():
            os._exit(0)

        window.events.closed += on_closed

        # Start the GUI event loop (blocks until window closes)
        webview.start(
            debug=False,
            private_mode=False,
        )

    except (ImportError, ValueError, Exception) as e:
        # Fallback: open in browser. pywebview can fail with ValueError on
        # older Python/macOS combinations where base_uri() can't resolve the
        # script path — don't crash the whole app, just fall back gracefully.
        import webbrowser
        reason = "not found" if isinstance(e, ImportError) else f"unavailable ({e})"
        print(f"[ApplyLoop] pywebview {reason} — opening in browser")
        print(f"  Server: {url}")
        print(f"  Press Ctrl+C to stop.")
        try:
            webbrowser.open(url)
        except Exception:
            pass
        try:
            server_thread.join()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
