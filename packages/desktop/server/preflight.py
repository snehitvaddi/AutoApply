"""
Preflight — comprehensive setup readiness audit for the ApplyLoop desktop app.

Runs on app launch (gating PTY auto-start), on-demand via /api/setup/status
(powering the multi-step wizard UI), and inside the worker's main loop
(gating job claims). Checks cloud data + local binaries + subscription
state in one place so the three enforcement points can't drift.

Each check returns:
  {
    "id":          stable machine-readable id (e.g. "claude_cli")
    "ok":          bool — is this requirement satisfied?
    "label":       human-readable name for the wizard UI
    "detail":      one-line status / error message
    "remediation": {"type": "route" | "install" | "link", "target": ...}
                   (populated when ok=False; tells the UI how to fix it)
    "optional":    bool — if True, a failure does NOT block ready=True
                   (only `git` is optional today)
  }

run_preflight() aggregates all checks and returns:
  {"ready": bool, "checks": [ ... ]}

`ready` is True iff every non-optional check is ok. That's the single
source of truth for "setup done" across the API, the lifespan guard,
and the worker preflight.
"""
from __future__ import annotations

import asyncio
import logging
import os
import platform
import shutil
import subprocess
from pathlib import Path

from . import stats
from .config import WORKSPACE_DIR, load_token

logger = logging.getLogger(__name__)

# Minimum profile fields the appliers need at runtime. Missing any of
# these means every apply will fail on the first form it encounters, so
# we refuse to start the loop until they're all present.
_REQUIRED_PROFILE_FIELDS = ("first_name", "last_name", "email")


def _check_token() -> dict:
    """1. Does the user have a worker token on disk AND does the cached
    auth state say it's still valid? Revoked tokens flip the auth state
    via stats._mark_auth_revoked() the first time a proxy call 401s."""
    token = load_token()
    if not token:
        return {
            "id": "token",
            "ok": False,
            "label": "Activation code",
            "detail": "No worker token on disk — paste your activation code.",
            "remediation": {"type": "route", "target": "/setup/"},
        }
    auth_state = stats.get_auth_state()
    if auth_state.get("status") == "revoked":
        return {
            "id": "token",
            "ok": False,
            "label": "Activation code",
            "detail": f"Worker token revoked ({auth_state.get('last_error', 'unknown')}). Re-activate.",
            "remediation": {"type": "route", "target": "/setup/"},
        }
    return {
        "id": "token",
        "ok": True,
        "label": "Activation code",
        "detail": f"Token loaded (token auth state = {auth_state.get('status', 'unknown')})",
    }


async def _check_profile() -> dict:
    """2. Profile minimally complete — first_name, last_name, email, and
    at least one of phone / linkedin_url. These are the bare-minimum fields
    every ATS form will ask for."""
    result = await stats._proxy("load_profile")
    if result.get("error"):
        # If the proxy itself failed (network, 401, etc.), we can't say
        # anything about the profile. Treat as not-ok so the user goes
        # back to the wizard rather than hitting mysterious errors later.
        return {
            "id": "profile",
            "ok": False,
            "label": "Profile information",
            "detail": f"Could not load profile: {result.get('error', 'unknown')}",
            "remediation": {"type": "route", "target": "/settings?tab=ai"},
        }

    data = result.get("data", {}) or {}
    profile = data.get("profile") or {}
    user = data.get("user") or {}

    # email lives on the users (auth-managed) row, NOT on user_profiles.
    # first_name / last_name / phone / linkedin_url live on user_profiles.
    # Until v1.0.7 this check only looked at `profile`, which meant every
    # user — even after fully completing web onboarding — was reported as
    # "missing email". Pujith hit it on v1.0.6.
    def _f(key: str) -> str:
        return (profile.get(key) or user.get(key) or "").strip()

    missing = [field for field in _REQUIRED_PROFILE_FIELDS if not _f(field)]
    if not (_f("phone") or _f("linkedin_url")):
        missing.append("phone or linkedin_url")

    if missing:
        return {
            "id": "profile",
            "ok": False,
            "label": "Profile information",
            "detail": f"Missing: {', '.join(missing)}",
            "remediation": {"type": "route", "target": "/settings?tab=ai"},
        }
    return {
        "id": "profile",
        "ok": True,
        "label": "Profile information",
        "detail": f"Profile complete ({_f('first_name')} {_f('last_name')})".strip(),
    }


