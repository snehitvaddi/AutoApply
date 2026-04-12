"""Platform-aware PTY abstraction.

Mac/Linux: UnixPTY (pty.fork + fcntl + termios — the existing codepath)
Windows:   WindowsPTY (pywinpty/ConPTY — new, same interface)

The rest of the codebase (pty_terminal.py, watchdog, nudge, chat bridge)
calls PlatformPTY methods and never touches pty.fork() or fcntl directly.
Adding a new platform means implementing PTYBackend and adding a branch here.
"""
from __future__ import annotations

import sys
from typing import Protocol, runtime_checkable


@runtime_checkable
class PTYBackend(Protocol):
    """Cross-platform PTY interface.

    Implementations must provide spawn/read/write/resize/terminate.
    pty_terminal.py calls these instead of raw Unix syscalls.
    """

    def spawn(self, cmd: list[str], cwd: str, env: dict[str, str]) -> int:
        """Start the child process. Returns the child PID.
        On Unix: pty.fork() + os.execvpe in child.
        On Windows: ConPTY CreateProcess.
        """
        ...

    def read(self, size: int = 4096) -> bytes:
        """Non-blocking read from the PTY master. Returns b'' on EOF."""
        ...

    def write(self, data: bytes) -> None:
        """Write bytes to the PTY master (user input → child stdin)."""
        ...

    def resize(self, cols: int, rows: int) -> None:
        """Update the terminal window size."""
        ...

    def is_alive(self) -> bool:
        """Return True if the child process is still running."""
        ...

    def terminate(self) -> None:
        """Send SIGTERM (Unix) or TerminateProcess (Windows)."""
        ...

    def kill(self) -> None:
        """Force-kill the child process."""
        ...

    def close(self) -> None:
        """Clean up file descriptors / handles."""
        ...

    @property
    def pid(self) -> int | None:
        """Child process PID, or None if not started."""
        ...


# Conditional import — the right backend for this platform.
# On Mac/Linux, UnixPTY wraps the familiar pty.fork(). On Windows,
# WindowsPTY wraps pywinpty (ConPTY). Both implement PTYBackend.
if sys.platform == "win32":
    from .pty_windows import WindowsPTY as PlatformPTY  # type: ignore[assignment]
else:
    from .pty_unix import UnixPTY as PlatformPTY  # type: ignore[assignment]

__all__ = ["PTYBackend", "PlatformPTY"]
