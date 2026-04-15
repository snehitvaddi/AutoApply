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


# Sentinel tokens that bracket Claude's reply so we can pluck it out of
# the PTY byte stream cleanly. Claude is instructed (via the envelope
# built in this module) to wrap a 1-2 sentence reply between these on
# their own lines. Any tool output / chrome / xterm echo outside the
# sentinels is ignored. Tokens are intentionally unlikely to appear in
# ordinary terminal output — triple angles + ALL_CAPS + underscore.
_REPLY_START = "<<<REPLY_START>>>"
_REPLY_END = "<<<REPLY_END>>>"
_REPLY_RE = re.compile(
    rf"{re.escape(_REPLY_START)}\s*(.+?)\s*{re.escape(_REPLY_END)}",
    re.DOTALL,
)

# Prompt chrome / UI decoration that sometimes shows up between sentinels
# if Claude embeds a code block or command suggestion. Belt-and-suspenders
# cleanup applied AFTER the sentinel match, not before.
_CHROME_LINE_RE = re.compile(
    r"(bypass permissions|ctrl\+|shift\+tab|esc to|╭─|╰─|│)",
    re.IGNORECASE,
)

# Cap the reply length for Telegram / chat-UI readability. Claude is told
# to keep it to 1-2 sentences — 600 chars is generous headroom + an
# ellipsis suffix.
_MAX_REPLY_CHARS = 600


def _build_reply_envelope(user_text: str) -> str:
    """Wrap the user's raw text in a plain-English instruction that tells
    Claude to bracket its reply with sentinel tokens we can extract
    downstream.

    Claude keeps running whatever it was doing (tool calls, scouting,
    apply loop) — we explicitly say "tool output above is fine". Only
    the bracketed text makes it back to Telegram / chat.

    No /btw. No "[via Telegram]" marker. Plain English prose instruction
    that Claude treats as a normal user turn.
    """
    # Use a NON-PLACEHOLDER example so the envelope's echo (which xterm
    # emits as the user types) never gets mistaken for Claude's reply
    # by the downstream regex. Previous bug: we typed "your one-or-two-
    # sentence reply here" inside the sentinels, xterm echoed it, the
    # regex matched the echo first, and Telegram received the literal
    # placeholder text. Fix: describe the reply format without typing a
    # complete sentinel pair, so only Claude's actual output will contain
    # the START/END bracketed reply.
    return (
        f"The user just sent you this message:\n\n"
        f"{user_text}\n\n"
        f"Reply in 1–2 short sentences. Bracket ONLY your reply text "
        f"on its own lines with these exact tokens — tool output above "
        f"is fine, but emit the tokens only around your reply, not "
        f"anywhere else:\n"
        f"  opening token:  {_REPLY_START}\n"
        f"  your 1-2 sentence reply on the next line\n"
        f"  closing token:  {_REPLY_END}"
    )


