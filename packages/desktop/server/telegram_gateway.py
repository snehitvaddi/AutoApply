"""
Telegram Gateway — makes Telegram a second input into the same Claude Code PTY
that the desktop chat UI talks to.

Flow:
  phone (Telegram) → _poll_loop → _handle_update → MessageRouter → PTY (Claude Code)
                  ↙                                              ↘
           broadcast to chat UI                          send_message back to Telegram
                  ↘                                              ↙
                    (chat UI shows the message + reply; Telegram shows the reply)

Replaces the OpenClaw gateway layer (NodeJS + codex) by bringing Telegram Q&A
into the same single LLM session as the chat UI.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Awaitable, Callable

import httpx

from . import qa_agent
from .config import WORKSPACE_DIR, load_token, APP_URL
from .message_router import message_router  # legacy — kept for rollback

logger = logging.getLogger(__name__)

# No hardcoded credentials — Telegram integration is opt-in per user. If neither
# env vars nor the cloud config are set, the gateway fails closed (does not start).
# This prevents any possibility of a non-developer user's messages being routed
# to somebody else's bot via leftover developer credentials.

OFFSET_FILE = WORKSPACE_DIR / "telegram-offset.json"
POLL_TIMEOUT_SEC = 30  # long-poll; Telegram holds the connection until a message arrives or timeout
TELEGRAM_MAX_MSG_LEN = 4000  # keep below the 4096 API limit with a safety margin

# ── Message routing ──────────────────────────────────────────────────────
#
# ALL messages go to the PTY by default. Claude Code can both answer
# questions AND execute commands — there's no need to classify intent.
#
# The only exception: prefix `?` forces the qa_agent fast-path for a
# quick stat lookup without touching the PTY. This is an explicit
# user opt-in, not an auto-detection heuristic.


def _is_question(text: str) -> bool:
    """Only returns True if the user explicitly prefixes with `?`.

    Everything else goes to the PTY where Claude Code decides what to do.
    No heuristic classification — Claude is the classifier.
    """
    return text.strip().startswith("?")


class TelegramClient:
    """Thin Telegram Bot API wrapper — send_message + get_updates."""

    def __init__(self, token: str):
        self.token = token
        self.api_base = f"https://api.telegram.org/bot{token}"

    async def send_message(self, chat_id: str, text: str) -> None:
        """Send text to a chat, auto-chunking long messages."""
        if not text:
            return
        chunks = _chunk_text(text, TELEGRAM_MAX_MSG_LEN)
        async with httpx.AsyncClient(timeout=15.0) as client:
            for chunk in chunks:
                try:
                    # Try Markdown first; fall back to plain text if Telegram rejects formatting
                    r = await client.post(
                        f"{self.api_base}/sendMessage",
                        data={
                            "chat_id": chat_id,
                            "text": chunk,
                            "parse_mode": "Markdown",
                            "disable_web_page_preview": True,
                        },
                    )
                    if r.status_code != 200:
                        # Retry without Markdown
                        await client.post(
                            f"{self.api_base}/sendMessage",
                            data={
                                "chat_id": chat_id,
                                "text": chunk,
                                "disable_web_page_preview": True,
                            },
                        )
                except Exception as e:
                    logger.warning(f"sendMessage failed: {e}")

    async def get_updates(self, offset: int, timeout: int = POLL_TIMEOUT_SEC) -> list[dict]:
        """Long-poll the getUpdates endpoint. Returns the updates list (can be empty)."""
        # httpx timeout must exceed Telegram's long-poll timeout
        async with httpx.AsyncClient(timeout=timeout + 10) as client:
            r = await client.get(
                f"{self.api_base}/getUpdates",
                params={"offset": offset, "timeout": timeout, "allowed_updates": '["message"]'},
            )
            r.raise_for_status()
            return r.json().get("result", [])


def _chunk_text(text: str, max_len: int) -> list[str]:
    """Split text into chunks ≤ max_len, preferring line boundaries when possible."""
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    remaining = text
    while len(remaining) > max_len:
        # Try to cut at the last newline before max_len
        cut = remaining.rfind("\n", 0, max_len)
        if cut <= 0:
            cut = max_len
        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")
    if remaining:
        chunks.append(remaining)
    return chunks


def _load_offset() -> int:
    """Load the last-seen update_id from disk. 0 if none."""
    if not OFFSET_FILE.exists():
        return 0
    try:
        data = json.loads(OFFSET_FILE.read_text())
        return int(data.get("offset", 0))
    except Exception:
        return 0


def _save_offset(offset: int) -> None:
    try:
        OFFSET_FILE.parent.mkdir(parents=True, exist_ok=True)
        OFFSET_FILE.write_text(json.dumps({"offset": offset}))
    except Exception as e:
        logger.warning(f"Failed to save Telegram offset: {e}")


async def _resolve_credentials() -> tuple[str, str] | None:
    """
    Determine Telegram bot token + admin chat ID.

    Priority:
      1. Environment vars TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID
      2. Remote worker proxy `get_telegram_config` action (user-specific config)

    If neither source returns valid credentials, return None. The caller
    MUST fail closed — do not start the gateway. Never fall back to
    hardcoded credentials: a non-developer user's messages would leak to
    somebody else's Telegram bot.
    """
    env_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    env_chat = os.environ.get("TELEGRAM_CHAT_ID")
    if env_token and env_chat:
        return env_token, env_chat

    # Try remote config
    token = load_token()
    if token:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(
                    f"{APP_URL}/api/worker/proxy",
                    json={"action": "get_telegram_config"},
                    headers={"X-Worker-Token": token},
                )
                r.raise_for_status()
                data = r.json().get("data", {}) or {}
                bot_token = data.get("bot_token")
                chat_id = data.get("chat_id")
                if bot_token and chat_id:
                    return bot_token, str(chat_id)
        except Exception as e:
            logger.debug(f"Remote Telegram config fetch failed: {e}")

    return None


class TelegramGateway:
    """
    Background long-polling loop for Telegram → Claude Code PTY.

    Callbacks `on_message_in` / `on_message_out` are invoked whenever a message
    flows in from Telegram or out to Telegram, so the desktop chat UI can mirror them.
    """

    def __init__(
        self,
        on_message_in: Callable[[str], Awaitable[None]] | None = None,
        on_message_out: Callable[[str], Awaitable[None]] | None = None,
    ):
        self.on_message_in = on_message_in
        self.on_message_out = on_message_out
        self._task: asyncio.Task | None = None
        self._stop = False
        self.client: TelegramClient | None = None
        self.admin_chat_id: str | None = None
        self.offset: int = 0

    async def start(self) -> None:
        creds = await _resolve_credentials()
        if not creds:
            logger.warning(
                "Telegram gateway: no credentials configured "
                "(set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID env vars, "
                "or configure via cloud). Gateway will NOT start — this is "
                "the correct behaviour for users who haven't opted in."
            )
            return
        token, chat_id = creds
        self.client = TelegramClient(token)
        self.admin_chat_id = chat_id
        self.offset = _load_offset()
        self._stop = False
        self._task = asyncio.create_task(self._poll_loop(), name="telegram-gateway")
        logger.info(f"Telegram gateway started (admin chat {chat_id}, offset {self.offset})")

    async def stop(self) -> None:
        self._stop = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            logger.info("Telegram gateway stopped")

    async def send_telegram(self, text: str) -> None:
        """Public helper — send an arbitrary message to the admin chat.

        Used by chat_bridge to mirror chat-UI responses to Telegram.
        """
        if self.client and self.admin_chat_id:
            await self.client.send_message(self.admin_chat_id, text)

    async def _poll_loop(self) -> None:
        assert self.client is not None and self.admin_chat_id is not None
        while not self._stop:
            try:
                updates = await self.client.get_updates(self.offset + 1, timeout=POLL_TIMEOUT_SEC)
            except asyncio.CancelledError:
                break
            except httpx.ReadTimeout:
                # Expected — long-poll expired with no messages. Loop again.
                continue
            except Exception as e:
                logger.warning(f"Telegram poll error: {e}; retrying in 5s")
                await asyncio.sleep(5)
                continue

            for update in updates:
                try:
                    await self._handle_update(update)
                except Exception as e:
                    logger.warning(f"Failed to handle Telegram update {update.get('update_id')}: {e}")
                # Always advance the offset so bad updates don't get replayed
                self.offset = max(self.offset, int(update.get("update_id", 0)))
            if updates:
                _save_offset(self.offset)

    async def _handle_update(self, update: dict) -> None:
        assert self.client is not None and self.admin_chat_id is not None

        msg = update.get("message") or update.get("edited_message") or {}
        if not msg:
            return
        chat = msg.get("chat", {})
        chat_id = str(chat.get("id", ""))
        text = (msg.get("text") or "").strip()

        # Admin allowlist — drop anything not from our chat ID
        if chat_id != self.admin_chat_id:
            logger.warning(f"Rejected Telegram message from unauthorized chat {chat_id}")
            return

        if not text:
            return  # Ignore non-text messages (photos, stickers, etc.) for now

        logger.info(f"Telegram in: {text[:120]}")

        # 1) Mirror the incoming message to the desktop chat UI
        if self.on_message_in:
            try:
                await self.on_message_in(text)
            except Exception as e:
                logger.debug(f"on_message_in callback failed: {e}")

        # 2) Route: PTY is the default (Claude can both act AND answer).
        # qa_agent is a fast-path optimization for obvious status questions
        # where we don't want to interrupt the apply loop.
        #
        # Why PTY-default: qa_agent CANNOT execute commands, but PTY CAN
        # answer questions. Misrouting a command to qa_agent = dead end.
        # Misrouting a question to PTY = works, just slightly slower.
        # Safe default = PTY.
        #
        # Prefix `?` forces qa_agent. Prefix `!` forces PTY.
        if _is_question(text):
            q_text = text.lstrip("?").strip()
            try:
                response = await qa_agent.answer(q_text)
            except Exception as e:
                response = f"⚠️ Error processing question: {e}"
        else:
            user_text = text.lstrip("!").strip()
            try:
                response = await message_router.submit(
                    "telegram",
                    f"USER MESSAGE (from Telegram — read this and act if needed, "
                    f"answer if it's a question): {user_text}",
                    timeout=60.0,
                )
            except Exception as e:
                response = f"⚠️ Message delivery failed: {e}"
            if not response or response.startswith("Claude is busy"):
                # Fallback: if PTY didn't respond (busy applying), try qa_agent
                try:
                    response = await qa_agent.answer(user_text)
                except Exception:
                    pass

        # 3) Send Claude's reply back to Telegram
        try:
            await self.client.send_message(self.admin_chat_id, response)
        except Exception as e:
            logger.warning(f"Failed to send Telegram reply: {e}")

        # 4) Mirror the outgoing reply to the desktop chat UI
        if self.on_message_out:
            try:
                await self.on_message_out(response)
            except Exception as e:
                logger.debug(f"on_message_out callback failed: {e}")


# Module-level singleton — started/stopped by app.py lifespan
telegram_gateway = TelegramGateway()
