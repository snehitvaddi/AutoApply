#!/usr/bin/env python3
"""
ApplyLoop Desktop — Single-process launcher.

Architecture:
  - FastAPI serves the static UI (HTML/CSS/JS) + API + WebSocket
  - ONE process, ONE port, no Node.js needed at runtime
  - Click the app icon → browser opens → everything works
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent

HOST = os.environ.get("APPLYLOOP_HOST", "127.0.0.1")
PORT = int(os.environ.get("APPLYLOOP_PORT", "18790"))


def check_deps():
    """Ensure Python deps are installed (fast if already present)."""
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
        import httpx    # noqa: F401
    except ImportError:
        print("[ApplyLoop] Installing dependencies...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-q", "-r",
             str(HERE / "requirements.txt")],
        )


def open_browser():
    """Open the browser after a short delay to let the server start."""
    time.sleep(2)
    webbrowser.open(f"http://localhost:{PORT}")


def main():
    print()
    print("  ╔══════════════════════════════════════╗")
    print("  ║        ApplyLoop Desktop              ║")
    print("  ║   Automated Job Application Tracker   ║")
    print("  ╚══════════════════════════════════════╝")
    print()

    check_deps()

    # Ensure we're in the right directory for module imports
    os.chdir(str(HERE))
    sys.path.insert(0, str(HERE))

    print(f"  Server: http://localhost:{PORT}")
    print(f"  Press Ctrl+C to stop.")
    print()

    # Open browser in background
    threading.Thread(target=open_browser, daemon=True).start()

    # Run FastAPI server (single process — serves UI + API + WebSocket)
    import uvicorn
    uvicorn.run(
        "server.app:app",
        host=HOST,
        port=PORT,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