async def _check_resume() -> dict:
    """3. At least one resume uploaded to user_resumes."""
    result = await stats._proxy("list_resumes")
    if result.get("error"):
        return {
            "id": "resume",
            "ok": False,
            "label": "Resume uploaded",
            "detail": f"Could not load resumes: {result.get('error')}",
            "remediation": {"type": "route", "target": "/settings?tab=resume"},
        }
    data = result.get("data", {}) or {}
    resumes = data.get("resumes") or []
    if not resumes:
        return {
            "id": "resume",
            "ok": False,
            "label": "Resume uploaded",
            "detail": "No resume on file — the worker will fail every apply without one.",
            "remediation": {"type": "route", "target": "/settings?tab=resume"},
        }
    default = next((r for r in resumes if r.get("is_default")), resumes[0])
    return {
        "id": "resume",
        "ok": True,
        "label": "Resume uploaded",
        "detail": f"{len(resumes)} resume(s) on file · default: {default.get('file_name', 'resume.pdf')}",
    }


async def _check_preferences() -> dict:
    """4. User_job_preferences.target_titles has at least one entry."""
    result = await stats._proxy("load_preferences")
    if result.get("error"):
        return {
            "id": "preferences",
            "ok": False,
            "label": "Job preferences",
            "detail": f"Could not load preferences: {result.get('error')}",
            "remediation": {"type": "route", "target": "/settings?tab=preferences"},
        }
    data = result.get("data", {}) or {}
    prefs = data.get("preferences") or {}
    titles = prefs.get("target_titles") or []
    if not titles:
        return {
            "id": "preferences",
            "ok": False,
            "label": "Job preferences",
            "detail": "No target roles set — the scout has nothing to filter on.",
            "remediation": {"type": "route", "target": "/settings?tab=preferences"},
        }
    return {
        "id": "preferences",
        "ok": True,
        "label": "Job preferences",
        "detail": f"{len(titles)} target role(s): {', '.join(titles[:3])}{'…' if len(titles) > 3 else ''}",
    }


# ── Local binary checks ───────────────────────────────────────────────

_CLAUDE_FALLBACK_PATHS = (
    "~/.local/bin/claude",
    "/usr/local/bin/claude",
    "/opt/homebrew/bin/claude",
    "~/.npm-global/bin/claude",
)


def _find_binary(name: str, fallbacks: tuple[str, ...] = ()) -> str | None:
    """PATH lookup + fallback list. Mirrors pty_terminal.PTYSession._find_claude."""
    found = shutil.which(name)
    if found:
        return found
    for p in fallbacks:
        expanded = os.path.expanduser(p)
        if os.path.isfile(expanded) and os.access(expanded, os.X_OK):
            return expanded
    return None


def _check_claude_cli() -> dict:
    """5. `claude` CLI findable on PATH or in a known fallback location.
    Without it the PTY session can't start at all."""
    found = _find_binary("claude", _CLAUDE_FALLBACK_PATHS)
    if found:
        return {
            "id": "claude_cli",
            "ok": True,
            "label": "Claude Code CLI",
            "detail": f"Found at {found}",
        }
    return {
        "id": "claude_cli",
        "ok": False,
        "label": "Claude Code CLI",
        "detail": "claude CLI not found on PATH or in ~/.local/bin, /usr/local/bin, /opt/homebrew/bin, ~/.npm-global/bin",
        "remediation": {
            "type": "install",
            "target": "claude",
            "command": "brew install claude",
            "fallback_url": "https://claude.com/product/claude-code",
        },
    }


def _check_openclaw_cli() -> dict:
    """6. `openclaw` CLI on PATH. Every ATS applier shells out to
    `openclaw browser …` — no CLI = no applies."""
    found = _find_binary("openclaw")
    if found:
        return {
            "id": "openclaw_cli",
            "ok": True,
            "label": "OpenClaw CLI",
            "detail": f"Found at {found}",
        }
    return {
        "id": "openclaw_cli",
        "ok": False,
        "label": "OpenClaw CLI",
        "detail": "openclaw CLI not found on PATH",
        "remediation": {
            "type": "install",
            "target": "openclaw",
            "command": "npm install -g openclaw",
            "fallback_url": "https://openclaw.com/install",
        },
    }


