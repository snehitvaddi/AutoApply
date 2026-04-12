"""Unix PTY backend — wraps pty.fork() + fcntl + termios.

This is the EXISTING Mac/Linux codepath extracted from pty_terminal.py into
a standalone class. No behavior change on Mac — the same syscalls, same
byte sequences, same raw-mode terminal. Just moved behind the PTYBackend
interface so pty_terminal.py doesn't import Unix-only modules at the top
level (which would crash on Windows).
"""
from __future__ import annotations

import fcntl
import logging
import os
import pty
import signal
import struct
import termios
import time

logger = logging.getLogger(__name__)


class UnixPTY:
    """PTYBackend implementation using Unix pty.fork().

    The child process is exec'd in the forked child. The parent gets a
    master file descriptor for bidirectional I/O.
    """

    def __init__(self) -> None:
        self._master_fd: int | None = None
        self._child_pid: int | None = None

    @property
    def pid(self) -> int | None:
        return self._child_pid

    def spawn(self, cmd: list[str], cwd: str, env: dict[str, str]) -> int:
        """Fork a PTY child and exec the command.

        The cmd is expected to be ["/bin/bash", "-c", "<wrapper_script>"]
        for the bash-wrapper pattern used by pty_terminal.py. The cwd and
        env are applied in the child before exec.

        Returns the child PID (parent side). Never returns in the child
        (exec replaces the process image).
        """
        child_pid, master_fd = pty.fork()

        if child_pid == 0:
            # ── Child process ──
            os.chdir(cwd)
            os.execvpe(cmd[0], cmd, env)
            # execvpe never returns; if it does, the child exits immediately
            os._exit(127)
        else:
            # ── Parent process ──
            self._master_fd = master_fd
            self._child_pid = child_pid
            return child_pid

    def read(self, size: int = 4096) -> bytes:
        """Read from the PTY master fd. Returns b'' if the fd is closed."""
        if self._master_fd is None:
            return b""
        try:
            return os.read(self._master_fd, size)
        except OSError:
            return b""

    def write(self, data: bytes) -> None:
        """Write bytes to the PTY master fd (user input → child stdin)."""
        if self._master_fd is not None:
            os.write(self._master_fd, data)

    def resize(self, cols: int, rows: int) -> None:
        """Set the terminal window size via TIOCSWINSZ ioctl."""
        if self._master_fd is not None:
            try:
                winsize = struct.pack("HHHH", rows, cols, 0, 0)
                fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, winsize)
            except Exception:
                pass

    def is_alive(self) -> bool:
        """Non-blocking check: is the child process still running?"""
        if self._child_pid is None:
            return False
        try:
            pid, status = os.waitpid(self._child_pid, os.WNOHANG)
            if pid != 0:
                # Child has exited
                return False
            return True
        except ChildProcessError:
            return False

    def terminate(self) -> None:
        """Send SIGTERM to the child process."""
        if self._child_pid is not None:
            try:
                os.kill(self._child_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def kill(self) -> None:
        """Force-kill the child process with SIGKILL."""
        if self._child_pid is not None:
            try:
                os.kill(self._child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def close(self) -> None:
        """Close the master file descriptor."""
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except Exception:
                pass
            self._master_fd = None

    def wait_brief_death_check(self, timeout: float = 0.05) -> int | None:
        """Brief post-fork death check. If the child died immediately after
        exec (bad binary, missing cwd, etc.), return the exit code. If the
        child is still alive, return None.

        Used by pty_terminal.py to detect immediate exec failures and show
        a useful error instead of "Session active" with an empty terminal.
        """
        time.sleep(timeout)
        if self._child_pid is None:
            return 127
        try:
            pid, status_code = os.waitpid(self._child_pid, os.WNOHANG)
            if pid == self._child_pid:
                if os.WIFEXITED(status_code):
                    return os.WEXITSTATUS(status_code)
                return -1
        except ChildProcessError:
            return -1
        return None  # still alive