async def capture_btw_response(text: str, timeout: float = 30.0) -> str:
    """
    Inject `text` into the PTY as a NORMAL user message (no /btw prefix)
    and capture Claude's reply, bracketed by REPLY_START/END sentinels.

    Previously this function used a heuristic echo-filter on the raw PTY
    byte stream. That returned garbage to Telegram / chat because:
      - xterm echoes the typed message with cursor-move bytes that
        collapse spaces into letter runs
      - Claude's concurrent tool output (openclaw, bash, "Sketching…")
        interleaves with its prose reply
      - Prompt chrome (╭─, │, "bypass permissions", etc.) mixes in
    The echo-filter tried to strip the user's own message by substring
    match on the first 30 chars — fragile enough that the actual reply
    was usually dropped and the user saw terminal garbage instead.

    Now: we wrap the user's text in a plain-English envelope that tells
    Claude to bracket its reply with sentinel tokens. We extract only
    the bracketed text. If Claude doesn't honor the sentinel format
    (busy, rate-limited, buffer cut off), we return a deterministic
    short fallback — NOT raw terminal output.

    Why chunked write + separate \\r:
      Writing the whole message + \\r in one os.write often makes
      Claude's Ink TUI drop the trailing \\r (it processes the input
      buffer as a single chunk). Splitting into 16-char chunks with tiny
      delays, then sending \\r AND \\n as two more separate writes,
      reliably triggers submit. Verified via live PTY echo test.

    Flatten to one line because \\n inside the body is cursor movement
    in raw mode, not submit — it corrupts the input buffer.

    If no PTY session is alive, returns a friendly error message.
    """
    if not session_manager.pty.is_alive:
        return "⚠️ Claude Code session is not running. Start the app and try again."

    raw_user_text = text.strip()
    if not raw_user_text:
        return "Empty message"

    envelope = _build_reply_envelope(raw_user_text)

    # Flatten newlines to spaces — \n corrupts raw-mode input. Sentinel
    # tokens stay recognizable (no internal whitespace), so flattening
    # them into a single line is harmless.
    flat = envelope.replace("\r\n", " ").replace("\n", " ").replace("\r", "")
    while "  " in flat:
        flat = flat.replace("  ", " ")
    flat = flat.strip()

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

        # Capture loop: bail early the moment we see REPLY_END so we don't
        # sit idle waiting for the timeout once Claude has finished its
        # bracketed reply. Still has the blank-count + TimeoutError paths
        # as safety nets if the sentinel never arrives.
        deadline = time.time() + timeout
        blank_count = 0
        saw_end_sentinel = False
        while time.time() < deadline and not saw_end_sentinel:
            try:
                data = await asyncio.wait_for(queue.get(), timeout=2.0)
                chunk_out = data.decode("utf-8", errors="replace")
                clean = _ANSI_RE.sub("", chunk_out)
                clean = re.sub(r'[\r\x00-\x08\x0e-\x1f]', '', clean)
                response_chunks.append(clean)
                if _REPLY_END in "".join(response_chunks):
                    saw_end_sentinel = True
                    break
                if clean.strip():
                    blank_count = 0
                else:
                    blank_count += 1
                    # Two consecutive blanks after some non-blank content =
                    # response stream quieted. Keep our existing fallback
                    # heuristic for cases where Claude doesn't emit the
                    # end sentinel within the capture window.
                    if any(c.strip() for c in response_chunks) and blank_count >= 2:
                        break
            except asyncio.TimeoutError:
                if any(c.strip() for c in response_chunks):
                    break  # Got something, idle timeout = done
    finally:
        session_manager.pty.unsubscribe(queue)

    # Extract ONLY what's between the sentinels. Anything else (echo,
    # tool output, prompt chrome) is ignored.
    #
    # Take the LAST sentinel pair in the buffer, not the first. The
    # envelope no longer types a complete pair inline (we moved to a
    # labeled-token format), but belt-and-suspenders: if xterm echoes
    # the envelope back in an order that happens to form a pair, or if
    # Claude emits multiple brackets, the LAST one is Claude's final
    # reply — earlier matches are noise.
    full = "".join(response_chunks)
    matches = list(_REPLY_RE.finditer(full))
    if matches:
        reply = matches[-1].group(1).strip()
    else:
        # Sentinel didn't land in the capture window. Common reasons:
        # Claude is mid-tool-call and hasn't emitted the end sentinel
        # yet, rate-limited, or the buffer flushed partially. Return a
        # deterministic short status — NEVER raw terminal garbage.
        logger.info("capture_btw_response: no sentinel match in captured output")
        return (
            "Claude saw your message and is working on it — check the "
            "desktop window for the full context."
        )

    # Belt-and-suspenders: strip any sentinel residue, drop lines that
    # look like TUI chrome (╭─ borders, "bypass permissions" hints).
    reply = re.sub(r"<<<REPLY_(START|END)>>>", "", reply).strip()
    reply = "\n".join(
        line for line in reply.splitlines() if not _CHROME_LINE_RE.search(line)
    ).strip()
    # Strip markdown code fences — Telegram renders them as literal
    # backticks which looks wrong.
    reply = reply.replace("```", "").strip()

    # Guard against the envelope's own instructional text leaking
    # through as if it were Claude's reply. If the extracted text
    # matches known template-y fragments, treat it as an extraction
    # miss and return the deterministic fallback instead of confusing
    # the user with placeholder language.
    _TEMPLATE_LEAK_RE = re.compile(
        r"(your\s+(one[-\s]?or[-\s]?two|1[-\s]?2)[-\s]?sentence"
        r"|your 1-2 sentence reply"
        r"|opening token|closing token"
        r"|bracket only your reply"
        r"|the user just sent you this message)",
        re.IGNORECASE,
    )
    if _TEMPLATE_LEAK_RE.search(reply):
        logger.info(
            "capture_btw_response: extracted text looks like template "
            "leak, returning fallback instead: %r", reply[:100]
        )
        return (
            "Claude saw your message and is working on it — check the "
            "desktop window for the full context."
        )

    if not reply:
        return "Claude saw your message. No reply text was returned."

    if len(reply) > _MAX_REPLY_CHARS:
        reply = reply[:_MAX_REPLY_CHARS].rstrip() + "…"

    return reply


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