def _check_openclaw_gateway() -> dict:
    """7. `openclaw gateway status` returns a live gateway. Gateway
    activation is tied to the Pro subscription — the CLI can be
    installed without a valid Pro licence, and that would fail at
    apply time with a confusing error. Catch it here instead."""
    openclaw = _find_binary("openclaw")
    if not openclaw:
        # Already covered by _check_openclaw_cli. Mark this row hidden so
        # the UI doesn't show two consecutive rows about the same missing
        # CLI — once openclaw is installed, the gateway check runs for
        # real and surfaces subscription state.
        return {
            "id": "openclaw_gateway",
            "ok": False,
            "hidden": True,
            "label": "OpenClaw Pro subscription",
            "detail": "Pending OpenClaw CLI install",
            "remediation": {"type": "install", "target": "openclaw"},
        }
    try:
        r = subprocess.run(
            [openclaw, "gateway", "status"],
            capture_output=True, text=True, timeout=8,
        )
    except subprocess.TimeoutExpired:
        return {
            "id": "openclaw_gateway",
            "ok": False,
            "label": "OpenClaw Pro subscription",
            "detail": "gateway status check timed out after 8s",
            "remediation": {
                "type": "link",
                "target": "https://openclaw.com/pricing",
            },
        }
    except Exception as e:
        return {
            "id": "openclaw_gateway",
            "ok": False,
            "label": "OpenClaw Pro subscription",
            "detail": f"gateway status error: {e}",
            "remediation": {
                "type": "link",
                "target": "https://openclaw.com/pricing",
            },
        }

    stdout = (r.stdout or "").strip().lower()
    stderr = (r.stderr or "").strip().lower()
    combined = f"{stdout}\n{stderr}"
    # Heuristics — openclaw's exact output format may drift, so check for
    # both a healthy marker ("running" / "active" / "ready") and error markers
    # ("not running" / "expired" / "invalid license").
    if r.returncode == 0 and any(k in combined for k in ("running", "active", "ready", "ok")):
        return {
            "id": "openclaw_gateway",
            "ok": True,
            "label": "OpenClaw Pro subscription",
            "detail": (stdout or "gateway healthy").splitlines()[0][:100],
        }
    return {
        "id": "openclaw_gateway",
        "ok": False,
        "label": "OpenClaw Pro subscription",
        "detail": (stdout or stderr or "gateway not running").splitlines()[-1][:140],
        "remediation": {
            "type": "link",
            "target": "https://openclaw.com/pricing",
        },
    }


def _check_git() -> dict:
    """8. `git` on PATH — optional, only affects auto-updates. Never
    blocks ready=True."""
    found = _find_binary("git")
    if found:
        return {
            "id": "git",
            "ok": True,
            "label": "Git (optional)",
            "detail": f"Found at {found}",
            "optional": True,
        }
    return {
        "id": "git",
        "ok": False,
        "label": "Git (optional)",
        "detail": "git not found — daily auto-updates disabled.",
        "remediation": {
            "type": "install",
            "target": "git",
            "command": "brew install git",
            "fallback_url": "https://git-scm.com/download/mac",
        },
        "optional": True,
    }


# ── Orchestrator ─────────────────────────────────────────────────────


async def run_preflight() -> dict:
    """Run every check and return a structured result.

    Returns:
        {
            "ready": bool,        # all non-optional checks passed
            "checks": [ ... ],    # ordered list of check dicts
        }
    """
    checks: list[dict] = []

    # Check 1 — token. If this fails, every cloud check will also fail
    # (they all need the token to talk to the proxy). Short-circuit the
    # rest to save round-trips on the no-token path.
    token_check = _check_token()
    checks.append(token_check)

    if token_check["ok"]:
        # Cloud checks run concurrently — 3 round-trips to the worker
        # proxy in parallel, ~100ms total on a good connection.
        try:
            profile_check, resume_check, prefs_check = await asyncio.gather(
                _check_profile(),
                _check_resume(),
                _check_preferences(),
            )
        except Exception as e:
            logger.warning(f"Preflight cloud checks failed: {e}")
            profile_check = {
                "id": "profile", "ok": False, "label": "Profile information",
                "detail": f"Cloud error: {e}",
                "remediation": {"type": "route", "target": "/settings?tab=ai"},
            }
            resume_check = {
                "id": "resume", "ok": False, "label": "Resume uploaded",
                "detail": f"Cloud error: {e}",
                "remediation": {"type": "route", "target": "/settings?tab=resume"},
            }
            prefs_check = {
                "id": "preferences", "ok": False, "label": "Job preferences",
                "detail": f"Cloud error: {e}",
                "remediation": {"type": "route", "target": "/settings?tab=preferences"},
            }
        checks.extend([profile_check, resume_check, prefs_check])
    else:
        # Render placeholder rows so the UI can still show the checklist
        # shape even before the user activates — they'll flip to real
        # status as soon as the token lands.
        for cid, label, tab in (
            ("profile", "Profile information", "ai"),
            ("resume", "Resume uploaded", "resume"),
            ("preferences", "Job preferences", "preferences"),
        ):
            checks.append({
                "id": cid,
                "ok": False,
                "label": label,
                "detail": "Activate first (needs token)",
                "remediation": {"type": "route", "target": f"/settings?tab={tab}"},
            })

    # Local binary checks — synchronous, fast. Run unconditionally so
    # the user can install tools in parallel with activation.
    checks.append(_check_claude_cli())
    checks.append(_check_openclaw_cli())
    checks.append(_check_openclaw_gateway())
    checks.append(_check_git())

    ready = all(c["ok"] for c in checks if not c.get("optional"))
    return {"ready": ready, "checks": checks}


