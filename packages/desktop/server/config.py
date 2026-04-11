"""Configuration for the desktop backend server."""
from __future__ import annotations

import os
from pathlib import Path

# Paths — honor APPLYLOOP_WORKSPACE for multi-tenant/test isolation.
# Falling back to ~/.autoapply/workspace for the normal single-user install.
_ws_env = os.environ.get("APPLYLOOP_WORKSPACE")
WORKSPACE_DIR = Path(_ws_env).expanduser() if _ws_env else (Path.home() / ".autoapply" / "workspace")
TOKEN_FILE = WORKSPACE_DIR / ".api-token"
WORKER_PID_FILE = WORKSPACE_DIR / "worker.pid"
# The SQLite applications.db lives inside the workspace too; unless the user
# explicitly overrides APPLYLOOP_DB we propagate WORKSPACE_DIR into it so all
# the worker + desktop modules agree on a single source of truth per instance.
if "APPLYLOOP_DB" not in os.environ:
    os.environ["APPLYLOOP_DB"] = str(WORKSPACE_DIR / "applications.db")
# Find worker directory — could be in repo or relative to .app bundle
_server_dir = Path(__file__).resolve().parent
WORKER_DIR = None
for _w in [
    Path.home() / ".autoapply" / "worker",              # preferred: non-TCC-restricted location
    _server_dir.parent.parent.parent / "worker",        # repo: packages/desktop/server -> packages/worker
    _server_dir.parent / "worker",                      # .app bundle: Resources/server -> Resources/worker
    Path.home() / "Downloads" / "Drive-D" / "AutoApply" / "packages" / "worker",
]:
    if (_w / "worker.py").exists():
        WORKER_DIR = _w
        break
if WORKER_DIR is None:
    WORKER_DIR = _server_dir.parent.parent.parent / "worker"  # default even if missing

# Server
HOST = os.environ.get("APPLYLOOP_HOST", "127.0.0.1")
PORT = int(os.environ.get("APPLYLOOP_PORT", "18790"))
UI_PORT = int(os.environ.get("APPLYLOOP_UI_PORT", "18791"))

# Remote API
APP_URL = os.environ.get(
    "NEXT_PUBLIC_APP_URL",
    os.environ.get("AUTOAPPLY_API", "https://applyloop.vercel.app"),
)


def load_token() -> str | None:
    """Load the API/worker token from disk."""
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()
    # Also check env
    return os.environ.get("AUTOAPPLY_TOKEN") or os.environ.get("WORKER_TOKEN")


def get_worker_env() -> dict[str, str]:
    """Build environment variables for the worker subprocess."""
    token = load_token()
    env = {
        **os.environ,
        "NEXT_PUBLIC_APP_URL": APP_URL,
        "WORKER_ID": "desktop-1",
        # Ensure the worker writes to the same SQLite DB that the desktop UI reads
        "APPLYLOOP_DB": str(WORKSPACE_DIR / "applications.db"),
    }
    if token:
        env["WORKER_TOKEN"] = token
        env["AUTOAPPLY_TOKEN"] = token
    return env
