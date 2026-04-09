#!/usr/bin/env python3
"""
ApplyLoop Desktop — Native window launcher using pywebview.

Architecture:
  - FastAPI serves the static UI + API + WebSocket on localhost:18790
  - pywebview creates a native macOS window (WKWebView) pointing to it
  - Window shows in Dock, closing it stops everything
  - Falls back to browser if pywebview isn't available
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

HOST = os.environ.get("APPLYLOOP_HOST", "127.0.0.1")
PORT = int(os.environ.get("APPLYLOOP_PORT", "18790"))


def check_deps():
    """Ensure Python deps are installed."""
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
        import httpx    # noqa: F401
    except ImportError:
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

    # Start FastAPI server in background thread
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    # Wait for server to be ready
    if not wait_for_server():
        print("[ApplyLoop] Server failed to start")
        sys.exit(1)

    url = f"http://localhost:{PORT}"

    # Try pywebview (native window), fall back to browser
    try:
        import webview

        window = webview.create_window(
            title="ApplyLoop",
            url=url,
            width=1400,
            height=900,
            min_size=(800, 600),
            text_select=True,
        )

        # When window closes, exit the process (kills server thread)
        def on_closed():
            os._exit(0)

        window.events.closed += on_closed

        # Start the GUI event loop (blocks until window closes)
        webview.start(
            debug=False,
            private_mode=False,
        )

    except ImportError:
        # Fallback: open in browser
        import webbrowser
        print(f"[ApplyLoop] pywebview not found — opening in browser")
        print(f"  Server: {url}")
        print(f"  Press Ctrl+C to stop.")
        webbrowser.open(url)
        try:
            server_thread.join()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