# ── Install orchestration ────────────────────────────────────────────
#
# Tracks background install subprocesses so the UI can poll for live
# output + completion status. Keyed by tool name so parallel installs
# for different tools don't collide.

_INSTALL_STATE: dict[str, dict] = {}


def _install_log_path(tool: str) -> Path:
    return WORKSPACE_DIR / f"install-{tool}.log"


_INSTALL_COMMANDS = {
    "claude": {
        "Darwin": ["brew", "install", "claude"],
    },
    "openclaw": {
        "Darwin": ["npm", "install", "-g", "openclaw"],
    },
    "git": {
        "Darwin": ["brew", "install", "git"],
    },
    # brew bootstrap — only used if user clicks "Install Homebrew" on the
    # needs_brew fallback path. Full command quoted below because it uses
    # shell indirection (bash -c $(curl …)).
    "brew": {
        "Darwin": [
            "bash", "-c",
            '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"',
        ],
    },
}


def install_tool_status(tool: str) -> dict:
    """Return the current install status for a tool (for polling UI)."""
    state = _INSTALL_STATE.get(tool)
    if not state:
        return {"running": False, "exit_code": None, "last_lines": [], "started": False}
    log_path = state["log_path"]
    last_lines: list[str] = []
    try:
        if log_path.exists():
            # Read last 40 lines without buffering the whole file
            with open(log_path, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                read_from = max(0, size - 8192)
                f.seek(read_from)
                chunk = f.read().decode("utf-8", errors="replace")
            last_lines = chunk.splitlines()[-40:]
    except Exception as e:
        last_lines = [f"(could not read log: {e})"]
    proc = state.get("process")
    running = proc is not None and proc.poll() is None
    exit_code = None if running else (proc.poll() if proc else None)
    if not running and state.get("running_flag"):
        state["running_flag"] = False
    return {
        "running": running,
        "exit_code": exit_code,
        "last_lines": last_lines,
        "started": True,
        "log_path": str(log_path),
    }


def start_install(tool: str) -> dict:
    """Kick off a background install subprocess. Returns immediately.

    Returns:
        {"ok": bool, "error"?: str, "needs_brew"?: bool, "log_path"?: str}
    """
    if tool not in _INSTALL_COMMANDS:
        return {"ok": False, "error": f"unknown tool: {tool}"}

    system = platform.system()
    cmds = _INSTALL_COMMANDS[tool]
    if system not in cmds:
        return {
            "ok": False,
            "error": f"install for {tool!r} on {system} is not implemented yet",
        }

    # Refuse to start a second install for the same tool while one is
    # already running. The UI should poll install_tool_status() to see
    # when the first one finishes, not hammer this endpoint.
    existing = _INSTALL_STATE.get(tool)
    if existing and existing.get("process") and existing["process"].poll() is None:
        return {
            "ok": True,
            "error": "install already running",
            "log_path": str(existing["log_path"]),
            "already_running": True,
        }

    # brew dependency — if the user clicks "install claude" and brew
    # isn't on PATH, fail fast with needs_brew so the UI can bootstrap.
    if tool != "brew" and system == "Darwin":
        first_arg = cmds[system][0]
        if first_arg in ("brew", "npm") and not shutil.which(first_arg):
            return {
                "ok": False,
                "error": f"required tool {first_arg!r} is not installed on this Mac",
                "needs_brew": first_arg == "brew",
                "needs_node": first_arg == "npm",
            }

    cmd = cmds[system]
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    log_path = _install_log_path(tool)
    log_file = open(log_path, "w")
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env={**os.environ, "NONINTERACTIVE": "1"},
        )
    except Exception as e:
        log_file.close()
        return {"ok": False, "error": f"failed to spawn: {e}"}

    _INSTALL_STATE[tool] = {
        "process": proc,
        "log_file": log_file,
        "log_path": log_path,
        "running_flag": True,
        "started_at": __import__("time").time(),
    }
    logger.info(f"Install of {tool!r} started (pid={proc.pid}, log={log_path})")
    return {"ok": True, "pid": proc.pid, "log_path": str(log_path)}


