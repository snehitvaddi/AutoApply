#!/usr/bin/env python3
"""
ApplyLoop CLI terminal bridge.

This is the frontend for `applyloop run` — chat with Claude Code right in
your terminal, no app window. It connects the real terminal to the
desktop server's PTY Claude session over the `/ws/pty` WebSocket — the
*exact same* session the GUI app drives.

Architecture parity:
  - The FastAPI server (browser gateway + worker + PTY Claude + the
    localhost:18790 dashboard) runs identically to the GUI app.
  - The ONLY difference is the frontend: instead of a pywebview/WebView2
    window hosting xterm.js, this module bridges the PTY straight to the
    terminal's stdin/stdout.
  - Because the server is shared, the watchdog/heartbeat loops, MCP
    tools, OpenClaw, and the worker all behave exactly as they do for
    the app — no second code path to keep in sync.

Cross-platform:
  - Unix: raw tty via termios/tty.
  - Windows 10 1809+: VT input/output via SetConsoleMode (the parent-side
    counterpart to the ConPTY the server already uses for the child).

Press Ctrl+] to quit (detach from the session).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time

# Byte that quits the bridge. 0x1d == Ctrl+] — the classic telnet/tmux
# escape. It is never produced by normal typing, so it is a safe sentinel
# that won't collide with anything the user sends to Claude.
_QUIT_BYTE = 0x1D

# Diagnostic tracing — set APPLYLOOP_CLI_DEBUG to a file path to capture a
# timestamped trace of the bridge's lifecycle. Off (no-op) by default.
_DBG_PATH = os.environ.get("APPLYLOOP_CLI_DEBUG", "")


def _dbg(msg: str) -> None:
    if not _DBG_PATH:
        return
    try:
        with open(_DBG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"{time.time():.3f} {msg}\n")
    except Exception:
        pass


# ── Raw-mode terminal setup ──────────────────────────────────────────────────

def _enter_raw_mode():
    """Put the terminal into raw mode so keystrokes pass straight through
    to Claude's TUI (no line buffering, no echo, no signal generation).

    Returns a zero-arg restore() callable. Always safe to call restore()
    even if entering raw mode partially failed.
    """
    if os.name == "posix":
        return _enter_raw_mode_posix()
    if sys.platform == "win32":
        return _enter_raw_mode_windows()
    return lambda: None


def _enter_raw_mode_posix():
    import termios
    import tty

    fd = sys.stdin.fileno()
    try:
        old = termios.tcgetattr(fd)
    except (termios.error, ValueError):
        # Not a real tty (piped stdin) — nothing to restore.
        return lambda: None
    # TCSANOW, not the tty.setraw default of TCSAFLUSH: TCSAFLUSH blocks
    # tcsetattr until pending terminal *output* has drained, which would
    # stall bridge startup if the terminal is momentarily not consuming
    # output. We want raw mode applied immediately, unconditionally.
    tty.setraw(fd, termios.TCSANOW)

    def restore():
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        except Exception:
            pass

    return restore


def _enter_raw_mode_windows():
    """Switch the Windows console to VT mode.

    Disables line input + echo + Ctrl+C processing on stdin and enables
    ENABLE_VIRTUAL_TERMINAL_INPUT so arrow keys etc. arrive as real ANSI
    escape sequences (the format Claude's TUI expects). Enables
    ENABLE_VIRTUAL_TERMINAL_PROCESSING on stdout so the PTY's ANSI output
    renders. Requires Windows 10 1809+ (same baseline as ConPTY).
    """
    import ctypes

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    STD_INPUT_HANDLE = -10
    STD_OUTPUT_HANDLE = -11
    ENABLE_PROCESSED_INPUT = 0x0001
    ENABLE_LINE_INPUT = 0x0002
    ENABLE_ECHO_INPUT = 0x0004
    ENABLE_VIRTUAL_TERMINAL_INPUT = 0x0200
    ENABLE_PROCESSED_OUTPUT = 0x0001
    ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004

    h_in = kernel32.GetStdHandle(STD_INPUT_HANDLE)
    h_out = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
    old_in = ctypes.c_uint32()
    old_out = ctypes.c_uint32()
    have_in = bool(kernel32.GetConsoleMode(h_in, ctypes.byref(old_in)))
    have_out = bool(kernel32.GetConsoleMode(h_out, ctypes.byref(old_out)))

    if have_in:
        new_in = (
            old_in.value
            & ~(ENABLE_PROCESSED_INPUT | ENABLE_LINE_INPUT | ENABLE_ECHO_INPUT)
        ) | ENABLE_VIRTUAL_TERMINAL_INPUT
        kernel32.SetConsoleMode(h_in, new_in)
    if have_out:
        new_out = (
            old_out.value | ENABLE_PROCESSED_OUTPUT | ENABLE_VIRTUAL_TERMINAL_PROCESSING
        )
        kernel32.SetConsoleMode(h_out, new_out)

    def restore():
        try:
            if have_in:
                kernel32.SetConsoleMode(h_in, old_in.value)
            if have_out:
                kernel32.SetConsoleMode(h_out, old_out.value)
        except Exception:
            pass

    return restore


def _term_size() -> tuple[int, int]:
    """Current terminal (cols, rows). Falls back to 80x24 off a tty."""
    try:
        size = os.get_terminal_size()
        return size.columns, size.lines
    except OSError:
        return 80, 24


# ── stdin reader ─────────────────────────────────────────────────────────────

def _start_stdin_reader(loop: asyncio.AbstractEventLoop, queue: asyncio.Queue) -> None:
    """Read raw stdin bytes on a daemon thread and hand them to the event
    loop via the queue.

    Why a dedicated daemon thread instead of loop.run_in_executor:
    os.read() on stdin blocks indefinitely. A run_in_executor task would
    keep the default ThreadPoolExecutor alive, and asyncio.run()'s
    shutdown waits on that executor — so a blocked read would hang exit.
    A daemon thread is abandoned cleanly when the interpreter exits.
    """
    fd = sys.stdin.fileno()

    def _reader():
        _dbg(f"stdin reader thread live, fd={fd}")
        while True:
            try:
                data = os.read(fd, 4096)
            except (OSError, ValueError) as exc:
                _dbg(f"stdin os.read raised {exc!r}")
                data = b""
            _dbg(f"stdin read -> {data!r}")
            try:
                loop.call_soon_threadsafe(queue.put_nowait, data)
            except RuntimeError:
                # Event loop already closed — bridge is shutting down.
                break
            if not data:
                break

    threading.Thread(target=_reader, name="applyloop-cli-stdin", daemon=True).start()


# ── Pumps ────────────────────────────────────────────────────────────────────

async def _pump_output(ws, detach: asyncio.Event) -> None:
    """PTY output (binary WS frames) → terminal stdout."""
    try:
        async for message in ws:
            if isinstance(message, (bytes, bytearray)):
                os.write(1, bytes(message))
            # Text frames are {"type": "status", ...} JSON — not rendered.
    except Exception as exc:
        _dbg(f"_pump_output exception: {exc!r}")
    finally:
        _dbg("_pump_output ended -> detach")
        detach.set()


async def _pump_input(ws, queue: asyncio.Queue, detach: asyncio.Event) -> None:
    """Terminal stdin → PTY input (binary WS frames). Ctrl+] quits."""
    try:
        while not detach.is_set():
            data = await queue.get()
            _dbg(f"_pump_input dequeued {data!r}")
            if not data:  # EOF on stdin
                break
            if _QUIT_BYTE in data:
                # Forward anything typed before the quit byte, then stop.
                idx = data.index(_QUIT_BYTE)
                if idx > 0:
                    await ws.send(bytes(data[:idx]))
                break
            await ws.send(bytes(data))
            _dbg(f"_pump_input sent {len(data)}B to ws")
    except Exception as exc:
        _dbg(f"_pump_input exception: {exc!r}")
    finally:
        _dbg("_pump_input ended -> detach")
        detach.set()


async def _pump_resize(ws, detach: asyncio.Event) -> None:
    """Poll terminal size and push resize events to the PTY.

    Polling (vs a SIGWINCH handler) keeps one code path for Unix and
    Windows. The first tick fires immediately so Claude's TUI is sized
    correctly before the user does anything.
    """
    last: tuple[int, int] | None = None
    try:
        while not detach.is_set():
            size = _term_size()
            if size != last:
                last = size
                await ws.send(json.dumps(
                    {"type": "resize", "cols": size[0], "rows": size[1]}
                ))
            await asyncio.sleep(1.0)
    except Exception:
        pass


# ── Entry point ──────────────────────────────────────────────────────────────

async def _bridge_main(ws_url: str) -> int:
    try:
        import websockets
    except ImportError:
        sys.stderr.write(
            "[ApplyLoop] The 'websockets' package is missing from the venv.\n"
            "[ApplyLoop] Fix it with: applyloop update\n"
        )
        return 1

    print(f"[ApplyLoop] Connecting to the Claude Code session...")
    try:
        ws = await websockets.connect(ws_url, max_size=None, ping_interval=20)
    except Exception as exc:
        sys.stderr.write(f"[ApplyLoop] Could not connect to {ws_url}: {exc}\n")
        return 1

    print("[ApplyLoop] Connected. You're in the live terminal — type to chat "
          "with Claude.")
    print("[ApplyLoop] Press Ctrl+] to quit.\n")
    _dbg("connected + banner printed")

    restore = _enter_raw_mode()
    _dbg("raw mode entered")
    loop = asyncio.get_running_loop()
    detach = asyncio.Event()
    stdin_queue: asyncio.Queue = asyncio.Queue()
    _start_stdin_reader(loop, stdin_queue)
    _dbg("stdin reader started")

    try:
        tasks = [
            asyncio.create_task(_pump_output(ws, detach)),
            asyncio.create_task(_pump_input(ws, stdin_queue, detach)),
            asyncio.create_task(_pump_resize(ws, detach)),
        ]
        _dbg("pumps created — awaiting detach")
        await detach.wait()
        _dbg("detach fired — cancelling pumps")
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        restore()
        try:
            await ws.close()
        except Exception:
            pass
    return 0


def run_cli_bridge(url: str) -> int:
    """Bridge this terminal to the desktop server's PTY Claude session.

    `url` is the FastAPI server base URL (e.g. http://localhost:18790).
    Blocks until the user quits (Ctrl+]) or the session ends.
    """
    ws_url = (
        url.replace("https://", "wss://").replace("http://", "ws://").rstrip("/")
        + "/ws/pty"
    )
    try:
        return asyncio.run(_bridge_main(ws_url))
    except KeyboardInterrupt:
        return 0
