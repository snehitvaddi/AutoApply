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
import shutil
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
    NUDGE_MESSAGE = (
        "Status check: are you still applying? If idle, resume work. "
        "If no jobs in queue, scout new jobs then filter and apply. "
        "Run: python3 scripts/auto_loop.py\n"
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

        # Use the openclaw workspace (has SOUL.md, AGENTS.md, PROFILE.md, etc.)
        openclaw_ws = Path.home() / ".openclaw" / "agents" / "job-bot" / "workspace"
        if openclaw_ws.exists():
            cwd = str(openclaw_ws)
        elif WORKSPACE_DIR.exists():
            cwd = str(WORKSPACE_DIR)
        else:
            cwd = os.path.expanduser("~")

        env = {**os.environ}
        token = load_token()
        if token:
            env["AUTOAPPLY_TOKEN"] = token
            env["WORKER_TOKEN"] = token
        # Ensure claude is on PATH
        local_bin = os.path.expanduser("~/.local/bin")
        if local_bin not in env.get("PATH", ""):
            env["PATH"] = f"{local_bin}:{env.get('PATH', '')}"

        # Fork a PTY
        child_pid, master_fd = pty.fork()

        if child_pid == 0:
            # Child process — exec claude with initial instruction as prompt
            os.chdir(cwd)
            initial_prompt = (
                "Read CLAUDE.md and SOUL.md. You are the ApplyLoop job bot. "
                "Start immediately: scout for new AI/ML jobs across all sources, "
                "filter by preferences, then apply. Run: python3 scripts/auto_loop.py. "
                "Do not wait for further instructions — be autonomous."
            )
            os.execvpe(claude, [claude, "--dangerously-skip-permissions", initial_prompt], env)
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
