"""
Real interactive PTY terminal for the browser.

Spawns `claude --dangerously-skip-permissions` in a real pseudo-terminal.
Bridges PTY I/O to WebSocket — user can type, see output, just like a real terminal.
Session persists across page refreshes (reconnect gets buffer backfill).
"""
from __future__ import annotations

import asyncio
import logging
import os
import shlex
import shutil
import subprocess
import time
import uuid
import struct
import fcntl
import termios
import pty
import signal
from collections import deque
from pathlib import Path

from fastapi import WebSocket, WebSocketDisconnect

from .config import load_token, WORKSPACE_DIR

logger = logging.getLogger(__name__)

MAX_BUFFER = 50000  # characters of scrollback


class SessionRecord:
    """Track a single session's lifecycle."""
    def __init__(self, pid: int):
        self.session_id = str(uuid.uuid4())[:8]
        self.pid = pid
        self.started_at = time.time()
        self.stopped_at: float | None = None
        self.status = "running"

    def stop(self):
        self.stopped_at = time.time()
        self.status = "stopped"

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "pid": self.pid,
            "started_at": self.started_at,
            "stopped_at": self.stopped_at,
            "status": self.status,
            "duration": (self.stopped_at or time.time()) - self.started_at,
        }


# Global session history
session_history: list[SessionRecord] = []


