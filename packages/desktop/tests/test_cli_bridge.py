"""End-to-end tests for the `applyloop run` terminal bridge (cli_terminal.py).

What this covers — without applying to a single job:
  - Cross-platform: helper invariants + clean failure when no server is up.
  - Unix (mac/linux): a REAL end-to-end run — the actual run_cli_bridge()
    code is spawned as a subprocess attached to a real PTY, pointed at a
    mock /ws/pty server. We type bytes into the PTY, assert they round-trip
    through the WebSocket, and assert Ctrl+] quits the bridge cleanly.

The mock server stands in for the desktop FastAPI server, so this never
boots OpenClaw, the worker, or a Claude session. It proves the bridge
plumbing (raw-mode stdin, PTY output rendering, resize frames, the Ctrl+]
quit path) — the genuinely new code in `applyloop run`.

The full live chain (install → login → scout → apply) is deliberately
NOT automated here: it needs a real Windows host and would submit real
job applications. That stays a manual smoke test.
"""
from __future__ import annotations

import asyncio
import json
import os
import select
import subprocess
import sys
import threading
import time
import unittest

_DESKTOP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _DESKTOP_DIR not in sys.path:
    sys.path.insert(0, _DESKTOP_DIR)

import cli_terminal  # noqa: E402


# ── Mock /ws/pty server ──────────────────────────────────────────────────────

class _MockPtyServer:
    """A throwaway WebSocket server that mimics the desktop's /ws/pty.

    Protocol parity with pty_terminal.pty_terminal_websocket:
      - on connect: send one {"type":"status",...} JSON text frame
      - binary frame in  → echo back as b"ECHO:" + data (stands in for the
        PTY round-tripping a keystroke to Claude and printing a response)
      - text frame in    → a resize event; recorded, not echoed
    """

    def __init__(self) -> None:
        self.port: int = 0
        self.resize_frames: list[dict] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server = None
        self._ready = threading.Event()

    async def _handler(self, ws) -> None:
        await ws.send(json.dumps({"type": "status", "alive": True}))
        async for msg in ws:
            if isinstance(msg, (bytes, bytearray)):
                await ws.send(b"ECHO:" + bytes(msg))
            else:
                try:
                    self.resize_frames.append(json.loads(msg))
                except Exception:
                    pass

    async def _serve(self) -> None:
        import websockets
        self._server = await websockets.serve(self._handler, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        self._ready.set()

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._serve())
        self._loop.run_forever()

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()
        if not self._ready.wait(timeout=10):
            raise RuntimeError("mock /ws/pty server did not start")

    def stop(self) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)


# ── Cross-platform tests (run on Windows CI too) ─────────────────────────────

class CliBridgeHelpersTest(unittest.TestCase):
    def test_quit_byte_is_ctrl_rbracket(self) -> None:
        # Ctrl+] == 0x1d. Never produced by ordinary typing, so it is a
        # safe sentinel that won't collide with input meant for Claude.
        self.assertEqual(cli_terminal._QUIT_BYTE, 0x1D)

    def test_term_size_returns_int_pair(self) -> None:
        cols, rows = cli_terminal._term_size()
        self.assertIsInstance(cols, int)
        self.assertIsInstance(rows, int)
        self.assertGreater(cols, 0)
        self.assertGreater(rows, 0)

    def test_enter_raw_mode_returns_callable_restore(self) -> None:
        # Off a non-tty (the test runner has no controlling terminal) this
        # must still return a callable no-op restore — never raise.
        restore = cli_terminal._enter_raw_mode()
        self.assertTrue(callable(restore))
        restore()  # must not raise

    def test_no_server_fails_cleanly(self) -> None:
        # Port 1 is never an ApplyLoop server. run_cli_bridge must return a
        # non-zero exit WITHOUT touching the terminal (connect happens
        # before raw mode is entered) — i.e. no hang, no traceback.
        rc = cli_terminal.run_cli_bridge("http://127.0.0.1:1")
        self.assertEqual(rc, 1)