# ── Bootstrap orchestrator ───────────────────────────────────────────
#
# The single auto-install chain triggered after activation. Walks a
# dependency graph (brew → node → openclaw, brew → claude), runs each
# step in order, streams stdout to a single bootstrap.log + a rolling
# log_tail in _BOOTSTRAP_STATE so the wizard can render live progress
# from one polling endpoint instead of N per-tool polls.
#
# Why a separate state machine from _INSTALL_STATE: the manual per-tool
# install endpoints stay around as a fallback (user clicks "Install"
# from a row that failed during bootstrap). Bootstrap is the happy
# path; per-tool is the recovery path.

import threading

# (prereq, install_argv, post_check)
# install_argv=None means "special handling" (brew bootstrap via Terminal.app)
_BOOTSTRAP_GRAPH: dict[str, tuple[str | None, list[str] | None]] = {
    "brew":     (None,    None),
    "node":     ("brew",  ["brew", "install", "node"]),
    "openclaw": ("node",  ["npm", "install", "-g", "openclaw"]),
    "claude":   ("brew",  ["brew", "install", "claude"]),
}


def _bootstrap_post_check(tool: str) -> bool:
    """Did this tool actually land on PATH after the install command?
    Some installers exit 0 but don't put the binary where we expect."""
    if tool == "brew":
        return shutil.which("brew") is not None
    if tool == "node":
        return shutil.which("npm") is not None
    if tool == "claude":
        return _find_binary("claude", _CLAUDE_FALLBACK_PATHS) is not None
    if tool == "openclaw":
        return _find_binary("openclaw") is not None
    return False


def _plan_bootstrap(targets: list[str]) -> list[str]:
    """Topologically order the install plan, dropping anything already
    installed. So if brew + node already exist, the plan for ["claude",
    "openclaw"] is just ["claude", "openclaw"] in that order."""
    plan: list[str] = []
    visited: set[str] = set()

    def visit(tool: str) -> None:
        if tool in visited:
            return
        visited.add(tool)
        prereq, _ = _BOOTSTRAP_GRAPH[tool]
        if prereq:
            visit(prereq)
        if not _bootstrap_post_check(tool):
            plan.append(tool)

    for t in targets:
        visit(t)
    return plan


_BOOTSTRAP_STATE: dict = {
    "running": False,
    "plan": [],
    "current": None,
    "completed": [],
    "failed": None,
    "needs_brew_terminal": False,
    "log_tail": [],
    "started_at": None,
}
_BOOTSTRAP_LOCK = threading.Lock()


def _bootstrap_log_path() -> Path:
    return WORKSPACE_DIR / "bootstrap.log"


def _append_log(line: str) -> None:
    """Append a single line to bootstrap.log + the rolling tail."""
    try:
        with _bootstrap_log_path().open("a") as f:
            f.write(line + "\n")
    except Exception:
        pass
    tail = _BOOTSTRAP_STATE["log_tail"]
    tail.append(line)
    if len(tail) > 60:
        del tail[: len(tail) - 60]


def _open_brew_install_terminal() -> None:
    """Open Terminal.app with the official Homebrew installer pre-typed.

    Brew is the only step we can't run silently from inside the desktop
    server: the install script needs sudo and there's no PTY here for
    password input. Spawning Terminal.app via osascript hands control
    to the user; the wizard polls shutil.which("brew") and resumes the
    chain automatically once brew lands on PATH.
    """
    install_cmd = (
        '/bin/bash -c "$(curl -fsSL '
        'https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
    )
    # Wrap in single-quote then echo a marker so the user sees a clear
    # finish line in their Terminal window.
    apple_script = (
        f'tell application "Terminal" to do script '
        f'"{install_cmd}; echo; echo \\"=== brew install finished — '
        f'you can close this window ===\\""'
    )
    try:
        subprocess.Popen(["osascript", "-e", apple_script])
        _append_log("[bootstrap] opened Terminal.app for brew install")
    except Exception as e:
        _append_log(f"[bootstrap] failed to open Terminal.app: {e}")


