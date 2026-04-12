"""Windows PTY backend — wraps pywinpty (ConPTY).

ConPTY is the Windows Pseudo Console API (Windows 10 1809+). It's the same
API that Windows Terminal, VS Code terminal, and Git Bash use. pywinpty
provides a Python binding that gives us a PtyProcess with .read() / .write()
— close enough to the Unix master_fd that pty_terminal.py works unchanged.

Install: pip install pywinpty  (only needed on Windows; the requirements.txt
uses a platform marker so Mac/Linux don't pull it in).
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time

logger = logging.getLogger(__name__)

# Guard: this module is only imported on Windows via pty_backend.py's
# conditional import. If someone accidentally imports it on Mac, fail
# with a clear message instead of a cryptic winpty error.
if sys.platform != "win32":
    raise ImportError("pty_windows.py is Windows-only. Use pty_unix.py on Mac/Linux.")

try:
    from winpty import PtyProcess  # type: ignore[import-untyped]
except ImportError:
    raise ImportError(
        "pywinpty is required on Windows. Install: pip install pywinpty>=2.0.0"
    )


class WindowsPTY:
    """PTYBackend implementation using pywinpty (ConPTY).

    Mirrors the UnixPTY interface: spawn/read/write/resize/terminate.
    The main difference is that pywinpty handles fork+exec internally —
    we just call PtyProcess.spawn() with the command and get a process
    handle back.
    """

    def __init__(self) -> None:
        self._proc: PtyProcess | None = None
        self._pid: int | None = None

    @property
    def pid(self) -> int | None:
        return self._pid

    def spawn(self, cmd: list[str], cwd: str, env: dict[str, str]) -> int:
        """Start the child process in a ConPTY.

        pywinpty takes the command as a single string (not a list), so we
        join it. The dimensions default to 80x24 and get updated by the
        first resize() call from the client.

        On Windows, the bash wrapper from pty_terminal.py needs adaptation:
        instead of `/bin/bash -c "..."`, we use `cmd /c "..."` or
        `powershell -Command "..."`. The caller (pty_terminal._build_windows_cmd)
        is responsible for constructing the right command — we just spawn it.
        """
        # pywinpty.PtyProcess.spawn expects a string command on Windows
        if len(cmd) == 1:
            cmd_str = cmd[0]
        else:
            # Join with proper quoting for cmd.exe
            cmd_str = subprocess.list2cmdline(cmd)

        self._proc = PtyProcess.spawn(
            cmd_str,
            cwd=cwd,
            env=env,
            dimensions=(24, 80),
        )
        self._pid = self._proc.pid
        logger.info(f"WindowsPTY spawned PID {self._pid}: {cmd_str[:120]}")
        return self._pid

    def read(self, size: int = 4096) -> bytes:
        """Read from the ConPTY output. Returns b'' on EOF/error."""
        if self._proc is None:
            return b""
        try:
            data = self._proc.read(size)
            if isinstance(data, str):
                return data.encode("utf-8", errors="replace")
            return data
        except EOFError:
            return b""
        except Exception:
            return b""

    def write(self, data: bytes) -> None:
        """Write bytes to the ConPTY input (user input → child stdin)."""
        if self._proc is not None:
            try:
                text = data.decode("utf-8", errors="replace")
                self._proc.write(text)
            except Exception as e:
                logger.debug(f"WindowsPTY write error: {e}")

    def resize(self, cols: int, rows: int) -> None:
        """Update the ConPTY window size."""
        if self._proc is not None:
            try:
                self._proc.setwinsize(rows, cols)
            except Exception:
                pass

    def is_alive(self) -> bool:
        """Check if the child process is still running."""
        if self._proc is None:
            return False
        return self._proc.isalive()

    def terminate(self) -> None:
        """Terminate the child process."""
        if self._proc is not None:
            try:
                self._proc.terminate()
            except Exception:
                pass

    def kill(self) -> None:
        """Force-kill the child process."""
        if self._proc is not None:
            try:
                self._proc.terminate(force=True)
            except Exception:
                # Fallback: use taskkill
                if self._pid:
                    try:
                        subprocess.run(
                            ["taskkill", "/F", "/PID", str(self._pid)],
                            capture_output=True, timeout=5,
                        )
                    except Exception:
                        pass

    def close(self) -> None:
        """Clean up the ConPTY process."""
        if self._proc is not None:
            try:
                if self._proc.isalive():
                    self._proc.terminate()
            except Exception:
                pass
            self._proc = None

    def wait_brief_death_check(self, timeout: float = 0.5) -> int | None:
        """Check if the child died immediately after spawn.

        On Windows, ConPTY processes can take a moment to start, so we use
        a slightly longer timeout than Unix (0.5s vs 0.05s). Returns the
        exit code if dead, None if still alive.
        """
        time.sleep(timeout)
        if self._proc is None:
            return 127
        if not self._proc.isalive():
            try:
                return self._proc.exitstatus or -1
            except Exception:
                return -1
        return None  # still alive