# ── Real end-to-end PTY bridge test (Unix only) ──────────────────────────────

_BRIDGE_SUBPROCESS = (
    "import sys; sys.path.insert(0, %r); "
    "from cli_terminal import run_cli_bridge; "
    "sys.exit(run_cli_bridge(sys.argv[1]))"
) % _DESKTOP_DIR


@unittest.skipIf(sys.platform == "win32",
                 "PTY-driven E2E is Unix-only; Windows raw-console path is "
                 "exercised by the manual smoke test")
class CliBridgeEndToEndTest(unittest.TestCase):
    """Spawn the real run_cli_bridge() in a subprocess on a real PTY and
    drive it against the mock server — the closest thing to a live
    `applyloop run` that does not apply to any jobs."""

    def setUp(self) -> None:
        self.server = _MockPtyServer()
        self.server.start()
        self._screen = bytearray()       # everything the bridge has printed
        self._screen_lock = threading.Lock()
        self._draining = True

    def tearDown(self) -> None:
        self._draining = False
        self.server.stop()

    def _start_drain(self, master: int) -> None:
        """Continuously read the PTY master — a real terminal always
        consumes output, and the bridge's raw-mode + flow control assume
        that. A test that only reads at checkpoints would stall it."""
        def _drain():
            while self._draining:
                r, _, _ = select.select([master], [], [], 0.2)
                if not r:
                    continue
                try:
                    chunk = os.read(master, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                with self._screen_lock:
                    self._screen.extend(chunk)
        threading.Thread(target=_drain, daemon=True).start()

    def _wait_for(self, needle: bytes, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._screen_lock:
                if needle in self._screen:
                    return True
            time.sleep(0.05)
        return False

    def _screen_bytes(self) -> bytes:
        with self._screen_lock:
            return bytes(self._screen)

    def test_bridge_round_trips_input_and_quits_on_ctrl_rbracket(self) -> None:
        import fcntl
        import pty
        import struct
        import termios

        master, slave = pty.openpty()
        # Give the PTY a real window size so the bridge's resize frame
        # carries non-zero cols/rows (mirrors a real terminal).
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
        self._start_drain(master)

        url = f"http://127.0.0.1:{self.server.port}"
        proc = subprocess.Popen(
            [sys.executable, "-c", _BRIDGE_SUBPROCESS, url],
            stdin=slave, stdout=slave, stderr=slave, close_fds=True,
        )
        os.close(slave)

        try:
            # 1. Bridge connects and prints its banner.
            self.assertTrue(
                self._wait_for(b"Ctrl+]", timeout=15),
                f"bridge never connected. Screen: {self._screen_bytes()!r}",
            )
            self.assertIn(b"Connected", self._screen_bytes())

            # 2. Type a line — it must round-trip stdin → WS → stdout via
            #    the mock's echo. Proves the full bridge data path.
            os.write(master, b"hello\r")
            self.assertTrue(
                self._wait_for(b"ECHO:hello", timeout=10),
                f"keystrokes did not round-trip. Screen: {self._screen_bytes()!r}",
            )

            # 3. Ctrl+] must quit the bridge cleanly (exit code 0).
            os.write(master, b"\x1d")
            proc.wait(timeout=10)
            self.assertEqual(proc.returncode, 0,
                             "Ctrl+] should quit the bridge with exit 0")

            # 4. The bridge should have pushed a resize frame carrying the
            #    real terminal size (40 rows x 120 cols).
            self.assertTrue(self.server.resize_frames,
                            "bridge never sent a resize frame")
            first = self.server.resize_frames[0]
            self.assertEqual(first.get("type"), "resize")
            self.assertEqual(first.get("cols"), 120)
            self.assertEqual(first.get("rows"), 40)
        finally:
            self._draining = False
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
            os.close(master)


if __name__ == "__main__":
    unittest.main()