def _wait_for_binary(name: str, timeout: int) -> bool:
    """Block until `name` is on PATH (post-bootstrap), or until timeout."""
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        if shutil.which(name):
            return True
        time.sleep(2)
    return False


def _run_install_step(tool: str, cmd: list[str]) -> bool:
    """Run one install command synchronously, tee stdout into the rolling
    log + bootstrap.log. Returns True iff the command exits 0 AND the
    post-check (binary actually on PATH) also passes."""
    _append_log(f"\n=== {tool}: {' '.join(cmd)} ===")
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env={**os.environ, "NONINTERACTIVE": "1"},
        )
    except FileNotFoundError as e:
        _append_log(f"[bootstrap] spawn failed: {e}")
        return False
    except Exception as e:
        _append_log(f"[bootstrap] spawn error: {e}")
        return False

    assert proc.stdout is not None
    for line in proc.stdout:
        _append_log(line.rstrip())
    code = proc.wait()
    if code != 0:
        _append_log(f"[bootstrap] {tool} install exited {code}")
        return False
    if not _bootstrap_post_check(tool):
        _append_log(f"[bootstrap] {tool} install exited 0 but binary still missing")
        return False
    return True


def _run_bootstrap(plan: list[str]) -> None:
    """Worker thread body: walks the plan in order, updating state."""
    for tool in plan:
        with _BOOTSTRAP_LOCK:
            _BOOTSTRAP_STATE["current"] = tool
        ok = False
        if tool == "brew":
            with _BOOTSTRAP_LOCK:
                _BOOTSTRAP_STATE["needs_brew_terminal"] = True
            _open_brew_install_terminal()
            ok = _wait_for_binary("brew", timeout=600)
            with _BOOTSTRAP_LOCK:
                _BOOTSTRAP_STATE["needs_brew_terminal"] = False
        else:
            _, cmd = _BOOTSTRAP_GRAPH[tool]
            if cmd is None:
                ok = False
            else:
                ok = _run_install_step(tool, cmd)

        if not ok:
            with _BOOTSTRAP_LOCK:
                _BOOTSTRAP_STATE["failed"] = tool
                _BOOTSTRAP_STATE["running"] = False
                _BOOTSTRAP_STATE["current"] = None
            return

        with _BOOTSTRAP_LOCK:
            _BOOTSTRAP_STATE["completed"].append(tool)

    with _BOOTSTRAP_LOCK:
        _BOOTSTRAP_STATE["current"] = None
        _BOOTSTRAP_STATE["running"] = False


def start_bootstrap() -> dict:
    """Kick off the auto-install chain in a background thread.

    Idempotent: if a bootstrap is already running, returns the current
    plan with `already_running=True`. The wizard calls this once after
    activation and then polls bootstrap_status() for progress.
    """
    import time
    with _BOOTSTRAP_LOCK:
        if _BOOTSTRAP_STATE["running"]:
            return {
                "ok": True,
                "already_running": True,
                "plan": list(_BOOTSTRAP_STATE["plan"]),
            }

        plan = _plan_bootstrap(["claude", "openclaw"])
        if not plan:
            # Nothing to install — short-circuit so the wizard skips the overlay.
            return {"ok": True, "plan": [], "already_running": False, "nothing_to_do": True}

        # Reset and seed state
        _BOOTSTRAP_STATE.update(
            running=True,
            plan=plan,
            current=None,
            completed=[],
            failed=None,
            needs_brew_terminal=False,
            log_tail=[],
            started_at=time.time(),
        )
        # Wipe the previous bootstrap.log so the new run starts clean.
        try:
            _bootstrap_log_path().write_text("")
        except Exception:
            pass

    _append_log(f"[bootstrap] plan: {plan}")
    threading.Thread(target=_run_bootstrap, args=(plan,), daemon=True).start()
    return {"ok": True, "plan": plan}


def bootstrap_status() -> dict:
    """Snapshot of the current bootstrap state for the polling UI."""
    with _BOOTSTRAP_LOCK:
        return {
            "running": _BOOTSTRAP_STATE["running"],
            "plan": list(_BOOTSTRAP_STATE["plan"]),
            "current": _BOOTSTRAP_STATE["current"],
            "completed": list(_BOOTSTRAP_STATE["completed"]),
            "failed": _BOOTSTRAP_STATE["failed"],
            "needs_brew_terminal": _BOOTSTRAP_STATE["needs_brew_terminal"],
            "log_tail": list(_BOOTSTRAP_STATE["log_tail"]),
            "started_at": _BOOTSTRAP_STATE["started_at"],
        }
