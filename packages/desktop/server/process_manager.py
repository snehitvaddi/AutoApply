"""Manage the worker.py subprocess lifecycle."""
from __future__ import annotations

import asyncio
import logging
import os
import platform
import signal
import subprocess
import time
from collections import deque
from pathlib import Path

from .config import WORKER_DIR, WORKER_PID_FILE, get_worker_env

_IS_DARWIN = platform.system() == "Darwin"
_IS_WINDOWS = platform.system() == "Windows"

logger = logging.getLogger(__name__)

# Ring buffer for terminal output
MAX_LINES = 5000


class WorkerProcess:
    """Manages the worker.py subprocess."""

    def __init__(self):
        self.process: subprocess.Popen | None = None
        self.output_buffer: deque[str] = deque(maxlen=MAX_LINES)
        self.started_at: float | None = None
        self.restart_count: int = 0
        self._readers: list[asyncio.Queue] = []
        self._read_task: asyncio.Task | None = None

    @property
    def is_running(self) -> bool:
        if self.process is None:
            return False
        return self.process.poll() is None

    @property
    def pid(self) -> int | None:
        return self.process.pid if self.process else None

    @property
    def uptime_seconds(self) -> float:
        if not self.started_at or not self.is_running:
            return 0
        return time.time() - self.started_at

    def status(self) -> dict:
        return {
            "running": self.is_running,
            "pid": self.pid,
            "uptime": self.uptime_seconds,
            "restart_count": self.restart_count,
            "buffer_lines": len(self.output_buffer),
        }

    def subscribe(self) -> asyncio.Queue:
        """Subscribe to live output. Returns a queue that receives new lines."""
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._readers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        """Remove a subscriber."""
        if q in self._readers:
            self._readers.remove(q)

    def _broadcast(self, line: str):
        """Send a line to all subscribers."""
        dead = []
        for q in self._readers:
            try:
                q.put_nowait(line)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._readers.remove(q)

    async def _read_output(self):
        """Read stdout from the subprocess and buffer + broadcast."""
        if not self.process or not self.process.stdout:
            return
        loop = asyncio.get_event_loop()
        while self.is_running:
            try:
                line = await loop.run_in_executor(
                    None, self.process.stdout.readline
                )
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip("\n")
                self.output_buffer.append(text)
                self._broadcast(text)
            except Exception:
                break

    def _check_existing(self) -> bool:
        """Check if a worker is already running from a PID file.

        Liveness check uses os.kill(pid, 0) which works identically on
        Unix and Windows — raises ProcessLookupError on Unix and OSError
        on Windows if the PID isn't alive, and does nothing otherwise.
        The command-name verification step uses `ps` on Unix and `tasklist`
        on Windows; if either is unavailable we just trust the os.kill
        result rather than failing the whole startup.
        """
        if not WORKER_PID_FILE.exists():
            return False
        try:
            pid = int(WORKER_PID_FILE.read_text().strip())
            os.kill(pid, 0)  # cross-platform liveness check
            # Verify it's actually a python/worker process, not a reused PID
            try:
                if _IS_WINDOWS:
                    result = subprocess.run(
                        ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                        capture_output=True, text=True, timeout=2,
                    )
                    cmd = result.stdout.strip().lower()
                else:
                    result = subprocess.run(
                        ["ps", "-p", str(pid), "-o", "command="],
                        capture_output=True, text=True, timeout=2,
                    )
                    cmd = result.stdout.strip()
                if "worker" not in cmd.lower() and "python" not in cmd.lower():
                    logger.info(f"PID {pid} exists but is not a worker: {cmd[:50]}")
                    WORKER_PID_FILE.unlink(missing_ok=True)
                    return False
            except Exception:
                # Can't verify command name — trust the liveness check
                pass
            logger.info(f"Worker already running with PID {pid}")
            return True
        except (ValueError, OSError):
            WORKER_PID_FILE.unlink(missing_ok=True)
            return False

    async def start(self) -> dict:
        """Start the worker subprocess."""
        if self.is_running:
            return {"ok": False, "error": "Worker is already running", **self.status()}

        if self._check_existing():
            return {"ok": False, "error": "Worker already running from another session"}

        worker_script = WORKER_DIR / "worker.py"
        if not worker_script.exists():
            return {"ok": False, "error": f"worker.py not found at {worker_script}"}

        env = get_worker_env()
        # macOS: wrap the worker in `script(1)` to allocate a PTY — this
        # bypasses macOS TCC restrictions that would otherwise block
        # .app-spawned processes from reading user files in Downloads/
        # Desktop/etc. (Those restrictions don't exist on Windows/Linux,
        # so we spawn the Python interpreter directly there.)
        if _IS_DARWIN:
            script_wrapper = f"""cd '{str(WORKER_DIR)}' && exec python3 '{str(worker_script)}'"""
            self.process = subprocess.Popen(
                ["/usr/bin/script", "-q", "/dev/null", "/bin/bash", "-l", "-c", script_wrapper],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
            )
        else:
            # Windows + Linux: direct spawn, no PTY wrapper needed.
            import sys as _sys
            self.process = subprocess.Popen(
                [_sys.executable, str(worker_script)],
                cwd=str(WORKER_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
            )
        self.started_at = time.time()

        # Write PID file
        WORKER_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        WORKER_PID_FILE.write_text(str(self.process.pid))

        # Start reading output in background
        self._read_task = asyncio.create_task(self._read_output())

        logger.info(f"Worker started with PID {self.process.pid}")
        return {"ok": True, **self.status()}

    async def stop(self) -> dict:
        """Stop the worker subprocess gracefully."""
        if not self.is_running:
            return {"ok": False, "error": "Worker is not running"}

        pid = self.process.pid
        self.process.send_signal(signal.SIGTERM)

        # Wait up to 10s for graceful shutdown
        for _ in range(100):
            if self.process.poll() is not None:
                break
            await asyncio.sleep(0.1)

        if self.process.poll() is None:
            self.process.kill()
            logger.warning(f"Worker {pid} killed after timeout")

        WORKER_PID_FILE.unlink(missing_ok=True)

        if self._read_task:
            self._read_task.cancel()
            self._read_task = None

        self._broadcast("[Worker stopped]")
        logger.info(f"Worker {pid} stopped")
        return {"ok": True, "pid": pid}

    async def restart(self) -> dict:
        """Stop then start the worker."""
        if self.is_running:
            await self.stop()
        self.restart_count += 1
        return await self.start()


# Singleton instance
worker = WorkerProcess()
