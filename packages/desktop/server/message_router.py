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
    Inject `text` into the PTY as a NORMAL user message (no /btw prefix)
    and capture Claude's reply. Uses the exact same chunked-write + \\r + \\n
    sequence as PTYSession._submit_to_pty — the nudge path proved this
    sequence is what actually makes Claude's TUI submit the message.

    Why no /btw:
      /btw is a Claude Code side-channel. Claude receives it but doesn't
      always respond (it's "by the way" context, not a user turn). When
      the user types in chat UI or Telegram, they expect Claude to REPLY
      — so the message must land as a real user turn. Same fix as the
      watchdog nudge.

    Why chunked write + separate \\r:
      Writing the whole message + \\r in one os.write often makes Claude's
      Ink TUI drop the trailing \\r (it processes the input buffer as a
      single chunk). Splitting into 16-char chunks with tiny delays, then
      sending \\r AND \\n as two more separate writes, reliably triggers
      submit. Verified via live PTY echo test.

    Flatten to one line because \\n inside the body is cursor movement
    in raw mode, not submit — it corrupts the input buffer.

    If no PTY session is alive, returns a friendly error message.
    """
    if not session_manager.pty.is_alive:
        return "⚠️ Claude Code session is not running. Start the app and try again."

    # Flatten newlines to spaces — \n corrupts raw-mode input
    flat = text.replace("\r\n", " ").replace("\n", " ").replace("\r", "")
    while "  " in flat:
        flat = flat.replace("  ", " ")
    flat = flat.strip()
    if not flat:
        return "Empty message"

    # Subscribe BEFORE writing so we catch all output
    queue = session_manager.pty.subscribe()
    response_chunks: list[str] = []

    try:
        # Clear any stale input first
        session_manager.pty.write(b"\x15")
        await asyncio.sleep(0.05)

        # Type the message in chunks (matches xterm.js keypress delivery)
        CHUNK_SIZE = 16
        for i in range(0, len(flat), CHUNK_SIZE):
            chunk = flat[i:i + CHUNK_SIZE]
            session_manager.pty.write(chunk.encode("utf-8"))
            await asyncio.sleep(0.01)

        # Pause for TUI to process, then press Enter (\r then \n as backup)
        await asyncio.sleep(0.3)
        session_manager.pty.write(b"\r")
        await asyncio.sleep(0.05)
        session_manager.pty.write(b"\n")

        deadline = time.time() + timeout
        blank_count = 0
        while time.time() < deadline:
            try:
                data = await asyncio.wait_for(queue.get(), timeout=2.0)
                chunk_out = data.decode("utf-8", errors="replace")
                clean = _ANSI_RE.sub("", chunk_out)
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

    # Post-process: drop claude-cli chrome + any echo of our own message
    full = "\n".join(response_chunks)
    lines = full.split("\n")
    clean_lines: list[str] = []
    # The first ~3 lines are typically Claude echoing what we typed (xterm
    # display echo). Skip those so the returned text is Claude's response,
    # not the user's own message bounced back.
    echo_line = flat[:60].lower()
    for line in lines:
        stripped = line.strip()
        if not stripped or len(stripped) < 2:
            continue
        if stripped.startswith("/btw"):
            continue  # legacy residue
        if "bypass permissions" in stripped.lower():
            continue
        if "ctrl+" in stripped.lower() or "shift+tab" in stripped.lower():
            continue
        if "esc to" in stripped.lower():
            continue
        # Drop lines that are substring-echoes of our typed message
        if echo_line and echo_line[:30] in stripped.lower():
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

        Side effect: persists the inbound user message to chat_log so the
        chat UI's scrollback includes what the user typed, not just Claude's
        replies. Source-to-sender mapping:
            "chat_ui"   → chat_log.SENDER_USER_UI
            "telegram"  → chat_log.SENDER_USER_TG
            anything else → chat_log.SENDER_USER_UI (safe default)
        """
        try:
            from . import chat_log
            from .pty_terminal import session_manager
            sender = chat_log.SENDER_USER_TG if source == "telegram" else chat_log.SENDER_USER_UI
            chat_log.append_message(
                session_id=session_manager.active_session_id or "unknown",
                sender=sender,
                content=text,
                meta={"source": source},
            )
        except Exception as e:
            logger.debug(f"router persist skipped: {e}")

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
