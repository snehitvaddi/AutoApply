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
# Find worker directory. Fallback chain, in priority order:
#
#   1. $APPLYLOOP_WORKER_DIR env var — explicit override for tests / CI
#   2. $APPLYLOOP_HOME/packages/worker — what install.sh produces on
#      a client machine (~/.applyloop/packages/worker)
#   3. Dev repo layout — traversing two parents up from this file
#      (packages/desktop/server/config.py → packages/desktop → packages,
#      then + worker) lands at the sibling packages/worker
#   4. Legacy ~/.autoapply/worker — older convention, kept for older installs
#   5. Old .dmg bundle layout — Resources/server → Resources/worker
#
# The old chain had a math bug (`.parent.parent.parent / "worker"` from
# server/config.py landed at <repo_root>/worker instead of packages/worker)
# that was masked on the admin's dev box by a hardcoded absolute-path
# fallback. Both the buggy chain and the hardcoded path are gone now —
# client installs resolve via option 2 ($APPLYLOOP_HOME), dev runs
# resolve via option 3.
_server_dir = Path(__file__).resolve().parent
_candidates = []
_env_worker_dir = os.environ.get("APPLYLOOP_WORKER_DIR")
if _env_worker_dir:
    _candidates.append(Path(_env_worker_dir).expanduser())
_env_applyloop_home = os.environ.get("APPLYLOOP_HOME")
if _env_applyloop_home:
    _candidates.append(Path(_env_applyloop_home).expanduser() / "packages" / "worker")
_candidates.extend([
    _server_dir.parent.parent / "worker",     # dev: packages/desktop/server -> packages/worker
    Path.home() / ".autoapply" / "worker",    # legacy: ~/.autoapply/worker
    _server_dir.parent / "worker",            # old .app bundle: Resources/server -> Resources/worker
])

WORKER_DIR = None
for _w in _candidates:
    if (_w / "worker.py").exists():
        WORKER_DIR = _w
        break

if WORKER_DIR is None:
    # No existing worker.py found. Default to the install.sh layout if
    # APPLYLOOP_HOME is set, otherwise the dev layout. Either way, the
    # default path is honest about where we expect the worker to live,
    # so any downstream "worker.py not found" error points at the right
    # spot instead of a stale admin path.
    if _env_applyloop_home:
        WORKER_DIR = Path(_env_applyloop_home).expanduser() / "packages" / "worker"
    else:
        WORKER_DIR = _server_dir.parent.parent / "worker"

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
