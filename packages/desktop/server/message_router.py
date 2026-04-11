"""
Message Router — serializes /btw input into the Claude Code PTY.

Both the chat UI (/ws/chat) and the Telegram gateway submit messages here.
This module owns the single lock on the PTY write → capture → clean response cycle,
so two channels never fight for the same output stream.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time

from .pty_terminal import session_manager

logger = logging.getLogger(__name__)

# ANSI escape stripper — same pattern used by chat_bridge.py
_ANSI_RE = re.compile(
    r'\x1b\[[0-9;?]*[a-zA-Z]'
    r'|\x1b\][^\x07]*\x07'
    r'|\x1b\([A-Z]'
    r'|\x1b[=><=<>]'
    r'|\x1b'
)


async def capture_btw_response(text: str, timeout: float = 30.0) -> str:
    """
    Write `/btw <text>\\n` to the PTY, subscribe to output, capture the reply,
    strip ANSI codes and claude-cli noise, and return a cleaned string.

    If no PTY session is alive, returns a friendly error message.
    """
    if not session_manager.pty.is_alive:
        return "⚠️ Claude Code session is not running. Start the app and try again."

    # Subscribe BEFORE writing so we catch all output
    queue = session_manager.pty.subscribe()
    response_chunks: list[str] = []

    try:
        btw_cmd = f"/btw {text}\n"
        session_manager.pty.write(btw_cmd.encode("utf-8"))

        deadline = time.time() + timeout
        blank_count = 0
        while time.time() < deadline:
            try:
                data = await asyncio.wait_for(queue.get(), timeout=2.0)
                chunk = data.decode("utf-8", errors="replace")
                clean = _ANSI_RE.sub("", chunk)
                clean = re.sub(r'[\r\x00-\x08\x0e-\x1f]', '', clean)
                stripped = clean.strip()
                if stripped:
                    response_chunks.append(stripped)
                    blank_count = 0
                else:
                    blank_count += 1
                    # Two consecutive blanks after some content = response done
                    if response_chunks and blank_count >= 2:
                        break
            except asyncio.TimeoutError:
                if response_chunks:
                    break  # Got something, idle timeout = done
    finally:
        session_manager.pty.unsubscribe(queue)

    # Post-process: drop /btw echo and claude-cli chrome
    full = "\n".join(response_chunks)
    lines = full.split("\n")
    clean_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("/btw"):
            continue
        if "bypass permissions" in stripped.lower():
            continue
        if "ctrl+" in stripped.lower() or "shift+tab" in stripped.lower():
            continue
        if "esc to" in stripped.lower():
            continue
        if len(stripped) < 2:
            continue
        clean_lines.append(line)

    response = "\n".join(clean_lines).strip()
    if not response:
        response = "Claude is busy. Your message was sent — check back shortly."
    return response


class MessageRouter:
    """
    Singleton async router. Submit (source, text) → get back the cleaned PTY response.

    Serializes all /btw traffic so chat UI and Telegram don't step on each other.
    """

    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._stopping = False

    async def start(self) -> None:
        if self._task is None:
            self._stopping = False
            self._task = asyncio.create_task(self._worker(), name="message-router")
            logger.info("Message router started")

    async def stop(self) -> None:
        self._stopping = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            logger.info("Message router stopped")

    async def submit(self, source: str, text: str, timeout: float = 30.0) -> str:
        """
        Submit a message. Blocks the caller until the PTY response is ready.

        `source` is a label like "chat_ui" or "telegram" (for logging/attribution).
        """
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        await self._queue.put((source, text, timeout, fut))
        return await fut

    async def _worker(self) -> None:
        """Serial worker — pulls one item at a time and runs it to completion."""
        while not self._stopping:
            try:
                source, text, timeout, fut = await self._queue.get()
            except asyncio.CancelledError:
                break
            try:
                logger.debug(f"Router dispatching [{source}]: {text[:80]}")
                response = await capture_btw_response(text, timeout=timeout)
                if not fut.done():
                    fut.set_result(response)
            except Exception as e:
                logger.warning(f"Router dispatch failed [{source}]: {e}")
                if not fut.done():
                    fut.set_exception(e)


# Module-level singleton
message_router = MessageRouter()
