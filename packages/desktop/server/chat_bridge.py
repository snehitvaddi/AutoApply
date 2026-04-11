"""
Smart Chat Bridge — Telegram-first, SQLite fallback + /btw Questions.

Architecture:
  IF Telegram configured:
    - Fetch bot messages from Telegram Bot API (getUpdates)
    - Show real Telegram conversation in chat
    - User can send messages that go to both Telegram + PTY
  ELSE (fallback):
    - Poll SQLite for status updates
    - Show Telegram-style notification cards

  USER QUESTIONS always go via /btw to the Terminal PTY session.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time

import httpx
from fastapi import WebSocket, WebSocketDisconnect

from . import local_data, qa_agent
from .config import load_token, APP_URL
from .message_router import message_router  # legacy PTY router — kept for rollback

logger = logging.getLogger(__name__)

# ── Global chat-UI fanout ────────────────────────────────────────────────────
# Any /ws/chat client that connects is registered here so background components
# (like telegram_gateway) can push events to every open desktop chat UI.

_chat_ui_subscribers: set[WebSocket] = set()


async def broadcast_to_chat_ui(payload: dict) -> None:
    """Fan-out a payload to every connected /ws/chat client.

    Safe to call from any async context. Silently drops disconnected clients.
    """
    stale: list[WebSocket] = []
    for ws in list(_chat_ui_subscribers):
        try:
            await ws.send_json(payload)
        except Exception:
            stale.append(ws)
    for ws in stale:
        _chat_ui_subscribers.discard(ws)

# ── Telegram integration ─────────────────────────────────────────────────────

_telegram_config: dict | None = None


async def _get_telegram_config() -> dict | None:
    """Fetch Telegram bot token + chat_id from the worker proxy API."""
    global _telegram_config
    if _telegram_config is not None:
        return _telegram_config if _telegram_config.get("bot_token") else None

    token = load_token()
    if not token:
        _telegram_config = {}
        return None

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{APP_URL}/api/worker/proxy",
                json={"action": "get_telegram_config"},
                headers={"X-Worker-Token": token},
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            _telegram_config = {
                "bot_token": data.get("bot_token"),
                "chat_id": data.get("chat_id"),
            }
            if _telegram_config["bot_token"] and _telegram_config["chat_id"]:
                logger.info("Telegram configured — using Telegram for chat feed")
                return _telegram_config
            _telegram_config = {}
            return None
    except Exception as e:
        logger.debug(f"Telegram config fetch failed: {e}")
        _telegram_config = {}
        return None


async def _fetch_telegram_messages(bot_token: str, chat_id: str, since_id: int = 0) -> list[dict]:
    """Fetch recent bot messages from Telegram using getUpdates."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Use getUpdates to get recent messages the bot sent
            resp = await client.get(
                f"https://api.telegram.org/bot{bot_token}/getUpdates",
                params={"offset": since_id + 1, "limit": 20, "timeout": 0},
            )
            resp.raise_for_status()
            updates = resp.json().get("result", [])

            messages = []
            for update in updates:
                msg = update.get("message", {})
                if str(msg.get("chat", {}).get("id")) == str(chat_id):
                    messages.append({
                        "update_id": update.get("update_id", 0),
                        "text": msg.get("text", ""),
                        "date": msg.get("date", 0),
                        "from_bot": msg.get("from", {}).get("is_bot", False),
                    })
            return messages
    except Exception as e:
        logger.debug(f"Telegram fetch failed: {e}")
        return []


# ── WebSocket handler ────────────────────────────────────────────────────────

async def chat_websocket(ws: WebSocket):
    """
    Chat WebSocket handler.

    Message types sent to client:
    - {"type": "activity", "entries": [...]}  — SQLite activity feed
    - {"type": "btw_response", "data": "..."} — response to a /btw question
    - {"type": "telegram", "data": "...", "from_bot": bool} — mirrored Telegram traffic
    - {"type": "system", "data": "..."}       — system messages
    - {"type": "queue_update", ...}           — queue count changes
    - {"type": "session_idle", ...}           — PTY idle warning
    """
    await ws.accept()
    _chat_ui_subscribers.add(ws)

    from .pty_terminal import session_manager

    last_check_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 300))
    last_queue_count = local_data.get_queue_count()

    await ws.send_json({
        "type": "system",
        "data": "Connected to ApplyLoop. Status updates from local database.",
    })

    recent = local_data.get_recent_activity(limit=20)
    if recent:
        await ws.send_json({"type": "activity", "entries": recent})

    async def _status_feed():
        """Poll SQLite for activity + queue changes + PTY idle status."""
        nonlocal last_check_time, last_queue_count
        try:
            while True:
                await asyncio.sleep(5)

                new_entries = local_data.get_recent_activity(since=last_check_time, limit=10)
                if new_entries:
                    last_check_time = new_entries[0].get("applied_at", last_check_time)
                    await ws.send_json({"type": "activity", "entries": new_entries})

                current_queue = local_data.get_queue_count()
                if current_queue != last_queue_count:
                    diff = current_queue - last_queue_count
                    if diff > 0:
                        await ws.send_json({
                            "type": "queue_update",
                            "data": f"+{diff} jobs added to queue ({current_queue} total)",
                            "count": current_queue,
                        })
                    elif diff < 0:
                        await ws.send_json({
                            "type": "queue_update",
                            "data": f"{abs(diff)} jobs processed ({current_queue} remaining)",
                            "count": current_queue,
                        })
                    last_queue_count = current_queue

                if session_manager.pty.is_alive:
                    idle = time.time() - session_manager.pty.last_output_at if session_manager.pty.last_output_at else 0
                    if idle > 900:  # 15 min
                        await ws.send_json({
                            "type": "session_idle",
                            "data": f"Session idle for {int(idle/60)}m",
                            "idle_minutes": int(idle / 60),
                        })

        except Exception as e:
            logger.debug(f"Status feed ended: {e}")

    feed_task = asyncio.create_task(_status_feed())

    try:
        while True:
            msg = await ws.receive_json()
            action = msg.get("action", "message")

            if action == "message":
                user_input = msg.get("message", "").strip()
                if not user_input:
                    continue

                await ws.send_json({"type": "thinking", "data": "Asking Claude..."})

                # Route through the fire-and-forget Q&A agent (standalone claude --print
                # subprocess with pre-baked DB context). The main PTY applier loop is
                # untouched.
                try:
                    response = await qa_agent.answer(user_input)
                except Exception as e:
                    response = f"⚠️ Error processing message: {e}"

                await ws.send_json({"type": "btw_response", "data": response})

                # Mirror the reply to Telegram so phone + desktop stay in sync.
                try:
                    from .telegram_gateway import telegram_gateway
                    await telegram_gateway.send_telegram(response)
                except Exception as e:
                    logger.debug(f"Telegram mirror failed: {e}")

            elif action == "status":
                stats = local_data.get_stats()
                await ws.send_json({"type": "stats", "data": stats})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug(f"Chat WS closed: {e}")
    finally:
        feed_task.cancel()
        _chat_ui_subscribers.discard(ws)