class PTYSession:
    """A persistent PTY session running claude --dangerously-skip-permissions."""

    IDLE_THRESHOLD = 1800  # 30 minutes
    WATCHDOG_INTERVAL = 300  # check every 5 minutes
    # Updated for v1.0.10 + AGENTS.md architecture. Old copy pointed at
    # `python3 scripts/auto_loop.py` which was the pre-worker layout.
    NUDGE_MESSAGE = (
        "Status check (auto-nudge from ApplyLoop watchdog): you've been idle "
        "for over 30 minutes. What have you been doing? If you've finished the "
        "current scout/filter/apply round, kick off the next one: "
        "cd ~/.applyloop/packages/worker && python3 worker.py. "
        "If you're waiting on user input, tell them explicitly in one short line "
        "so they know to check in. Do not sit silent.\n"
    )

    def __init__(self):
        self.master_fd: int | None = None
        self.child_pid: int | None = None
        self.output_buffer: deque[bytes] = deque(maxlen=MAX_BUFFER)
        self._subscribers: list[asyncio.Queue] = []
        self._read_task: asyncio.Task | None = None
        self._watchdog_task: asyncio.Task | None = None
        self._alive = False
        self.session_id: str | None = None
        self.last_output_at: float = 0
        self.started_at: float = 0

    @property
    def is_alive(self) -> bool:
        if not self._alive or self.child_pid is None:
            return False
        try:
            pid, status = os.waitpid(self.child_pid, os.WNOHANG)
            if pid != 0:
                self._alive = False
                return False
            return True
        except ChildProcessError:
            self._alive = False
            return False

    def status(self) -> dict:
        idle_seconds = (time.time() - self.last_output_at) if self.last_output_at else 0
        return {
            "session_id": self.session_id,
            "alive": self.is_alive,
            "pid": self.child_pid,
            "buffer_size": sum(len(b) for b in self.output_buffer),
            "subscribers": len(self._subscribers),
            "uptime": (time.time() - self.started_at) if self.started_at and self.is_alive else 0,
            "idle_seconds": idle_seconds if self.is_alive else 0,
            "idle_minutes": int(idle_seconds / 60) if self.is_alive else 0,
        }

    @staticmethod
    def _find_claude() -> str | None:
        """Find claude binary."""
        claude = shutil.which("claude")
        if claude:
            return claude
        for p in [
            os.path.expanduser("~/.local/bin/claude"),
            "/usr/local/bin/claude",
            "/opt/homebrew/bin/claude",
            os.path.expanduser("~/.npm-global/bin/claude"),
        ]:
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return p
        return None

    def start(self) -> bool:
        """Spawn the PTY session."""
        if self.is_alive:
            return True

        claude = self._find_claude()
        if not claude:
            logger.error("Claude CLI not found")
            return False

        # Use the configured ApplyLoop workspace. (Legacy ~/.openclaw fallback
        # removed — honoring it broke multi-tenancy because every instance
        # would fight over the same directory regardless of APPLYLOOP_WORKSPACE.)
        # Prefer the install dir ($APPLYLOOP_HOME or ~/.applyloop) so relative
        # paths in AGENTS.md / SOUL.md resolve — that's where the script,
        # worker, profile.json, and .env all live. Fall back to WORKSPACE_DIR
        # and finally $HOME if the install dir doesn't exist.
        applyloop_home = os.environ.get(
            "APPLYLOOP_HOME", os.path.expanduser("~/.applyloop")
        )
        if os.path.isdir(applyloop_home):
            cwd = applyloop_home
        elif WORKSPACE_DIR.exists():
            cwd = str(WORKSPACE_DIR)
        else:
            try:
                WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
                cwd = str(WORKSPACE_DIR)
            except Exception:
                cwd = os.path.expanduser("~")

        # Belt-and-suspenders: make sure cwd actually exists on disk. If a
        # stale APPLYLOOP_HOME env var points at a deleted directory,
        # os.chdir() in the child would raise and claude would exit before
        # producing any output — the terminal tab would be empty with no
        # explanation. Create it if it's missing.
        try:
            os.makedirs(cwd, exist_ok=True)
        except Exception as e:
            logger.warning(f"Could not create cwd {cwd}: {e}")
            cwd = os.path.expanduser("~")

        env = {**os.environ}
        token = load_token()
        if token:
            env["AUTOAPPLY_TOKEN"] = token
            env["WORKER_TOKEN"] = token

        # Build a PATH that includes every place claude/openclaw/npm could
        # live. When the app is launched from Finder/Dock, macOS gives the
        # process a bare PATH (/usr/bin:/bin:/usr/sbin:/sbin) and the
        # launcher's brew shellenv adds /opt/homebrew/bin, but if the user
        # bypasses the launcher (dev mode, launchctl, etc.) those dirs
        # aren't there. Explicitly prepend them so the child can always
        # find claude regardless of how the server was started.
        path_prepends = [
            os.path.expanduser("~/.local/bin"),
            "/opt/homebrew/bin",
            "/usr/local/bin",
        ]
        # Also include the npm global prefix if we can find it — that's
        # where `openclaw` lands.
        try:
            npm_prefix = os.environ.get("NPM_CONFIG_PREFIX") or (
                subprocess.run(
                    ["npm", "config", "get", "prefix"],
                    capture_output=True, text=True, timeout=3,
                ).stdout.strip() if shutil.which("npm") else ""
            )
            if npm_prefix and os.path.isdir(f"{npm_prefix}/bin"):
                path_prepends.append(f"{npm_prefix}/bin")
        except Exception:
            pass

        existing_path = env.get("PATH", "")
        existing_parts = existing_path.split(":") if existing_path else []
        for p in path_prepends:
            if p and p not in existing_parts:
                existing_parts.insert(0, p)
        env["PATH"] = ":".join(existing_parts)

        logger.info(
            f"PTY start: claude={claude} cwd={cwd} "
            f"PATH-head={':'.join(existing_parts[:3])}"
        )

        # Pre-fill the output buffer with a visible "starting..." line so
        # WebSocket clients that connect BEFORE Claude produces its first
        # byte see something instead of an empty black screen. The line
        # is sent via the normal _broadcast path the moment a subscriber
        # attaches.
        startup_banner = (
            "\x1b[36m[ApplyLoop]\x1b[0m Starting Claude Code session...\r\n"
            "\x1b[36m[ApplyLoop]\x1b[0m On first run, Claude will print an\r\n"
            "\x1b[36m[ApplyLoop]\x1b[0m OAuth URL - open it in your browser,\r\n"
            "\x1b[36m[ApplyLoop]\x1b[0m paste the code back here, and you're in.\r\n"
            "\r\n"
        ).encode("utf-8")
        self.output_buffer.append(startup_banner)

        # Fork a PTY
        child_pid, master_fd = pty.fork()

        if child_pid == 0:
            # Child process — exec a bash wrapper that:
            #   1. Checks if ~/.claude/ has any auth state (tokens cached
            #      from a prior `claude login`).
            #   2. If yes: runs claude --dangerously-skip-permissions with
            #      the initial prompt. Claude starts immediately with
            #      context from AGENTS.md + SOUL.md + profile.json.
            #   3. When Claude exits (normal exit, auth error, user
            #      pressed Ctrl-C, anything): falls through to `exec zsh
            #      -l`, dropping the user to a real shell prompt so they
            #      can debug, re-run commands, or `claude login` + retry.
            #
            # Why this matters (Pujith's feedback): the previous direct
            # exec of claude meant that if Claude crashed or exited, the
            # terminal tab was DEAD — no way to type commands, no way to
            # fix things without restarting the whole session. Non-
            # technical users saw a black screen and gave up. With the
            # wrapper, they always have a shell fallback.
            os.chdir(cwd)

            initial_prompt = (
                "Read ./AGENTS.md for your full context and system status. "
                "Then read ./packages/worker/SOUL.md for the scout/apply playbook. "
                "Read ./profile.json to know who the user is. "
                "Greet the user by first name (from profile.json personal.first_name) ONCE, "
                "describe your capabilities briefly, then WAIT for commands. "
                "DO NOT auto-start the loop - the user must say 'start' or 'scout'. "
                "If profile.json is missing, tell the user the install is incomplete "
                "and point them at `applyloop update`."
            )
            # Single-quote escape for the prompt inside the bash -c string:
            # any single-quote in the prompt becomes '"'"'. We don't have
            # any in the current prompt text, but defensive anyway.
            escaped_prompt = initial_prompt.replace("'", "'\"'\"'")

            # The claude binary path is resolved above; pass it in via
            # env var so the wrapper finds it without its own PATH lookup.
            env["APPLYLOOP_CLAUDE_BIN"] = claude

            # Build the wrapper script via string concat (not an f-string)
            # because the heredoc has `%s` printf format specifiers and f-
            # strings mangle braces. Only two substitutions: the cwd and
            # the escaped prompt. Use .replace() for both.
            wrapper_template = r"""#!/bin/bash
# Child wrapper — keeps the PTY alive even if claude exits.
# Drop into a zsh login shell on exit so the user can recover.
cd __CWD__

CYAN=$'\033[36m'
GREEN=$'\033[32m'
YELLOW=$'\033[33m'
RESET=$'\033[0m'

printf '%s[ApplyLoop]%s cwd=%s%s%s\r\n' "$CYAN" "$RESET" "$CYAN" "$PWD" "$RESET"

# Check Claude Code authentication state. Claude stores tokens under
# ~/.claude/ after `claude login`. If the directory exists AND has
# content (not just an empty marker), we consider it authed.
if [[ -d "$HOME/.claude" ]] && [[ -n "$(ls -A "$HOME/.claude" 2>/dev/null)" ]]; then
  printf '%s[ApplyLoop]%s Claude Code is authenticated - starting session...\r\n' "$GREEN" "$RESET"
  # Capture a small tail of claude's output to the session log so we can
  # classify exit reasons below. Use `script` if available for real PTY
  # mirroring, else fall back to tee — but tee captures are worse for
  # ANSI handling. Keep it simple: rely on ~/.claude/logs tail instead.
  "$APPLYLOOP_CLAUDE_BIN" --dangerously-skip-permissions '__PROMPT__'
  CLAUDE_EXIT=$?

  # Exit-code + log-tail classifier. Tries to translate whatever Claude
  # printed into a human line. Non-technical users see "your plan has
  # hit its daily limit, resets in N hours" instead of a raw red error.
  CLAUDE_REASON=""
  CLAUDE_HINT=""
  # Look at the last ~40 lines of the most recent claude log.
  CLAUDE_LOG_DIR="$HOME/.claude/logs"
  LAST_LINES=""
  if [[ -d "$CLAUDE_LOG_DIR" ]]; then
    LATEST_LOG=$(ls -t "$CLAUDE_LOG_DIR"/*.log 2>/dev/null | head -1)
    if [[ -n "$LATEST_LOG" && -f "$LATEST_LOG" ]]; then
      LAST_LINES=$(tail -40 "$LATEST_LOG" 2>/dev/null)
    fi
  fi
  # Pattern-match against common Claude Code error phrases. Order
  # matters — more-specific matches first.
  if echo "$LAST_LINES" | grep -qiE 'rate.?limit|429|too many requests'; then
    CLAUDE_REASON="Anthropic API rate limit hit"
    CLAUDE_HINT="Wait a few minutes and try again. If this keeps happening, your Claude plan may be undersized for the workload."
  elif echo "$LAST_LINES" | grep -qiE 'daily.{0,20}limit|usage.{0,20}limit|quota.{0,20}exceeded|plan.{0,20}limit'; then
    CLAUDE_REASON="Your Claude plan's daily quota is used up"
    CLAUDE_HINT="Resets at midnight Pacific time. Or upgrade at https://claude.com/billing"
  elif echo "$LAST_LINES" | grep -qiE 'upgrade|pro plan|max plan|requires.{0,20}subscription'; then
    CLAUDE_REASON="Claude needs a higher-tier plan for this model"
    CLAUDE_HINT="Upgrade at https://claude.com/billing"
  elif echo "$LAST_LINES" | grep -qiE 'invalid.{0,20}token|unauthorized|401|expired.{0,20}token|re-?authenticate|please.{0,20}log.?in'; then
    CLAUDE_REASON="Claude Code auth expired or invalid"
    CLAUDE_HINT="Run: claude login (then paste the code from your browser)"
  elif echo "$LAST_LINES" | grep -qiE 'connection.{0,20}refused|network|timeout|could not connect|ENOTFOUND|dns'; then
    CLAUDE_REASON="Network error reaching Anthropic"
    CLAUDE_HINT="Check your internet. If you're on a corporate VPN, try toggling it off. Claude needs api.anthropic.com reachable."
  elif [[ "$CLAUDE_EXIT" == "0" ]]; then
    CLAUDE_REASON="Session ended normally"
    CLAUDE_HINT="Type 'claude' to start a new one, or 'applyloop status' for worker state."
  elif [[ "$CLAUDE_EXIT" == "127" ]]; then
    CLAUDE_REASON="Claude Code binary not found on PATH"
    CLAUDE_HINT="Run: applyloop update  (this reinstalls claude via brew)"
  elif [[ "$CLAUDE_EXIT" == "130" ]]; then
    CLAUDE_REASON="Session interrupted with Ctrl-C"
    CLAUDE_HINT="Type 'claude' to restart."
  else
    CLAUDE_REASON="Claude Code session ended unexpectedly (exit $CLAUDE_EXIT)"
    CLAUDE_HINT="Try 'claude' to restart. If it keeps failing, 'applyloop logs' shows the full trace."
  fi

  printf '\r\n%s[ApplyLoop]%s %s%s%s\r\n' "$YELLOW" "$RESET" "$CYAN" "$CLAUDE_REASON" "$RESET"
  printf '%s[ApplyLoop]%s %s\r\n' "$YELLOW" "$RESET" "$CLAUDE_HINT"
  printf '%s[ApplyLoop]%s Dropping to shell - type %sclaude%s to restart.\r\n\r\n' "$YELLOW" "$RESET" "$CYAN" "$RESET"
else
  printf '%s[ApplyLoop]%s Claude Code is not authenticated yet.\r\n' "$YELLOW" "$RESET"
  printf '%s[ApplyLoop]%s Run: %sclaude login%s\r\n' "$YELLOW" "$RESET" "$CYAN" "$RESET"
  printf '%s[ApplyLoop]%s Follow the browser prompt, paste the code back here,\r\n' "$YELLOW" "$RESET"
  printf '%s[ApplyLoop]%s then type %sclaude%s to start the session.\r\n\r\n' "$YELLOW" "$RESET" "$CYAN" "$RESET"
fi

# Drop to a login shell so the user always has something to type into.
# zsh -l loads .zprofile + .zshrc so they get their normal environment.
exec /bin/zsh -l
"""
            wrapper = wrapper_template.replace("__CWD__", shlex.quote(cwd)).replace("__PROMPT__", escaped_prompt)
            os.execvpe("/bin/bash", ["/bin/bash", "-c", wrapper], env)
        else:
            # Parent process
            self.master_fd = master_fd
            self.child_pid = child_pid
            self._alive = True
            self.started_at = time.time()
            self.last_output_at = time.time()
            self._current_record = SessionRecord(child_pid)
            self.session_id = self._current_record.session_id

            # Set terminal size (80x24 default, will be resized by client)
            self._set_size(80, 24)

            # Brief post-fork death check. If execvpe failed in the child
            # (bad cwd, missing claude binary, permission denied, etc.) the
            # child exits instantly. Without this check, the parent sets
            # self._alive = True and returns success — the UI shows
            # "Session active" but the terminal is empty. waitpid with
            # WNOHANG is non-blocking; if the child is still running we
            # get pid=0.
            time.sleep(0.05)  # give execvpe a moment to either succeed or fail
            try:
                pid, status_code = os.waitpid(child_pid, os.WNOHANG)
                if pid == child_pid:
                    # Child died before we could attach — log the exit code
                    # and surface it as a banner in the buffer so the UI
                    # shows what happened.
                    exit_code = os.WEXITSTATUS(status_code) if os.WIFEXITED(status_code) else -1
                    logger.error(
                        f"PTY child died immediately after fork "
                        f"(pid={child_pid}, exit_code={exit_code}). "
                        f"Likely causes: claude binary at {claude} is broken, "
                        f"cwd {cwd} inaccessible, or exec environment missing "
                        f"critical vars."
                    )
                    self.output_buffer.append(
                        f"\x1b[31m[ApplyLoop]\x1b[0m Claude Code failed to start "
                        f"(exit {exit_code}).\r\n"
                        f"\x1b[31m[ApplyLoop]\x1b[0m Check ~/.autoapply/desktop.log "
                        f"for details. Try: applyloop update\r\n\r\n".encode()
                    )
                    self._alive = False
                    self.child_pid = None
                    try:
                        os.close(master_fd)
                    except Exception:
                        pass
                    self.master_fd = None
                    return False
            except ChildProcessError:
                # Already reaped — fall through
                pass

            # Start reading + watchdog in background
            self._read_task = asyncio.create_task(self._read_loop())
            self._watchdog_task = asyncio.create_task(self._watchdog_loop())

            logger.info(f"PTY session started: PID {child_pid}, claude at {claude}")
            return True

    def _set_size(self, cols: int, rows: int):
        """Resize the PTY."""
        if self.master_fd is not None:
            try:
                winsize = struct.pack("HHHH", rows, cols, 0, 0)
                fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)
            except Exception:
                pass

    async def _read_loop(self):
        """Read PTY output and broadcast to subscribers."""
        loop = asyncio.get_event_loop()
        try:
            while self.is_alive and self.master_fd is not None:
                try:
                    data = await loop.run_in_executor(
                        None, lambda: os.read(self.master_fd, 4096)
                    )
                    if not data:
                        break
                    self.output_buffer.append(data)
                    self.last_output_at = time.time()
                    self._broadcast(data)
                except OSError:
                    break
        finally:
            self._alive = False
            self._broadcast(b"\r\n[Session ended]\r\n")

    async def _watchdog_loop(self):
        """Check every 5 min if the PTY session is idle. Nudge after 30 min."""
        try:
            while self.is_alive:
                await asyncio.sleep(self.WATCHDOG_INTERVAL)
                if not self.is_alive or not self.last_output_at:
                    continue
                idle_seconds = time.time() - self.last_output_at
                idle_min = int(idle_seconds / 60)
                if idle_seconds > self.IDLE_THRESHOLD:
                    logger.info(f"PTY idle for {idle_min}m — sending nudge")
                    self.write(self.NUDGE_MESSAGE.encode("utf-8"))
                    self.last_output_at = time.time()  # reset to avoid spamming
                elif idle_seconds > self.IDLE_THRESHOLD / 2:
                    logger.debug(f"PTY idle for {idle_min}m (nudge at 30m)")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f"Watchdog ended: {e}")
            logger.info("PTY read loop ended")

    def _broadcast(self, data: bytes):
        """Send data to all WebSocket subscribers."""
        dead = []
        for q in self._subscribers:
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._subscribers.remove(q)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        if q in self._subscribers:
            self._subscribers.remove(q)

    def write(self, data: bytes):
        """Write user input to the PTY."""
        if self.master_fd is not None and self.is_alive:
            os.write(self.master_fd, data)

    def resize(self, cols: int, rows: int):
        """Handle terminal resize from the client."""
        self._set_size(cols, rows)

    def stop(self):
        """Kill the PTY session."""
        if hasattr(self, '_current_record') and self._current_record:
            self._current_record.stop()
        if self.child_pid and self.is_alive:
            try:
                os.kill(self.child_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        if self.master_fd is not None:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            self.master_fd = None
        self._alive = False
        if self._read_task:
            self._read_task.cancel()
            self._read_task = None
        if self._watchdog_task:
            self._watchdog_task.cancel()
            self._watchdog_task = None

    def restart(self):
        """Stop and restart."""
        self.stop()
        self.output_buffer.clear()
        self.start()


# ── Session Manager ──────────────────────────────────────────────────────────

class SessionManager:
    """
    Manages PTY sessions — one active at a time, with history.

    Rules:
    - Only ONE session can be active at a time
    - Dead sessions stay in history (viewable, deletable, not resumable)
    - Deleting the active session stops it and does NOT auto-create a new one
    - User must click "New Session" or "Start Session" to create a new one
    - No duplicates in the session list
    """

    def __init__(self):
        self.sessions: list[SessionRecord] = []
        self.pty: PTYSession = PTYSession()

    @property
    def active_session_id(self) -> str | None:
        return self.pty.session_id if self.pty.is_alive else None

    def _sync(self):
        """Ensure session list is consistent with PTY state."""
        # Mark records as stopped if their PTY is dead
        active_id = self.active_session_id
        for s in self.sessions:
            if s.status == "running" and s.session_id != active_id:
                s.stop()
        # Deduplicate by session_id
        seen = set()
        unique = []
        for s in self.sessions:
            if s.session_id not in seen:
                seen.add(s.session_id)
                unique.append(s)
        self.sessions = unique

    def get_sessions(self) -> list[dict]:
        self._sync()
        return [s.to_dict() for s in self.sessions]

    def new_session(self) -> dict:
        """Stop current PTY, create a fresh one."""
        if self.pty.is_alive:
            self.pty.stop()
        self.pty = PTYSession()
        self.pty.start()
        # Register in history (only if start succeeded)
        if self.pty._current_record:
            self.sessions.append(self.pty._current_record)
        self._sync()
        return self.pty.status()

    def delete_session(self, session_id: str) -> dict:
        """Delete a session. If active, just stops it — does NOT auto-create."""
        self._sync()
        record = next((s for s in self.sessions if s.session_id == session_id), None)
        if not record:
            return {"ok": False, "error": "Session not found"}

        is_active = (self.pty.session_id == session_id)
        if is_active and self.pty.is_alive:
            self.pty.stop()

        self.sessions.remove(record)
        return {"ok": True, "active_session_id": self.active_session_id}

    def clear_history(self):
        """Remove all stopped sessions from history."""
        self._sync()
        self.sessions = [s for s in self.sessions if s.status == "running"]


session_manager = SessionManager()


async def pty_terminal_websocket(ws: WebSocket):
    """
    Interactive PTY terminal over WebSocket.

    Messages from client:
      - {"type": "input", "data": "..."} — keystrokes
      - {"type": "resize", "cols": N, "rows": N} — terminal resize
      - {"type": "start"} — start/restart session

    Messages to client:
      - binary frames — raw PTY output
    """
    await ws.accept()

    # Auto-start if not running (go through manager so it's registered)
    if not session_manager.pty.is_alive:
        session_manager.new_session()

    # Send status
    await ws.send_json({"type": "status", **session_manager.pty.status()})

    # Backfill — send buffered output
    for chunk in session_manager.pty.output_buffer:
        await ws.send_bytes(chunk)

    # Subscribe to live output
    queue = session_manager.pty.subscribe()

    async def _relay_output():
        """Forward PTY output to WebSocket."""
        try:
            while True:
                data = await queue.get()
                await ws.send_bytes(data)
        except Exception:
            pass

    relay_task = asyncio.create_task(_relay_output())

    try:
        while True:
            msg = await ws.receive()

            if "text" in msg:
                import json
                parsed = json.loads(msg["text"])
                msg_type = parsed.get("type", "")

                if msg_type == "input":
                    session_manager.pty.write(parsed["data"].encode("utf-8"))
                elif msg_type == "resize":
                    session_manager.pty.resize(parsed.get("cols", 80), parsed.get("rows", 24))
                elif msg_type == "start":
                    session_manager.pty.restart()
                    await ws.send_json({"type": "status", **session_manager.pty.status()})
                elif msg_type == "stop":
                    session_manager.pty.stop()
                    await ws.send_json({"type": "status", **session_manager.pty.status()})

            elif "bytes" in msg:
                # Raw binary input from xterm.js
                session_manager.pty.write(msg["bytes"])

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug(f"PTY WS closed: {e}")
    finally:
        relay_task.cancel()
        session_manager.pty.unsubscribe(queue)
