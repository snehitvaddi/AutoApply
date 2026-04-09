"""
Persistent PTY bridge between the Chat UI and Claude Code / Codex CLI.

Architecture:
  - One long-running CLI process per app session (singleton)
  - User messages are written to the PTY stdin
  - All output streams back to all connected WebSocket clients
  - Session persists across page reloads (reconnect gets buffer backfill)
  - Auto-restarts if the CLI process dies
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import time
from collections import deque
from enum import Enum

from fastapi import WebSocket, WebSocketDisconnect

from .config import load_token, WORKSPACE_DIR, WORKER_DIR

logger = logging.getLogger(__name__)

MAX_BUFFER = 2000  # lines of output to keep for backfill


class SessionState(str, Enum):
    IDLE = "idle"
    THINKING = "thinking"
    STREAMING = "streaming"
    ERROR = "error"
    DEAD = "dead"


class CLISession:
    """
    Persistent Claude Code / Codex CLI session.

    Maintains a single long-running process with PTY I/O.
    All chat WebSocket clients share this one session.
    """

    def __init__(self):
        self.process: asyncio.subprocess.Process | None = None
        self.output_buffer: deque[str] = deque(maxlen=MAX_BUFFER)
        self.state: SessionState = SessionState.DEAD
        self.cli_name: str = ""
        self.started_at: float = 0
        self._subscribers: list[asyncio.Queue] = []
        self._read_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    @property
    def is_alive(self) -> bool:
        return self.process is not None and self.process.returncode is None

    @property
    def uptime(self) -> float:
        return time.time() - self.started_at if self.is_alive else 0

    def status(self) -> dict:
        return {
            "alive": self.is_alive,
            "state": self.state.value,
            "cli": self.cli_name,
            "uptime": self.uptime,
            "buffer_lines": len(self.output_buffer),
            "subscribers": len(self._subscribers),
        }

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        if q in self._subscribers:
            self._subscribers.remove(q)

    def _broadcast(self, msg: dict):
        dead = []
        for q in self._subscribers:
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._subscribers.remove(q)

    @staticmethod
    def _find_cli() -> tuple[str, list[str]] | None:
        """Find available CLI and return (name, base_args).

        Checks shutil.which first, then common global install paths
        since the venv Python's PATH may not include them.
        """
        # Try standard PATH lookup first
        claude = shutil.which("claude")
        if not claude:
            # Check common installation locations for Claude Code
            common_paths = [
                os.path.expanduser("~/.local/bin/claude"),
                "/usr/local/bin/claude",
                os.path.expanduser("~/.npm-global/bin/claude"),
                "/opt/homebrew/bin/claude",
            ]
            for p in common_paths:
                if os.path.isfile(p) and os.access(p, os.X_OK):
                    claude = p
                    break
        if claude:
            return ("claude", [claude, "--dangerously-skip-permissions"])

        codex = shutil.which("codex")
        if codex:
            return ("codex", [codex])
        return None

    async def start(self) -> bool:
        """Start the CLI session. Returns True on success."""
        async with self._lock:
            if self.is_alive:
                return True

            cli = self._find_cli()
            if not cli:
                self.state = SessionState.ERROR
                self._broadcast({"type": "error", "data": "No CLI found. Install Claude Code (`npm i -g @anthropic-ai/claude-code`) or Codex CLI."})
                return False

            self.cli_name, base_cmd = cli

            env = {**os.environ}
            token = load_token()
            if token:
                env["AUTOAPPLY_TOKEN"] = token
                env["WORKER_TOKEN"] = token

            cwd = str(WORKSPACE_DIR) if WORKSPACE_DIR.exists() else str(WORKER_DIR)

            try:
                # Launch via login shell to get full user PATH/env
                shell_cmd = " ".join(base_cmd)
                self.process = await asyncio.create_subprocess_exec(
                    "/bin/bash", "-l", "-c", f"cd {cwd} && {shell_cmd}",
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    env=env,
                )
                self.started_at = time.time()
                self.state = SessionState.IDLE

                # Start reading output in background
                self._read_task = asyncio.create_task(self._read_loop())

                logger.info(f"CLI session started: {self.cli_name} (PID {self.process.pid})")
                self._broadcast({"type": "system", "data": f"Session started with {self.cli_name}"})
                return True

            except Exception as e:
                self.state = SessionState.ERROR
                logger.error(f"Failed to start CLI: {e}")
                self._broadcast({"type": "error", "data": f"Failed to start {self.cli_name}: {e}"})
                return False

    async def _read_loop(self):
        """Continuously read stdout and broadcast to subscribers."""
        try:
            while self.is_alive:
                line = await self.process.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip("\n\r")
                if not text:
                    continue

                self.output_buffer.append(text)

                # Detect state transitions from output patterns
                if self.state == SessionState.THINKING and text.strip():
                    self.state = SessionState.STREAMING

                self._broadcast({"type": "stream", "data": text})

        except Exception as e:
            logger.debug(f"Read loop ended: {e}")
        finally:
            self.state = SessionState.DEAD
            self._broadcast({"type": "session_ended", "data": "CLI session ended"})
            logger.info("CLI session ended")

    async def send_message(self, text: str) -> bool:
        """Send a user message to the CLI stdin."""
        if not self.is_alive:
            # Auto-restart on send
            started = await self.start()
            if not started:
                return False
            # Give the CLI a moment to initialize
            await asyncio.sleep(1)

        if not self.process or not self.process.stdin:
            return False

        try:
            self.state = SessionState.THINKING
            self._broadcast({"type": "status", "data": "thinking"})

            # Write message + newline to stdin
            self.process.stdin.write((text + "\n").encode("utf-8"))
            await self.process.stdin.drain()
            return True
        except Exception as e:
            self.state = SessionState.ERROR
            self._broadcast({"type": "error", "data": f"Send failed: {e}"})
            return False

    async def stop(self):
        """Gracefully stop the CLI session."""
        async with self._lock:
            if self.process and self.is_alive:
                try:
                    self.process.stdin.write(b"/exit\n")
                    await self.process.stdin.drain()
                except Exception:
                    pass

                try:
                    await asyncio.wait_for(self.process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    self.process.terminate()
                    try:
                        await asyncio.wait_for(self.process.wait(), timeout=3)
                    except asyncio.TimeoutError:
                        self.process.kill()

            if self._read_task:
                self._read_task.cancel()
                self._read_task = None

            self.state = SessionState.DEAD
            self._broadcast({"type": "session_ended", "data": "Session stopped"})

    async def restart(self):
        """Stop and restart the session."""
        await self.stop()
        await asyncio.sleep(0.5)
        await self.start()


# ── Singleton session (kept for backward compat, but Chat now uses PTY) ──────

session = CLISession()


# ── WebSocket handler — pipes Chat through the PTY terminal session ──────────

async def chat_websocket(ws: WebSocket):
    """
    Chat WebSocket that connects to the SAME PTY session as the Terminal tab.

    User messages are written to the PTY stdin.
    PTY output is streamed back as clean text (ANSI codes stripped).
    This gives a VS Code extension-like chat experience over the real terminal.
    """
    await ws.accept()

    # Import PTY session
    from .pty_terminal import pty_session

    # Auto-start PTY if not running
    if not pty_session.is_alive:
        pty_session.start()
        await asyncio.sleep(3)  # Wait for Claude to initialize

    await ws.send_json({
        "type": "session_status",
        "alive": pty_session.is_alive,
        "state": "running" if pty_session.is_alive else "dead",
    })

    # Subscribe to PTY output
    queue = pty_session.subscribe()

    # Buffer to accumulate PTY output into coherent messages
    _ansi_escape = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?\x07|\x1b[^[\]()]|\r')

    async def _relay_output():
        """Forward PTY output to Chat WebSocket, stripping ANSI codes."""
        buffer = ""
        try:
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=0.5)
                    # Strip ANSI escape codes for clean chat display
                    text = data.decode("utf-8", errors="replace")
                    clean = _ansi_escape.sub("", text)
                    clean = clean.replace("\r", "")
                    if clean.strip():
                        buffer += clean
                except asyncio.TimeoutError:
                    # Flush buffer as a message after a pause in output
                    if buffer.strip():
                        await ws.send_json({"type": "stream", "data": buffer.strip()})
                        buffer = ""
                    continue
        except Exception:
            pass

    relay_task = asyncio.create_task(_relay_output())

    try:
        while True:
            msg = await ws.receive_json()
            action = msg.get("action", "message")

            if action == "message":
                user_input = msg.get("message", "").strip()
                if user_input:
                    if not pty_session.is_alive:
                        pty_session.start()
                        await asyncio.sleep(3)
                    # Write to PTY stdin (same as typing in Terminal)
                    pty_session.write((user_input + "\n").encode("utf-8"))
                    await ws.send_json({"type": "status", "data": "thinking"})

            elif action == "restart":
                pty_session.restart()
                await ws.send_json({"type": "system", "data": "Session restarted"})

            elif action == "stop":
                pty_session.stop()
                await ws.send_json({"type": "session_ended", "data": "Session stopped"})

            elif action == "status":
                await ws.send_json({
                    "type": "session_status",
                    "alive": pty_session.is_alive,
                    "state": "running" if pty_session.is_alive else "dead",
                })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug(f"Chat WS closed: {e}")
    finally:
        relay_task.cancel()
        pty_session.unsubscribe(queue)
